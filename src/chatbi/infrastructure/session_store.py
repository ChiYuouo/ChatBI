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
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger("chatbi.session")

DEFAULT_DB_PATH = "data/sessions.db"

# 每次回灌给模型的最近轮数。
# 实测每轮约 170 字符，8 轮约 1.4K 字符（Prompt 总量的两成上下），
# 对上下文窗口没有压力；再长就该考虑摘要压缩而不是继续加轮数。
DEFAULT_HISTORY_TURNS = 8

# 清理策略：超过 N 天的记录删除；单会话最多保留 M 轮。
# 两者都可通过环境变量覆盖。
DEFAULT_RETENTION_DAYS = 7
DEFAULT_MAX_TURNS_PER_SESSION = 100

# 过期清理不必每次写入都跑，间隔节流即可
_PRUNE_INTERVAL_SECONDS = 3600


def _env_int(name: str, default: int) -> int:
    """读环境变量整数；缺失或非法都回退默认值，不让配置问题打挂服务。"""
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("环境变量 %s=%r 不是合法整数，回退默认值 %s", name, raw, default)
        return default

# SQL 文本落库前的截断上限，防御异常长的模型输出
_MAX_SQL_CHARS = 2000
# 归因报告等回答文本的截断上限（报告 markdown 全文可能远超此长度）
_MAX_ANSWER_CHARS = 8000
# 注入 Prompt 的历史里，回答文本只取摘要，避免报告全文撑爆上下文
_HISTORY_ANSWER_CHARS = 400

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_turn (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL,
    user_id     TEXT    NOT NULL,
    question    TEXT    NOT NULL,
    sql_text    TEXT,
    answer_text TEXT,
    created_at  TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chat_turn_lookup
    ON chat_turn (session_id, user_id, id DESC);
"""


@dataclass(slots=True)
class ConversationTurn:
    """一轮问答记录。"""

    question: str
    sql: str | None = None
    created_at: str | None = None
    # 归因分析等场景的回答文本（报告摘要/结论）；普通查询为 None
    answer: str | None = None


class SessionStore:
    """SQLite 会话历史存储。

    每次操作使用独立连接：sqlite3.Connection 默认不允许跨线程使用，
    而 FastAPI 的请求可能落在不同线程上。会话读写频率很低，
    SQLite 连接开销也小，因此不引入连接池。
    """

    def __init__(
        self,
        db_path: str | None = None,
        history_turns: int | None = None,
        retention_days: int | None = None,
        max_turns_per_session: int | None = None,
    ):
        self.db_path = db_path or os.getenv("SESSION_DB_PATH", DEFAULT_DB_PATH)
        self.history_turns = (
            history_turns
            if history_turns is not None
            else _env_int("SESSION_HISTORY_TURNS", DEFAULT_HISTORY_TURNS)
        )
        self.retention_days = (
            retention_days
            if retention_days is not None
            else _env_int("SESSION_RETENTION_DAYS", DEFAULT_RETENTION_DAYS)
        )
        self.max_turns_per_session = (
            max_turns_per_session
            if max_turns_per_session is not None
            else _env_int("SESSION_MAX_TURNS", DEFAULT_MAX_TURNS_PER_SESSION)
        )
        # 用 RLock：append_turn 持锁期间还会调用内部清理逻辑
        self._write_lock = threading.RLock()
        self._last_prune = 0.0
        self._ensure_schema()
        # 进程启动先清一次过期记录，避免长期运行的服务越堆越多
        self._prune_expired(force=True)

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
                        self._migrate_schema(conn)
                    # WAL 让读写不互相阻塞，避免并发请求下读历史被写阻塞
                    conn.execute("PRAGMA journal_mode=WAL")
                finally:
                    conn.close()
        except (sqlite3.Error, OSError) as exc:
            logger.warning("会话表初始化失败，多轮上下文不可用: %s", exc)

    @staticmethod
    def _migrate_schema(conn: sqlite3.Connection) -> None:
        """存量库的增量迁移。CREATE TABLE IF NOT EXISTS 不会给已存在的表加列，
        这里按列名逐一检查、缺失才 ALTER，保证可重复执行（幂等）。"""
        existing = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(chat_turn)").fetchall()
        }
        if "answer_text" not in existing:
            conn.execute("ALTER TABLE chat_turn ADD COLUMN answer_text TEXT")
            logger.info("会话表已迁移：chat_turn 新增 answer_text 列")

    def _prune_expired(self, force: bool = False) -> None:
        """删除超过保留期的会话记录；失败只记日志。

        节流：默认一小时内最多真正执行一次，避免每次写入都扫表。
        """
        now = time.monotonic()
        if not force and now - self._last_prune < _PRUNE_INTERVAL_SECONDS:
            return
        self._last_prune = now

        cutoff = (datetime.now() - timedelta(days=self.retention_days)).isoformat(
            timespec="seconds"
        )
        try:
            with self._write_lock:
                conn = self._connect()
                try:
                    with conn:
                        cursor = conn.execute(
                            "DELETE FROM chat_turn WHERE created_at < ?", (cutoff,)
                        )
                        deleted = cursor.rowcount
                finally:
                    conn.close()
            if deleted:
                logger.info(
                    "会话历史清理：删除 %s 条超过 %s 天的记录",
                    deleted,
                    self.retention_days,
                )
        except (sqlite3.Error, OSError) as exc:
            logger.warning("会话历史过期清理失败（不影响查询）: %s", exc)

    # ------------------------------------------------------------------ 读写

    def append_turn(
        self,
        session_id: str | None,
        user_id: str | None,
        question: str,
        sql: str | None = None,
        answer: str | None = None,
    ) -> None:
        """追加一轮问答。失败只记日志，不抛出。

        answer 用于归因分析等带结论文本的场景（如报告 markdown），
        落库前截断到 _MAX_ANSWER_CHARS，防御异常长的模型输出。
        """
        if not session_id:
            return
        owner = user_id or "anonymous"
        try:
            with self._write_lock:
                conn = self._connect()
                try:
                    with conn:
                        conn.execute(
                            "INSERT INTO chat_turn"
                            " (session_id, user_id, question, sql_text,"
                            " answer_text, created_at)"
                            " VALUES (?, ?, ?, ?, ?, ?)",
                            (
                                session_id,
                                owner,
                                question,
                                (sql or "")[:_MAX_SQL_CHARS] or None,
                                (answer or "")[:_MAX_ANSWER_CHARS] or None,
                                datetime.now().isoformat(timespec="seconds"),
                            ),
                        )
                        # 单会话只保留最近 N 轮，避免长会话把库撑大
                        conn.execute(
                            "DELETE FROM chat_turn"
                            " WHERE session_id = ? AND user_id = ?"
                            "   AND id NOT IN ("
                            "     SELECT id FROM chat_turn"
                            "     WHERE session_id = ? AND user_id = ?"
                            "     ORDER BY id DESC LIMIT ?"
                            "   )",
                            (
                                session_id,
                                owner,
                                session_id,
                                owner,
                                self.max_turns_per_session,
                            ),
                        )
                finally:
                    conn.close()
            # 顺带按节流触发一次过期清理
            self._prune_expired()
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
                    "SELECT question, sql_text, answer_text, created_at FROM chat_turn"
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
            ConversationTurn(
                question=row["question"],
                sql=row["sql_text"],
                created_at=row["created_at"],
                answer=row["answer_text"],
            )
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
            # 归因报告等回答文本只注入摘要，报告全文会撑爆上下文
            if turn.answer:
                summary = turn.answer[:_HISTORY_ANSWER_CHARS].strip()
                lines.append(f"      分析结论（摘要）：{summary}")
        return "\n".join(lines)

    def list_sessions(self, user_id: str | None) -> list[dict]:
        """列出某用户的全部会话（聚合自轮次表），按最后活动倒序。

        标题取该会话的第一个问题 —— 这是侧边栏里用户辨认对话的依据。
        会话没有独立的元数据表：一张轮次表聚合即可，避免两处存储互相同步。
        """
        if not user_id:
            return []
        try:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT t.session_id,
                           COUNT(*) AS turns,
                           MIN(t.created_at) AS created_at,
                           MAX(t.created_at) AS updated_at,
                           (SELECT t2.question FROM chat_turn t2
                            WHERE t2.session_id = t.session_id
                              AND t2.user_id = t.user_id
                            ORDER BY t2.id ASC LIMIT 1) AS title
                    FROM chat_turn t
                    WHERE t.user_id = ?
                    GROUP BY t.session_id
                    ORDER BY MAX(t.id) DESC
                    """,
                    (user_id,),
                ).fetchall()
            finally:
                conn.close()
        except (sqlite3.Error, OSError) as exc:
            logger.warning("会话列表查询失败: %s", exc)
            return []
        return [
            {
                "session_id": row["session_id"],
                "title": row["title"] or "(空会话)",
                "turns": row["turns"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def get_turns(self, session_id: str | None, user_id: str | None) -> list[ConversationTurn]:
        """取某会话的全部轮次（时间正序），用于前端回填历史对话。"""
        if not session_id:
            return []
        try:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT question, sql_text, answer_text, created_at FROM chat_turn"
                    " WHERE session_id = ? AND user_id = ?"
                    " ORDER BY id ASC",
                    (session_id, user_id or "anonymous"),
                ).fetchall()
            finally:
                conn.close()
        except (sqlite3.Error, OSError) as exc:
            logger.warning("会话轮次查询失败: %s", exc)
            return []
        return [
            ConversationTurn(
                question=row["question"],
                sql=row["sql_text"],
                created_at=row["created_at"],
                answer=row["answer_text"],
            )
            for row in rows
        ]

    def delete_session(self, session_id: str | None, user_id: str | None) -> int:
        """删除某会话在某用户名下的全部记录，返回删除条数。

        「新会话」必须调它 —— 只换 session_id 而不删数据，
        旧查询记录（含 SQL）会一直留在磁盘上直到过期清理，
        用户以为清了其实还在。
        """
        if not session_id:
            return 0
        try:
            with self._write_lock:
                conn = self._connect()
                try:
                    with conn:
                        cursor = conn.execute(
                            "DELETE FROM chat_turn WHERE session_id = ? AND user_id = ?",
                            (session_id, user_id or "anonymous"),
                        )
                        deleted = cursor.rowcount
                finally:
                    conn.close()
            if deleted:
                logger.info("会话历史已清除: session=%s 删除 %s 条", session_id, deleted)
            return deleted
        except (sqlite3.Error, OSError) as exc:
            logger.warning("会话历史删除失败: %s", exc)
            return 0


__all__ = ["ConversationTurn", "SessionStore"]
