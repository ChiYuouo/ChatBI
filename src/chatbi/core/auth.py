"""
认证模块

用户存储（SQLite）+ 密码哈希（pbkdf2）+ JWT 签发/解析。

三条硬约束：
1. 用户表放独立的 data/users.db，与业务库彻底隔离 —— Text2SQL 永远不会看到它。
2. 身份只从 token 来：请求体/请求头里任何自报的 user_id/role/region 都不再被读取。
3. password 只在登录校验那一瞬间使用，绝不进 token、不落日志。
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import jwt

logger = logging.getLogger("chatbi.auth")

DEFAULT_USERS_DB_PATH = "data/users.db"

# token 有效期：8 小时，覆盖一个工作日；过期后必须重新登录
DEFAULT_TOKEN_TTL_SECONDS = 8 * 3600

# token 签名密钥：必须通过 JWT_SECRET 配置。
# 未配置时退化为随机密钥 —— 所有 token 在服务重启后失效，功能可用但不持久。
def _load_secret() -> str:
    secret = os.getenv("JWT_SECRET")
    if secret:
        return secret
    secret = secrets.token_hex(32)
    logger.warning(
        "未配置 JWT_SECRET，本次进程使用随机密钥 —— 服务重启后所有已登录 token 将失效。"
        "请在 .env 中配置固定的 JWT_SECRET。"
    )
    return secret


_JWT_SECRET = _load_secret()
_JWT_ALGORITHM = "HS256"

# pbkdf2 迭代次数：OWASP 对 sha256 的建议下限
_PBKDF2_ITERATIONS = 100_000


@dataclass(slots=True)
class AuthUser:
    """用户表里的一行（不含密码）。"""

    user_id: str
    username: str
    role: str
    region: str | None = None


def hash_password(password: str) -> str:
    """pbkdf2 哈希；盐随机生成，存储格式 `salt_hex$hash_hex`。"""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), _PBKDF2_ITERATIONS
    ).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), _PBKDF2_ITERATIONS
    ).hex()
    return secrets.compare_digest(candidate, digest)


def create_token(user: AuthUser, ttl_seconds: int = DEFAULT_TOKEN_TTL_SECONDS) -> str:
    """签发身份 token。载荷只含身份属性与过期时间，不含密码。"""
    now = int(time.time())
    payload = {
        "sub": user.user_id,
        "username": user.username,
        "role": user.role,
        "region": user.region,
        "iat": now,
        "exp": now + ttl_seconds,
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)


def decode_token(token: str) -> AuthUser | None:
    """验签 + 过期检查；任何失败都返回 None（调用方据此返回 401）。"""
    if not token:
        return None
    try:
        payload = jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
    except jwt.InvalidTokenError as exc:
        logger.info("token 校验失败: %s", exc)
        return None
    return AuthUser(
        user_id=str(payload.get("sub") or ""),
        username=str(payload.get("username") or ""),
        role=str(payload.get("role") or "admin"),
        region=payload.get("region"),
    )


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sys_user (
    user_id       TEXT PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL,
    region        TEXT,
    enabled       INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL
);
"""

# 首次启动自动创建的演示账号；密码是公开默认值，生产环境务必修改
_DEMO_USERS = [
    ("u_admin", "admin", "admin123", "admin", None),
    ("u_finance", "finance", "finance123", "finance", None),
    ("u_sales", "sales", "sales123", "sales", "欧洲"),
]


class UserStore:
    """SQLite 用户存储。每次操作独立连接，与会话存储相同的并发策略。"""

    def __init__(self, db_path: str | None = None, seed_defaults: bool = True):
        self.db_path = db_path or os.getenv("USERS_DB_PATH", DEFAULT_USERS_DB_PATH)
        self._write_lock = threading.Lock()
        self._ensure_schema()
        if seed_defaults:
            self._seed_demo_users()

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
                finally:
                    conn.close()
        except (sqlite3.Error, OSError) as exc:
            logger.warning("用户表初始化失败，登录功能不可用: %s", exc)

    def _seed_demo_users(self) -> None:
        try:
            with self._write_lock:
                conn = self._connect()
                try:
                    with conn:
                        for user_id, username, password, role, region in _DEMO_USERS:
                            conn.execute(
                                "INSERT OR IGNORE INTO sys_user"
                                " (user_id, username, password_hash, role, region, enabled, created_at)"
                                " VALUES (?, ?, ?, ?, ?, 1, ?)",
                                (
                                    user_id,
                                    username,
                                    hash_password(password),
                                    role,
                                    region,
                                    datetime.now().isoformat(timespec="seconds"),
                                ),
                            )
                finally:
                    conn.close()
        except (sqlite3.Error, OSError) as exc:
            logger.warning("演示账号初始化失败: %s", exc)

    @staticmethod
    def _row_to_user(row: sqlite3.Row) -> AuthUser | None:
        if not row or not row["enabled"]:
            return None
        return AuthUser(
            user_id=row["user_id"],
            username=row["username"],
            role=row["role"],
            region=row["region"],
        )

    # ------------------------------------------------------------------ 对外

    def authenticate(self, username: str | None, password: str | None) -> AuthUser | None:
        """登录校验：按 username 查行 → 校验密码与启用状态。失败返回 None。"""
        if not username or not password:
            return None
        try:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM sys_user WHERE username = ?", (username,)
                ).fetchone()
            finally:
                conn.close()
        except (sqlite3.Error, OSError) as exc:
            logger.warning("用户查询失败: %s", exc)
            return None

        user = self._row_to_user(row)
        if user is None:
            # 用户不存在与密码错误统一返回 None，避免暴露账号是否存在
            return None
        if not verify_password(password, row["password_hash"]):
            return None
        return user

    def get(self, user_id: str) -> AuthUser | None:
        """按 user_id 取用户（备用；当前鉴权不依赖它 —— token 自包含）。"""
        if not user_id:
            return None
        try:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM sys_user WHERE user_id = ?", (user_id,)
                ).fetchone()
            finally:
                conn.close()
        except (sqlite3.Error, OSError) as exc:
            logger.warning("用户查询失败: %s", exc)
            return None
        return self._row_to_user(row)


__all__ = [
    "AuthUser",
    "UserStore",
    "create_token",
    "decode_token",
    "hash_password",
    "verify_password",
]
