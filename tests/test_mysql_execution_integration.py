"""显式开启的 MySQL 8.4 集成测试；只创建和销毁本模块自己的临时容器。"""
import os
from pathlib import Path
import subprocess
import time
import uuid
from decimal import Decimal
import json

import pymysql
import pytest

from chatbi.core.security import UserContext
from chatbi.execution.budget import ExecutionLimits, ExecutionBudget
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


@pytest.fixture()
def financial_source(mysql_source):
    """只向本模块的临时容器加入边界样例，不修改用户业务库。"""
    admin_config = {**mysql_source, "user": "root", "password": "temporary-test-admin-42"}
    with pymysql.connect(**admin_config) as conn:
        try:
            with conn.cursor() as cursor:
                cursor.executemany(
                    "INSERT INTO sales_orders(order_id,order_no,customer_id,product_id,region,order_date,"
                    "order_status,quantity,net_amount,currency) VALUES (%s,%s,%s,1,%s,%s,%s,1,%s,%s)", [
                    (1001, "FX1", 1, "欧洲", "2026-07-01", "completed", 10, "USD"),
                    (1002, "FX2", 2, "北美", "2026-07-02", "completed", 20, "EUR"),
                    (1003, "FX3", 1, "欧洲", "2026-07-03", "completed", 30, "CNY"),
                    (1004, "FX4", 1, "欧洲", "2026-07-04", "cancelled", 100, "USD"),
                    (1005, "FX5", 1, "欧洲", "2026-07-05", "pending", 100, "USD"),
                    (1006, "FX6", 3, "欧洲", "2026-07-01", "completed", 10, "EUR"),
                ])
                cursor.executemany("INSERT INTO exchange_rates VALUES (%s,%s,%s)", [
                    ("2026-07-01", "USD", 2), ("2026-07-01", "EUR", 3),
                    ("2026-07-02", "USD", 2),  # 同日但币种不同，不能冒用。
                ])
            yield mysql_source, conn
        finally:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM sales_orders WHERE order_id BETWEEN 1001 AND 1006")
                cursor.execute("DELETE FROM exchange_rates WHERE rate_date BETWEEN '2026-07-01' AND '2026-07-05'")


def revenue_sql(where):
    return ("SELECT SUM(o.net_amount * CASE WHEN o.currency='CNY' THEN 1 ELSE r.rate_to_cny END) AS revenue FROM sales_orders o "
        "LEFT JOIN exchange_rates r ON o.order_date=r.rate_date AND o.currency=r.currency "
        f"WHERE o.order_status='completed' AND {where}")


def test_schema_reads_non_demo_tables_and_changed_columns(mysql_source):
    """仅在专用临时容器中建表，验证结构没有演示表/字段回退。"""
    from chatbi.infrastructure.database_schema import render_schema
    from chatbi.core.security import SecurityError
    config = {**mysql_source, "user": "root", "password": "temporary-test-admin-42"}
    db = DatabaseClient(db_config=config, slow_query_threshold_ms=float("inf"))
    with pymysql.connect(**config) as conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute("CREATE TABLE QueryEvents (event_id INT PRIMARY KEY COMMENT '记录编号', label VARCHAR(20) COMMENT '处理标签') COMMENT='结构测试表'")
                cursor.execute("INSERT INTO QueryEvents VALUES (1,'ok'), (2,'ok')")
            metadata = db.describe_schema()
            own = [table for table in metadata if table["table_name"] == "QueryEvents"]
            assert "处理标签" in render_schema(own)
            assert "sales_orders" not in render_schema(own)
            assert db.execute_query("SELECT COUNT(*) AS total FROM QueryEvents", UserContext.demo_admin()).rows == [(2,)]
            with conn.cursor() as cursor:
                cursor.execute("ALTER TABLE QueryEvents ADD current_value INT DEFAULT 7 COMMENT '新增字段'")
            refreshed = db.describe_schema()
            assert "新增字段" in render_schema([table for table in refreshed if table["table_name"] == "QueryEvents"])
            assert db.execute_query("SELECT SUM(current_value) FROM QueryEvents", UserContext.demo_admin()).rows == [(Decimal(14),)]
            with pytest.raises(SecurityError):
                db.execute_query("SELECT missing_column FROM QueryEvents", UserContext.demo_admin())
        finally:
            db.close()
            with conn.cursor() as cursor:
                cursor.execute("DROP TABLE IF EXISTS QueryEvents")


@pytest.mark.parametrize("source_kind", ["default", "added"])
@pytest.mark.parametrize("stream", [False, True])
def test_frontend_knowledge_and_real_schema_reach_query_prompt(client, mysql_source, tmp_path, monkeypatch, source_kind, stream):
    """真实 HTTP 配置保存 + MySQL 结构/查询；模型只使用本地假实现。"""
    from copy import deepcopy
    from cryptography.fernet import Fernet
    from chatbi.api import routes
    from chatbi.bootstrap import runtime_factory
    from chatbi.infrastructure.datasource_store import DataSourceStore
    from chatbi.services import chatbi_service
    from chatbi.retrieval import schema_index

    class LocalEmbeddings:
        def embed_documents(self, texts):
            return [[1.0, 0.5, 0.25] for _ in texts]

        def embed_query(self, text):
            return [1.0, 0.5, 0.25]

    monkeypatch.setattr(schema_index, "CHROMA_ROOT", tmp_path / "vectors")
    monkeypatch.setattr(schema_index, "_get_embeddings", lambda budget=None: LocalEmbeddings())

    store = DataSourceStore(str(tmp_path / "sources.db"))
    for module in (routes, runtime_factory, chatbi_service):
        monkeypatch.setattr(module, "get_datasource_store", lambda: store)
    monkeypatch.setenv("DATASOURCE_ENCRYPTION_KEY", Fernet.generate_key().decode())
    default_source = routes.APP_CONFIG["database"]["default_source"]
    source = default_source
    if source_kind == "added":
        draft = {key: mysql_source[key] for key in ("host", "port", "database", "user", "password", "charset")}
        assert client.post("/api/v1/data-sources/test-connection", json=draft).status_code == 200
        assert store.list(admin=True) == []
        created = client.post("/api/v1/data-sources", json={"name": "独立集成测试源", **draft})
        assert created.status_code == 201, created.text
        source = created.json()["source_id"]

    url = f"/api/v1/data-sources/{source}/knowledge"
    content = {
        "business_rule_items": [{"title": "前端业务规则", "content": "按当前结构统计订单"}],
        "error_guard_items": [{"title": "前端错误防护", "content": "禁止使用不存在的字段"}],
        "sql_examples": [{"question": "前端 fewshot 问题", "sql": "SELECT COUNT(*) AS probe FROM sales_orders"}],
    }
    assert client.put(url, json={"knowledge": content}).status_code == 200

    class LocalLLM:
        def __init__(self):
            self.prompts = []

        def generate_sql(self, system_msg, prompt):
            self.prompts.append(prompt)
            return "SELECT COUNT(*) AS probe FROM sales_orders"

        def generate_sql_stream(self, system_msg, prompt):
            yield self.generate_sql(system_msg, prompt)

    llm = LocalLLM()
    config = deepcopy(routes.APP_CONFIG)
    config["features"] = {"few_shot": True, "rules": True, "guards": True}
    config["database"]["sources"][default_source] = {"driver": "mysql", **mysql_source}
    monkeypatch.setattr(routes, "APP_CONFIG", config)

    def factory(app_config, source_id=None):
        runtime = runtime_factory.build_runtime(app_config, source_id)
        runtime.llm.close()
        runtime.llm = llm
        return runtime

    system = chatbi_service.ChatBISystem(app_config=config, runtime_factory=factory)
    monkeypatch.setattr(routes, "system", system)
    query_url = "/api/v1/query/stream" if stream else "/api/v1/query"
    payload = {"question": "统计订单数量", "source_id": source, "use_indicator_knowledge": False,
               "use_indicator_rag": False, "use_schema_linking": True}
    try:
        response = client.post(query_url, json=payload)
        assert response.status_code == 200, response.text
        if stream:
            assert "event: result" in response.text and "event: error" not in response.text
        else:
            assert response.json()["columns"] == ["probe"]
        for marker in ("前端业务规则", "前端错误防护", "前端 fewshot 问题", "表：sales_orders"):
            assert marker in llm.prompts[-1]
        assert schema_index.schema_index_status(source, store.tables(source))["status"] == "ready"
        assert "【数据库Schema】\nNone" not in llm.prompts[-1]
        assert client.put(url, json={"knowledge": {key: [] for key in content}}).status_code == 200
        cleared = client.post(query_url, json=payload)
        assert cleared.status_code == 200, cleared.text
        if stream:
            assert "event: result" in cleared.text and "event: error" not in cleared.text
        for marker in ("前端业务规则", "前端错误防护", "前端 fewshot 问题", "【示例】"):
            assert marker not in llm.prompts[-1]
    finally:
        system.close()


@pytest.mark.parametrize("cny_rate", [None, 99])
def test_cny_needs_no_rate_and_gross_profit_uses_cny_income(financial_source, cny_rate):
    config, admin = financial_source
    if cny_rate is not None:
        with admin.cursor() as cursor:
            cursor.execute("INSERT INTO exchange_rates VALUES ('2026-07-03','CNY',%s)", (cny_rate,))
    catalog = json.loads((Path(__file__).resolve().parents[1] / 'indicators_full.json').read_text(encoding='utf-8'))
    db = DatabaseClient(db_config=config, slow_query_threshold_ms=float("inf"))
    try:
        for name, expected in [("收入", Decimal("80")), ("毛利", Decimal("-1810"))]:
            template = next(item['sql_template'] for item in catalog['indicators'] if item['name'] == name)
            budget = ExecutionBudget(db.limits)
            result = db.execute_query(template + " AND o.order_id IN (1001,1003,1004,1005,1006)", UserContext("f", "finance"), budget)
            assert budget.executions == 1
            assert result.rows[0][0] == expected
    finally:
        db.close()


def test_date_and_customer_filters_exclude_unrelated_missing_rates(financial_source):
    config, _ = financial_source
    db = DatabaseClient(db_config=config, slow_query_threshold_ms=float("inf"))
    try:
        assert db.execute_query(revenue_sql(where="o.order_id>=1001 AND o.order_date='2026-07-01'"), UserContext("f", "finance")).rows == [(Decimal("50"),)]
        query = revenue_sql(where="o.order_id IN (1001,1002,1003,1004,1005,1006) AND c.region='欧洲'")
        query = query.replace("LEFT JOIN exchange_rates", "JOIN dim_customers c ON o.customer_id=c.customer_id LEFT JOIN exchange_rates")
        assert db.execute_query(query, UserContext("f", "finance")).rows == [(Decimal("80"),)]
    finally:
        db.close()
def test_reader_can_query_and_region_filter_is_enforced(database):
    finance = database.execute_query("SELECT COUNT(*) AS orders FROM sales_orders", UserContext("f", "finance"))
    sales = database.execute_query("SELECT COUNT(*) AS orders FROM sales_orders WHERE 1=1 OR region='北美'",
        UserContext("s", "sales", "欧洲"))
    assert finance.rows == [(229,)]
    assert sales.rows == [(69,)]


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
        assert db.execute_query("SELECT COUNT(*) AS orders FROM sales_orders", UserContext("f", "finance")).rows == [(229,)]
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
