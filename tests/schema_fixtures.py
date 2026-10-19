"""现有离线测试使用的结构夹具；从建表脚本读取，生产代码不导入此模块。"""
from pathlib import Path
import re

from chatbi.core.security import QuerySecurityManager
from chatbi.infrastructure.database import DatabaseClient


_ddl = (Path(__file__).resolve().parents[1] / "docker/mysql/init/01-init.sql").read_text(encoding="utf-8")
TEST_SCHEMA = {
    match.group(1): dict.fromkeys(re.findall(r"^\s*`([^`]+)`", match.group(2), flags=re.M), "UNKNOWN")
    for match in re.finditer(r"CREATE TABLE `([^`]+)`\s*\((.*?)\)\s*ENGINE=", _ddl, flags=re.S)
}


class FixtureDatabaseClient(DatabaseClient):
    """测试连接只模拟业务查询，由夹具显式提供结构，不伪装成元数据查询结果。"""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("schema", {name: dict(columns) for name, columns in TEST_SCHEMA.items()})
        super().__init__(*args, **kwargs)


class FixtureSecurityManager(QuerySecurityManager):
    def secure_sql(self, sql, user=None, schema=None):
        return super().secure_sql(sql, user, schema=TEST_SCHEMA if schema is None else schema)
