"""测试未保存连接与最终保存使用同一探测逻辑，且探测不会写入数据源。"""
from unittest.mock import MagicMock

import pymysql
import pytest
from cryptography.fernet import Fernet

from chatbi.api import routes
from chatbi.infrastructure.datasource_store import DataSourceStore


@pytest.fixture()
def draft_environment(tmp_path, monkeypatch):
    store = DataSourceStore(str(tmp_path / "sources.db"))
    monkeypatch.setattr(routes, "get_datasource_store", lambda: store)
    monkeypatch.setenv("DATASOURCE_ENCRYPTION_KEY", Fernet.generate_key().decode())
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchall.side_effect = lambda: {
        1: [("events", "处理记录")],
        2: [("events", "id", "int", "NO", "编号", "PRI", 1)],
        0: [("events", "id", "PRIMARY", None, None, 1, "PRIMARY KEY")],
    }[conn.cursor.return_value.__enter__.return_value.execute.call_count % 3]
    connect = MagicMock(return_value=conn)
    monkeypatch.setattr(routes.pymysql, "connect", connect)
    return store, connect, conn


def draft():
    return {"host": "test.invalid", "port": 3306, "database": "demo", "user": "reader", "password": "offline-test", "charset": "utf8mb4"}


def test_testing_draft_never_creates_source_and_does_not_need_encryption_key(client, draft_environment, monkeypatch):
    store, connect, conn = draft_environment
    monkeypatch.delenv("DATASOURCE_ENCRYPTION_KEY")
    response = client.post("/api/v1/data-sources/test-connection", json=draft())
    assert response.status_code == 200, response.text
    assert response.json() == {"success": True, "visible_tables": 1}
    assert store.list(admin=True) == []
    conn.close.assert_called_once()
    assert "offline-test" not in response.text


def test_source_is_only_created_after_save_and_is_rechecked(client, draft_environment):
    store, connect, conn = draft_environment
    assert client.post("/api/v1/data-sources/test-connection", json=draft()).status_code == 200
    assert store.list(admin=True) == []
    response = client.post("/api/v1/data-sources", json={"name": "运营库", **draft()})
    assert response.status_code == 201, response.text
    assert len(store.list(admin=True)) == 1
    assert connect.call_count == 2
    assert conn.close.call_count == 2
    saved = store.get(response.json()["source_id"], include_secret=True)
    assert saved["config"]["password"] == "offline-test"


def test_failed_test_and_failed_save_leave_no_data(client, draft_environment):
    store, connect, conn = draft_environment
    connect.side_effect = pymysql.OperationalError("offline connection failure")
    assert client.post("/api/v1/data-sources/test-connection", json=draft()).status_code == 503
    assert client.post("/api/v1/data-sources", json={"name": "运营库", **draft()}).status_code == 503
    assert store.list(admin=True) == []


def test_failed_metadata_probe_closes_connection(client, draft_environment):
    store, connect, conn = draft_environment
    conn.cursor.return_value.__enter__.return_value.execute.side_effect = pymysql.OperationalError("metadata denied")
    assert client.post("/api/v1/data-sources/test-connection", json=draft()).status_code == 503
    conn.close.assert_called_once()
    assert store.list(admin=True) == []


def test_connection_probe_requires_admin(anonymous_client, draft_environment):
    from chatbi.core.auth import AuthUser, create_token
    store, connect, conn = draft_environment
    assert anonymous_client.post("/api/v1/data-sources/test-connection", json=draft()).status_code == 401
    token = create_token(AuthUser(user_id="alice", username="alice", role="sales", region="欧洲"))
    response = anonymous_client.post("/api/v1/data-sources/test-connection", json=draft(), headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
    connect.assert_not_called()
