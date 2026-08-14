"""
数据库模块

负责数据库连接、SQL 执行和结果获取。
将数据库操作封装为独立模块，便于后续扩展（如连接池、读写分离等）。
"""

from __future__ import annotations

from typing import Any, Callable

import pymysql

from config import DB_CONFIG
from security import QuerySecurityManager, UserContext


class DatabaseClient:
    """MySQL 数据库客户端"""

    def __init__(
        self,
        connection_factory: Callable[[], Any] | None = None,
        security_manager: QuerySecurityManager | None = None,
    ):
        self.config = DB_CONFIG
        self.connection_factory = connection_factory or (
            lambda: pymysql.connect(**self.config)
        )
        self.security = security_manager or QuerySecurityManager()

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
        user_context = user or UserContext.demo_admin()
        secured_sql = self.security.secure_sql(sql, user_context)
        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                cursor.execute(secured_sql)
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
                results = cursor.fetchall()
                _, masked_rows = self.security.mask_result(columns, results, user_context)
                return columns, masked_rows
        finally:
            conn.close()

    def validate_connection(self) -> bool:
        """验证数据库连接是否正常"""
        try:
            conn = pymysql.connect(**self.config)
            conn.close()
            return True
        except Exception:
            return False