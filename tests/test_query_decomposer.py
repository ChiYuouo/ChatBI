import json

from chatbi.analysis.query_decomposer import QueryDecomposer, build_decomposition_prompt, build_dimension_catalog


def test_build_decomposition_prompt_includes_schema_and_indicator_catalog():
    _system_msg, prompt = build_decomposition_prompt("分析近半年的利润变化情况", "sales_orders(order_date, net_amount)")

    assert "【数据库 Schema】" in prompt
    assert "【可用分析维度】" in prompt
    assert "【可用指标】" in prompt
    assert "【常见分析类型拆解策略】" in prompt
    assert "sales_orders.order_date" in prompt
    assert "利润" in prompt


def test_query_decomposer_rejects_unsupported_dimensions():
    raw_response = json.dumps(
        {
            "question_type": "利润下降原因分析",
            "analysis_goal": "定位利润下降原因",
            "subtasks": [
                {
                    "task_id": "task_1",
                    "task_name": "确认最近三个月利润趋势及下降幅度",
                    "task_type": "时间趋势分析",
                    "description": "查看利润趋势",
                    "depends_on": [],
                    "dimensions": ["sales_orders.order_date"],
                    "metrics": ["利润"],
                },
                {
                    "task_id": "task_2",
                    "task_name": "拆解利润构成指标变化",
                    "task_type": "指标拆解分析",
                    "description": "拆解收入、成本、费用",
                    "depends_on": ["task_1"],
                    "dimensions": ["sales_orders.order_date"],
                    "metrics": ["收入", "成本", "费用", "利润"],
                },
                {
                    "task_id": "task_3",
                    "task_name": "分析业务维度对利润下降的贡献",
                    "task_type": "维度对比分析",
                    "description": "分析产品线、客户、区域贡献",
                    "depends_on": ["task_1", "task_2"],
                    "dimensions": ["sales_orders.order_date", "渠道"],
                    "metrics": ["利润", "收入", "成本"],
                },
            ],
        },
        ensure_ascii=False,
    )

    decomposer = QueryDecomposer(
        schema_text="sales_orders(order_date, net_amount)",
        response_generator=lambda _system_msg, _prompt: raw_response
    )

    try:
        decomposer.decompose("最近三个月利润为什么下降？")
    except ValueError as exc:
        assert "不支持的分析维度" in str(exc)
        assert "渠道" in str(exc)
    else:
        raise AssertionError("应当拒绝未注册维度")


def test_query_decomposer_retries_when_trend_plan_has_too_many_tasks():
    oversized_plan = json.dumps(
        {
            "question_type": "trend_analysis",
            "analysis_goal": "分析近半年利润变化情况",
            "subtasks": [
                {
                    "task_id": f"task_{i}",
                    "task_name": f"任务{i}",
                    "task_type": "aggregation",
                    "description": "测试任务",
                    "depends_on": [],
                    "dimensions": ["sales_orders.order_date"],
                    "metrics": ["利润"],
                }
                for i in range(1, 8)
            ],
        },
        ensure_ascii=False,
    )
    valid_plan = json.dumps(
        {
            "question_type": "trend_analysis",
            "analysis_goal": "分析近半年利润变化情况",
            "subtasks": [
                {
                    "task_id": "task_1",
                    "task_name": "统计近半年月度利润趋势",
                    "task_type": "aggregation",
                    "description": "查看利润趋势",
                    "depends_on": [],
                    "dimensions": ["sales_orders.order_date"],
                    "metrics": ["利润"],
                },
                {
                    "task_id": "task_2",
                    "task_name": "统计近半年月度收入趋势",
                    "task_type": "aggregation",
                    "description": "查看收入趋势",
                    "depends_on": [],
                    "dimensions": ["sales_orders.order_date"],
                    "metrics": ["收入"],
                },
            ],
        },
        ensure_ascii=False,
    )
    responses = iter([oversized_plan, valid_plan])

    decomposer = QueryDecomposer(
        schema_text="sales_orders(order_date, net_amount)",
        response_generator=lambda _system_msg, _prompt: next(responses)
    )

    result = decomposer.decompose("分析近半年的利润变化情况")

    assert len(result["subtasks"]) == 2


def test_dimension_catalog_uses_current_fields_and_comments_including_new_business_domains():
    tables = [{"table_name": "tickets", "columns": [
        {"name": "queue", "type": "varchar(30)", "comment": "受理渠道"},
        {"name": "created_at", "type": "datetime", "comment": "创建时间"}]}]
    assert build_dimension_catalog("", tables) == {
        "tickets.queue": "受理渠道", "tickets.created_at": "创建时间"}
    assert "月份" not in build_dimension_catalog("", tables)


def test_decomposer_uses_structured_metadata_without_demo_dimension_fallback():
    from types import SimpleNamespace
    tables = [{"table_name": "tickets", "columns": [
        {"name": "queue", "type": "varchar(30)", "comment": "受理渠道"}]}]
    captured = []

    def response(_system, prompt):
        captured.append(prompt)
        return json.dumps({"question_type": "dimension", "analysis_goal": "渠道分布", "subtasks": [
            {"task_id": "task_1", "task_name": "按受理渠道统计", "task_type": "aggregation",
             "description": "按受理渠道统计工单数量", "dimensions": ["tickets.queue"], "metrics": []}]})

    decomposer = QueryDecomposer(llm_client=SimpleNamespace(), response_generator=response, schema_tables=tables)
    assert decomposer.decompose("各渠道工单数量")['subtasks'][0]['dimensions'] == ["tickets.queue"]
    dimensions_section = captured[0].split("【可用分析维度】", 1)[1].split("【可用指标】", 1)[0]
    assert "tickets.queue：受理渠道" in dimensions_section
    assert "客户类型" not in dimensions_section and "产品线" not in dimensions_section


def test_rendered_schema_text_compatibility_preserves_qualified_field_names():
    from chatbi.infrastructure.database_schema import render_schema
    tables = [{"table_name": "QueryEvents", "columns": [
        {"name": "created_at", "type": "datetime", "comment": "创建时间"}]}]
    assert build_dimension_catalog(render_schema(tables)) == {"QueryEvents.created_at": "创建时间"}
