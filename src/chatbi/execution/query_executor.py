from __future__ import annotations

from typing import TYPE_CHECKING
import sqlglot
from sqlglot import exp

from chatbi.contracts.execution import ExecutionContext, QueryExecutionResult
from chatbi.core.security import QuerySecurityManager, SecurityError, UserContext
from chatbi.execution.budget import ExecutionBudget

if TYPE_CHECKING:
    from chatbi.infrastructure.database import DatabaseClient


class QueryExecutor:
    """同步、流式与 Agent 重试共用的执行边界。"""

    def __init__(self, database: DatabaseClient, security: QuerySecurityManager):
        self.database = database
        self.security = security

    def execute(self, sql: str, user: UserContext | None, budget: ExecutionBudget | None = None) -> QueryExecutionResult:
        user = self.security.require_user(user)
        context = ExecutionContext.from_user(user, self.database.source_id)
        if not context.source_id:
            raise SecurityError("缺少数据源执行上下文。")
        secured_sql = self.security.secure_sql(sql, context.to_user())
        budget = budget or ExecutionBudget(self.database.limits)
        budget.remaining()
        tree = sqlglot.parse_one(secured_sql, read="mysql")
        maximum = min(self.database.limits.max_rows, budget.limits.max_rows) + 1
        limit = tree.args.get("limit")
        if limit is None or (
            isinstance(limit.expression, exp.Literal) and int(limit.expression.this) > maximum
        ):
            tree = tree.limit(maximum)
            secured_sql = tree.sql(dialect="mysql", identify=True)
        return self.database._execute_secured(sql, secured_sql, context, budget)
