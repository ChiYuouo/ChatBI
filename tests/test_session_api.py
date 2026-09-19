"""会话历史接口的测试。

用假 SessionStore 替换真实存储，只验证路由与参数传递，不落任何数据库文件。
"""

import pytest
from fastapi.testclient import TestClient

from chatbi.api import routes
from chatbi.api.app import app


@pytest.fixture()
def client():
    return TestClient(app)


class FakeSessionStore:
    def __init__(self, deleted: int = 3):
        self.deleted = deleted
        self.calls: list[tuple[str, str]] = []

    def delete_session(self, session_id, user_id) -> int:
        self.calls.append((session_id, user_id))
        return self.deleted


def test_clear_session_deletes_and_reports_count(client, monkeypatch):
    fake = FakeSessionStore(deleted=3)
    monkeypatch.setattr(routes.system, "_session_store", fake)

    response = client.delete("/api/v1/session/abc-123")

    assert response.status_code == 200
    assert response.json() == {"session_id": "abc-123", "deleted": 3}
    assert fake.calls == [("abc-123", "demo_admin")]


def test_clear_session_uses_request_user(client, monkeypatch):
    """删除范围必须限定在发起请求的用户名下，不能跨用户误删。"""
    fake = FakeSessionStore()
    monkeypatch.setattr(routes.system, "_session_store", fake)

    client.delete("/api/v1/session/abc", headers={"x-user-id": "alice"})

    assert fake.calls == [("abc", "alice")]
