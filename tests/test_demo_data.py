"""Check that fictional demo records support the main BI query paths."""

from collections import Counter
from decimal import Decimal

from chatbi.tools.demo_data import SQL_PATH, demo_rows, money, render_sql


def test_demo_data_covers_monthly_analysis_and_joins():
    data = demo_rows()
    orders = data["sales_orders"]
    assert len(orders) == 224
    assert {str(row[5])[:7] for row in orders} == {f"2026-{month:02d}" for month in range(1, 11)}
    assert {row[4] for row in orders} == {"欧洲", "北美", "亚太", "中东非洲", "拉美"}
    assert {row[6] for row in orders} == {"completed", "cancelled", "pending"}
    assert len({row[1] for row in orders}) == len(orders)
    assert {row[12] for row in orders} == {"EUR", "USD", "JPY"}

    customer_ids = {1, 2, 3, 4, 5} | {row[0] for row in data["dim_customers"]}
    product_ids = {1, 2, 3, 4, 5} | {row[0] for row in data["dim_products"]}
    regions = {row[0]: row[5] for row in data["dim_customers"]}
    regions.update({1: "欧洲", 2: "北美", 3: "欧洲", 4: "欧洲", 5: "亚太"})
    rates = {(row[0], row[1]) for row in data["exchange_rates"]}
    for row in orders:
        assert row[2] in customer_ids and row[3] in product_ids
        assert row[4] == regions[row[2]]
        assert (row[5], row[12]) in rates
        assert money(row[7] * row[8] - row[9]) == row[11]
        assert money(row[11] * Decimal("1.13")) == row[10]

    completed = Counter(str(row[5])[:7] for row in orders if row[6] == "completed")
    assert all(completed[f"2026-{month:02d}"] > 0 for month in range(1, 11))
    assert any(row[0] == 116 and row[0] not in {order[2] for order in orders}
               for row in data["dim_customers"])


def test_expenses_are_monthly_and_sales_subitems_not_double_counted():
    expenses = demo_rows()["finance_expenses"]
    assert len(expenses) == 27
    assert {str(row[1])[:7] for row in expenses} == {f"2026-{month:02d}" for month in range(1, 11)}
    assert all(row[4] >= sum(row[7:10]) for row in expenses)


def test_first_boot_sql_matches_generator():
    assert SQL_PATH.read_text(encoding="utf-8") == render_sql(demo_rows())
