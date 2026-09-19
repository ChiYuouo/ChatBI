"""FastAPI 应用创建与全局中间件配置。"""

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from chatbi.api.dependencies import attach_user_context
from chatbi.api.routes import router
from chatbi.api.schemas import ErrorResponse
from chatbi.core.config import APP_CONFIG

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
| `/api/v1/analyze/stream` | POST | SSE 流式归因分析，多步执行 + 结论报告 |
| `/health` | GET | 健康检查 |

### SSE 流式接口事件类型

`/api/v1/query/stream` 返回 `sql_chunk`、`sql_done`、`result` 和 `error` 事件。

`/api/v1/analyze/stream` 按归因阶段返回 `start`、`decomposition_start`、
`decomposition_done`、`plan_ready`、`step_start`、`step_sql_chunk`、
`step_sql_done`、`step_result`、`step_retry`、`step_done`、`summary_done`、
`report_start`、`report_done`、`done` 和 `error` 事件。

其中 SQL 执行失败时会把数据库报错回灌给模型重写，重写过程通过 `step_retry`
事件（`mode=rewrite`）推送；瞬时故障的原样重试则标记为 `mode=retry`。
""",
        openapi_tags=[
            {"name": "查询", "description": "自然语言转 SQL 查询接口"},
            {"name": "分析", "description": "复杂问题的多步归因分析接口"},
            {"name": "系统", "description": "系统运维与监控接口"},
        ],
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=APP_CONFIG["http"]["cors_allowed_origins"],
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

    return application


app = create_app()
