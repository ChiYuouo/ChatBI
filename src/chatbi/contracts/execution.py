from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from chatbi.core.security import UserContext


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """每次执行的身份快照，避免重试或线程共享可变身份。"""

    user_id: str
    role: str
    source_id: str
    regions: tuple[str, ...] = ()
    trace_id: str | None = None

    @classmethod
    def from_user(cls, user: UserContext, source_id: str) -> ExecutionContext:
        regions = tuple(user.allowed_regions) or ((user.region,) if user.region else ())
        return cls(user.user_id, user.role, source_id, regions, user.trace_id)

    def to_user(self) -> UserContext:
        return UserContext(self.user_id, self.role, allowed_regions=list(self.regions), trace_id=self.trace_id)


@dataclass(frozen=True, slots=True)
class QueryExecutionResult:
    input_sql: str
    executed_sql: str
    source_id: str
    columns: list[str]
    rows: list[tuple]
    duration_ms: float
    explain_plan: list[dict[str, Any]] = field(default_factory=list)
    result_bytes: int = 0
    sql_timeout_ms: int | None = None
    slow_query: bool = False

    @property
    def metadata(self) -> dict[str, Any]:
        return {"sql": self.executed_sql, "duration_ms": self.duration_ms,
                "slow_query": self.slow_query or bool(self.explain_plan), "explain_plan": self.explain_plan,
                "result_bytes": self.result_bytes, "sql_timeout_ms": self.sql_timeout_ms,
                "complete": True}
