"""兼容原有 FastAPI 启动入口。"""

import uvicorn

from chatbi.api.app import app, create_app
from chatbi.api.dependencies import (
    _build_user_context,
    _resolve_query_options,
    _rows_to_dicts,
    system,
)
from chatbi.api.routes import health_check, query_chatbi, query_chatbi_stream, read_root
from chatbi.api.schemas import (
    ErrorResponse,
    HealthResponse,
    QueryRequest,
    QuerySuccessResponse,
)

__all__ = [
    "ErrorResponse",
    "HealthResponse",
    "QueryRequest",
    "QuerySuccessResponse",
    "app",
    "create_app",
    "system",
]


if __name__ == "__main__":
    uvicorn.run("api_service:app", host="0.0.0.0", port=8000, reload=True)
