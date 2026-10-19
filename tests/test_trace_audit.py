"""验证同一请求的执行事件可追溯，且拒绝的 SQL 不会触库。"""

from chatbi.api import routes
from chatbi.contracts.execution import QueryExecutionResult
from chatbi.core.auth import AuthUser, create_token
from chatbi.core.security import QuerySecurityManager, SecurityError, UserContext
from chatbi.execution.budget import ExecutionLimits
from chatbi.execution.query_executor import QueryExecutor
from chatbi.infrastructure.audit_store import get_trace_events


def test_query_trace_is_returned_and_admin_can_inspect(client, monkeypatch):
    monkeypatch.setattr(routes.system, "run", lambda **kwargs: {
        "success": True, "sql": "SELECT 1", "columns": ["value"], "results": [(1,)],
        "formatted": "1", "metadata": {},
    })
    response = client.post("/api/v1/query", json={"question": "订单数"})
    trace_id = response.headers["X-Trace-Id"]
    assert response.status_code == 200
    assert response.json()["metadata"]["trace_id"] == trace_id
    events = client.get(f"/api/v1/traces/{trace_id}").json()["events"]
    assert [event["event"] for event in events] == ["query_started", "query_succeeded"]
    assert events[0]["user_id"] == "test_admin"
    assert "订单数" not in str(events)


def test_sql_rejection_is_audited_without_opening_database(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "audit.db"))

    class Database:
        source_id = "mysql_main"
        limits = ExecutionLimits()

        def _execute_secured(self, *args):
            raise AssertionError("拒绝的 SQL 不能触库")

    trace_id = "a" * 32
    user = UserContext("alice", "sales", region="欧洲", trace_id=trace_id)
    executor = QueryExecutor(Database(), QuerySecurityManager())
    try:
        executor.execute("DELETE FROM sales_orders", user)
    except SecurityError:
        pass
    else:
        raise AssertionError("写入 SQL 应被拒绝")
    events = get_trace_events(trace_id)
    assert [event["event"] for event in events] == ["sql_rejected"]
    assert events[0]["error_type"] == "SecurityError"
    assert events[0]["sql_hash"] and "DELETE" not in str(events)


def test_sql_execution_events_keep_request_trace(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "audit.db"))

    class Database:
        source_id = "mysql_main"
        limits = ExecutionLimits()
        schema = {"sales_orders": {"order_id": "int"}}

        def _execute_secured(self, original, secured, context, budget):
            assert context.trace_id == "b" * 32
            return QueryExecutionResult(original, secured, context.source_id,
                                        ["orders"], [(2,)], 1.5)

    trace_id = "b" * 32
    result = QueryExecutor(Database(), QuerySecurityManager()).execute(
        "SELECT COUNT(*) AS orders FROM sales_orders",
        UserContext("alice", "admin", trace_id=trace_id),
    )
    assert result.rows == [(2,)]
    events = get_trace_events(trace_id)
    assert [event["event"] for event in events] == ["sql_started", "sql_succeeded"]
    assert events[0]["sql_hash"] == events[1]["sql_hash"]
    assert events[1]["row_count"] == 1


def test_non_admin_cannot_read_trace(anonymous_client):
    token = create_token(AuthUser(user_id="alice", username="alice", role="sales", region="欧洲"))
    response = anonymous_client.get("/api/v1/traces/" + "a" * 32,
                                    headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


def test_analyze_stream_events_share_trace(client, monkeypatch):
    def fake_events(**kwargs):
        assert kwargs["security_context"].trace_id
        yield "start", {}
        yield "done", {}

    monkeypatch.setattr(routes.analysis_service, "run_stream_events", fake_events)
    response = client.post("/api/v1/analyze/stream", json={"question": "利润为何变化"})
    trace_id = response.headers["X-Trace-Id"]
    assert response.status_code == 200
    assert response.text.count(f'"trace_id": "{trace_id}"') == 2
    events = client.get(f"/api/v1/traces/{trace_id}").json()["events"]
    assert [event["event"] for event in events] == ["analysis_started", "analysis_succeeded"]
