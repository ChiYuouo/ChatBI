"""请求级预算；模型不能修改，重试和子步骤共享同一截止时间。"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock
from time import monotonic
from typing import Callable


class BudgetExceeded(RuntimeError):
    error_type = "budget_exceeded"


_current_budget = ContextVar("chatbi_execution_budget", default=None)


@contextmanager
def bind_budget(budget):
    token = _current_budget.set(budget)
    try:
        yield
    finally:
        _current_budget.reset(token)


def request_timeout(default: float) -> float:
    budget = _current_budget.get()
    return min(default, budget.remaining()) if budget is not None else default


def budgeted_events(iterator, budget):
    # SSE 的不同 next() 可能运行在不同线程；预算上下文只包住一次 next，不跨 yield。
    try:
        while True:
            with bind_budget(budget):
                try:
                    event = next(iterator)
                except StopIteration:
                    return
            yield event
    finally:
        with bind_budget(budget):
            iterator.close()


@dataclass(frozen=True, slots=True)
class ExecutionLimits:
    max_rows: int = 1000
    max_result_bytes: int = 1048576
    sql_timeout_ms: int = 5000
    total_timeout_seconds: float = 120
    max_executions: int = 20
    max_total_result_bytes: int = 4194304

    def __post_init__(self):
        if any(not isfinite(value) or value <= 0 for value in (self.max_rows, self.max_result_bytes, self.sql_timeout_ms,
                self.total_timeout_seconds, self.max_executions, self.max_total_result_bytes)):
            raise ValueError("执行预算必须大于零。")

    @classmethod
    def from_config(cls, config: dict) -> ExecutionLimits:
        names = cls.__dataclass_fields__
        return cls(**{key: value for key, value in config.items() if key in names})


class ExecutionBudget:
    def __init__(self, limits: ExecutionLimits | None = None, clock: Callable[[], float] = monotonic):
        self.limits = limits or ExecutionLimits()
        self.clock = clock
        self.deadline = clock() + self.limits.total_timeout_seconds
        self._lock = Lock()
        self.executions = 0
        self.result_bytes = 0

    def remaining(self) -> float:
        remaining = self.deadline - self.clock()
        if remaining <= 0:
            raise BudgetExceeded("分析总时间预算已耗尽，请缩小问题范围后重试。")
        return remaining

    def start_execution(self) -> int:
        self.remaining()
        with self._lock:
            if self.executions >= self.limits.max_executions:
                raise BudgetExceeded("分析 SQL 执行次数预算已耗尽，修复重试也计入次数。")
            self.executions += 1
        return max(1, min(self.limits.sql_timeout_ms, int(self.remaining() * 1000)))

    def consume_result_bytes(self, size: int) -> None:
        self.remaining()
        with self._lock:
            if self.result_bytes + size > self.limits.max_total_result_bytes:
                raise BudgetExceeded("分析累计结果大小预算已耗尽，请减少返回字段或缩小查询范围。")
            self.result_bytes += size
