"""安全边界回归：拒绝必须发生在建连之前；范围改写验证实际返回值。"""
import sqlite3
from types import SimpleNamespace

import pytest
import sqlglot
from fastapi import HTTPException
from starlette.requests import Request

from chatbi.api.dependencies import _build_user_context
from chatbi.core.security import QuerySecurityManager, SecurityError, UserContext
from chatbi.execution.sql_policy import BUSINESS_SCHEMA
from chatbi.infrastructure.database import DatabaseClient
from chatbi.services.chatbi_service import ChatBISystem

ADMIN = UserContext("admin", "admin")
SALES = UserContext("sales", "sales", "Europe")


@pytest.mark.parametrize("sql", [
    "DELETE FROM sales_orders", "SELECT 1; SELECT 2", "SELECT * FROM mysql.user",
    "SELECT COUNT(*) FROM unknown_table", "SELECT @@version", "SELECT @secret",
    "SELECT SLEEP(2)", "SELECT BENCHMARK(100, 1)", "SELECT LOAD_FILE('/etc/passwd')",
    "SELECT 1 INTO OUTFILE '/tmp/x'", "SELECT * FROM sales_orders FOR UPDATE",
    "SELECT /*!50000 SLEEP(2) */ 1", "SELECT /*+ MAX_EXECUTION_TIME(99999) */ 1",
    "SELECT * FROM sales_orders o CROSS JOIN dim_customers c",
    "SELECT o.order_id FROM sales_orders o RIGHT JOIN dim_customers c ON o.customer_id=c.customer_id",
    "WITH RECURSIVE x AS (SELECT 1 UNION ALL SELECT 1 FROM x) SELECT * FROM x",
    "WITH dim_customers AS (SELECT customer_id, region FROM sales_orders) SELECT COUNT(*) FROM sales_orders",
    "SELECT o.order_id FROM sales_orders o WHERE o.customer_id IN (SELECT c.customer_id FROM dim_customers c WHERE c.customer_id=o.customer_id)",
    "SELECT ROW_NUMBER() OVER (ORDER BY order_id) FROM sales_orders",
    "SELECT missing_column FROM sales_orders",
    "SELECT customer_id FROM sales_orders o JOIN dim_customers c ON o.customer_id=c.customer_id",
])
def test_unsafe_or_unsupported_sql_is_rejected_before_connecting(sql):
    opened = []
    client = DatabaseClient(connection_factory=lambda: opened.append(True))
    with pytest.raises(SecurityError):
        client.execute_query(sql, ADMIN)
    assert opened == []


@pytest.mark.parametrize("sql", [
    "SELECT net_amount AS revenue FROM sales_orders",
    "SELECT SUM(net_amount) AS revenue FROM sales_orders",
    "SELECT COUNT(*) FROM sales_orders WHERE net_amount > 100",
    "SELECT order_id FROM sales_orders ORDER BY net_amount",
    "SELECT * FROM sales_orders", "SELECT o.* FROM sales_orders o",
    "SELECT standard_cost * 2 AS price FROM dim_products",
    "SELECT labor_cost FROM dim_products", "SELECT unit_price FROM sales_orders",
    "WITH x AS (SELECT SUM(net_amount) AS r FROM sales_orders) SELECT r FROM x",
    "SELECT r FROM (SELECT net_amount AS r FROM sales_orders) x",
    "SELECT order_id FROM sales_orders UNION ALL SELECT net_amount FROM sales_orders",
    "SELECT COUNT(*) FROM finance_expenses",
])
def test_sales_cannot_hide_forbidden_sources_in_aliases_or_scopes(sql):
    with pytest.raises(SecurityError):
        QuerySecurityManager().secure_sql(sql, SALES)


@pytest.fixture()
def business_db():
    conn = sqlite3.connect(":memory:")
    for table, columns in BUSINESS_SCHEMA.items():
        conn.execute(f"CREATE TABLE {table} ({', '.join(name + ' TEXT' for name in columns)})")
    conn.executemany("INSERT INTO dim_customers(customer_id, region) VALUES (?, ?)",
                     [("1", "Europe"), ("2", "NorthAmerica"), ("3", "Europe")])
    # 订单冗余区域故意和客户不同：必须按客户权限过滤。
    conn.executemany("INSERT INTO sales_orders(order_id, customer_id, product_id, region) VALUES (?, ?, ?, ?)",
                     [("10", "1", "p1", "NorthAmerica"), ("20", "2", "p1", "Europe"), ("30", "3", "p2", "Europe")])
    conn.executemany("INSERT INTO dim_products(product_id) VALUES (?)", [("p1",), ("p2",), ("p3",)])
    yield conn
    conn.close()


@pytest.mark.parametrize("sql, expected", [
    ("SELECT COUNT(*) AS orders FROM sales_orders", [(2,)]),
    ("SELECT order_id FROM sales_orders WHERE 1=1 OR region='NorthAmerica' ORDER BY order_id", [("10",), ("30",)]),
    ("SELECT customer_id FROM dim_customers WHERE 1=1 OR region='NorthAmerica' ORDER BY customer_id", [("1",), ("3",)]),
    ("WITH x AS (SELECT order_id FROM sales_orders) SELECT * FROM x ORDER BY order_id", [("10",), ("30",)]),
    ("SELECT order_id FROM (SELECT order_id FROM sales_orders) x ORDER BY order_id", [("10",), ("30",)]),
    ("SELECT order_id FROM sales_orders UNION SELECT order_id FROM sales_orders ORDER BY order_id", [("10",), ("30",)]),
    ("SELECT order_id FROM sales_orders WHERE customer_id IN (SELECT customer_id FROM dim_customers) ORDER BY order_id", [("10",), ("30",)]),
    ("SELECT p.product_id, COUNT(o.order_id) AS orders FROM dim_products p LEFT JOIN sales_orders o ON p.product_id=o.product_id GROUP BY p.product_id ORDER BY p.product_id", [("p1", 1), ("p2", 1), ("p3", 0)]),
])
def test_region_rewrite_returns_only_authorized_data_and_preserves_left_join(business_db, sql, expected):
    secured = QuerySecurityManager().secure_sql(sql, SALES)
    portable = sqlglot.parse_one(secured, read="mysql").sql(dialect="sqlite")
    assert business_db.execute(portable).fetchall() == expected


def test_region_is_a_literal_not_sql_and_multiple_regions_work(business_db):
    manager = QuerySecurityManager()
    malicious = UserContext("s", "sales", "Europe' OR 1=1 --\\")
    secured = manager.secure_sql("SELECT COUNT(*) FROM sales_orders", malicious)
    assert business_db.execute(sqlglot.parse_one(secured, read="mysql").sql(dialect="sqlite")).fetchall() == [(0,)]
    multiple = UserContext("s", "sales", allowed_regions=["Europe", "NorthAmerica"])
    secured = manager.secure_sql("SELECT COUNT(*) FROM sales_orders", multiple)
    assert business_db.execute(sqlglot.parse_one(secured, read="mysql").sql(dialect="sqlite")).fetchall() == [(3,)]


@pytest.mark.parametrize("user", [None, UserContext("", "admin"), UserContext("new"), UserContext("s", "sales")])
def test_missing_or_incomplete_identity_is_rejected(user):
    with pytest.raises(SecurityError):
        QuerySecurityManager().secure_sql("SELECT 1", user)


def test_request_without_attached_identity_is_unauthorized():
    with pytest.raises(HTTPException) as error:
        _build_user_context(Request({"type": "http"}))
    assert error.value.status_code == 401


def test_health_remains_public(anonymous_client, monkeypatch):
    from chatbi.api import routes

    monkeypatch.setattr(routes.system, "_get_runtime", lambda: SimpleNamespace(
        db=SimpleNamespace(validate_connection=lambda: True)))
    response = anonymous_client.get("/health")
    assert response.status_code == 200
    assert response.json()["database_connected"] is True


def test_public_middleware_does_not_attach_administrator():
    import asyncio
    from starlette.responses import Response
    from chatbi.api.dependencies import attach_user_context

    request = Request({"type": "http", "path": "/health", "headers": []})

    async def next_handler(incoming):
        assert getattr(incoming.state, "user_context", None) is None
        return Response(status_code=200)

    assert asyncio.run(attach_user_context(request, next_handler)).status_code == 200


def test_query_entry_rejects_missing_identity_before_model_or_database():
    system = ChatBISystem(runtime=SimpleNamespace(source_id="test", parser=None, llm=None,
        db=None, formatter=None, indicator_knowledge=None))
    assert system.run("orders")["error_type"] == "security"
    assert list(system.run_stream_events("orders"))[0][1]["error_type"] == "security"


def test_finance_readonly_queries_and_literal_keywords_are_allowed():
    manager = QuerySecurityManager()
    for sql in ["SELECT SUM(net_amount) AS revenue FROM sales_orders", "SELECT 'DELETE; DROP' AS label",
                "SELECT DATE_FORMAT(order_date, '%Y-%m') AS month, SUM(net_amount) FROM sales_orders GROUP BY month",
                "SELECT order_id FROM sales_orders WHERE order_date >= DATE_SUB(CURDATE(), INTERVAL 1 MONTH)"]:
        secured = manager.secure_sql(sql, UserContext("finance", "finance"))
        assert sqlglot.parse_one(secured, read="mysql") is not None


def test_result_mask_is_only_additional_protection():
    columns, rows = QuerySecurityManager().mask_result(["customer_name", "net_amount"], [("customer", 100)], SALES)
    assert columns == ["customer_name", "net_amount"]
    assert rows == [("customer", "***")]
