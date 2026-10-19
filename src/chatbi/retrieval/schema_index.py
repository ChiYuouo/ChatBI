"""按数据源保存真实 Schema 的表/字段向量；结构或模型变化时自动更新。"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3

from filelock import FileLock

from chatbi.core.config import CHROMA_ROOT, LLM_CONFIG
from chatbi.execution.budget import request_timeout
from chatbi.infrastructure.database_schema import render_schema

_EMBEDDING_BATCH_SIZE = 10  # 沿用现有检索模块的批量上限，兼容当前向量服务。


def _documents(tables: list[dict]) -> tuple[list[str], list[dict], list[str]]:
    texts, metadata, ids = [], [], []
    for table in sorted(tables, key=lambda item: item["table_name"]):
        name = table["table_name"]
        entries = [("table", "", render_schema([table]))]
        for column in table["columns"]:
            text = (f"表：{name} {table.get('comment', '')}\n"
                    f"字段：{column['name']} {column['type']} {column.get('comment', '')}")
            entries.append(("field", column["name"], text))
        for kind, field, text in entries:
            texts.append(text[:6000])
            metadata.append({"kind": kind, "table_name": name, "field_name": field})
            ids.append(hashlib.sha256(json.dumps([name, kind, field]).encode()).hexdigest())
    return texts, metadata, ids


def _snapshot(source_id: str, tables: list[dict]):
    documents = _documents(tables)
    payload = {"version": 1, "tables": sorted(tables, key=lambda item: item["table_name"]),
               "model": LLM_CONFIG["embedding_model"], "endpoint": LLM_CONFIG["base_url"].rstrip("/")}
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    namespace = hashlib.sha256(source_id.encode()).hexdigest()
    return CHROMA_ROOT / "schemas" / namespace, "schema_" + digest[:48], documents


def _get_embeddings(budget=None):
    # 关闭 Schema Linking 时不会导入向量依赖，也不会创建 Embedding 客户端。
    from langchain_openai import OpenAIEmbeddings
    timeout = request_timeout(LLM_CONFIG["timeout_seconds"])
    if budget is not None:
        timeout = min(timeout, budget.remaining())
    return OpenAIEmbeddings(model=LLM_CONFIG["embedding_model"], base_url=LLM_CONFIG["base_url"],
        api_key=LLM_CONFIG["api_key"], check_embedding_ctx_length=False, chunk_size=_EMBEDDING_BATCH_SIZE,
        request_timeout=timeout, max_retries=0)


def _prepare(directory, collection_name, documents, *, force=False, budget=None):
    from langchain_chroma import Chroma
    texts, metadata, ids = documents
    if not ids:
        raise ValueError("没有可索引的数据库结构")
    store = Chroma(collection_name=collection_name, embedding_function=None,
                   persist_directory=str(directory), collection_metadata={"hnsw:space": "cosine"})
    collection = store._collection
    ready = collection.count() == len(ids) and set(collection.get(include=[])["ids"]) == set(ids)
    if force or not ready:
        # 先取得并验证全部向量，再写索引；失败时不会删除上一版本。
        vectors = []
        for start in range(0, len(texts), _EMBEDDING_BATCH_SIZE):
            if budget is not None:
                budget.remaining()
            # 每批按剩余预算创建客户端，不能沿用首次构建时的较长超时。
            vectors.extend(_get_embeddings(budget).embed_documents(texts[start:start + _EMBEDDING_BATCH_SIZE]))
        if len(vectors) != len(ids) or not vectors or not vectors[0]:
            raise ValueError("Embedding 返回的向量数量或维度无效")
        dimension = len(vectors[0])
        if any(len(vector) != dimension or not all(math.isfinite(value) for value in vector) for vector in vectors):
            raise ValueError("Embedding 返回了无效向量")
        # 同一版本损坏或 --force 时，取得全部新向量后才清理该版本的旧内容。
        store.reset_collection()
        collection = store._collection
        for start in range(0, len(ids), 128):
            if budget is not None:
                budget.remaining()
            collection.upsert(ids=ids[start:start + 128], embeddings=vectors[start:start + 128],
                              documents=texts[start:start + 128], metadatas=metadata[start:start + 128])
        if collection.count() != len(ids) or set(collection.get(include=[])["ids"]) != set(ids):
            raise RuntimeError("Schema 索引写入不完整")
    # 构建与召回共用数据源锁，旧版本没有读取者后才清理，避免结构变更不断占用空间。
    for previous in store._client.list_collections():
        name = previous.name if hasattr(previous, "name") else str(previous)
        if name.startswith("schema_") and name != collection_name:
            store._client.delete_collection(name)
    return store


def ensure_schema_index(source_id: str, tables: list[dict], *, force=False, budget=None) -> dict:
    directory, collection, documents = _snapshot(source_id, tables)
    directory.mkdir(parents=True, exist_ok=True)
    with FileLock(str(directory / "schema.lock"), timeout=min(30, budget.remaining()) if budget else 30):
        _prepare(directory, collection, documents, force=force, budget=budget)
    return {"status": "ready", "count": len(documents[2])}


def schema_index_status(source_id: str, tables: list[dict]) -> dict:
    """只读查看当前快照对应的索引，不访问数据库、不创建 Chroma 或调用模型。"""
    directory, collection, documents = _snapshot(source_id, tables)
    database = directory / "chroma.sqlite3"
    if not tables or not database.is_file():
        return {"status": "missing"}
    try:
        with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.3) as conn:
            row = conn.execute("SELECT id,dimension FROM collections WHERE name=?", (collection,)).fetchone()
            if not row:
                return {"status": "stale"}
            ids = {item[0] for item in conn.execute(
                "SELECT e.embedding_id FROM embeddings e JOIN segments s ON e.segment_id=s.id WHERE s.collection=?",
                (row[0],))}
        return {"status": "ready" if row[1] and ids == set(documents[2]) else "incomplete", "count": len(ids)}
    except (OSError, ValueError, sqlite3.Error):
        return {"status": "error"}


def recall_schema(query: str, source_id: str, tables: list[dict], allowed_names: list[str], *, budget=None) -> list[dict]:
    """同一问题只向量化一次，分别召回表与字段，检索范围限定在授权表内。"""
    if not allowed_names:
        return []
    directory, collection, documents = _snapshot(source_id, tables)
    directory.mkdir(parents=True, exist_ok=True)
    with FileLock(str(directory / "schema.lock"), timeout=min(30, budget.remaining()) if budget else 30):
        store = _prepare(directory, collection, documents, budget=budget)
        if budget is not None:
            budget.remaining()
        # 仅限制召回文本长度；完整指标/规则仍用于引用保护和最终提示词。
        vector = _get_embeddings(budget).embed_query(query[:6000])
        hits = []
        allowed = set(allowed_names)
        for kind, top_k in (("table", 3), ("field", 12)):
            count = sum(meta["kind"] == kind and meta["table_name"] in allowed for meta in documents[1])
            if not count:
                continue
            if budget is not None:
                budget.remaining()
            result = store._collection.query(query_embeddings=[vector], n_results=min(top_k, count),
                where={"$and": [{"kind": kind}, {"table_name": {"$in": allowed_names}}]},
                include=["metadatas", "distances"])
            for meta, distance in zip(result["metadatas"][0], result["distances"][0]):
                if distance <= 0.75:
                    hits.append(meta)
        return hits
