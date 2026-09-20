"""tests 共享 fixture。

业务端点现在要求登录，走 HTTP 的测试统一用这里的 client ——
它自带一个有效的 admin token，避免每个测试重复登录。
"""

import pytest
from fastapi.testclient import TestClient

from chatbi.api.app import app
from chatbi.core.auth import AuthUser, create_token


@pytest.fixture()
def auth_headers() -> dict[str, str]:
    """按需生成一个 admin 身份的 Authorization 头。"""
    user = AuthUser(user_id="test_admin", username="tester", role="admin")
    return {"Authorization": f"Bearer {create_token(user)}"}


@pytest.fixture()
def client(auth_headers) -> TestClient:
    """带有效 token 的测试客户端（业务端点要求登录）。"""
    return TestClient(app, headers=auth_headers)


@pytest.fixture()
def anonymous_client() -> TestClient:
    """不带 token 的客户端：用于登录接口与 401 行为的测试。"""
    return TestClient(app)
