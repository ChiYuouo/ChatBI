"""使用真实安全层和数据库客户端，验证同步、流式与修复重试的入口一致。"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

import pymysql
import pytest
import sqlglot

from chatbi.analysis.agent_planner import ExecutionPlan, PlanStep, StepExecutor
from chatbi.core.security import UserContext
from chatbi.infrastructure.database import QueryExecutionError
from schema_fixtures import FixtureDatabaseClient as DatabaseClient
from chatbi.services.chatbi_service import ChatBISystem
from chatbi.text2sql.query_parser import QueryParser
from chatbi.text2sql.result_formatter import ResultFormatter

OPTIONS = dict(use_few_shot=False, use_rules=False, use_guards=False,
               use_schema_linking=False, use_indicator_rag=False,
               use_indicator_knowledge=False, use_query_rewrite=False)


class Cursor:
    def __init__(self, sqls, error=None, barrier=None):
        self.sqls = sqls
        self.error = error
        self.barrier = barrier
        self.description = [("orders",)]
        self.rows = [(2,)]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def close(self):
        pass

    def execute(self, sql):
        if sql.startswith("SET "):
            return
        self._remaining = iter(self.rows)
        self.sqls.append(sql)
        if self.barrier:
            self.barrier.wait(timeout=5)
            projection = sqlglot.parse_one(sql, read="mysql").expressions[0]
            self.description = [(projection.alias,)]
            self.rows = [(int(projection.this.this),)]
        self._remaining = iter(self.rows)
        if self.error:
            raise self.error

    def fetchone(self):
        return next(self._remaining, None)

    def fetchmany(self, size):
        return self.rows[:size]


class Connection:
    def __init__(self, cursor):
        self.instance = cursor
        self.closed = False

    def cursor(self, cursorclass=None):
        return self.instance

    def close(self):
        self.closed = True


class LLM:
    def __init__(self, queries):
        self.queries = iter(queries)
        self.prompts = []

    def generate_sql(self, system_msg, prompt):
        self.prompts.append(prompt)
        return next(self.queries)

    def generate_sql_stream(self, system_msg, prompt):
        yield self.generate_sql(system_msg, prompt)


def build_system(db, queries):
    return ChatBISystem(runtime=SimpleNamespace(source_id=db.source_id, db=db,
        llm=LLM(queries), parser=QueryParser(), formatter=ResultFormatter(), indicator_knowledge=None, schema_text="sales_orders(order_id, order_date, region, net_amount)"),
        app_config={"features": {}})


@pytest.mark.parametrize("stream", [False, True])
def test_query_results_contain_actual_sql_after_security_rewrite(stream):
    sqls = []
    db = DatabaseClient(connection_factory=lambda: Connection(Cursor(sqls)), slow_query_threshold_ms=float("inf"))
    system = build_system(db, ["SELECT COUNT(*) AS orders FROM sales_orders"])
    user = UserContext("sales", "sales", "Europe")
    if stream:
        result = dict(system.run_stream_events("orders", security_context=user, **OPTIONS))["result"]
    else:
        result = system.run("orders", security_context=user, **OPTIONS)
        assert result["success"]
    assert len(sqls) == 1
    assert result["sql"] == sqls[0]
    assert "Europe" in result["sql"]
    assert result["metadata"]["db_duration_ms"] is not None


@pytest.mark.parametrize("stream", [False, True])
def test_repair_is_checked_again_and_permission_failure_ends_retries(stream):
    sqls = []
    opened = []

    def factory():
        opened.append(True)
        return Connection(Cursor(sqls, error=pymysql.err.ProgrammingError(1055, "GROUP BY error")))

    db = DatabaseClient(connection_factory=factory)
    system = build_system(db, ["SELECT COUNT(*) AS orders FROM sales_orders",
                              "SELECT SUM(net_amount) AS revenue FROM sales_orders"])
    plan = ExecutionPlan(original_question="orders", question_type="trend", analysis_goal="orders", steps=[
        PlanStep(step_id="step_1", task_id="task_1", step_name="orders", question="orders", task_type="trend",
                 description="orders", expected_output="count")])
    executor = StepExecutor(chatbi_system=system, chatbi_run_options=OPTIONS,
        security_context=UserContext("sales", "sales", "Europe"), max_retries=3)
    if stream:
        events = list(executor.execute_plan_streaming(plan))
        result = next(data for kind, data in events if kind == "step_done")
        assert len([1 for kind, _ in events if kind == "step_retry"]) == 1
    else:
        result = executor.execute_plan(plan)[0].model_dump()
    assert result["attempts"] == 2
    assert result["error_type"] == "security"
    assert len(system.llm.prompts) == 2
    assert len(opened) == 1  # 第二条 SQL 在打开连接前已拒绝。
    assert "GROUP BY error" in system.llm.prompts[1]


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("invalid_sql, expected_error", [
    ("SELECT ROW_NUMBER() OVER (ORDER BY order_id) FROM sales_orders", "窗口函数"),
    ("SELECT channel FROM sales_orders", "字段 channel 无法确定"),
    ("SELECT order_id FROM sales_orders WHERE (", "SQL 语法不完整"),
    ("SELECT o.order_id FROM sales_orders o FULL OUTER JOIN dim_customers c "
     "ON o.customer_id = c.customer_id", "RIGHT/FULL JOIN"),
])
def test_generated_sql_is_rewritten_and_rechecked(stream, invalid_sql, expected_error):
    sqls = []
    db = DatabaseClient(connection_factory=lambda: Connection(Cursor(sqls)))
    valid_sql = "SELECT COUNT(*) AS orders FROM sales_orders"
    system = build_system(db, [invalid_sql, valid_sql])
    plan = ExecutionPlan(original_question="orders", question_type="trend", analysis_goal="orders", steps=[
        PlanStep(step_id="step_1", task_id="task_1", step_name="orders", question="orders", task_type="trend",
                 description="orders", expected_output="count")])
    executor = StepExecutor(chatbi_system=system, chatbi_run_options=OPTIONS,
                            security_context=UserContext("admin", "admin"), max_retries=1)
    if stream:
        events = list(executor.execute_plan_streaming(plan))
        result = next(data for kind, data in events if kind == "step_done")
        retries = [data for kind, data in events if kind == "step_retry"]
        assert len(retries) == 1 and retries[0]["mode"] == "rewrite"
        assert expected_error in retries[0]["previous_error"]
    else:
        result = executor.execute_plan(plan)[0].model_dump()
    assert result["success"] is True
    assert result["attempts"] == 2
    assert result["repaired"] is True
    assert len(sqls) == 1
    assert expected_error in system.llm.prompts[1]
    assert "窗口函数" in system.llm.prompts[1]


def test_concurrent_results_keep_their_own_sql_rows_and_statistics():
    sqls = []
    barrier = Barrier(2)
    db = DatabaseClient(connection_factory=lambda: Connection(Cursor(sqls, barrier=barrier)),
                        slow_query_threshold_ms=float("inf"))
    queries = ["SELECT 1 AS first", "SELECT 2 AS second"]
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda sql: db.execute_query(sql, UserContext("finance", "finance")), queries))
    assert results[0].columns == ["first"] and results[0].rows == [(1,)]
    assert results[1].columns == ["second"] and results[1].rows == [(2,)]
    for query, result in zip(queries, results):
        assert result.input_sql == query
        assert result.metadata["sql"] == result.executed_sql
        assert result.duration_ms >= 0
    assert not hasattr(db, "last_query_info")


def test_mysql_permission_programming_error_is_not_repairable_syntax():
    db = DatabaseClient(connection_factory=lambda: Connection(Cursor([], error=pymysql.err.ProgrammingError(1142, "denied"))))
    with pytest.raises(QueryExecutionError) as error:
        db.execute_query("SELECT COUNT(*) FROM sales_orders", UserContext("f", "finance"))
    assert error.value.error_type == "permission_denied"


@pytest.mark.parametrize("error_type", ["security", "permission_denied", "database_permission_denied",
    "query_timeout", "database_query_timeout", "llm", "unknown"])
def test_terminal_errors_are_never_retried(error_type):
    calls = []

    def runner(question):
        calls.append(question)
        return {"success": False, "error": "stop", "error_type": error_type}

    plan = ExecutionPlan(original_question="orders", question_type="trend", analysis_goal="orders", steps=[
        PlanStep(step_id="step_1", task_id="task_1", step_name="orders", question="orders", task_type="trend",
                 description="orders", expected_output="count")])
    result = StepExecutor(step_runner=runner, max_retries=3).execute_plan(plan)[0]
    assert result.attempts == 1
    assert len(calls) == 1


@pytest.mark.parametrize("stream", [False, True])
def test_each_analysis_step_keeps_original_scope_and_executed_dependency_sql(stream):
    seen = []
    original = "统计2026年7月欧洲已完成订单的数量和人民币收入"
    sql = "SELECT order_id FROM sales_orders WHERE order_date >= '2026-07-01' AND order_date < '2026-08-01'"
    def runner(question):
        seen.append(question)
        return {"success": True, "sql": sql, "columns": ["orders"], "rows": [{"orders": 2}]}
    plan = ExecutionPlan(original_question=original, question_type="dimension", analysis_goal="count and revenue", steps=[
        PlanStep(step_id="step_1", task_id="task_1", step_name="orders", question="查询订单", task_type="query",
            description="orders", expected_output="orders"),
        PlanStep(step_id="step_2", task_id="task_2", step_name="revenue", question="汇总所有订单人民币收入", task_type="query",
            description="revenue", expected_output="revenue", depends_on=["step_1"]),
    ])
    executor = StepExecutor(step_runner=runner)
    try:
        if stream:
            list(executor.execute_plan_streaming(plan))
        else:
            executor.execute_plan(plan)
        assert len(seen) == 2
        assert all(original in question for question in seen)
        assert sql in seen[1]
        assert "2026-08-01" in seen[1]
    finally:
        executor.cleanup()
