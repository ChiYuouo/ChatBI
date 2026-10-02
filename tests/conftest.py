"""tests 共享 fixture。

业务端点现在要求登录，走 HTTP 的测试统一用这里的 client ——
它自带一个有效的 admin token，避免每个测试重复登录。
"""

import pytest
import sqlite3
from fastapi.testclient import TestClient

from chatbi.api import dependencies, routes
from chatbi.api.app import app
from chatbi.core.auth import AuthUser, UserStore, create_token, hash_password


@pytest.fixture()
def auth_store(tmp_path, monkeypatch) -> UserStore:
    """为 HTTP 测试准备隔离账户，不依赖本地 users.db。"""
    store = UserStore(str(tmp_path / "users.db"))
    with sqlite3.connect(store.db_path) as conn:
        for user_id, username, role, region in (
            ("test_admin", "tester", "admin", None),
            ("alice", "alice", "sales", "欧洲"),
            ("u_sales", "sales", "sales", "欧洲"),
        ):
            conn.execute(
                "INSERT INTO sys_user"
                " (user_id, username, password_hash, role, region, enabled, created_at)"
                " VALUES (?, ?, ?, ?, ?, 1, ?)",
                (user_id, username, hash_password("test-password"), role, region, "2026-01-01"),
            )
    monkeypatch.setattr(dependencies, "get_user_store", lambda: store)
    monkeypatch.setattr(routes, "get_user_store", lambda: store)
    return store


@pytest.fixture()
def auth_headers() -> dict[str, str]:
    """按需生成一个 admin 身份的 Authorization 头。"""
    user = AuthUser(user_id="test_admin", username="tester", role="admin")
    return {"Authorization": f"Bearer {create_token(user)}"}


@pytest.fixture()
def client(auth_headers, auth_store) -> TestClient:
    """带有效 token 的测试客户端（业务端点要求登录）。"""
    return TestClient(app, headers=auth_headers)


@pytest.fixture()
def anonymous_client(auth_store) -> TestClient:
    """不带 token 的客户端：用于登录接口与 401 行为的测试。"""
    return TestClient(app)
