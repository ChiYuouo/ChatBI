"""业务知识、指标文件和实时 Schema 的边界；不调用真实模型服务。"""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from chatbi.bootstrap.runtime_factory import AppRuntime
from chatbi.core.security import QuerySecurityManager, SecurityError, UserContext
from chatbi.infrastructure.database import DatabaseClient, QueryExecutionError
from chatbi.infrastructure.database_schema import read_schema, render_schema
from chatbi.infrastructure.datasource_store import DataSourceStore
from chatbi.retrieval.indicator_knowledge import IndicatorKnowledge
from chatbi.text2sql.prompt_builder import build_prompt


def schema_connection():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.side_effect = [
        [("events", "处理记录")],
        [("events", "id", "int", "NO", "记录编号", "PRI", 1),
         ("events", "owner_id", "int", "YES", "所属人员", "", 2)],
        [("events", "id", "PRIMARY", None, None, 1, "PRIMARY KEY")],
    ]
    return conn, cursor


def test_schema_uses_real_metadata_and_parameterized_database_name():
    conn, cursor = schema_connection()
    metadata = read_schema(conn, "current_database")
    text = render_schema(metadata)
    assert "events（处理记录）" in text
    assert "owner_id int 可空；所属人员" in text
    assert "PRIMARY KEY：id" in text
    assert "sales_orders" not in text
    assert cursor.execute.call_count == 3
    assert all(call.args[1] == ("current_database",) for call in cursor.execute.call_args_list)


def test_incomplete_schema_is_rejected():
    conn, cursor = schema_connection()
    cursor.fetchall.side_effect = [[("events", "处理记录")], []]
    with pytest.raises(ValueError, match="无法读取字段"):
        read_schema(conn, "current_database")


def test_database_execution_schema_matches_read_metadata_and_connection_is_released():
    conn, _ = schema_connection()
    db = DatabaseClient(db_config={"database": "current_database"}, connection_factory=lambda: conn)
    metadata = db.describe_schema()
    assert db.schema == {"events": {"id": "int", "owner_id": "int"}}
    assert render_schema(metadata).startswith("表：events")
    conn.close.assert_called_once()
    manager = QuerySecurityManager()
    with pytest.raises(SecurityError):
        manager.secure_sql("SELECT missing_column FROM events", UserContext.demo_admin(), schema=db.schema)
    with pytest.raises(SecurityError):
        manager.secure_sql("SELECT id FROM events", UserContext("finance", "finance", allowed_tables=[]), schema=db.schema)
    granted = UserContext("finance", "finance", allowed_tables=["events"])
    assert "events" in manager.secure_sql("SELECT id FROM events", granted, schema=db.schema)


def test_schema_failure_does_not_fall_back_to_demo_or_leak_credentials():
    conn, cursor = schema_connection()
    cursor.execute.side_effect = RuntimeError("private-password")
    db = DatabaseClient(db_config={"database": "current_database"}, connection_factory=lambda: conn)
    with pytest.raises(QueryExecutionError) as error:
        db.describe_schema()
    assert error.value.error_type == "schema_error"
    assert "private-password" not in str(error.value)
    conn.close.assert_called_once()


@pytest.mark.parametrize("stream", [False, True])
def test_schema_read_failure_stops_model_and_sql_generation(stream):
    from chatbi.services.chatbi_service import ChatBISystem
    db = MagicMock()
    db.describe_schema.side_effect = QueryExecutionError("schema_error", "结构读取失败")
    parser = SimpleNamespace(parse=lambda text: text, validate=lambda text: True)
    llm = MagicMock()
    runtime = AppRuntime("source", parser, llm, db, None, None)
    system = ChatBISystem(runtime=runtime, app_config={"features": {}})
    try:
        if stream:
            error = dict(system.run_stream_events("记录数", security_context=UserContext.demo_admin()))["error"]
        else:
            error = system.run("记录数", security_context=UserContext.demo_admin())
        assert error["error_type"] == "database_schema_error"
        llm.generate_sql.assert_not_called()
        llm.generate_sql_stream.assert_not_called()
        db.execute_query.assert_not_called()
    finally:
        system.close()


@pytest.mark.parametrize("empty", [None, "", "  \n"])
def test_empty_business_knowledge_adds_no_rules_guards_or_examples(empty):
    _, prompt = build_prompt("记录数", use_rules=True, use_guards=True, use_few_shot=True,
                             schema_text="events(id)", rules_text=empty, guards_text=empty, examples_text=empty)
    for heading in ("【关键业务规则】", "【常见错误防护】", "【示例】"):
        assert heading not in prompt
    assert "sales_orders" not in prompt


@pytest.mark.parametrize("empty", [None, "", "  \n"])
def test_missing_schema_fails_instead_of_using_hardcoded_tables(empty):
    with pytest.raises(ValueError, match="没有可用的数据库结构"):
        build_prompt("记录数", schema_text=empty)


def test_runtime_renders_current_database_every_time_and_respects_grants():
    db = SimpleNamespace(describe_schema=MagicMock(return_value=[
        {"table_name": "events", "columns": [{"name": "id", "type": "int"}], "keys": []},
        {"table_name": "people", "columns": [{"name": "name", "type": "varchar(20)"}], "keys": []},
    ]))
    runtime = AppRuntime("source", None, None, db, None, None)
    restricted = UserContext("finance", "finance", allowed_tables=["events"])
    text = runtime.get_schema_text(user=restricted)
    assert "events" in text and "people" not in text
    db.describe_schema.return_value[0]["columns"].append({"name": "new_column", "type": "int"})
    assert "new_column" in runtime.get_schema_text(user=restricted)
    assert db.describe_schema.call_count == 2
    with pytest.raises(QueryExecutionError) as error:
        runtime.get_schema_text(user=UserContext("finance", "finance", allowed_tables=["unavailable"]))
    assert error.value.error_type == "permission_denied"


def test_indicators_load_from_json_and_never_migrate_into_knowledge(monkeypatch):
    from chatbi.bootstrap import runtime_factory
    store = MagicMock()
    store.knowledge.return_value = {"indicators": [{"name": "旧数据库副本"}]}
    monkeypatch.setattr(runtime_factory, "get_datasource_store", lambda: store)
    monkeypatch.setattr(runtime_factory, "build_database_client", lambda *args, **kwargs: SimpleNamespace())
    config = {"database": {"default_source": "default"}}
    runtime = runtime_factory.build_runtime(config)
    catalog = json.loads((Path(__file__).resolve().parents[1] / "indicators_full.json").read_text(encoding="utf-8"))
    assert set(runtime.indicator_knowledge.indicators) == {item["name"] for item in catalog["indicators"]}
    assert "旧数据库副本" not in runtime.indicator_knowledge.indicators
    custom = runtime_factory.build_runtime(config, source_id="custom")
    assert custom.indicator_knowledge.indicators == {}
    store.set_knowledge.assert_not_called()
    runtime.llm.close()
    custom.llm.close()


def test_indicator_loader_reads_updated_json_directly(tmp_path):
    path = tmp_path / "indicators.json"
    path.write_text(json.dumps({"indicators": [{"name": "记录数", "aliases": []}]}), encoding="utf-8")
    assert set(IndicatorKnowledge(path).indicators) == {"记录数"}
    path.write_text(json.dumps({"indicators": [{"name": "处理量", "aliases": []}]}), encoding="utf-8")
    assert set(IndicatorKnowledge(path).indicators) == {"处理量"}


def test_api_patches_three_sections_without_losing_legacy_data(client, monkeypatch, tmp_path):
    from chatbi.api import routes
    store = DataSourceStore(str(tmp_path / "sources.db"))
    monkeypatch.setattr(routes, "get_datasource_store", lambda: store)
    source = routes.APP_CONFIG["database"]["default_source"]
    original = {"indicators": [{"name": "历史备份"}], "legacy_texts": {"business_rules": "原规则文本"}}
    store.set_knowledge(source, original)
    url = f"/api/v1/data-sources/{source}/knowledge"
    for changes in (
        {"business_rule_items": [{"title": "状态", "content": "仅统计已处理记录"}]},
        {"error_guard_items": [{"title": "字段", "content": "核对当前库的字段"}]},
        {"sql_examples": [{"question": "记录数", "sql": "SELECT COUNT(*) FROM events"}]},
    ):
        assert client.put(url, json={"knowledge": changes}).status_code == 200
    saved = store.knowledge(source)
    assert "仅统计已处理记录" in saved["business_rules"]
    assert "核对当前库的字段" in saved["error_guards"]
    assert "SELECT COUNT(*) FROM events" in saved["few_shot_examples"]
    assert saved["indicators"] == original["indicators"]
    assert saved["legacy_texts"] == original["legacy_texts"]
    assert client.put(url, json={"knowledge": {"business_rule_items": []}}).status_code == 200
    assert store.knowledge(source)["business_rules"] == ""
    legacy = {"business_rules": "1. 新状态：只统计已审核记录"}
    assert client.put(url, json={"knowledge": legacy}).status_code == 200
    assert store.knowledge(source)["business_rule_items"] == [{"title": "新状态", "content": "只统计已审核记录"}]


def test_sales_region_policy_is_still_applied_with_real_schema():
    from schema_fixtures import TEST_SCHEMA
    sql = QuerySecurityManager().secure_sql("SELECT COUNT(*) FROM sales_orders",
        UserContext("sales", "sales", region="Europe"), schema=TEST_SCHEMA)
    assert "Europe" in sql
    assert "dim_customers" in sql
