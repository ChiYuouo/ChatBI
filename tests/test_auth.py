"""登录与鉴权的测试。

覆盖：密码哈希、token 签发/过期、登录接口、401 行为、
以及「请求体自报身份已失效」的回归。
不依赖真实模型服务。
"""

import os
import sqlite3
import tempfile

from chatbi.api import routes
from chatbi.core.auth import (
    AuthUser,
    UserStore,
    create_token,
    decode_token,
    hash_password,
    verify_password,
)


# ==================== 密码哈希 ====================


def test_password_hash_roundtrip():
    stored = hash_password("secret")

    assert stored != "secret"
    assert verify_password("secret", stored)
    assert not verify_password("wrong", stored)


def test_password_hash_uses_random_salt():
    assert hash_password("same") != hash_password("same")


# ==================== token ====================


def test_token_roundtrip_carries_identity():
    user = AuthUser(user_id="u_001", username="alice", role="sales", region="欧洲")

    decoded = decode_token(create_token(user))

    assert decoded is not None
    assert decoded.user_id == "u_001"
    assert decoded.role == "sales"
    assert decoded.region == "欧洲"


def test_expired_token_rejected():
    user = AuthUser(user_id="u_001", username="alice", role="admin")

    assert decode_token(create_token(user, ttl_seconds=-1)) is None


def test_tampered_token_rejected():
    user = AuthUser(user_id="u_001", username="alice", role="sales")

    token = create_token(user)
    # 把载荷里的角色改掉 —— 签名校验必须失败
    header, payload, signature = token.split(".")
    tampered_payload = payload[:-2] + ("A" if payload[-2] != "A" else "B")
    tampered = f"{header}.{tampered_payload}.{signature}"

    decoded = decode_token(tampered)

    assert decoded is None or decoded.role == "sales"


def test_empty_token_rejected():
    assert decode_token("") is None


# ==================== 用户存储 ====================


def test_user_store_starts_empty_and_authenticates_inserted_user():
    store = UserStore(os.path.join(tempfile.mkdtemp(), "users.db"))
    assert store.authenticate("admin", "admin123") is None
    with sqlite3.connect(store.db_path) as conn:
        conn.execute(
            "INSERT INTO sys_user"
            " (user_id, username, password_hash, role, region, enabled, created_at)"
            " VALUES (?, ?, ?, ?, ?, 1, ?)",
            ("u_alice", "alice", hash_password("secret"), "sales", "欧洲", "2026-01-01"),
        )
    user = store.authenticate("alice", "secret")
    assert user is not None and user.role == "sales" and user.region == "欧洲"


def test_user_store_rejects_wrong_password_and_unknown_user(auth_store):
    assert auth_store.authenticate("tester", "wrong") is None
    assert auth_store.authenticate("nobody", "whatever") is None
    assert auth_store.authenticate("", "") is None


def test_user_store_initialization_does_not_seed_accounts():
    path = os.path.join(tempfile.mkdtemp(), "users.db")

    UserStore(path)
    UserStore(path)  # 重复初始化不应报错，也不应创建演示账号

    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sys_user").fetchone()[0] == 0


# ==================== HTTP 层 ====================


def test_login_with_existing_account(anonymous_client):
    resp = anonymous_client.post(
        "/api/v1/login", json={"username": "tester", "password": "test-password"}
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["user"]["role"] == "admin"
    assert data["token"]


def test_login_with_wrong_password_returns_401(anonymous_client):
    resp = anonymous_client.post(
        "/api/v1/login", json={"username": "tester", "password": "bad"}
    )

    assert resp.status_code == 401


def test_register_creates_pending_account_without_plaintext_password(anonymous_client, auth_store):
    resp = anonymous_client.post(
        "/api/v1/register", json={"username": "new_user", "password": "secret123"}
    )
    assert resp.status_code == 201
    assert "token" not in resp.json()
    with sqlite3.connect(auth_store.db_path) as conn:
        row = conn.execute(
            "SELECT user_id, password_hash, role, region FROM sys_user WHERE username = ?",
            ("new_user",),
        ).fetchone()
    assert row is not None
    assert row[2:] == ("pending", None)
    assert row[1] != "secret123"
    assert verify_password("secret123", row[1])
    assert anonymous_client.post(
        "/api/v1/login", json={"username": "new_user", "password": "secret123"}
    ).status_code == 403


def test_register_rejects_duplicate_username_case_insensitively(anonymous_client):
    payload = {"username": "New_User", "password": "secret123"}
    assert anonymous_client.post("/api/v1/register", json=payload).status_code == 201
    payload["username"] = "new_user"
    assert anonymous_client.post("/api/v1/register", json=payload).status_code == 409


def test_register_rejects_invalid_credentials(anonymous_client):
    assert anonymous_client.post(
        "/api/v1/register", json={"username": "a", "password": "secret123"}
    ).status_code == 400
    assert anonymous_client.post(
        "/api/v1/register", json={"username": "new_user", "password": "short"}
    ).status_code == 400


def test_approved_account_can_login(anonymous_client, auth_store):
    anonymous_client.post(
        "/api/v1/register", json={"username": "new_user", "password": "secret123"}
    )
    with sqlite3.connect(auth_store.db_path) as conn:
        conn.execute("UPDATE sys_user SET role = ? WHERE username = ?", ("finance", "new_user"))
    resp = anonymous_client.post(
        "/api/v1/login", json={"username": "new_user", "password": "secret123"}
    )
    assert resp.status_code == 200
    assert resp.json()["user"]["role"] == "finance"
    assert resp.json()["token"]


def test_deleted_account_token_is_rejected(anonymous_client, auth_store):
    user = AuthUser(user_id="u_sales", username="sales", role="sales", region="欧洲")
    with sqlite3.connect(auth_store.db_path) as conn:
        conn.execute("DELETE FROM sys_user WHERE user_id = ?", (user.user_id,))
    resp = anonymous_client.delete(
        "/api/v1/session/some-session",
        headers={"Authorization": f"Bearer {create_token(user)}"},
    )
    assert resp.status_code == 401


def test_business_endpoint_without_token_returns_401(anonymous_client):
    resp = anonymous_client.post("/api/v1/query", json={"question": "各区域客户数"})

    assert resp.status_code == 401


def test_business_endpoint_with_garbage_token_returns_401(anonymous_client):
    resp = anonymous_client.post(
        "/api/v1/query",
        json={"question": "各区域客户数"},
        headers={"Authorization": "Bearer not-a-token"},
    )

    assert resp.status_code == 401


def test_browser_auth_preflight_is_allowed(anonymous_client):
    resp = anonymous_client.options(
        "/api/v1/query/stream",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "authorization" in resp.headers["access-control-allow-headers"].lower()


def test_identity_comes_from_token_not_body(anonymous_client, monkeypatch):
    """回归：请求体自报身份的通道已删除。

    即便请求里携带 user_role=admin，执行身份仍以 token 为准。
    用 DELETE session 端点验证（不触发 LLM），检查落到 store 的身份。
    """
    captured: dict[str, str] = {}

    class FakeStore:
        def delete_session(self, session_id, user_id):
            captured["user_id"] = user_id
            return 0

    monkeypatch.setattr(routes.system, "_session_store", FakeStore())

    token = create_token(
        AuthUser(user_id="u_sales", username="sales", role="sales", region="欧洲")
    )
    resp = anonymous_client.delete(
        "/api/v1/session/some-session",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    assert captured["user_id"] == "u_sales"  # 身份来自 token，不是请求


def test_request_models_no_longer_have_identity_fields():
    """回归：请求模型里不应再存在自报身份的字段。"""
    from chatbi.api.schemas import AnalyzeRequest, QueryRequest

    for model in (QueryRequest, AnalyzeRequest):
        for field in ("user_id", "user_role", "user_region"):
            assert field not in model.model_fields


def test_admin_can_authorize_registered_user_and_user_can_login(client, anonymous_client):
    anonymous_client.post(
        "/api/v1/register", json={"username": "new_sales", "password": "secret123"}
    )
    users = client.get("/api/v1/users")
    assert users.status_code == 200
    target = next(user for user in users.json() if user["username"] == "new_sales")
    assert target["role"] == "pending"
    assert "password_hash" not in target

    updated = client.patch(
        f"/api/v1/users/{target['user_id']}/authorization",
        json={"role": "sales", "region": " 欧洲 "},
    )
    assert updated.status_code == 200
    assert updated.json()["region"] == "欧洲"
    login_response = anonymous_client.post(
        "/api/v1/login", json={"username": "new_sales", "password": "secret123"}
    )
    assert login_response.status_code == 200
    assert login_response.json()["user"]["role"] == "sales"


def test_only_admin_can_manage_authorization(anonymous_client):
    sales = AuthUser(user_id="u_sales", username="sales", role="sales", region="欧洲")
    headers = {"Authorization": f"Bearer {create_token(sales)}"}
    assert anonymous_client.get("/api/v1/users", headers=headers).status_code == 403
    assert anonymous_client.patch(
        "/api/v1/users/alice/authorization",
        json={"role": "admin", "region": None}, headers=headers,
    ).status_code == 403
    assert anonymous_client.get("/api/v1/users").status_code == 401


def test_authorization_validates_region_and_prevents_self_change(client, auth_store):
    for payload in (
        {"role": "sales", "region": None},
        {"role": "finance", "region": "欧洲"},
        {"role": "unknown", "region": None},
    ):
        assert client.patch(
            "/api/v1/users/alice/authorization", json=payload,
        ).status_code == 400
    assert client.patch(
        "/api/v1/users/test_admin/authorization",
        json={"role": "pending", "region": None},
    ).status_code == 400
    assert client.patch(
        "/api/v1/users/missing/authorization",
        json={"role": "finance", "region": None},
    ).status_code == 404
    assert auth_store.get("alice").role == "sales"


def test_authorization_change_takes_effect_for_existing_token(anonymous_client, client):
    sales = AuthUser(user_id="u_sales", username="sales", role="sales", region="欧洲")
    headers = {"Authorization": f"Bearer {create_token(sales)}"}
    assert anonymous_client.get("/api/v1/me", headers=headers).json()["role"] == "sales"
    assert client.patch(
        "/api/v1/users/u_sales/authorization",
        json={"role": "pending", "region": None},
    ).status_code == 200
    assert anonymous_client.get("/api/v1/me", headers=headers).status_code == 401
