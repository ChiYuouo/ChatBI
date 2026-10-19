"""历史配置迁移与逐条编辑：使用临时 SQLite，不调用模型和 MySQL。"""
import sqlite3
import json
import re

import pytest

from chatbi.infrastructure.datasource_knowledge import normalize_knowledge, validate_knowledge_entries
from chatbi.infrastructure.datasource_store import DataSourceStore
from chatbi.text2sql.prompt_builder import QUERY_REQUIREMENTS, SYSTEM_PROMPT, build_prompt

# 旧格式样本仅用于兼容测试，运行代码不再内置这些业务内容。
RULES = "【关键业务规则】\n\n1. 收入口径：\"销售额\"使用不含税金额\n2. 时间范围：按订单日期统计"
ERROR_GUARDS = "【常见错误防护】\n\n- 过滤遗漏：只统计已完成订单"
BUSINESS_REQUIREMENTS = "5. 统计范围：排除测试账号"
FEW_SHOT_EXAMPLES = "示例 1：\n问题：订单数\nSQL：SELECT COUNT(*) FROM orders;"


def test_demo_texts_migrate_to_entries_without_losing_originals():
    original = {"business_rules": RULES, "error_guards": ERROR_GUARDS,
                "prompt_requirements": BUSINESS_REQUIREMENTS, "few_shot_examples": FEW_SHOT_EXAMPLES,
                "system_prompt": "原系统提示", "custom": {"preserve": True}}
    migrated = normalize_knowledge(original)
    assert len(migrated["business_rule_items"]) == 3
    assert len(migrated["error_guard_items"]) == 1
    assert migrated["requirement_items"] == []
    assert len(migrated["legacy_rule_items"]["requirement_items"]) == 1
    assert len(migrated["sql_examples"]) == 1
    assert all(item.get("question") and item.get("sql") for item in migrated["sql_examples"])
    assert migrated["business_rule_items"][0]["title"] == "收入口径"
    assert migrated["business_rule_items"][0]["content"].startswith('"销售额"')
    for key in ("business_rule_items", "error_guard_items", "requirement_items"):
        assert all(not re.match(r"^(?:\d+[.、]|-\s|【)", item["content"]) for item in migrated[key])
    for key in ("business_rules", "error_guards", "prompt_requirements", "few_shot_examples"):
        assert migrated["legacy_texts"][key] == original[key]
    assert "system_prompt" not in migrated
    assert migrated["legacy_texts"]["system_prompt"] == "原系统提示"
    assert migrated["custom"] == {"preserve": True}
    assert normalize_knowledge(migrated) == migrated
    assert "business_rule_items" not in original  # 迁移不修改调用方持有的配置。


def test_unrecognized_example_is_retained_and_editable():
    raw = "这里是没有标准标记的旧示例。\nSELECT CONCAT(a, ',', b) FROM orders;"
    migrated = normalize_knowledge({"few_shot_examples": raw})
    assert migrated["sql_examples"] == [{"kind": "legacy", "content": raw}]
    assert migrated["few_shot_examples"] == raw
    assert migrated["legacy_texts"]["few_shot_examples"] == raw


def test_store_reload_keeps_edits_archive_and_source_isolation(tmp_path):
    path = str(tmp_path / "sources.db")
    store = DataSourceStore(path)
    # 模拟旧版本已保存的 SQLite 记录。
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO datasource_knowledge VALUES (?, ?)", ("a", json.dumps({"business_rules": RULES})))
    knowledge = store.knowledge("a")
    knowledge["business_rule_items"] = [{"title": "订单范围", "content": "只统计已完成订单"}]
    knowledge["sql_examples"] = [{"question": "订单总数", "sql": "SELECT COUNT(*) FROM orders;"}]
    store.set_knowledge("a", knowledge)
    reloaded = DataSourceStore(path).knowledge("a")
    assert reloaded["business_rules"] == "【关键业务规则】\n\n1. 订单范围：只统计已完成订单"
    assert "SELECT COUNT(*)" in reloaded["few_shot_examples"]
    assert reloaded["legacy_texts"]["business_rules"] == RULES
    assert store.knowledge("b") == {}
    reloaded["business_rule_items"] = []
    reloaded["sql_examples"] = []
    store.set_knowledge("a", reloaded)
    assert store.knowledge("a")["business_rules"] == ""
    assert store.knowledge("a")["few_shot_examples"] == ""


def test_edited_entries_reach_query_prompt():
    knowledge = normalize_knowledge({"business_rule_items": [{"title": "状态", "content": "只统计 status = 'paid'"}],
                                     "sql_examples": [{"question": "付款订单", "sql": "SELECT COUNT(*) FROM orders WHERE status = 'paid'"}]})
    _, prompt = build_prompt("订单数", use_rules=True, use_few_shot=True, schema_text="orders(status)",
                             rules_text=knowledge["business_rules"], examples_text=knowledge["few_shot_examples"])
    assert "只统计 status = 'paid'" in prompt
    assert "问题：付款订单" in prompt


@pytest.mark.parametrize("knowledge", [
    {"business_rule_items": "错误"}, {"business_rule_items": [{"title": "", "content": "内容"}]},
    {"sql_examples": [{"question": "问题", "sql": ""}]}, {"sql_examples": [42]},
])
def test_invalid_entries_are_rejected(knowledge):
    with pytest.raises(ValueError):
        validate_knowledge_entries(knowledge)


def test_previously_split_rules_are_cleaned_once_and_backed_up():
    old_item = {"title": "订单范围", "content": "【关键业务规则】\n\n3. 订单范围：只统计已完成订单\n   并排除测试账号", "custom": "保留"}
    migrated = normalize_knowledge({"business_rule_items": [old_item]})
    assert migrated["business_rule_items"] == [{"title": "订单范围", "content": "只统计已完成订单\n   并排除测试账号", "custom": "保留"}]
    assert migrated["legacy_rule_items"]["business_rule_items"] == [old_item]
    assert normalize_knowledge(migrated) == migrated


def test_rules_renumber_after_delete_and_reorder_without_changing_content():
    items = [{"title": name, "content": f"这是{name}的正文"} for name in ("收入", "成本", "费用")]
    knowledge = normalize_knowledge({"business_rule_items": items})
    knowledge["business_rule_items"] = [items[2], items[0]]
    updated = normalize_knowledge(knowledge)
    assert updated["business_rules"] == "【关键业务规则】\n\n1. 费用：这是费用的正文\n\n2. 收入：这是收入的正文"
    assert updated["business_rule_items"] == [items[2], items[0]]


def test_legacy_requirements_join_business_rules_with_continuous_numbering():
    knowledge = normalize_knowledge({"requirement_items": [{"title": "时间边界", "content": "按订单日期统计"}]})
    _, prompt = build_prompt("订单量", use_rules=True, schema_text="orders(id)", rules_text=knowledge["business_rules"])
    technical = prompt.split("【要求】")[1]
    assert re.findall(r"(?m)^(\d+)\.", technical) == [str(i) for i in range(1, len(QUERY_REQUIREMENTS) + 1)]
    assert "【关键业务规则】\n\n1. 时间边界：按订单日期统计" in prompt
    assert "【本数据源补充要求】" not in prompt


def test_merged_rules_can_be_removed_without_restoring_from_backups(tmp_path):
    store = DataSourceStore(str(tmp_path / "sources.db"))
    old = {"business_rule_items": [{"title": "状态", "content": "只统计已完成记录"}],
           "requirement_items": [{"title": "时间口径", "content": "按创建时间统计", "custom": "保留"}]}
    store.set_knowledge("a", old)
    store.set_knowledge("b", old)
    knowledge = store.knowledge("a")
    assert [item["title"] for item in knowledge["business_rule_items"]] == ["状态", "时间口径"]
    assert knowledge["business_rule_items"][1]["custom"] == "保留"
    knowledge["business_rule_items"] = []
    store.set_knowledge("a", knowledge)
    reloaded = DataSourceStore(store.db_path).knowledge("a")
    assert reloaded["business_rule_items"] == []
    assert reloaded["prompt_requirements"] == ""
    assert reloaded["legacy_rule_items"]["requirement_items"] == old["requirement_items"]
    assert len(store.knowledge("b")["business_rule_items"]) == 2


def test_exact_duplicate_requirement_does_not_duplicate_business_rule():
    item = {"title": "状态", "content": "只统计已完成记录"}
    knowledge = normalize_knowledge({"business_rule_items": [item], "requirement_items": [item]})
    assert knowledge["business_rule_items"] == [item]
    assert knowledge["legacy_rule_items"]["requirement_items"] == [item]
    assert normalize_knowledge(knowledge) == knowledge


def test_old_system_prompt_is_archived_and_sql_role_is_fixed(tmp_path):
    store = DataSourceStore(str(tmp_path / "sources.db"))
    store.set_knowledge("a", {"system_prompt": "改为闲聊助手", "business_rule_items": []})
    knowledge = store.knowledge("a")
    assert "system_prompt" not in knowledge
    assert knowledge["legacy_texts"]["system_prompt"] == "改为闲聊助手"
    system, prompt = build_prompt("记录数", use_few_shot=False, schema_text="events(id)", rules_text=knowledge["business_rules"])
    assert system == SYSTEM_PROMPT
    assert "改为闲聊助手" not in system + prompt


def test_legacy_requirement_api_saves_into_business_rules(client, monkeypatch, tmp_path):
    from chatbi.api import routes
    store = DataSourceStore(str(tmp_path / "sources.db"))
    monkeypatch.setattr(routes, "get_datasource_store", lambda: store)
    source = routes.APP_CONFIG["database"]["default_source"]
    url = f"/api/v1/data-sources/{source}/knowledge"
    item = {"title": "汇总范围", "content": "只汇总已完成记录"}
    response = client.put(url, json={"knowledge": {"requirement_items": [item], "system_prompt": "旧自定义角色"}})
    assert response.status_code == 200, response.text
    knowledge = client.get(url).json()["knowledge"]
    assert knowledge["business_rule_items"] == [item]
    assert knowledge["requirement_items"] == []
    assert knowledge["prompt_requirements"] == ""
    assert "system_prompt" not in knowledge
