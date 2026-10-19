from types import SimpleNamespace

import pytest

from chatbi.api import routes
from chatbi.retrieval import index_manager


@pytest.mark.parametrize("connected", [False, True])
def test_database_failure_is_not_reported_healthy(anonymous_client, monkeypatch, connected):
    monkeypatch.setattr(routes.system, "_get_runtime", lambda: SimpleNamespace(db=SimpleNamespace(validate_connection=lambda: connected)))
    response = anonymous_client.get("/health")
    assert response.status_code == (200 if connected else 503)
    assert response.json()["status"] == ("ok" if connected else "degraded")


def test_schema_index_can_be_prepared_lazily_and_health_does_not_create_it(anonymous_client, tmp_path, monkeypatch):
    monkeypatch.setattr(routes.system, "_get_runtime", lambda: SimpleNamespace(db=SimpleNamespace(validate_connection=lambda: True)))
    monkeypatch.setitem(routes.APP_CONFIG["features"], "schema_linking", True)
    index_root = tmp_path / "indexes"
    monkeypatch.setattr(index_manager, "CHROMA_ROOT", index_root)
    from chatbi.retrieval import schema_index
    monkeypatch.setattr(schema_index, "CHROMA_ROOT", index_root)
    response = anonymous_client.get("/health")
    assert response.status_code == 200
    assert response.json()["database_connected"]
    assert response.json()["retrieval_ready"]
    assert response.json()["indexes"]["schema"]["status"] == "missing"
    assert response.json()["indexes"]["schema"]["fallback"] == "current_full_schema"
    assert not index_root.exists()


def test_liveness_is_public_and_independent_of_database(anonymous_client, monkeypatch):
    monkeypatch.setattr(routes.system, "_get_runtime", lambda: (_ for _ in ()).throw(AssertionError("must not connect")))
    assert anonymous_client.get("/live").json() == {"status": "ok"}


@pytest.mark.parametrize("stream", [False, True])
def test_missing_indexes_fail_before_remote_model_or_query(stream, monkeypatch, tmp_path):
    from chatbi.services.chatbi_service import ChatBISystem
    from chatbi.core.security import UserContext
    runtime = SimpleNamespace(source_id="test", db=SimpleNamespace(), llm=SimpleNamespace(),
                              parser=None, formatter=None, indicator_knowledge=None)
    system = ChatBISystem(runtime=runtime, app_config={"features": {}})
    monkeypatch.setattr(index_manager, "CHROMA_ROOT", tmp_path)
    options = {"security_context": UserContext.demo_admin(), "use_indicator_rag": True}
    if stream:
        events = list(system.run_stream_events("订单数量", **options))
        assert dict(events)["error"]["error_type"] == "retrieval_not_ready"
    else:
        assert system.run("订单数量", **options)["error_type"] == "retrieval_not_ready"


def test_analysis_none_override_keeps_feature_configuration_before_creating_runtime(monkeypatch, tmp_path):
    from chatbi.analysis.analysis_service import AnalysisService
    from chatbi.core.security import UserContext
    def unexpected_runtime(*args, **kwargs):
        raise AssertionError("未就绪前不应创建模型运行时")
    service = AnalysisService(app_config={"features": {"indicator_rag": True}}, runtime_factory=unexpected_runtime)
    monkeypatch.setattr(index_manager, "CHROMA_ROOT", tmp_path)
    events = list(service.run_stream_events("统计订单", security_context=UserContext.demo_admin(),
        chatbi_run_options={"use_indicator_rag": None}))
    assert dict(events)["error"]["error_type"] == "retrieval_not_ready"
