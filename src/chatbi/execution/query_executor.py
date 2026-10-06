from __future__ import annotations

from typing import TYPE_CHECKING
from time import perf_counter
import sqlglot
from sqlglot import exp

from chatbi.contracts.execution import ExecutionContext, QueryExecutionResult
from chatbi.core.security import QuerySecurityManager, SecurityError, UserContext
from chatbi.execution.budget import ExecutionBudget
from chatbi.infrastructure.audit_store import record_event, sql_digest

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
        started = perf_counter()
        audit = {"trace_id": context.trace_id, "user_id": context.user_id,
                 "role": context.role, "source_id": context.source_id}
        try:
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
        except Exception as exc:
            record_event(**audit, event="sql_rejected", sql_hash=sql_digest(sql),
                         duration_ms=round((perf_counter() - started) * 1000, 2),
                         error_type=getattr(exc, "error_type", type(exc).__name__))
            raise
        digest = sql_digest(secured_sql)
        record_event(**audit, event="sql_started", sql_hash=digest)
        try:
            result = self.database._execute_secured(sql, secured_sql, context, budget)
        except Exception as exc:
            record_event(**audit, event="sql_failed", sql_hash=digest,
                         duration_ms=round((perf_counter() - started) * 1000, 2),
                         error_type=getattr(exc, "error_type", type(exc).__name__))
            raise
        record_event(**audit, event="sql_succeeded", sql_hash=digest,
                     duration_ms=round((perf_counter() - started) * 1000, 2),
                     row_count=len(result.rows))
        return result
