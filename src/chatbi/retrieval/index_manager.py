"""统一索引构建、版本识别和只读就绪检查。健康轮询不创建 Chroma 客户端。"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from importlib import import_module
import json
import math
from pathlib import Path
import sqlite3
from typing import Callable
import uuid

from filelock import FileLock

from chatbi.core.config import CHROMA_ROOT, LLM_CONFIG


class IndexNotReady(RuntimeError):
    """启用的检索索引尚未准备好，不应静默当作检索成功。"""


@dataclass
class IndexSpec:
    kind: str
    collection: str
    documents: list
    ids: list[str]
    definitions: dict
    store_factory: Callable


def get_index_spec(kind: str) -> IndexSpec:
    # 延迟导入：检索关闭时无需加载向量依赖，也不创建 Embedding 客户端。
    from langchain_core.documents import Document
    if kind == "tables":
        module = import_module("chatbi.retrieval.table_retriever")
        definitions = module.TABLE_METADATA
        docs = [Document(page_content=meta["description"], metadata={
            "table_name": name, "domain": meta["domain"], "key_fields": meta["key_fields"],
        }) for name, meta in definitions.items()]
        collection = "table_descriptions"
    elif kind == "fields":
        module = import_module("chatbi.retrieval.field_matcher")
        definitions = module.FIELD_METADATA
        docs = [Document(page_content=meta["description"], metadata={
            "table_name": meta["table"], "field_name": meta["field"], "field_key": name, "domain": meta["domain"],
        }) for name, meta in definitions.items()]
        collection = "field_descriptions"
    elif kind == "indicators":
        module = import_module("chatbi.retrieval.indicator_retriever")
        definitions = module.load_indicators()
        docs = []
        for name, meta in definitions.items():
            aliases = "、".join(meta.get("aliases", []))
            docs.append(Document(page_content=f"指标：{name}（{aliases}）\n定义：{meta['definition']}\n计算公式：{meta['formula']}",
                metadata={"name": name, "level": meta.get("level", ""), "aliases": aliases,
                          "formula": meta["formula"], "data_source": meta.get("data_source", ""),
                          "depends_on": ",".join(meta.get("depends_on", []))}))
        collection = "indicator_definitions"
    else:
        raise ValueError(f"未知索引类型：{kind}")
    return IndexSpec(kind, collection, docs, list(definitions), definitions, module.get_vectorstore)


def fingerprint(spec: IndexSpec) -> str:
    payload = {"version": 1, "definitions": spec.definitions, "metric": "cosine",
               "embedding_model": LLM_CONFIG["embedding_model"],
               "embedding_endpoint": LLM_CONFIG["base_url"].rstrip("/")}
    # 只保存摘要，不记录 API Key 或服务凭据。
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def required_index_kinds(features: dict) -> list[str]:
    kinds = ["tables", "fields"] if features.get("schema_linking", False) else []
    if features.get("indicator_rag", False):
        kinds.append("indicators")
    return kinds


def _stored_index(spec: IndexSpec, directory: Path) -> tuple[set[str], int]:
    database = directory / "chroma.sqlite3"
    if not database.is_file():
        return set(), 0
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=0.3) as conn:
        row = conn.execute("SELECT id, dimension FROM collections WHERE name=?", (spec.collection,)).fetchone()
        if row is None:
            return set(), 0
        ids = {item[0] for item in conn.execute(
            "SELECT e.embedding_id FROM embeddings e JOIN segments s ON e.segment_id=s.id WHERE s.collection=?",
            (row[0],))}
        return ids, row[1] or 0


def index_status(kind: str, root: Path | None = None) -> dict:
    directory = (root or CHROMA_ROOT).resolve() / kind
    manifest = directory / "manifest.json"
    if not manifest.is_file():
        return {"status": "missing", "message": "索引尚未初始化或旧索引没有版本记录"}
    try:
        spec = get_index_spec(kind)
        record = json.loads(manifest.read_text(encoding="utf-8"))
        if not isinstance(record, dict):
            raise ValueError("索引版本记录不是对象")
        if record.get("fingerprint") != fingerprint(spec):
            return {"status": "stale", "message": "定义或 Embedding 配置已变更，需要重新初始化"}
        ids, dimension = _stored_index(spec, directory)
        if ids != set(spec.ids) or not dimension or dimension != record.get("dimension"):
            return {"status": "incomplete", "message": "索引内容不完整，需要重新初始化"}
        return {"status": "ready", "count": len(ids)}
    except (OSError, ValueError, sqlite3.Error):
        return {"status": "error", "message": "索引状态不可读取，需要检查目录或重新初始化"}


def indexes_status(features: dict, root: Path | None = None) -> dict[str, dict]:
    return {kind: index_status(kind, root) for kind in required_index_kinds(features)}


def require_indexes(features: dict) -> None:
    states = indexes_status(features)
    unavailable = [kind for kind, state in states.items() if state["status"] != "ready"]
    if unavailable:
        raise IndexNotReady("检索索引未就绪（" + "、".join(unavailable) + "），请运行索引初始化后重试。")


def ensure_index(kind: str, force: bool = False):
    spec = get_index_spec(kind)
    directory = CHROMA_ROOT / kind
    directory.mkdir(parents=True, exist_ok=True)
    with FileLock(str(directory / "build.lock"), timeout=60):
        if not force and index_status(kind)["status"] == "ready":
            print(f"{kind} 索引版本有效，跳过 Embedding 调用。")
            return spec.store_factory()
        manifest = directory / "manifest.json"
        manifest.unlink(missing_ok=True)
        store = spec.store_factory()
        # 先取得全部向量，再替换集合；API 失败不会先清空已有数据。
        vectors = store.embeddings.embed_documents([doc.page_content for doc in spec.documents])
        if len(vectors) != len(spec.ids) or not vectors or not vectors[0]:
            raise RuntimeError("Embedding 返回的向量数量或维度不正确。")
        dimension = len(vectors[0])
        if any(len(vector) != dimension or not all(math.isfinite(value) for value in vector) for vector in vectors):
            raise RuntimeError("Embedding 向量维度不一致或包含无效数值。")
        store.reset_collection()
        store._collection.upsert(ids=spec.ids, embeddings=vectors,
            documents=[doc.page_content for doc in spec.documents], metadatas=[doc.metadata for doc in spec.documents])
        ids, actual_dimension = _stored_index(spec, directory)
        if ids != set(spec.ids) or actual_dimension != dimension:
            raise RuntimeError("索引写入未完成，请重新初始化。")
        record = {"version": 1, "fingerprint": fingerprint(spec), "dimension": dimension, "count": len(ids)}
        temporary = directory / f"manifest.{uuid.uuid4().hex}.tmp"
        try:
            temporary.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
            temporary.replace(manifest)
        finally:
            temporary.unlink(missing_ok=True)
        print(f"{kind} 索引已就绪：{len(ids)} 条。")
        return store


def ensure_indexes(features: dict, force: bool = False) -> None:
    for kind in required_index_kinds(features):
        ensure_index(kind, force)
