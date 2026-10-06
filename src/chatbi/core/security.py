from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


class SecurityError(Exception):
    """身份、权限或 SQL 安全检查失败，不得交给模型重试绕过。"""


@dataclass(slots=True)
class UserContext:
    """当前请求身份，只能由可信调用方提供。"""

    user_id: str
    role: str = "pending"
    region: str | None = None
    allowed_regions: list[str] = field(default_factory=list)

    @classmethod
    def demo_admin(cls) -> UserContext:
        """离线评测显式使用的身份，业务链路不得自动回退到此身份。"""
        return cls(user_id="demo_admin", role="admin")


@dataclass(frozen=True, slots=True)
class SecurityPolicy:
    denied_columns: frozenset[str] = frozenset()
    denied_tables: frozenset[str] = frozenset()


class QuerySecurityManager:
    """执行前校验原始列来源；结果脱敏仅作为补充保护。"""

    def __init__(self):
        from chatbi.execution.sql_policy import SQLPolicy

        self.sql_policy = SQLPolicy()
        self.role_policies = {
            "admin": SecurityPolicy(),
            "finance": SecurityPolicy(denied_columns=frozenset({"customer_phone", "customer_email"})),
            "sales": SecurityPolicy(
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

    def secure_sql(self, sql: str, user: UserContext | None = None) -> str:
        user = self.require_user(user)
        return self.sql_policy.secure(sql, user, self.role_policies[user.role.lower()])

    def mask_result(
        self, columns: list[str], rows: Iterable[tuple | list], user: UserContext | None = None,
    ) -> tuple[list[str], list[tuple]]:
        user = self.require_user(user)
        denied = self.role_policies[user.role.lower()].denied_columns
        return columns, [
            tuple("***" if column.lower() in denied else value for column, value in zip(columns, row))
            for row in rows
        ]
