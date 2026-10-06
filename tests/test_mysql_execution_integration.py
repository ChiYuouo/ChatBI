"""显式开启的 MySQL 8.4 集成测试；只创建和销毁本模块自己的临时容器。"""
import os
from pathlib import Path
import subprocess
import time
import uuid

import pymysql
import pytest

from chatbi.core.security import UserContext
from chatbi.execution.budget import ExecutionLimits
from chatbi.infrastructure.database import DatabaseClient, QueryExecutionError

pytestmark = pytest.mark.skipif(os.getenv("CHATBI_MYSQL_INTEGRATION") != "1",
    reason="设 CHATBI_MYSQL_INTEGRATION=1 才会创建独立的 MySQL 测试容器")


@pytest.fixture(scope="module")
def mysql_source():
    root = Path(__file__).resolve().parents[1]
    name = "chatbi-phase1-test-" + uuid.uuid4().hex[:10]
    # 只用于临时容器的凭据，包含引号和反斜杠以验证初始化脚本的转义。
    reader_password = "Test'\\Reader-42"
    test_env = {**os.environ, "MYSQL_ROOT_PASSWORD": "temporary-test-admin-42",
        "MYSQL_DATABASE": "chatbi_mvp", "DB_USER": "chatbi_reader", "DB_PASSWORD": reader_password}
    created = False
    try:
        subprocess.run(["docker", "run", "-d", "--name", name, "--label", "chatbi.execution-test=true",
            "-e", "MYSQL_ROOT_PASSWORD", "-e", "MYSQL_DATABASE", "-e", "DB_USER", "-e", "DB_PASSWORD",
            "-p", "127.0.0.1::3306", "-v", f"{root / 'docker/mysql/init'}:/docker-entrypoint-initdb.d:ro",
            "mysql:8.4"], env=test_env, check=True, capture_output=True, timeout=30)
        created = True
        mapping = subprocess.run(["docker", "port", name, "3306"], check=True,
            capture_output=True, text=True, timeout=10).stdout.strip()
        config = dict(host="127.0.0.1", port=int(mapping.rsplit(":", 1)[1]), user="chatbi_reader",
            password=reader_password, database="chatbi_mvp", charset="utf8mb4", autocommit=True,
            connect_timeout=2, read_timeout=3, write_timeout=3)
        deadline = time.monotonic() + 55
        while True:
            try:
                conn = pymysql.connect(**config)
                conn.close()
                break
            except pymysql.MySQLError:
                if time.monotonic() >= deadline:
                    pytest.fail("临时 MySQL 未能在 55 秒内准备就绪；没有访问现有数据库。")
                time.sleep(0.5)
        yield config
    finally:
        if created:
            subprocess.run(["docker", "rm", "-f", "-v", name], check=True, capture_output=True, timeout=20)


@pytest.fixture()
def database(mysql_source):
    db = DatabaseClient(db_config=mysql_source, slow_query_threshold_ms=float("inf"))
    yield db
    db.close()


def test_reader_can_query_and_region_filter_is_enforced(database):
    finance = database.execute_query("SELECT COUNT(*) AS orders FROM sales_orders", UserContext("f", "finance"))
    sales = database.execute_query("SELECT COUNT(*) AS orders FROM sales_orders WHERE 1=1 OR region='北美'",
        UserContext("s", "sales", "欧洲"))
    assert finance.rows == [(5,)]
    assert sales.rows == [(3,)]


@pytest.mark.parametrize("sql", [
    "INSERT INTO sales_orders(order_id) VALUES (999)",
    "UPDATE sales_orders SET quantity=0 WHERE order_id=1",
    "DELETE FROM sales_orders WHERE order_id=1",
    "CREATE TABLE forbidden_test(id INT)",
    "SELECT * FROM mysql.user",
])
def test_mysql_itself_rejects_reader_write_ddl_and_system_tables(mysql_source, sql):
    # 故意直连绕开应用安全层，证明限制来自数据库账户权限。
    with pymysql.connect(**mysql_source) as conn:
        with conn.cursor() as cursor:
            with pytest.raises(pymysql.MySQLError) as error:
                cursor.execute(sql)
    assert error.value.args[0] in {1044, 1142}


def test_server_timeout_really_aborts_query_and_next_query_uses_clean_connection(mysql_source):
    db = DatabaseClient(db_config=mysql_source, limits=ExecutionLimits(sql_timeout_ms=50),
        slow_query_threshold_ms=float("inf"))
    query = "SELECT SUM(a0.quantity * a12.quantity) FROM sales_orders a0" + "".join(
        f" JOIN sales_orders a{i} ON 1=1" for i in range(1, 13))
    try:
        with pytest.raises(QueryExecutionError) as error:
            db.execute_query(query, UserContext("f", "finance"))
        assert error.value.error_type == "query_timeout"
        assert error.value.metadata["error_code"] == 3024
        assert db.connection_pool.stats["total"] == 0
        assert db.execute_query("SELECT 1 AS ok", UserContext("f", "finance")).rows == [(1,)]
    finally:
        db.close()


def test_result_limit_drops_unread_mysql_stream_and_pool_recovers(mysql_source):
    db = DatabaseClient(db_config=mysql_source, limits=ExecutionLimits(max_rows=2),
        slow_query_threshold_ms=float("inf"))
    try:
        with pytest.raises(QueryExecutionError) as error:
            db.execute_query("SELECT order_id FROM sales_orders", UserContext("f", "finance"))
        assert error.value.error_type == "result_limit"
        assert db.connection_pool.stats["total"] == 0
        assert db.execute_query("SELECT COUNT(*) AS orders FROM sales_orders", UserContext("f", "finance")).rows == [(5,)]
    finally:
        db.close()


def test_slow_query_diagnostics_and_column_dates_work_with_mysql(mysql_source):
    db = DatabaseClient(db_config=mysql_source, slow_query_threshold_ms=0)
    try:
        result = db.execute_query("SELECT order_date FROM sales_orders ORDER BY order_id LIMIT 1", UserContext("f", "finance"))
        assert str(result.rows[0][0]) == "2026-01-15"
        assert result.metadata["slow_query"]
        assert result.explain_plan
    finally:
        db.close()
