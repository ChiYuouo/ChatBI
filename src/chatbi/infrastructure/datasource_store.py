"""数据源连接、结构快照和业务知识的 SQLite 存储。"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet
from chatbi.infrastructure.datasource_knowledge import normalize_knowledge, validate_knowledge_entries


class DataSourceStore:
    """数据源元数据保存在独立 SQLite 文件，数据库密码只以密文落盘。"""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or os.getenv("DATASOURCES_DB_PATH", "data/datasources.db")
        self._lock = threading.RLock()
        self._ensure_schema()

    def _connect(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _connection(self):
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _ensure_schema(self):
        with self._connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS datasource (
                    source_id TEXT PRIMARY KEY, name TEXT NOT NULL, config_json TEXT NOT NULL,
                    password_cipher TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
                    config_version INTEGER NOT NULL DEFAULT 1, created_by TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS datasource_table (
                    source_id TEXT NOT NULL, table_name TEXT NOT NULL, metadata_json TEXT NOT NULL,
                    PRIMARY KEY (source_id, table_name),
                    FOREIGN KEY (source_id) REFERENCES datasource(source_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS datasource_schema (
                    source_id TEXT PRIMARY KEY, metadata_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS datasource_grant (
                    source_id TEXT NOT NULL, user_id TEXT NOT NULL, table_names_json TEXT NOT NULL,
                    PRIMARY KEY (source_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS datasource_knowledge (
                    source_id TEXT PRIMARY KEY, knowledge_json TEXT NOT NULL
                );
            """)

    @staticmethod
    def _cipher():
        key = os.getenv("DATASOURCE_ENCRYPTION_KEY", "").strip()
        if not key:
            raise ValueError("管理员尚未配置 DATASOURCE_ENCRYPTION_KEY，无法安全保存数据库密码")
        try:
            return Fernet(key.encode("ascii"))
        except Exception as exc:
            raise ValueError("DATASOURCE_ENCRYPTION_KEY 格式无效") from exc

    def create(self, name: str, config: dict[str, Any], password: str, created_by: str, *, tables: list[dict]) -> dict:
        source_id = "mysql_" + uuid.uuid4().hex[:16]
        cipher = self._cipher().encrypt(password.encode("utf-8")).decode("ascii")
        safe_config = {k: v for k, v in config.items() if k not in {"password", "driver"}}
        with self._lock, self._connection() as conn:
            conn.execute("INSERT INTO datasource(source_id,name,config_json,password_cipher,created_by) VALUES(?,?,?,?,?)",
                         (source_id, name.strip(), json.dumps(safe_config), cipher, created_by))
            conn.execute("INSERT INTO datasource_schema VALUES(?,?)", (source_id,
                json.dumps(sorted(tables, key=lambda table: table["table_name"]), ensure_ascii=False, sort_keys=True)))
        return {"source_id": source_id, "name": name.strip(), "enabled": True, "config_version": 1}

    def _row_config(self, row):
        config = json.loads(row["config_json"])
        config["password"] = self._cipher().decrypt(row["password_cipher"].encode("ascii")).decode("utf-8")
        config["driver"] = "mysql"
        return config

    def get(self, source_id: str, include_secret: bool = False) -> dict | None:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM datasource WHERE source_id=?", (source_id,)).fetchone()
            if not row:
                return None
            item = {"source_id": row["source_id"], "name": row["name"], "enabled": bool(row["enabled"]),
                    "config_version": row["config_version"], "config": self._row_config(row) if include_secret else json.loads(row["config_json"])}
            return item

    def list(self, user_id: str | None = None, admin: bool = False) -> list[dict]:
        with self._connection() as conn:
            if admin:
                rows = conn.execute("SELECT source_id,name,enabled,config_version FROM datasource ORDER BY name").fetchall()
            else:
                rows = conn.execute("""SELECT d.source_id,d.name,d.enabled,d.config_version
                    FROM datasource d JOIN datasource_grant g ON g.source_id=d.source_id
                    WHERE g.user_id=? AND d.enabled=1 ORDER BY d.name""", (user_id,)).fetchall()
            return [dict(r) | {"enabled": bool(r["enabled"])} for r in rows]

    def tables(self, source_id: str) -> list[dict]:
        with self._connection() as conn:
            snapshot = conn.execute("SELECT metadata_json FROM datasource_schema WHERE source_id=?", (source_id,)).fetchone()
            if snapshot is not None:
                return json.loads(snapshot[0])
            # 兼容旧版本按表保存的结构；下次成功读取真实结构后写入新快照。
            rows = conn.execute("SELECT metadata_json FROM datasource_table WHERE source_id=? ORDER BY table_name", (source_id,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def save_schema(self, source_id: str, tables: list[dict]) -> None:
        """替换当前结构快照（包括已删除的表），不改变连接或业务知识。"""
        metadata = json.dumps(sorted(tables, key=lambda table: table["table_name"]), ensure_ascii=False, sort_keys=True)
        with self._lock, self._connection() as conn:
            # .env 默认源也有快照，但不复制其连接和密码；内容不变时不产生写入。
            conn.execute("""INSERT INTO datasource_schema VALUES(?,?) ON CONFLICT(source_id)
                DO UPDATE SET metadata_json=excluded.metadata_json
                WHERE datasource_schema.metadata_json<>excluded.metadata_json""", (source_id, metadata))

    # 仅兼容已保存的旧表授权；本轮不再提供授权编辑。
    def allowed_tables(self, source_id: str, user_id: str, is_admin: bool) -> list[str]:
        if is_admin:
            return [t["table_name"] for t in self.tables(source_id)]
        with self._connection() as conn:
            row = conn.execute("SELECT table_names_json FROM datasource_grant WHERE source_id=? AND user_id=?", (source_id, user_id)).fetchone()
        return json.loads(row[0]) if row else []

    def set_knowledge(self, source_id: str, knowledge: dict):
        # 业务知识按源保存，模型生成建议不得覆盖此处已确认内容。
        validate_knowledge_entries(knowledge)
        knowledge = normalize_knowledge(knowledge)
        with self._lock, self._connection() as conn:
            conn.execute("INSERT INTO datasource_knowledge VALUES(?,?) ON CONFLICT(source_id) DO UPDATE SET knowledge_json=excluded.knowledge_json",
                         (source_id, json.dumps(knowledge, ensure_ascii=False)))
            conn.execute("UPDATE datasource SET config_version=config_version+1 WHERE source_id=?", (source_id,))

    def knowledge(self, source_id: str) -> dict:
        with self._connection() as conn:
            row = conn.execute("SELECT knowledge_json FROM datasource_knowledge WHERE source_id=?", (source_id,)).fetchone()
        return normalize_knowledge(json.loads(row[0])) if row else {}


_store: DataSourceStore | None = None
_store_lock = threading.Lock()

def get_datasource_store() -> DataSourceStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = DataSourceStore()
        return _store
