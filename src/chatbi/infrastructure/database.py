"""
数据库模块

负责数据库连接、SQL 执行和结果获取。
将数据库操作封装为独立模块，便于后续扩展（如连接池、读写分离等）。
"""

from __future__ import annotations

import logging
import json
from threading import Condition
from time import monotonic, perf_counter
from typing import Any, Callable

import pymysql

from chatbi.core.config import APP_CONFIG, DB_RUNTIME_CONFIG, get_database_source_config
from chatbi.core.security import QuerySecurityManager, UserContext
from chatbi.contracts.execution import ExecutionContext, QueryExecutionResult
from chatbi.execution.query_executor import QueryExecutor
from chatbi.execution.budget import BudgetExceeded, ExecutionBudget, ExecutionLimits
from chatbi.infrastructure.database_schema import read_schema

logger = logging.getLogger("chatbi.database")


class QueryExecutionError(RuntimeError):
    """数据库执行失败后的统一异常。"""

    def __init__(
        self,
        error_type: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.error_type = error_type
        self.metadata = metadata or {}


class DatabaseConnectionPool:
    """有界线程安全连接池；创建前预留名额，关闭后归还的连接也会销毁。"""

    def __init__(self, connection_factory: Callable[[], Any], pool_size: int,
                 max_overflow: int = 0, pool_timeout: float = 3.0):
        if pool_size < 1 or max_overflow < 0 or pool_timeout <= 0:
            raise ValueError("连接池容量和等待时间配置不合法。")
        self.connection_factory = connection_factory
        self.pool_size = pool_size
        self.max_overflow = max_overflow
        self.pool_timeout = pool_timeout
        self._condition = Condition()
        self._idle = []
        self._leased = {}
        self._total_connections = 0
        self._closed = False

    @property
    def stats(self) -> dict[str, Any]:
        with self._condition:
            return {"total": self._total_connections, "idle": len(self._idle),
                    "in_use": len(self._leased), "closed": self._closed}

    def acquire(self, timeout: float | None = None) -> Any:
        deadline = monotonic() + min(self.pool_timeout, timeout if timeout is not None else self.pool_timeout)
        while True:
            create = False
            with self._condition:
                if self._closed:
                    raise QueryExecutionError("connection_error", "数据库连接池已经关闭。")
                if self._idle:
                    conn = self._idle.pop()
                    self._leased[id(conn)] = conn
                elif self._total_connections < self.pool_size + self.max_overflow:
                    self._total_connections += 1
                    create = True
                else:
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        raise QueryExecutionError("pool_timeout", "数据库连接池繁忙，等待连接超时。")
                    self._condition.wait(remaining)
                    continue
            if create:
                try:
                    conn = self.connection_factory()
                except BaseException:
                    with self._condition:
                        self._total_connections -= 1
                        self._condition.notify_all()
                    raise
                with self._condition:
                    closed = self._closed
                    if closed:
                        self._total_connections -= 1
                        self._condition.notify_all()
                    else:
                        self._leased[id(conn)] = conn
                if closed:
                    self._close(conn)
                    raise QueryExecutionError("connection_error", "数据库连接池已经关闭。")
                return conn
            try:
                conn.ping(reconnect=False)
                return conn
            except Exception:
                self.release(conn, reusable=False)
                if monotonic() >= deadline:
                    raise QueryExecutionError("connection_error", "数据库空闲连接已失效。")

    def release(self, conn: Any, reusable: bool = True) -> None:
        with self._condition:
            if self._leased.pop(id(conn), None) is None:
                raise ValueError("连接没有借出或已经归还。")
            discard = self._closed or not reusable or len(self._idle) >= self.pool_size
            if discard:
                self._total_connections -= 1
            else:
                self._idle.append(conn)
            self._condition.notify_all()
        if discard:
            self._close(conn)

    def close_all(self) -> None:
        with self._condition:
            self._closed = True
            idle, self._idle = self._idle, []
            self._total_connections -= len(idle)
            self._condition.notify_all()
        for conn in idle:
            self._close(conn)

    @staticmethod
    def _close(conn: Any) -> None:
        try:
            conn.close()
        except Exception:
            logger.debug("Connection close failed", exc_info=True)


class DatabaseClient:
    """MySQL 数据库客户端"""

    def __init__(
        self,
        db_config: dict[str, Any] | None = None,
        source_id: str | None = None,
        connection_factory: Callable[[], Any] | None = None,
        security_manager: QuerySecurityManager | None = None,
        slow_query_threshold_ms: float | None = None,
        time_fn: Callable[[], float] | None = None,
        connection_pool: DatabaseConnectionPool | None = None,
        runtime_config: dict[str, Any] | None = None,
        limits: ExecutionLimits | None = None,
        schema: dict[str, dict[str, str]] | None = None,
    ):
        runtime_config = DB_RUNTIME_CONFIG if runtime_config is None else runtime_config
        self.limits = limits or ExecutionLimits.from_config(runtime_config)
        self.source_id = source_id or APP_CONFIG["database"]["default_source"]
        self.config = db_config or get_database_source_config(self.source_id)
        # 可信调用方可注入已读取的结构；未提供时由执行器在物理表查询前读取。
        self.schema = schema
        self.security = security_manager or QuerySecurityManager()
        self.time_fn = time_fn or perf_counter
        self.slow_query_threshold_ms = (
            slow_query_threshold_ms
            if slow_query_threshold_ms is not None
            else runtime_config.get("slow_query_threshold_ms", 200)
        )
        self.connection_factory = connection_factory
        self.connection_pool = connection_pool
        self.executor = QueryExecutor(self, self.security)

        if self.connection_factory is None and self.connection_pool is None:
            self.connection_pool = DatabaseConnectionPool(
                connection_factory=lambda: pymysql.connect(**self._connection_kwargs()),
                pool_size=runtime_config.get("pool_size", 5),
                max_overflow=runtime_config.get("max_overflow", 5),
                pool_timeout=runtime_config.get("pool_timeout", 3),
            )

    def execute(
        self,
        sql: str,
        user: UserContext | None = None,
    ) -> tuple[list[str], list[tuple]]:
        """
        执行 SQL 并返回结果

        Args:
            sql: 待执行的 SQL 语句

        Returns:
            (列名列表, 结果行列表)
        """
        result = self.execute_query(sql, user)
        return result.columns, result.rows

    def execute_query(self, sql: str, user: UserContext | None = None,
                      budget: ExecutionBudget | None = None) -> QueryExecutionResult:
        """返回独立执行结果；兼容 execute 的二元组接口也经过相同安全入口。"""
        return self.executor.execute(sql, user, budget)

    def _execute_secured(
        self, input_sql: str, secured_sql: str, context: ExecutionContext, budget: ExecutionBudget,
    ) -> QueryExecutionResult:
        started_at = self.time_fn()
        sql_timeout_ms = min(self.limits.sql_timeout_ms, budget.start_execution())
        conn = cursor = None
        reusable = False
        try:
            conn = self._acquire_connection(timeout=budget.remaining())
            sql_timeout_ms = max(1, min(sql_timeout_ms, int(budget.remaining() * 1000)))
            self._set_socket_timeout(conn, budget, sql_timeout_ms)
            # session 设置只能由执行器产生，模型输出中的 SET/优化器提示仍被拒绝。
            with conn.cursor() as setup:
                setup.execute("SET SESSION TRANSACTION READ ONLY")
                setup.execute(f"SET SESSION max_execution_time = {sql_timeout_ms}")
            cursor = conn.cursor(pymysql.cursors.SSCursor)
            self._set_socket_timeout(conn, budget, sql_timeout_ms)
            cursor.execute(secured_sql)
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            results, result_bytes = self._read_result(cursor, columns, conn, budget, sql_timeout_ms)
            duration_ms = round((self.time_fn() - started_at) * 1000, 2)
            explain_plan = self._explain(conn, secured_sql, duration_ms, budget)
            budget.remaining()
            _, masked_rows = self.security.mask_result(columns, results, context.to_user())
            reusable = True
            return QueryExecutionResult(
                input_sql=input_sql, executed_sql=secured_sql, source_id=context.source_id,
                columns=columns, rows=masked_rows, duration_ms=duration_ms, explain_plan=explain_plan,
                result_bytes=result_bytes, sql_timeout_ms=sql_timeout_ms,
                slow_query=duration_ms >= self.slow_query_threshold_ms,
            )
        except (pymysql.MySQLError, OSError) as exc:
            duration_ms = round((self.time_fn() - started_at) * 1000, 2)
            raise self._translate_db_error(exc, secured_sql, duration_ms) from exc
        finally:
            if conn is not None:
                if not reusable:
                    # SSCursor.close() 会读完剩余结果；先断开连接再清理，不能在超限时继续排空。
                    self._release_connection(conn, reusable=False)
                    if isinstance(conn, pymysql.connections.Connection):
                        result = getattr(conn, "_result", None)
                        if result is not None:
                            result.unbuffered_active = False
                            result.connection = None
                        if cursor is not None:
                            cursor.connection = None
                if cursor is not None:
                    try:
                        cursor.close()
                    except BaseException:
                        if reusable:
                            self._release_connection(conn, reusable=False)
                        raise
                if reusable:
                    self._release_connection(conn)

    def _read_result(self, cursor, columns, conn, budget, sql_timeout_ms):
        max_rows = min(self.limits.max_rows, budget.limits.max_rows)
        max_bytes = min(self.limits.max_result_bytes, budget.limits.max_result_bytes)
        size = len(json.dumps({"columns": columns, "rows": []}, ensure_ascii=False).encode("utf-8"))
        if size > max_bytes:
            raise QueryExecutionError("result_limit", "结果列信息超过字节限制，请减少返回字段。")
        budget.consume_result_bytes(size)
        rows = []
        while True:
            self._set_socket_timeout(conn, budget, sql_timeout_ms)
            row = cursor.fetchone()
            budget.remaining()
            if row is None:
                break
            if len(rows) >= max_rows:
                raise QueryExecutionError("result_limit", f"结果超过 {max_rows} 行限制，请增加筛选条件或使用聚合。")
            row_size = len(json.dumps(dict(zip(columns, row)), ensure_ascii=False, default=str).encode("utf-8")) + 2
            if size + row_size > max_bytes:
                raise QueryExecutionError("result_limit", f"结果超过 {max_bytes} 字节限制，请减少返回字段或缩小范围。")
            budget.consume_result_bytes(row_size)
            rows.append(tuple(row))
            size += row_size
        return rows, size

    @staticmethod
    def _set_socket_timeout(conn, budget, sql_timeout_ms):
        remaining = min(budget.remaining(), sql_timeout_ms / 1000 + 0.5)
        if isinstance(conn, pymysql.connections.Connection):
            conn._read_timeout = remaining
            conn._write_timeout = remaining

    def describe_schema(self, budget: ExecutionBudget | None = None) -> list[dict]:
        """查询当前结构；提示词和执行校验使用同一份实时元数据。"""
        budget = budget or ExecutionBudget(self.limits)
        budget.remaining()
        conn = None
        reusable = False
        try:
            conn = self._acquire_connection(timeout=budget.remaining())
            self._set_socket_timeout(conn, budget, self.limits.sql_timeout_ms)
            metadata = read_schema(conn, self.config["database"], budget)
            budget.remaining()
            self.schema = {table["table_name"]: {column["name"]: column["type"] for column in table["columns"]}
                           for table in metadata}
            reusable = True
            return metadata
        except BudgetExceeded:
            raise
        except Exception as exc:
            raise QueryExecutionError("schema_error", "无法读取当前数据源结构，请检查连接与数据库权限") from exc
        finally:
            if conn is not None:
                self._release_connection(conn, reusable=reusable)

    def validate_connection(self) -> bool:
        try:
            conn = self._acquire_connection()
            self._release_connection(conn)
            return True
        except Exception:
            return False

    def close(self) -> None:
        if self.connection_pool is not None:
            self.connection_pool.close_all()

    def _acquire_connection(self, timeout: float | None = None) -> Any:
        if self.connection_pool is not None:
            return self.connection_pool.acquire(timeout)
        if self.connection_factory is None:
            raise RuntimeError("数据库连接工厂未初始化")
        return self.connection_factory()

    def _release_connection(self, conn: Any, reusable: bool = True) -> None:
        if self.connection_pool is not None:
            self.connection_pool.release(conn, reusable=reusable)
        else:
            DatabaseConnectionPool._close(conn)

    def _connection_kwargs(self) -> dict[str, Any]:
        return {key: value for key, value in self.config.items() if key not in {"driver", "name"}}

    def _explain(self, conn, sql: str, duration_ms: float, budget: ExecutionBudget) -> list[dict[str, Any]]:
        if duration_ms < self.slow_query_threshold_ms:
            return []
        # 诊断也服从剩余预算；EXPLAIN 最多读取 100 行，不调用 fetchall。
        try:
            budget.remaining()
            self._set_socket_timeout(conn, budget, self.limits.sql_timeout_ms)
            with conn.cursor() as cursor:
                cursor.execute(f"EXPLAIN {sql}")
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
                rows = cursor.fetchmany(100)
                return [dict(zip(columns, row)) for row in rows]
        except BudgetExceeded:
            raise
        except Exception:
            logger.debug("Failed to capture EXPLAIN plan", exc_info=True)
            return []

    def _translate_db_error(
        self,
        exc: Exception,
        sql: str,
        duration_ms: float,
    ) -> QueryExecutionError:
        error_code = exc.args[0] if getattr(exc, "args", None) else None
        error_text = str(exc)
        metadata = {
            "sql": sql,
            "duration_ms": duration_ms,
            "error_code": error_code,
            "raw_error": error_text,
        }

        # 这些错误码都属于「SQL 写错了」，模型可以据此重写：
        #   1055 GROUP BY 中缺少非聚合列（ONLY_FULL_GROUP_BY）
        #   1056 GROUP BY 中出现了聚合函数
        #   1054 字段不存在   1052 字段名有歧义   1146 表不存在
        _REPAIRABLE_SQL_CODES = {1064, 1055, 1056, 1054, 1052, 1146}

        if error_code in {1044, 1045, 1142, 1143, 1227}:
            return QueryExecutionError(
                "permission_denied",
                "数据库拒绝执行该查询，请检查当前账号权限",
                metadata,
            )
        if error_code in _REPAIRABLE_SQL_CODES:
            return QueryExecutionError(
                "sql_syntax",
                "SQL 语法错误，请检查字段、聚合和别名是否正确",
                metadata,
            )
        if error_code in {1205, 3024} or (
            error_code in {2013}
            and "timed out" in error_text.lower()
        ):
            return QueryExecutionError(
                "query_timeout",
                "SQL 执行超时，请缩小时间范围或减少返回列后重试",
                metadata,
            )
        if isinstance(exc, OSError) or error_code in {2003, 2006, 2013}:
            return QueryExecutionError(
                "connection_error",
                "数据库连接失败，请检查连接池和数据库状态",
                metadata,
            )
        return QueryExecutionError(
            "execution_error",
            f"SQL 执行失败：{error_text}",
            metadata,
        )
