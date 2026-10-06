"""MySQL 只读 SQL 子集：验证所有作用域，再限制每个物理表的数据范围。"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import traverse_scope

from chatbi.core.security import SecurityError

if TYPE_CHECKING:
    from chatbi.core.security import SecurityPolicy, UserContext


# 当前仅支持现有制造业五表；不同 Schema 必须发布新的可信元数据。
BUSINESS_SCHEMA = {
    "dim_customers": dict.fromkeys(
        "customer_id customer_name customer_type industry country region".split(), "UNKNOWN"),
    "dim_products": dict.fromkeys(
        "product_id product_name product_line category tech_route standard_cost material_cost labor_cost".split(), "UNKNOWN"),
    "sales_orders": dict.fromkeys(
        "order_id order_no customer_id product_id region order_date order_status quantity unit_price discount_amount gross_amount net_amount currency".split(), "UNKNOWN"),
    "exchange_rates": dict.fromkeys("rate_date currency rate_to_cny".split(), "UNKNOWN"),
    "finance_expenses": dict.fromkeys(
        "expense_id expense_date department rd_expense selling_expense admin_expense finance_expense marketing_expense logistics_expense warranty_expense".split(), "UNKNOWN"),
}


class SQLPolicy:
    # 未知节点和函数不能因“解析成功”而获得执行权。
    _NODES = frozenset("""
        Select Union Subquery With CTE From Table TableAlias Identifier Column Star Alias
        Join Where Group Having Order Ordered Limit Offset Distinct Literal Null Boolean
        Paren And Or Not EQ NEQ GT GTE LT LTE NullSafeEQ NullSafeNEQ Is In Between Like
        Add Sub Mul Div IntDiv Mod Neg Interval Tuple DataType DataTypeParam
    """.split())
    _FUNCTIONS = frozenset("""
        COUNT SUM AVG MIN MAX ROUND ABS CEIL FLOOR COALESCE IF IFNULL NULLIF CASE
        CAST EXTRACT YEAR MONTH DAY DAY_OF_MONTH DATE CURRENT_DATE CURRENT_TIMESTAMP
        DATE_ADD DATE_SUB DATE_DIFF LAST_DAY TIME_TO_STR STR_TO_TIME TS_OR_DS_TO_DATE
        CONCAT CONCAT_WS LOWER UPPER LENGTH CHAR_LENGTH SUBSTRING TRIM
    """.split())

    def secure(self, sql: str, user: UserContext, policy: SecurityPolicy) -> str:
        normalized = re.sub(r"^```(?:sql)?\s*|```$", "", sql.strip(), flags=re.I).strip()
        if not normalized:
            raise SecurityError("SQL 不能为空。")
        if re.search(r"/\*\s*[!+]", normalized):
            raise SecurityError("不允许可执行注释或 SQL 提示。")
        try:
            statements = sqlglot.parse(normalized, read="mysql")
            if len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.Union)):
                raise SecurityError("只允许执行查询语句，且必须是单条 SQL。")
            tree = statements[0]
            self._validate_structure(tree)
            for identifier in tree.find_all(exp.Identifier):
                identifier.set("this", identifier.name.lower())
            tree = qualify(tree, dialect="mysql", schema=BUSINESS_SCHEMA,
                           infer_schema=False, validate_qualify_columns=True)
            physical_tables = []
            for scope in traverse_scope(tree):
                if scope.is_correlated_subquery:
                    raise SecurityError("暂不支持相关子查询，请拆成独立查询。")
                for _, source in scope.selected_sources.values():
                    if isinstance(source, exp.Table):
                        self._validate_table(source, policy)
                        physical_tables.append(source)
                for column in scope.columns:
                    source = scope.sources.get(column.table)
                    if isinstance(source, exp.Table) and column.name.lower() in policy.denied_columns:
                        raise SecurityError(f"无权访问字段：{source.name}.{column.name}。")
            for star in tree.find_all(exp.Star):
                if not isinstance(star.parent, exp.Count):
                    raise SecurityError("无法确定星号的字段范围。")
            if user.role.lower() == "sales":
                regions = tuple(user.allowed_regions) if user.allowed_regions else (user.region,)
                for table in physical_tables:
                    if table.name in {"sales_orders", "dim_customers"}:
                        self._restrict_region(table, regions, policy)
            for node in tree.walk():
                node.pop_comments()
            return tree.sql(dialect="mysql", identify=True, unsupported_level=sqlglot.ErrorLevel.RAISE)
        except SqlglotError as exc:
            raise SecurityError("SQL 不在已支持的安全范围内，或表/字段无法确定。") from exc

    def _validate_structure(self, tree: exp.Expression) -> None:
        for node in tree.walk():
            if isinstance(node, exp.Var) and (
                isinstance(node.parent, (exp.Interval, exp.DateAdd, exp.DateSub, exp.DateDiff)) and node.parent.args.get("unit") is node
                or isinstance(node.parent, exp.Extract) and node.parent.this is node
            ):
                # 日期单位是解析器的 Var 节点，用户/系统变量的 Parameter 仍拒绝。
                pass
            elif type(node).__name__ in self._NODES:
                pass
            elif isinstance(node, exp.Func):
                name = node.name.upper() if isinstance(node, exp.Anonymous) else node.sql_name()
                if name not in self._FUNCTIONS:
                    raise SecurityError(f"不允许使用函数：{name}。")
            else:
                raise SecurityError(f"暂不支持 SQL 结构：{type(node).__name__}。")
            if isinstance(node, exp.Table) and (node.db or node.catalog):
                raise SecurityError("不允许跨库或系统表查询。")
            if isinstance(node, exp.With) and node.args.get("recursive"):
                raise SecurityError("暂不支持递归 CTE。")
            if isinstance(node, exp.CTE) and node.alias_or_name.lower() in BUSINESS_SCHEMA:
                raise SecurityError("CTE 不能遮蔽已授权的业务表。")
            if isinstance(node, exp.Join):
                if node.side.upper() not in {"", "LEFT"} or node.kind.upper() not in {"", "INNER", "OUTER"}:
                    raise SecurityError("暂仅支持 INNER JOIN 与 LEFT JOIN。")
                if not node.args.get("on") or node.args.get("using"):
                    raise SecurityError("JOIN 必须使用明确的 ON 条件。")

    @staticmethod
    def _validate_table(table: exp.Table, policy: SecurityPolicy) -> None:
        if table.name not in BUSINESS_SCHEMA or table.name in policy.denied_tables:
            raise SecurityError(f"无权访问表：{table.name}。")

    @staticmethod
    def _restrict_region(table: exp.Table, regions: tuple[str, ...], policy: SecurityPolicy) -> None:
        # 过滤在基础表的派生查询里，OR 和 LEFT JOIN 不会冲掉或改变范围。
        alias = table.alias_or_name
        base = exp.to_table(table.name)
        allowed = exp.column("region").isin(*[exp.Literal.string(region) for region in regions])
        if table.name == "sales_orders":
            # 客户归属为授权事实源，不信任订单自身冗余 region。
            customers = exp.select("customer_id").from_("dim_customers").where(allowed)
            allowed = exp.In(this=exp.column("customer_id"), query=customers.subquery())
        columns = [exp.column(name) for name in BUSINESS_SCHEMA[table.name] if name not in policy.denied_columns]
        restricted = exp.select(*columns).from_(base).where(allowed)
        table.replace(restricted.subquery(alias=alias))
