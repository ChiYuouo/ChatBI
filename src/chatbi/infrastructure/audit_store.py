"""查询链路的最小持久审计：只保存身份、状态和 SQL 摘要。"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock


_write_lock = Lock()


def _db_path() -> Path:
    return Path(os.getenv("AUDIT_DB_PATH", "data/audit.db")).resolve()


def sql_digest(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


def record_event(
    trace_id: str | None,
    *,
    user_id: str,
    role: str,
    source_id: str | None,
    event: str,
    session_id: str | None = None,
    sql_hash: str | None = None,
    duration_ms: float | None = None,
    row_count: int | None = None,
    error_type: str | None = None,
) -> None:
    if not trace_id:
        return
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _write_lock, sqlite3.connect(path, timeout=5) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                trace_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                source_id TEXT,
                session_id TEXT,
                event TEXT NOT NULL,
                sql_hash TEXT,
                duration_ms REAL,
                row_count INTEGER,
                error_type TEXT
            )
        """)
        connection.execute("CREATE INDEX IF NOT EXISTS idx_audit_trace ON audit_events(trace_id, id)")
        connection.execute("""
            INSERT INTO audit_events (
                created_at, trace_id, user_id, role, source_id, session_id,
                event, sql_hash, duration_ms, row_count, error_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now(timezone.utc).isoformat(), trace_id, user_id, role,
            source_id, session_id, event, sql_hash, duration_ms, row_count, error_type,
        ))


def get_trace_events(trace_id: str, limit: int = 200) -> list[dict]:
    if not 1 <= limit <= 200:
        raise ValueError("审计记录数量超出限制")
    path = _db_path()
    if not path.exists():
        return []
    with sqlite3.connect(path, timeout=5) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute("""
            SELECT created_at, trace_id, user_id, role, source_id, session_id,
                   event, sql_hash, duration_ms, row_count, error_type
            FROM audit_events WHERE trace_id = ? ORDER BY id LIMIT ?
        """, (trace_id, limit)).fetchall()
    return [dict(row) for row in rows]
