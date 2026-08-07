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
    "temperature": 0.2,
    "max_tokens": 1024,
}