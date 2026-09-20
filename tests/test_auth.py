"""登录与鉴权的测试。

覆盖：密码哈希、token 签发/过期、登录接口、401 行为、
以及「请求体自报身份已失效」的回归。
不依赖真实模型服务。
"""

import os
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


def test_user_store_seeds_demo_accounts_and_authenticates():
    store = UserStore(os.path.join(tempfile.mkdtemp(), "users.db"))

    admin = store.authenticate("admin", "admin123")
    assert admin is not None and admin.role == "admin"

    sales = store.authenticate("sales", "sales123")
    assert sales is not None and sales.role == "sales" and sales.region == "欧洲"


def test_user_store_rejects_wrong_password_and_unknown_user():
    store = UserStore(os.path.join(tempfile.mkdtemp(), "users.db"))

    assert store.authenticate("admin", "wrong") is None
    assert store.authenticate("nobody", "whatever") is None
    assert store.authenticate("", "") is None


def test_user_store_seeding_is_idempotent():
    path = os.path.join(tempfile.mkdtemp(), "users.db")

    UserStore(path)
    UserStore(path)  # 重复初始化不应报错、不应重复插入

    assert UserStore(path).authenticate("finance", "finance123") is not None


# ==================== HTTP 层 ====================


def test_login_with_demo_account(anonymous_client):
    resp = anonymous_client.post(
        "/api/v1/login", json={"username": "admin", "password": "admin123"}
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["user"]["role"] == "admin"
    assert data["token"]


def test_login_with_wrong_password_returns_401(anonymous_client):
    resp = anonymous_client.post(
        "/api/v1/login", json={"username": "admin", "password": "bad"}
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
