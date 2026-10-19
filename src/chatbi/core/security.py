from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


class SecurityError(Exception):
    """身份、权限或 SQL 安全检查失败，不得交给模型重试绕过。"""


class SQLGenerationError(SecurityError):
    """模型生成了不完整或暂不支持的查询，可在重新校验后改写。"""


class SchemaRequiredError(SecurityError):
    """查询包含物理表，执行器必须先提供当前数据源的可信元数据。"""


@dataclass(slots=True)
class UserContext:
    """当前请求身份，只能由可信调用方提供。"""

    user_id: str
    role: str = "pending"
    region: str | None = None
    allowed_regions: list[str] = field(default_factory=list)
    trace_id: str | None = None
    # 数据源授权后的可访问表；None 表示使用数据源读取权限和角色策略。
    allowed_tables: list[str] | None = None

    @classmethod
    def demo_admin(cls) -> UserContext:
        """离线评测显式使用的身份，业务链路不得自动回退到此身份。"""
        return cls(user_id="demo_admin", role="admin")


@dataclass(frozen=True, slots=True)
class SecurityPolicy:
    denied_columns: frozenset[str] = frozenset()
    denied_tables: frozenset[str] = frozenset()
    allowed_tables: frozenset[str] | None = None


class QuerySecurityManager:
    """执行前校验原始列来源；结果脱敏仅作为补充保护。"""

    def __init__(self):
        from chatbi.execution.sql_policy import SQLPolicy

        self.sql_policy = SQLPolicy()
        self.role_policies = {
            "admin": SecurityPolicy(),
            "finance": SecurityPolicy(denied_columns=frozenset({"customer_phone", "customer_email"})),
            "sales": SecurityPolicy(
                # 旧销售角色仅开放已配置区域隔离的业务表和公共维表。
                # 这是角色授权范围，不是数据库结构；字段始终从当前数据源读取。
                allowed_tables=frozenset({"sales_orders", "dim_customers", "dim_products", "exchange_rates"}),
                denied_tables=frozenset({"finance_expenses"}),
                denied_columns=frozenset({
                    "customer_phone", "customer_email", "gross_amount", "net_amount",
                    "unit_price", "discount_amount", "material_cost", "standard_cost",
                    "labor_cost", "profit",
                }),
            ),
        }

    def require_user(self, user: UserContext | None) -> UserContext:
        if not isinstance(user, UserContext) or not user.user_id.strip():
            raise SecurityError("缺少可信用户身份，拒绝执行分析。")
        if user.role.lower() not in self.role_policies:
            raise SecurityError("当前账号没有查询权限。")
        if user.role.lower() == "sales" and not (user.region or user.allowed_regions):
            raise SecurityError("销售角色缺少区域权限信息。")
        return user

    def secure_sql(self, sql: str, user: UserContext | None = None, schema: dict | None = None) -> str:
        user = self.require_user(user)
        return self.sql_policy.secure(sql, user, self.role_policies[user.role.lower()], schema=schema,
                                      allowed_tables=user.allowed_tables)

    def mask_result(
        self, columns: list[str], rows: Iterable[tuple | list], user: UserContext | None = None,
    ) -> tuple[list[str], list[tuple]]:
        user = self.require_user(user)
        denied = self.role_policies[user.role.lower()].denied_columns
        return columns, [
            tuple("***" if column.lower() in denied else value for column, value in zip(columns, row))
            for row in rows
        ]
