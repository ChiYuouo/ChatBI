"""真实 Chroma 存储配合本地向量替身，验证动态 Schema 链路，不调用远程模型。"""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from chatbi.bootstrap.runtime_factory import AppRuntime
from chatbi.contracts.execution import QueryExecutionResult
from chatbi.core.security import QuerySecurityManager, SchemaRequiredError, SecurityError, UserContext
from chatbi.execution.budget import ExecutionLimits
from chatbi.execution.query_executor import QueryExecutor
from chatbi.infrastructure.datasource_store import DataSourceStore
from chatbi.retrieval import schema_index, schema_linker


def table(name, fields, keys=()):
    return {"table_name": name, "comment": "测试业务表", "keys": list(keys),
            "columns": [{"name": field, "type": "varchar(30)", "comment": "业务字段"} for field in fields]}


@pytest.fixture()
def vectors(tmp_path, monkeypatch):
    class Embeddings:
        calls = 0
        fail = False

        def embed_documents(self, texts):
            self.calls += 1
            if len(texts) > 10:
                raise ValueError("当前向量服务每批最多接受 10 条")
            if self.fail:
                raise RuntimeError("本地模拟向量服务不可用")
            return [[1.0, 0.5, 0.25] for _ in texts]

        def embed_query(self, query):
            return [1.0, 0.5, 0.25]

    embeddings = Embeddings()
    monkeypatch.setattr(schema_index, "CHROMA_ROOT", tmp_path / "vectors")
    monkeypatch.setattr(schema_index, "_get_embeddings", lambda budget=None: embeddings)
    return embeddings


def test_schema_vectors_persist_and_reuse_without_reembedding(vectors):
    tables = [table("events", ["id", "status"]), table("people", ["id", "name"])]
    assert schema_index.ensure_schema_index("source_a", tables) == {"status": "ready", "count": 6}
    schema_index.ensure_schema_index("source_a", tables)
    assert vectors.calls == 1
    assert schema_index.schema_index_status("source_a", tables) == {"status": "ready", "count": 6}
    hits = schema_index.recall_schema("记录状态", "source_a", tables, ["events"])
    assert hits and all(hit["table_name"] == "events" for hit in hits)
    assert vectors.calls == 1


def test_schema_vector_batches_respect_provider_limit(vectors):
    tables = [table("events", [f"column_{index}" for index in range(20)])]
    assert schema_index.ensure_schema_index("source", tables) == {"status": "ready", "count": 21}
    assert vectors.calls == 3


def test_changed_schema_removes_stale_tables_fields_and_index_version(vectors):
    previous = [table("events", ["id", "old_status"]), table("retired", ["id"])]
    current = [table("events", ["id", "new_status"])]
    schema_index.ensure_schema_index("source_a", previous)
    schema_index.ensure_schema_index("source_a", current)
    assert vectors.calls == 2
    assert schema_index.schema_index_status("source_a", previous)["status"] == "stale"
    hits = schema_index.recall_schema("记录状态", "source_a", current, ["events"])
    assert {hit["field_name"] for hit in hits if hit["kind"] == "field"} == {"id", "new_status"}


def test_sources_with_identical_names_keep_separate_indexes(vectors):
    first, second = [table("events", ["id"])], [table("events", ["name"])]
    schema_index.ensure_schema_index("first", first)
    schema_index.ensure_schema_index("second", second)
    assert schema_index.schema_index_status("first", first)["status"] == "ready"
    assert schema_index.schema_index_status("second", second)["status"] == "ready"
    assert schema_index._snapshot("first", first)[0] != schema_index._snapshot("second", second)[0]


def test_embedding_failure_preserves_previous_complete_version(vectors):
    previous = [table("events", ["id"])]
    current = [table("events", ["id", "status"])]
    schema_index.ensure_schema_index("source", previous)
    vectors.fail = True
    with pytest.raises(RuntimeError):
        schema_index.ensure_schema_index("source", current)
    assert schema_index.schema_index_status("source", previous)["status"] == "ready"
    vectors.fail = False
    schema_index.ensure_schema_index("source", current)
    assert schema_index.schema_index_status("source", current)["status"] == "ready"


def test_schema_status_does_not_create_indexes_or_embedding_clients(tmp_path, monkeypatch):
    root = tmp_path / "absent"
    monkeypatch.setattr(schema_index, "CHROMA_ROOT", root)
    monkeypatch.setattr(schema_index, "_get_embeddings", lambda *args: pytest.fail("只读状态不能调用模型"))
    assert schema_index.schema_index_status("source", [table("events", ["id"])])["status"] == "missing"
    assert not root.exists()


@pytest.mark.parametrize("config_key", ["embedding_model", "base_url"])
def test_embedding_configuration_changes_index_version(vectors, monkeypatch, config_key):
    tables = [table("events", ["id"])]
    schema_index.ensure_schema_index("source", tables)
    monkeypatch.setitem(schema_index.LLM_CONFIG, config_key, "changed-test-configuration")
    assert schema_index.schema_index_status("source", tables)["status"] == "stale"
    schema_index.ensure_schema_index("source", tables)
    assert vectors.calls == 2


def test_key_rotation_does_not_reembed_schema(vectors, monkeypatch):
    tables = [table("events", ["id"])]
    schema_index.ensure_schema_index("source", tables)
    monkeypatch.setitem(schema_index.LLM_CONFIG, "api_key", "rotated-test-key")
    schema_index.ensure_schema_index("source", tables)
    assert vectors.calls == 1


def test_linking_adds_real_foreign_key_bridge_and_preserves_required_fields(monkeypatch):
    tables = [
        table("orders", ["id", "amount", "notes"], [{"kind": "PRIMARY KEY", "column": "id"}]),
        table("items", ["order_id", "product_id"], [
            {"kind": "FOREIGN KEY", "column": "order_id", "referenced_table": "orders", "referenced_column": "id"},
            {"kind": "FOREIGN KEY", "column": "product_id", "referenced_table": "products", "referenced_column": "id"}]),
        table("products", ["id", "name", "notes"], [{"kind": "PRIMARY KEY", "column": "id"}]),
        table("audit", ["id"]),
    ]
    hits = [{"kind": "field", "table_name": "orders", "field_name": "amount"},
            {"kind": "field", "table_name": "products", "field_name": "name"}]
    monkeypatch.setattr(schema_linker, "recall_schema", lambda *args, **kwargs: hits)
    before = deepcopy(tables)
    linked = schema_linker.link_schema("统计商品金额", "source", tables, tables)
    assert [item["table_name"] for item in linked] == ["orders", "items", "products"]
    assert {field["name"] for field in linked[0]["columns"]} == {"id", "amount"}
    assert {field["name"] for field in linked[2]["columns"]} == {"id", "name"}
    protected = schema_linker.link_schema("统计商品金额", "source", tables, tables,
                                          required_context="计算公式：SUM(orders.amount)")
    assert "notes" in {field["name"] for field in protected[0]["columns"]}
    assert tables == before


def test_disconnected_or_empty_recall_uses_current_visible_schema(monkeypatch):
    tables = [table("events", ["id"]), table("people", ["id"])]
    monkeypatch.setattr(schema_linker, "recall_schema", lambda *args, **kwargs: [
        {"kind": "table", "table_name": "events"}, {"kind": "table", "table_name": "people"}])
    assert schema_linker.link_schema("统计记录", "source", tables, tables) is tables
    monkeypatch.setattr(schema_linker, "recall_schema", lambda *args, **kwargs: [])
    assert schema_linker.link_schema("统计记录", "source", tables, tables) is tables


@pytest.mark.parametrize("enabled", [False, True])
def test_runtime_fallback_and_disabled_linking_use_only_authorized_real_schema(tmp_path, monkeypatch, enabled):
    from chatbi.bootstrap import runtime_factory
    store = DataSourceStore(str(tmp_path / "sources.db"))
    monkeypatch.setattr(runtime_factory, "get_datasource_store", lambda: store)
    callback = MagicMock(side_effect=RuntimeError("本地模拟索引故障"))
    monkeypatch.setattr(schema_linker, "link_schema", callback)
    tables = [table("events", ["id", "status"]), table("hidden", ["secret"])]
    runtime = AppRuntime("source", None, None, SimpleNamespace(describe_schema=lambda budget: tables), None, None)
    text = runtime.get_schema_text(user=UserContext("f", "finance", allowed_tables=["events"]),
                                  question="统计记录", use_schema_linking=enabled)
    assert "events" in text and "hidden" not in text and "sales_orders" not in text
    assert callback.call_count == int(enabled)
    assert store.tables("source") == tables


def test_sql_policy_requires_real_metadata_for_physical_tables():
    manager = QuerySecurityManager()
    user = UserContext.demo_admin()
    with pytest.raises(SchemaRequiredError):
        manager.secure_sql("SELECT COUNT(*) FROM events", user)
    assert "SELECT" in manager.secure_sql("SELECT 1", user)
    assert "events" in manager.secure_sql("SELECT id FROM events", user, schema={"events": {"id": "int"}})
    with pytest.raises(SecurityError):
        manager.secure_sql("SELECT id FROM other_events", user, schema={"events": {"id": "int"}})


def test_direct_executor_loads_metadata_before_query_instead_of_demo_fallback():
    metadata = [table("events", ["id"])]
    describe = MagicMock(return_value=metadata)
    database = SimpleNamespace(source_id="custom", schema=None, limits=ExecutionLimits(), describe_schema=describe)
    database._execute_secured = lambda original, secured, context, budget: QueryExecutionResult(
        original, secured, context.source_id, ["count"], [(1,)], 1.0)
    result = QueryExecutor(database, QuerySecurityManager()).execute(
        "SELECT COUNT(*) AS count FROM events", UserContext.demo_admin())
    assert result.rows == [(1,)] and result.source_id == "custom"
    describe.assert_called_once()
