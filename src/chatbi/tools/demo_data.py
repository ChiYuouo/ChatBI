"""Deterministic, clearly fictional manufacturing data for the Compose demo database."""

from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SQL_PATH = ROOT / "docker" / "mysql" / "init" / "03-demo-expansion.sql"

COLUMNS = {
    "dim_customers": ("customer_id", "customer_name", "customer_type", "industry", "country", "region"),
    "dim_products": ("product_id", "product_name", "product_line", "category", "tech_route", "standard_cost", "material_cost", "labor_cost"),
    "exchange_rates": ("rate_date", "currency", "rate_to_cny"),
    "finance_expenses": ("expense_id", "expense_date", "department", "rd_expense", "selling_expense", "admin_expense", "finance_expense", "marketing_expense", "logistics_expense", "warranty_expense"),
    "sales_orders": ("order_id", "order_no", "customer_id", "product_id", "region", "order_date", "order_status", "quantity", "unit_price", "discount_amount", "gross_amount", "net_amount", "currency"),
}


def money(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def demo_rows() -> dict[str, list[tuple]]:
    customers = [
        (101, "某法国乘用车制造商", "OEM整车厂", "交通", "France", "欧洲"),
        (102, "某德国商用车集团", "OEM整车厂", "交通", "Germany", "欧洲"),
        (103, "某加拿大储能服务商", "储能集成商", "能源", "Canada", "北美"),
        (104, "某美国工商业能源公司", "工商业用户", "工业", "USA", "北美"),
        (105, "某韩国换电平台", "换电运营商", "交通", "South Korea", "亚太"),
        (106, "某澳大利亚储能集成商", "储能集成商", "能源", "Australia", "亚太"),
        (107, "某阿联酋电网运营商", "电网集团", "能源", "UAE", "中东非洲"),
        (108, "某南非工商业客户", "工商业用户", "工业", "South Africa", "中东非洲"),
        (109, "某巴西新能源经销商", "经销商", "交通", "Brazil", "拉美"),
        (110, "某墨西哥商用车厂", "OEM整车厂", "交通", "Mexico", "拉美"),
        (111, "某印度电池回收企业", "工商业用户", "工业", "India", "亚太"),
        (112, "某西班牙储能开发商", "储能集成商", "能源", "Spain", "欧洲"),
        (113, "某美国城市公交集团", "OEM整车厂", "交通", "USA", "北美"),
        (114, "某智利矿区储能公司", "工商业用户", "工业", "Chile", "拉美"),
        (115, "某日本车用电池经销商", "经销商", "交通", "Japan", "亚太"),
        (116, "某荷兰潜在客户", "储能集成商", "能源", "Netherlands", "欧洲"),
    ]
    products = [
        (101, "高能量密度型电芯 300Ah", "动力电池-乘用车", "高能量密度型", "三元锂", 920, 590, 90),
        (102, "混动专用型电池包", "动力电池-乘用车", "混动专用型", "磷酸铁锂", 680, 420, 65),
        (103, "工商业液冷储能柜 500kWh", "储能系统-工商业", "工商业储能型", "磷酸铁锂", 85000, 51000, 12000),
        (104, "电网级储能集装箱 2MWh", "储能系统-电网级", "电网级储能型", "磷酸铁锂", 230000, 145000, 28000),
        (105, "换电站标准电池模组", "动力电池-商用车", "商用车标准型", "磷酸铁锂", 450, 275, 55),
        (106, "电池回收再生材料包", "电池材料与回收", "回收材料型", "三元锂", 350, 180, 65),
        (107, "商用车长续航电池包", "动力电池-商用车", "商用车标准型", "磷酸铁锂", 640, 390, 60),
        (108, "固态电池试制模组", "动力电池-乘用车", "高能量密度型", "固态电池", 1400, 900, 160),
    ]
    # Existing customer and product IDs are intentionally retained unchanged.
    customer_info = {
        1: ("欧洲", "EUR", (1, 2, 4, 101, 102, 108)),
        2: ("北美", "USD", (3, 103, 104)),
        3: ("欧洲", "EUR", (1, 2, 5, 101, 107)),
        4: ("欧洲", "EUR", (3, 103, 104)),
        5: ("亚太", "JPY", (5, 105, 107)),
        101: ("欧洲", "EUR", (1, 2, 4, 101, 102, 108)),
        102: ("欧洲", "EUR", (5, 105, 107)),
        103: ("北美", "USD", (3, 103, 104)),
        104: ("北美", "USD", (3, 103, 104, 106)),
        105: ("亚太", "USD", (5, 105, 107)),
        106: ("亚太", "USD", (3, 103, 104)),
        107: ("中东非洲", "USD", (3, 103, 104)),
        108: ("中东非洲", "USD", (103, 106)),
        109: ("拉美", "USD", (1, 2, 5, 101, 107)),
        110: ("拉美", "USD", (5, 105, 107)),
        111: ("亚太", "USD", (106,)),
        112: ("欧洲", "EUR", (3, 103, 104)),
        113: ("北美", "USD", (5, 105, 107)),
        114: ("拉美", "USD", (103, 104, 106)),
        115: ("亚太", "JPY", (1, 2, 5, 101, 105)),
    }
    costs = {1: 630, 2: 440, 3: 325000, 4: 550, 5: 405}
    costs.update({p[0]: p[6] + p[7] for p in products})
    rates: dict[tuple[date, str], Decimal] = {}
    orders: list[tuple] = []
    ids = tuple(customer_info)
    for month in range(1, 11):
        days = (4, 8) if month == 10 else (4, 8, 12, 20, 24, 28)
        for position in range(len(days) * 4):
            day = days[position // 4]
            order_date = date(2026, month, day)
            customer_id = ids[(position * 7 + month * 3) % len(ids)]
            region, currency, choices = customer_info[customer_id]
            product_id = choices[(position + month) % len(choices)]
            for code, base, drift in (("EUR", "7.83", "0.006"), ("USD", "7.24", "0.009"), ("JPY", "0.0485", "0.00004")):
                rates[(order_date, code)] = (Decimal(base) + Decimal(month - 1) * Decimal(drift)
                    + Decimal(day - 12) * Decimal(drift) / 20).quantize(Decimal("0.0001"))
            rate = rates[(order_date, currency)]
            # A gradual July-to-September volume decline makes trend analysis nontrivial.
            month_factor = Decimal("1.20") if month == 7 else Decimal("1.00") if month == 8 else Decimal("0.76") if month == 9 else Decimal("0.90")
            base_quantity = Decimal(2 if costs[product_id] > 50000 else 80 + (position % 5) * 35)
            quantity = money(base_quantity * month_factor * (Decimal("0.90") if position % 3 == 0 else Decimal("1.00")))
            price_cny = Decimal(costs[product_id]) * (Decimal("1.34") + Decimal(position % 4) * Decimal("0.045"))
            unit_price = money(price_cny / rate)
            discount = money(quantity * unit_price * Decimal("0.02") * Decimal(position % 3))
            net = money(quantity * unit_price - discount)
            gross = money(net * Decimal("1.13"))
            status = "cancelled" if position % 17 == 0 else "pending" if position % 11 == 0 else "completed"
            order_id = 10000 + month * 100 + position + 1
            order_no = f"SO2026{month:02d}{position + 101:03d}"
            orders.append((order_id, order_no, customer_id, product_id, region, order_date, status,
                           quantity, unit_price, discount, gross, net, currency))

    # The already-running local demo volume has two legacy order dates absent from
    # the original dump. These extra FX rows let those orders join to a rate too.
    rates[(date(2026, 8, 5), "EUR")] = Decimal("7.8600")
    rates[(date(2026, 8, 13), "USD")] = Decimal("7.2400")

    expenses: list[tuple] = []
    expense_id = 1001
    for month in range(1, 11):
        expense_date = date(2026, month, 8 if month == 10 else (date(2026, month + 1, 1).toordinal() - date(2026, month, 1).toordinal()))
        for department, base in (("销售部", (620000, 460000, 260000, 80000)),
                                 ("研发部", (980000, 110000, 145000, 35000)),
                                 ("管理部", (180000, 90000, 440000, 60000))):
            if department == "销售部" and month <= 3:
                continue  # Preserve the three existing sales-department records.
            factor = Decimal("0.27") if month == 10 else Decimal("1") + Decimal(month - 1) * Decimal("0.025")
            rd, selling, admin, finance = (money(value * factor) for value in base)
            expenses.append((expense_id, expense_date, department, rd, selling, admin, finance,
                             money(selling * Decimal("0.36")), money(selling * Decimal("0.26")),
                             money(selling * Decimal("0.18"))))
            expense_id += 1

    return {
        "dim_customers": customers,
        "dim_products": products,
        "exchange_rates": [(d, c, r) for (d, c), r in sorted(rates.items())],
        "finance_expenses": expenses,
        "sales_orders": orders,
    }


def sql_literal(value: object) -> str:
    if isinstance(value, (date, str)):
        return "'" + str(value).replace("'", "''") + "'"
    return str(value)


def render_sql(rows: dict[str, list[tuple]]) -> str:
    lines = ["-- Fictional ChatBI demo data. Generated by python -m chatbi.tools.demo_data --write-sql.",
             "-- Append-only: preserves 01-init.sql rows; managed IDs start at 101/1001/10101.",
             "-- Existing MySQL volumes require: python -m chatbi.tools.demo_data --apply",
             "SET NAMES utf8mb4;", ""]
    for table, records in rows.items():
        cols = ", ".join(f"`{name}`" for name in COLUMNS[table])
        lines.append(f"INSERT INTO `{table}` ({cols}) VALUES")
        lines.append(",\n".join("  (" + ", ".join(map(sql_literal, row)) + ")" for row in records) + ";")
        lines.append("")
    return "\n".join(lines)


def apply_rows(rows: dict[str, list[tuple]], port: int = 3307) -> dict[str, int]:
    import os
    import pymysql
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    def comparable(value: object) -> object:
        return Decimal(str(value)) if isinstance(value, (int, float, Decimal)) else str(value)

    # This command targets only the Compose-published local demo port, never DB_HOST.
    connection = pymysql.connect(host="127.0.0.1", port=port, user="root",
                                 password=os.environ["MYSQL_ROOT_PASSWORD"],
                                 database=os.getenv("DB_NAME", "chatbi_mvp"), charset="utf8mb4",
                                 autocommit=False)
    inserted: dict[str, int] = {}
    try:
        with connection.cursor() as cursor:
            # Reject a conflicting managed key before writing anything.
            for table, records in rows.items():
                pk_cols = ("rate_date", "currency") if table == "exchange_rates" else (COLUMNS[table][0],)
                all_cols = ", ".join(f"`{column}`" for column in COLUMNS[table])
                where = " AND ".join(f"`{column}` = %s" for column in pk_cols)
                for record in records:
                    key = record[:len(pk_cols)]
                    cursor.execute(f"SELECT {all_cols} FROM `{table}` WHERE {where}", key)
                    existing = cursor.fetchone()
                    if existing is not None and tuple(map(comparable, existing)) != tuple(map(comparable, record)):
                        raise ValueError(f"{table} key {key} already contains different data; no rows were changed")
            for table, records in rows.items():
                cols = ", ".join(f"`{column}`" for column in COLUMNS[table])
                placeholders = ", ".join(["%s"] * len(COLUMNS[table]))
                pk_cols = ("rate_date", "currency") if table == "exchange_rates" else (COLUMNS[table][0],)
                where = " AND ".join(f"`{column}` = %s" for column in pk_cols)
                count = 0
                for record in records:
                    cursor.execute(f"SELECT 1 FROM `{table}` WHERE {where}", record[:len(pk_cols)])
                    if cursor.fetchone() is None:
                        cursor.execute(f"INSERT INTO `{table}` ({cols}) VALUES ({placeholders})", record)
                        count += 1
                inserted[table] = count
        connection.commit()
        return inserted
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate or append fictional ChatBI demo records")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write-sql", action="store_true", help="write first-boot SQL fixture")
    group.add_argument("--check-sql", action="store_true", help="verify checked-in SQL matches generator")
    group.add_argument("--apply", action="store_true", help="append to existing local MySQL volume")
    parser.add_argument("--port", type=int, default=3307, help="local Compose MySQL port (default: 3307)")
    args = parser.parse_args()
    rows = demo_rows()
    if args.write_sql:
        SQL_PATH.write_text(render_sql(rows), encoding="utf-8")
        print(f"Wrote {SQL_PATH}")
    elif args.check_sql:
        assert SQL_PATH.read_text(encoding="utf-8") == render_sql(rows)
        print("Demo SQL is up to date")
    else:
        print("Inserted:", apply_rows(rows, port=args.port))


if __name__ == "__main__":
    main()
