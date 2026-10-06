from types import SimpleNamespace

import pytest
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from chatbi.retrieval import index_manager as manager


@pytest.fixture()
def index_fixture(tmp_path, monkeypatch):
    calls = []
    class FakeEmbeddings(Embeddings):
        fail = False
        def embed_documents(self, texts):
            calls.append(list(texts))
            if self.fail:
                raise RuntimeError("offline provider failure")
            return [[1.0, float(i), 0.5] for i, _ in enumerate(texts)]
        def embed_query(self, text):
            raise AssertionError("初始化不应执行查询 Embedding")
    embeddings = FakeEmbeddings()
    definitions = {"one": {"description": "first"}, "two": {"description": "second"}}
    spec = manager.IndexSpec("tables", "test_tables", [
        Document(page_content=meta["description"], metadata={"name": name}) for name, meta in definitions.items()
    ], list(definitions), definitions, lambda: Chroma(collection_name="test_tables",
        embedding_function=embeddings, persist_directory=str(tmp_path / "tables"), collection_metadata={"hnsw:space": "cosine"}))
    monkeypatch.setattr(manager, "CHROMA_ROOT", tmp_path)
    monkeypatch.setattr(manager, "get_index_spec", lambda kind: spec)
    return SimpleNamespace(spec=spec, embeddings=embeddings, calls=calls, root=tmp_path)


def test_initialization_is_persistent_idempotent_and_health_never_calls_embedding(index_fixture):
    fixture = index_fixture
    assert manager.index_status("tables")["status"] == "missing"
    manager.ensure_index("tables")
    assert manager.index_status("tables") == {"status": "ready", "count": 2}
    manager.ensure_index("tables")
    manager.indexes_status({"schema_linking": True})
    assert len(fixture.calls) == 1
    assert (fixture.root / "tables" / "manifest.json").is_file()


def test_definition_change_rebuilds_instead_of_accepting_old_rows(index_fixture):
    manager.ensure_index("tables")
    index_fixture.spec.definitions["one"]["description"] = "updated"
    index_fixture.spec.documents[0].page_content = "updated"
    assert manager.index_status("tables")["status"] == "stale"
    manager.ensure_index("tables")
    assert len(index_fixture.calls) == 2
    assert manager.index_status("tables")["status"] == "ready"


def test_embedding_configuration_change_invalidates_index_but_key_rotation_does_not(index_fixture, monkeypatch):
    manager.ensure_index("tables")
    monkeypatch.setitem(manager.LLM_CONFIG, "api_key", "different-offline-key")
    assert manager.index_status("tables")["status"] == "ready"
    monkeypatch.setitem(manager.LLM_CONFIG, "embedding_model", "other-test-model")
    assert manager.index_status("tables")["status"] == "stale"
    assert "different-offline-key" not in (index_fixture.root / "tables" / "manifest.json").read_text()


def test_partial_collection_is_not_ready(index_fixture):
    store = manager.ensure_index("tables")
    store._collection.delete(ids=["two"])
    assert manager.index_status("tables")["status"] == "incomplete"


def test_failed_rebuild_does_not_publish_ready_or_delete_old_rows(index_fixture):
    store = manager.ensure_index("tables")
    index_fixture.embeddings.fail = True
    with pytest.raises(RuntimeError, match="offline provider"):
        manager.ensure_index("tables", force=True)
    assert manager.index_status("tables")["status"] == "missing"
    assert store._collection.count() == 2


def test_corrupt_manifest_is_reported(index_fixture):
    directory = index_fixture.root / "tables"
    directory.mkdir()
    (directory / "manifest.json").write_text("[]")
    assert manager.index_status("tables")["status"] == "error"


def test_disabled_retrieval_does_not_touch_vectors(tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "CHROMA_ROOT", tmp_path)
    def unexpected(*args):
        raise AssertionError("检索关闭时不应创建索引或 Embedding 客户端")
    monkeypatch.setattr(manager, "get_index_spec", unexpected)
    manager.ensure_indexes({"schema_linking": False, "indicator_rag": False})
    manager.require_indexes({})
    assert manager.indexes_status({}) == {}
    assert list(tmp_path.iterdir()) == []


def test_required_collections_follow_feature_flags():
    assert manager.required_index_kinds({"schema_linking": True}) == ["tables", "fields"]
    assert manager.required_index_kinds({"indicator_rag": True}) == ["indicators"]


@pytest.mark.parametrize("kind", ["tables", "fields", "indicators"])
def test_catalog_ids_and_documents_match_managed_definitions(kind):
    spec = manager.get_index_spec(kind)
    assert len(spec.ids) == len(spec.documents) == len(spec.definitions)
    assert len(set(spec.ids)) == len(spec.ids)
