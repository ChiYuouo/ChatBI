import json
from pathlib import Path

from chatbi.text2sql.prompt_builder import build_prompt


def test_prompt_and_all_revenue_templates_share_cny_and_foreign_currency_convention():
    data = json.loads((Path(__file__).resolve().parents[1] / "indicators_full.json").read_text(encoding="utf-8"))
    profit = next(item for item in data['indicators'] if item['name'] == '利润')
    assert '净利润' not in profit['aliases'] and '营业利润' not in profit['aliases']
    assert '同一个 MySQL' in profit['definition']
    for indicator in data['indicators']:
        sql = indicator['sql_template']
        if sql.startswith('SELECT') and 'exchange_rates' in sql:
            assert "CASE WHEN o.currency = 'CNY' THEN 1 ELSE r.rate_to_cny END" in sql
            assert 'LEFT JOIN exchange_rates' in sql
    _, prompt = build_prompt('毛利与经营利润', use_rules=True, use_guards=True)
    assert '人民币收入 - 估算销售成本' in prompt
    assert '毛利 = net_amount -' not in prompt
    assert '订单与费用在同一数据库' in prompt


def test_field_retrieval_returns_current_definition_even_with_old_index_text(monkeypatch):
    from types import SimpleNamespace
    from chatbi.retrieval import field_matcher
    old_doc = SimpleNamespace(page_content="毛利 = net_amount - (material_cost + labor_cost) * quantity",
        metadata={"field_key": "sales_orders.net_amount", "table_name": "sales_orders", "field_name": "net_amount"})
    monkeypatch.setattr(field_matcher, 'get_vectorstore', lambda: SimpleNamespace(
        similarity_search_with_relevance_scores=lambda *args, **kwargs: [(old_doc, 0.9)]))
    results = field_matcher.match_fields('毛利', candidate_tables=['sales_orders'])
    description = next(item['description'] for item in results if item['field_key'] == 'sales_orders.net_amount')
    assert '人民币收入' in description and '原币收入须先折算人民币' in description
    assert '毛利 = net_amount -' not in description
