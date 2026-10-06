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

    @classmethod
    def from_user(cls, user: UserContext, source_id: str) -> ExecutionContext:
        regions = tuple(user.allowed_regions) or ((user.region,) if user.region else ())
        return cls(user.user_id, user.role, source_id, regions)

    def to_user(self) -> UserContext:
        return UserContext(self.user_id, self.role, allowed_regions=list(self.regions))


@dataclass(frozen=True, slots=True)
class QueryExecutionResult:
    input_sql: str
    executed_sql: str
    source_id: str
    columns: list[str]
    rows: list[tuple]
    duration_ms: float
    explain_plan: list[dict[str, Any]] = field(default_factory=list)

    @property
    def metadata(self) -> dict[str, Any]:
        return {"sql": self.executed_sql, "duration_ms": self.duration_ms,
                "slow_query": bool(self.explain_plan), "explain_plan": self.explain_plan}
