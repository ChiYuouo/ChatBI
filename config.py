from dotenv import load_dotenv
load_dotenv()
import os

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", 3306)),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "chatbi_mvp"),
    "charset": "utf8mb4"
}

LLM_CONFIG = {
    "api_key": os.getenv("OPENAI_API_KEY"),
    "model": os.getenv("LLM_MODEL"),
    "base_url": os.getenv("OPENAI_BASE_URL"),
    "embedding_model": os.getenv("EMBEDDING_MODEL"),
    "temperature": 0.2,
    "max_tokens": int(os.getenv("LLM_MAX_TOKENS", 4000)),
    "charset": "utf8mb4",
    "autocommit": True,
    "connect_timeout": int(os.getenv("DB_CONNECT_TIMEOUT", 5)),
    "read_timeout": int(os.getenv("DB_READ_TIMEOUT", 8)),
    "write_timeout": int(os.getenv("DB_WRITE_TIMEOUT", 8)),
}

DB_RUNTIME_CONFIG = {
    "pool_size": int(os.getenv("DB_POOL_SIZE", 5)),
    "max_overflow": int(os.getenv("DB_POOL_MAX_OVERFLOW", 5)),
    "pool_timeout": float(os.getenv("DB_POOL_TIMEOUT", 3)),
    "slow_query_threshold_ms": float(os.getenv("DB_SLOW_QUERY_THRESHOLD_MS", 200)),
}