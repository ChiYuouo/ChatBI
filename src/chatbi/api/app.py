"""FastAPI 应用创建与全局中间件配置。"""

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from chatbi.api.dependencies import attach_user_context
from chatbi.api.routes import router
from chatbi.api.schemas import ErrorResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("chatbi.api")


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用。"""
    application = FastAPI(
        title="ChatBI MVP API",
        version="0.2.0",
        description="""
## ChatBI MVP API

企业级 ChatBI 最小可行产品的服务化接口。

### 接口概览

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/query` | POST | 同步查询，一次性返回完整结果 |
| `/api/v1/query/stream` | POST | SSE 流式查询，逐步推送 SQL 和结果 |
| `/health` | GET | 健康检查 |

### SSE 流式接口事件类型

`/api/v1/query/stream` 返回 `sql_chunk`、`sql_done`、`result` 和 `error` 事件。
""",
        openapi_tags=[
            {"name": "查询", "description": "自然语言转 SQL 查询接口"},
            {"name": "系统", "description": "系统运维与监控接口"},
        ],
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.middleware("http")(attach_user_context)

    @application.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ):
        return JSONResponse(
            status_code=422,
            content=ErrorResponse(
                error="请求参数校验失败",
                error_type="request_validation",
                metadata={
                    "path": str(request.url.path),
                    "details": exc.errors(),
                },
            ).model_dump(),
        )

    @application.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(
                error=str(exc.detail),
                error_type="http_exception",
                metadata={"path": str(request.url.path)},
            ).model_dump(),
        )

    @application.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled server error: %s", exc)
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error="服务内部异常",
                error_type="internal_server_error",
                metadata={"path": str(request.url.path)},
            ).model_dump(),
        )

    application.include_router(router)

    static_dir = Path(__file__).resolve().parents[3] / "static"
    if static_dir.is_dir():
        application.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    return application


app = create_app()
