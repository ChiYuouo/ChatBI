from __future__ import annotations

from dataclasses import dataclass
import logging

from chatbi.core.config import APP_CONFIG, get_database_source_config
from chatbi.core.security import QuerySecurityManager
from chatbi.infrastructure.database import DatabaseClient, QueryExecutionError
from chatbi.infrastructure.database_schema import render_schema
from chatbi.infrastructure.llm_client import LLMClient
from chatbi.retrieval.indicator_knowledge import IndicatorKnowledge
from chatbi.text2sql.query_parser import QueryParser
from chatbi.text2sql.result_formatter import ResultFormatter
from chatbi.infrastructure.datasource_store import get_datasource_store
from chatbi.execution.budget import BudgetExceeded

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AppRuntime:
    source_id: str
    parser: QueryParser
    llm: LLMClient
    db: DatabaseClient
    formatter: ResultFormatter
    indicator_knowledge: IndicatorKnowledge
    schema_text: str | None = None  # 归因请求副本传递结构；实际读取统一走 get_schema_text。
    knowledge_config: dict | None = None  # 前端保存的规则、防护和示例；不作为指标来源。

    def _read_schema(self, budget=None, user=None) -> tuple[list[dict], list[dict]]:
        # 延迟到请求时读取，Schema 不依赖演示常量或过期快照。
        all_tables = self.db.describe_schema(budget)
        get_datasource_store().save_schema(self.source_id, all_tables)
        tables = all_tables
        if user is not None:
            allowed = user.allowed_tables
            policy = QuerySecurityManager().role_policies[user.role.lower()]
            tables = [table for table in tables if table["table_name"].lower() not in policy.denied_tables
                      and (policy.allowed_tables is None or table["table_name"].lower() in policy.allowed_tables)]
            if allowed is not None:
                names = {name.lower() for name in allowed}
                tables = [table for table in tables if table["table_name"].lower() in names]
        if not tables:
            raise QueryExecutionError("permission_denied", "当前账号没有可用的表访问权限")
        return all_tables, tables

    def get_schema_tables(self, budget=None, user=None) -> list[dict]:
        """归因拆解使用同一份授权元数据生成维度，不反向解析提示词。"""
        return self._read_schema(budget, user)[1]

    def get_schema_text(self, budget=None, user=None, *, question: str = "",
                        use_schema_linking: bool = False, required_context: str = "") -> str:
        all_tables, tables = self._read_schema(budget, user)
        if use_schema_linking and question:
            try:
                from chatbi.retrieval.schema_linker import link_schema
                tables = link_schema(question, self.source_id, all_tables, tables,
                                     required_context=required_context, budget=budget)
            except BudgetExceeded:
                raise
            except Exception as exc:
                # 索引或 Embedding 不可用时，只回退当前账号可访问的真实结构。
                logger.warning("Schema Linking 回退全量结构 source=%s error=%s", self.source_id, type(exc).__name__)
        return render_schema(tables)


def build_database_client(app_config: dict | None = None, source_id: str | None = None) -> DatabaseClient:
    config = app_config or APP_CONFIG
    resolved_source_id = source_id or config["database"]["default_source"]
    store = get_datasource_store()
    saved = store.get(resolved_source_id, include_secret=True)
    if saved:
        if not saved["enabled"]:
            raise PermissionError("数据源已停用")
        db_config = saved["config"]
    else:
        db_config = get_database_source_config(resolved_source_id, config)
    return DatabaseClient(db_config=db_config, source_id=resolved_source_id,
                          runtime_config=config["database"].get("runtime"))


def build_runtime(app_config: dict | None = None, source_id: str | None = None) -> AppRuntime:
    config = app_config or APP_CONFIG
    resolved_source_id = source_id or config["database"]["default_source"]
    store = get_datasource_store()
    knowledge_config = store.knowledge(resolved_source_id)
    return AppRuntime(
        source_id=resolved_source_id,
        parser=QueryParser(),
        llm=LLMClient(),
        db=build_database_client(config, resolved_source_id),
        formatter=ResultFormatter(),
        indicator_knowledge=IndicatorKnowledge() if resolved_source_id == config["database"]["default_source"] else IndicatorKnowledge(config_path=None),
        knowledge_config=knowledge_config,
    )
