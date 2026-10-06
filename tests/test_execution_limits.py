from dataclasses import replace
from types import SimpleNamespace

import pytest

from chatbi.core.security import UserContext
from chatbi.execution.budget import BudgetExceeded, ExecutionBudget, ExecutionLimits, budgeted_events, request_timeout
from chatbi.execution.budgeted_llm import BudgetedLLM
from chatbi.infrastructure.database import DatabaseClient, QueryExecutionError
from chatbi.infrastructure.llm_client import LLMClient
from chatbi.services.chatbi_service import ChatBISystem
from chatbi.text2sql.query_parser import QueryParser
from chatbi.text2sql.result_formatter import ResultFormatter

USER = UserContext("finance", "finance")
OPTIONS = dict(use_few_shot=False, use_rules=False, use_guards=False,
    use_schema_linking=False, use_indicator_rag=False, use_indicator_knowledge=False, use_query_rewrite=False)


class Cursor:
    description = [("value",)]

    def __init__(self, connection, rows, error=None):
        self.connection = connection
        self.rows = iter(rows)
        self.error = error
        self.read_count = 0
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def execute(self, sql):
        self.connection.sqls.append(sql)
        if not sql.startswith("SET ") and self.error:
            raise self.error

    def fetchone(self):
        self.read_count += 1
        return next(self.rows, None)

    def close(self):
        self.closed = True


class Connection:
    def __init__(self, rows):
        self.rows = rows
        self.sqls = []
        self.closed = False
        self.cursors = []

    def cursor(self, kind=None):
        cursor = Cursor(self, self.rows)
        self.cursors.append(cursor)
        return cursor

    def close(self):
        self.closed = True


def database(rows, **limits):
    connection = Connection(rows)
    return DatabaseClient(connection_factory=lambda: connection, limits=ExecutionLimits(**limits),
        slow_query_threshold_ms=float("inf")), connection


def test_result_row_limit_does_not_return_partial_success_or_fetch_remaining_rows():
    db, conn = database([(1,), (2,), (3,), (4,)], max_rows=2)
    with pytest.raises(QueryExecutionError, match="2 行") as error:
        db.execute_query("SELECT order_id AS value FROM sales_orders", USER)
    assert error.value.error_type == "result_limit"
    assert conn.cursors[-1].read_count == 3
    assert conn.closed
    assert conn.sqls[-1].endswith("LIMIT 3")


def test_existing_smaller_sql_limit_is_preserved():
    db, conn = database([(1,)], max_rows=2)
    result = db.execute_query("SELECT order_id FROM sales_orders LIMIT 1", USER)
    assert result.executed_sql.endswith("LIMIT 1")
    assert result.metadata["complete"] is True


def test_result_byte_limit_counts_utf8_and_field_names():
    db, conn = database([("汉" * 20,)], max_result_bytes=64)
    with pytest.raises(QueryExecutionError) as error:
        db.execute_query("SELECT customer_name AS value FROM dim_customers", USER)
    assert error.value.error_type == "result_limit"
    assert conn.closed


def test_exact_row_limit_succeeds_and_reports_size_and_server_timeout():
    db, conn = database([(1,), (2,)], max_rows=2, sql_timeout_ms=250)
    result = db.execute_query("SELECT order_id AS value FROM sales_orders", USER)
    assert result.rows == [(1,), (2,)]
    assert result.result_bytes > 0
    assert result.sql_timeout_ms == 250
    assert "SET SESSION TRANSACTION READ ONLY" in conn.sqls
    assert "SET SESSION max_execution_time = 250" in conn.sqls


def test_expired_budget_does_not_open_connection():
    db, conn = database([])
    now = [0]
    budget = ExecutionBudget(ExecutionLimits(total_timeout_seconds=1), clock=lambda: now[0])
    now[0] = 2
    with pytest.raises(BudgetExceeded):
        db.execute_query("SELECT 1", USER, budget)
    assert not conn.sqls


def test_budget_counts_all_attempts_and_cumulative_bytes():
    budget = ExecutionBudget(ExecutionLimits(max_executions=1, max_total_result_bytes=40))
    budget.start_execution()
    with pytest.raises(BudgetExceeded, match="次数"):
        budget.start_execution()
    budget.consume_result_bytes(30)
    with pytest.raises(BudgetExceeded, match="累计"):
        budget.consume_result_bytes(11)


def test_failed_attempt_also_consumes_execution_budget():
    db, conn = database([])
    budget = ExecutionBudget(ExecutionLimits(max_executions=1))
    def fail():
        raise OSError("connection unavailable")
    db.connection_factory = fail
    with pytest.raises(QueryExecutionError):
        db.execute_query("SELECT 1", USER, budget)
    with pytest.raises(BudgetExceeded):
        db.execute_query("SELECT 1", USER, budget)
    assert budget.executions == 1


def test_streamed_model_output_is_closed_when_budget_expires():
    now = [0]
    closed = []
    budget = ExecutionBudget(ExecutionLimits(total_timeout_seconds=1), clock=lambda: now[0])
    class LLM:
        def generate_sql_stream(self, *args):
            try:
                yield "SELECT "
                now[0] = 2
                yield "1"
            finally:
                closed.append(True)
    stream = BudgetedLLM(LLM(), budget).generate_sql_stream("", "")
    assert next(stream) == "SELECT "
    with pytest.raises(BudgetExceeded):
        next(stream)
    assert closed == [True]


@pytest.mark.parametrize("stream", [False, True])
def test_single_query_does_not_execute_after_model_exhausts_budget(stream):
    now = [0]
    db, conn = database([])
    class LLM:
        def generate_sql(self, *args):
            now[0] = 2
            return "SELECT 1"
        def generate_sql_stream(self, *args):
            yield self.generate_sql(*args)
    runtime = SimpleNamespace(source_id="mysql_main", db=db, llm=LLM(), parser=QueryParser(),
        formatter=ResultFormatter(), indicator_knowledge=None)
    system = ChatBISystem(runtime=runtime, app_config={"features": {}})
    budget = ExecutionBudget(ExecutionLimits(total_timeout_seconds=1), clock=lambda: now[0])
    if stream:
        result = dict(system.run_stream_events("orders", security_context=USER, execution_budget=budget, **OPTIONS))["error"]
    else:
        result = system.run("orders", security_context=USER, execution_budget=budget, **OPTIONS)
    assert result["error_type"] == "database_budget_exceeded"
    assert not conn.sqls


def test_native_model_request_has_remaining_timeout_and_no_sdk_retries():
    client = LLMClient()
    options = []
    class RecordingClient:
        def with_options(self, **kwargs):
            options.append(kwargs)
            return self
    client.client = RecordingClient()
    now = [0]
    budget = ExecutionBudget(ExecutionLimits(total_timeout_seconds=2), clock=lambda: now[0])
    now[0] = 1.5
    client.request_client(budget)
    assert options == [{"timeout": 0.5, "max_retries": 0}]


def test_non_positive_limits_are_rejected():
    for field in ExecutionLimits.__dataclass_fields__:
        with pytest.raises(ValueError):
            replace(ExecutionLimits(), **{field: 0})


def test_budgeted_sse_iterator_can_be_resumed_in_different_threads():
    from concurrent.futures import ThreadPoolExecutor
    budget = ExecutionBudget(ExecutionLimits(total_timeout_seconds=5))
    def events():
        for value in range(3):
            assert 0 < request_timeout(30) <= 5
            yield value
    stream = budgeted_events(events(), budget)
    with ThreadPoolExecutor(max_workers=1) as first, ThreadPoolExecutor(max_workers=1) as second:
        for expected in range(3):
            thread = first if expected % 2 == 0 else second
            assert thread.submit(next, stream).result() == expected
        with pytest.raises(StopIteration):
            second.submit(next, stream).result()
    assert request_timeout(30) == 30


def test_nonfinite_timeout_is_rejected():
    for timeout in (float("inf"), float("nan")):
        with pytest.raises(ValueError):
            ExecutionLimits(total_timeout_seconds=timeout)
