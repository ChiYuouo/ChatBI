import pytest


@pytest.mark.parametrize("error_type, status", [
    ("database_result_limit", 413), ("database_budget_exceeded", 504),
    ("database_query_timeout", 504), ("database_pool_timeout", 503),
])
def test_query_resource_errors_have_explanatory_http_status(client, monkeypatch, error_type, status):
    from chatbi.api import routes
    monkeypatch.setattr(routes.system, "run", lambda **kwargs: {
        "success": False, "error": "查询超过资源限制", "error_type": error_type})
    response = client.post("/api/v1/query", json={"question": "订单查询"})
    assert response.status_code == status
    assert "资源限制" in response.json()["error"]


def test_resolve_query_options_uses_app_defaults_and_payload_overrides():
    from chatbi.api.dependencies import _resolve_query_options
    from chatbi.api.schemas import QueryRequest

    payload = QueryRequest(
        question="查看利润",
        use_rules=None,
        use_guards=True,
        use_schema_linking=None,
        use_indicator_rag=None,
    )
    app_config = {
        "features": {
            "few_shot": False,
            "rules": False,
            "guards": False,
            "indicator_knowledge": True,
            "schema_linking": True,
            "indicator_rag": False,
        }
    }

    options = _resolve_query_options(payload, app_config)

    assert options["use_few_shot"] is False
    assert options["use_rules"] is False
    assert options["use_guards"] is True
    assert options["use_schema_linking"] is True
    assert options["use_indicator_rag"] is False
