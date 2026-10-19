"""
配置管理模块

收拢环境配置、运行配置和功能开关，减少主链路里的硬编码默认值。
"""

from __future__ import annotations

import copy
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def parse_comma_separated(value: str) -> list[str]:
    """把逗号分隔的环境变量解析为非空字符串列表。"""
    return [item.strip() for item in value.split(",") if item.strip()]


def _build_default_db_source() -> dict[str, object]:
    return {
        "driver": os.getenv("DB_DRIVER", "mysql"),
        "host": os.getenv("DB_HOST", "localhost"),
        "port": int(os.getenv("DB_PORT", 3307)),
        "user": os.getenv("DB_USER", "chatbi_reader"),
        "password": os.getenv("DB_PASSWORD", ""),
        "database": os.getenv("DB_NAME", "chatbi_mvp"),
        "charset": "utf8mb4",
        "autocommit": True,
        "connect_timeout": int(os.getenv("DB_CONNECT_TIMEOUT", 5)),
        "read_timeout": int(os.getenv("DB_READ_TIMEOUT", 8)),
        "write_timeout": int(os.getenv("DB_WRITE_TIMEOUT", 8)),
    }


APP_CONFIG = {
    "environment": os.getenv("APP_ENV", "dev"),
    "http": {
        "cors_allowed_origins": parse_comma_separated(
            os.getenv(
                "CORS_ALLOWED_ORIGINS",
                "http://localhost:3000,http://127.0.0.1:3000",
            )
        ),
    },
    "database": {
        "default_source": os.getenv("DB_DEFAULT_SOURCE", "mysql_main"),
        "sources": {
            os.getenv("DB_DEFAULT_SOURCE", "mysql_main"): _build_default_db_source(),
        },
        "runtime": {
            "pool_size": int(os.getenv("DB_POOL_SIZE", 5)),
            "max_overflow": int(os.getenv("DB_POOL_MAX_OVERFLOW", 5)),
            "pool_timeout": float(os.getenv("DB_POOL_TIMEOUT", 3)),
            "slow_query_threshold_ms": float(os.getenv("DB_SLOW_QUERY_THRESHOLD_MS", 200)),
            "max_rows": int(os.getenv("DB_MAX_RESULT_ROWS", 1000)),
            "max_result_bytes": int(os.getenv("DB_MAX_RESULT_BYTES", 1048576)),
            "sql_timeout_ms": int(os.getenv("DB_SQL_TIMEOUT_MS", 5000)),
            "total_timeout_seconds": float(os.getenv("ANALYSIS_TIMEOUT_SECONDS", 120)),
            "max_executions": int(os.getenv("ANALYSIS_MAX_SQL_EXECUTIONS", 20)),
            "max_total_result_bytes": int(os.getenv("ANALYSIS_MAX_RESULT_BYTES", 4194304)),
        },
    },
    "llm": {
        "api_key": os.getenv("OPENAI_API_KEY"),
        "base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        "model": os.getenv("LLM_MODEL", "gpt-4"),
        "embedding_model": os.getenv("EMBEDDING_MODEL", "text-embedding-3-large"),
        "temperature": 0.1,
        "max_tokens": int(os.getenv("LLM_MAX_TOKENS", 4000)),
        "timeout_seconds": float(os.getenv("LLM_TIMEOUT_SECONDS", 30)),
    },
    "features": {
        # 代码默认全部关闭，开启一律通过 .env 显式声明（FEATURE_*），
        # 让实际生效的能力一眼可见，避免「代码里悄悄开着什么」。
        "few_shot": os.getenv("FEATURE_FEW_SHOT", "false").lower() == "true",
        "rules": os.getenv("FEATURE_RULES", "false").lower() == "true",
        "guards": os.getenv("FEATURE_GUARDS", "false").lower() == "true",
        "schema_linking": os.getenv("FEATURE_SCHEMA_LINKING", "false").lower() == "true",
        "indicator_knowledge": os.getenv("FEATURE_INDICATOR_KNOWLEDGE", "false").lower() == "true",
        "indicator_rag": os.getenv("FEATURE_INDICATOR_RAG", "false").lower() == "true",
        "query_rewrite": os.getenv("FEATURE_QUERY_REWRITE", "false").lower() == "true",
    },
}


def get_database_source_config(
    source_id: str | None = None,
    app_config: dict | None = None,
) -> dict[str, object]:
    """返回指定数据源的配置，默认取当前应用默认数据源。"""
    config = app_config or APP_CONFIG
    database_config = config["database"]
    resolved_source_id = source_id or database_config["default_source"]
    source = database_config["sources"].get(resolved_source_id)
    if source is None:
        raise KeyError(f"Unknown database source: {resolved_source_id}")
    return copy.deepcopy(source)


DB_CONFIG = get_database_source_config()
DB_RUNTIME_CONFIG = APP_CONFIG["database"]["runtime"]
LLM_CONFIG = APP_CONFIG["llm"]
# 所有索引共享根目录；Compose 将此目录挂载到持久卷。
CHROMA_ROOT = Path(os.getenv("CHROMA_PERSIST_DIR", str(Path(__file__).resolve().parents[3] / "chroma_db"))).resolve()
