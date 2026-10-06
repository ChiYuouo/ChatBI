"""独立 Compose 首次启动：关闭检索时不调用任何真实模型或向量服务。"""
import json
import os
from pathlib import Path
import subprocess
from urllib.request import urlopen
import uuid

import pytest


@pytest.mark.skipif(os.getenv("CHATBI_COMPOSE_INTEGRATION") != "1", reason="显式开启独立 Compose 验收")
def test_first_boot_with_fresh_volumes_and_no_indexes(tmp_path):
    root = Path(__file__).resolve().parents[1]
    project = "chatbi-bootstrap-test-" + uuid.uuid4().hex[:8]
    # 只读取模板值生成编排；绝不借用当前 .env 凭据、容器名和数据卷。
    rendered = subprocess.run(["docker", "compose", "--env-file", str(root / ".env.example"),
        "-f", str(root / "docker-compose.yml"), "config", "--format", "json"],
        check=True, capture_output=True, text=True, timeout=15)
    config = json.loads(rendered.stdout)
    config["name"] = project
    config["services"].pop("frontend")
    config["volumes"] = {"chatbi-mysql-data": {}, "chatbi-index-data": {}, "app-data": {}}
    config["networks"] = {"default": {}}
    for name, service in config["services"].items():
        service.pop("container_name", None)
        service.pop("build", None)
        service.pop("ports", None)
        service.pop("restart", None)
        environment = service["environment"]
        if name == "mysql":
            environment.update(MYSQL_ROOT_PASSWORD="isolated-admin-42", DB_PASSWORD="isolated-reader-42")
        else:
            service["image"] = os.getenv("CHATBI_COMPOSE_TEST_IMAGE", "chatbi-backend:phase1-clean")
            environment.update(OPENAI_API_KEY="offline-test-key", OPENAI_BASE_URL="http://127.0.0.1:1/v1",
                               FEATURE_SCHEMA_LINKING="false", FEATURE_INDICATOR_RAG="false")
        if name == "backend":
            environment["DB_PASSWORD"] = "isolated-reader-42"
            service["volumes"] = [
                {"type": "volume", "source": "app-data", "target": "/app/data"},
                {"type": "volume", "source": "chatbi-index-data", "target": "/app/chroma_db"},
            ]
            service["ports"] = [{"target": 8000, "published": "0", "host_ip": "127.0.0.1", "protocol": "tcp"}]
    compose_file = tmp_path / "compose.json"
    compose_file.write_text(json.dumps(config), encoding="utf-8")
    command = ["docker", "compose", "-p", project, "-f", str(compose_file)]
    try:
        subprocess.run(command + ["up", "-d", "--wait", "--wait-timeout", "80"],
            check=True, capture_output=True, text=True, timeout=100)
        mapping = subprocess.run(command + ["port", "backend", "8000"],
            check=True, capture_output=True, text=True, timeout=10).stdout.strip()
        url = "http://" + mapping
        with urlopen(url + "/health", timeout=5) as response:
            health = json.load(response)
        assert health["status"] == "ok" and health["database_connected"] and health["indexes"] == {}
        subprocess.run(command + ["exec", "-T", "backend", "python", "-c",
            "from pathlib import Path; from chatbi.core.config import DB_CONFIG; "
            "from chatbi.infrastructure.database import DatabaseClient; "
            "from chatbi.core.security import UserContext; "
            "assert not list(Path('/app/chroma_db').rglob('*.sqlite3')); "
            "db=DatabaseClient(db_config=DB_CONFIG); "
            "assert db.execute_query('SELECT COUNT(*) FROM sales_orders', UserContext.demo_admin()).rows == [(5,)]; db.close()"],
            check=True, capture_output=True, text=True, timeout=10)
        # 重启保持新卷内的数据与 reader 授权，不再触发种子覆盖。
        subprocess.run(command + ["restart", "backend"], check=True, capture_output=True, timeout=15)
        subprocess.run(command + ["up", "-d", "--wait", "--wait-timeout", "45"],
            check=True, capture_output=True, timeout=60)
    finally:
        subprocess.run(command + ["down", "-v", "--remove-orphans"], check=True, capture_output=True, timeout=30)
