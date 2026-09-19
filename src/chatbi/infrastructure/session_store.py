"""
会话历史存储模块（SQLite）

为单跳查询链路提供多轮上下文（第 0-1 步）。

三条设计约束：
1. 按 session_id + user_id 双键隔离 —— 即便拿到别人的 session_id 也读不到别人的历史。
2. 只记录「用户问题 + 生成的 SQL」，**不存结果数据** —— 结果一旦进 Prompt，
   模型可能在回答文本里复述，从而绕过 secure_sql 的行级过滤。
3. 存储失败一律降级为「无历史」，绝不阻断查询主链路。
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("chatbi.session")

DEFAULT_DB_PATH = "data/sessions.db"
DEFAULT_HISTORY_TURNS = 3

# SQL 文本落库前的截断上限，防御异常长的模型输出
_MAX_SQL_CHARS = 2000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_turn (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT    NOT NULL,
    user_id    TEXT    NOT NULL,
    question   TEXT    NOT NULL,
    sql_text   TEXT,
    created_at TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chat_turn_lookup
    ON chat_turn (session_id, user_id, id DESC);
"""


@dataclass(slots=True)
class ConversationTurn:
    """一轮问答记录。"""

    question: str
    sql: str | None = None


class SessionStore:
    """SQLite 会话历史存储。

    每次操作使用独立连接：sqlite3.Connection 默认不允许跨线程使用，
    而 FastAPI 的请求可能落在不同线程上。会话读写频率很低，
    SQLite 连接开销也小，因此不引入连接池。
    """

    def __init__(
        self,
        db_path: str | None = None,
        history_turns: int = DEFAULT_HISTORY_TURNS,
    ):
        self.db_path = db_path or os.getenv("SESSION_DB_PATH", DEFAULT_DB_PATH)
        self.history_turns = history_turns
        self._write_lock = threading.Lock()
        self._ensure_schema()

    # ------------------------------------------------------------------ 内部

    def _connect(self) -> sqlite3.Connection:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        try:
            with self._write_lock:
                conn = self._connect()
                try:
                    with conn:
                        conn.executescript(_SCHEMA)
                    # WAL 让读写不互相阻塞，避免并发请求下读历史被写阻塞
                    conn.execute("PRAGMA journal_mode=WAL")
                finally:
                    conn.close()
        except (sqlite3.Error, OSError) as exc:
            logger.warning("会话表初始化失败，多轮上下文不可用: %s", exc)

    # ------------------------------------------------------------------ 读写

    def append_turn(
        self,
        session_id: str | None,
        user_id: str | None,
        question: str,
        sql: str | None = None,
    ) -> None:
        """追加一轮问答。失败只记日志，不抛出。"""
        if not session_id:
            return
        try:
            with self._write_lock:
                conn = self._connect()
                try:
                    with conn:
                        conn.execute(
                            "INSERT INTO chat_turn"
                            " (session_id, user_id, question, sql_text, created_at)"
                            " VALUES (?, ?, ?, ?, ?)",
                            (
                                session_id,
                                user_id or "anonymous",
                                question,
                                (sql or "")[:_MAX_SQL_CHARS] or None,
                                datetime.now().isoformat(timespec="seconds"),
                            ),
                        )
                finally:
                    conn.close()
        except (sqlite3.Error, OSError) as exc:
            logger.warning("会话历史写入失败（不影响本次查询）: %s", exc)

    def recent_turns(
        self,
        session_id: str | None,
        user_id: str | None,
        limit: int | None = None,
    ) -> list[ConversationTurn]:
        """取最近 N 轮，按时间正序返回（便于直接渲染）。失败返回空列表。"""
        if not session_id:
            return []
        resolved_limit = limit or self.history_turns
        try:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT question, sql_text FROM chat_turn"
                    " WHERE session_id = ? AND user_id = ?"
                    " ORDER BY id DESC LIMIT ?",
                    (session_id, user_id or "anonymous", resolved_limit),
                ).fetchall()
            finally:
                conn.close()
        except (sqlite3.Error, OSError) as exc:
            logger.warning("会话历史读取失败，本次按无历史处理: %s", exc)
            return []
        return [
            ConversationTurn(question=row["question"], sql=row["sql_text"])
            for row in reversed(rows)
        ]

    def render_history(
        self,
        session_id: str | None,
        user_id: str | None,
        limit: int | None = None,
    ) -> str:
        """渲染为可直接注入 Prompt 的文本块；无历史时返回空字符串。"""
        turns = self.recent_turns(session_id, user_id, limit=limit)
        if not turns:
            return ""

        lines: list[str] = []
        for index, turn in enumerate(turns, start=1):
            lines.append(f"第{index}轮 用户问：{turn.question}")
            if turn.sql:
                lines.append(f"      生成SQL：{turn.sql}")
        return "\n".join(lines)


__all__ = ["ConversationTurn", "SessionStore"]
