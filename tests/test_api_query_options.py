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
