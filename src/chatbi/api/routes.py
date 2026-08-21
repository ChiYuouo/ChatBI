"""ChatBI API 路由。"""

import logging
from time import perf_counter

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from chatbi.api.dependencies import (
    _build_user_context,
    _resolve_query_options,
    _rows_to_dicts,
    system,
)
from chatbi.api.schemas import ErrorResponse, HealthResponse, QueryRequest, QuerySuccessResponse
from chatbi.config import APP_CONFIG

logger = logging.getLogger("chatbi.api")
router = APIRouter()


@router.get("/", tags=["系统"])
def read_root() -> dict[str, str]:
    """服务说明入口。"""
    return {
        "name": "ChatBI MVP API",
        "docs": "/docs",
        "health": "/health",
        "query": "/api/v1/query",
        "query_stream": "/api/v1/query/stream",
    }


@router.get("/health", response_model=HealthResponse, tags=["系统"])
def health_check() -> HealthResponse:
    """检查 API 服务和数据库连通性。"""
    runtime = system._get_runtime()
    return HealthResponse(
        status="ok",
        database_connected=runtime.db.validate_connection(),
    )


@router.post(
    "/api/v1/query",
    response_model=QuerySuccessResponse,
    tags=["查询"],
    summary="同步查询（一次性返回）",
    responses={
        400: {"model": ErrorResponse, "description": "输入问题不合法"},
        403: {"model": ErrorResponse, "description": "权限不足或安全策略拒绝"},
        422: {"model": ErrorResponse, "description": "生成的 SQL 无法执行"},
        502: {"model": ErrorResponse, "description": "LLM 调用失败"},
        503: {"model": ErrorResponse, "description": "数据库连接异常"},
        504: {"model": ErrorResponse, "description": "数据库查询超时"},
        500: {"model": ErrorResponse, "description": "数据库或服务内部异常"},
    },
)
def query_chatbi(payload: QueryRequest, request: Request) -> QuerySuccessResponse:
    """执行自然语言查询，并返回标准化结果。"""
    started_at = perf_counter()
    logger.info("Received question: %s", payload.question)
    user_context = _build_user_context(request, payload)
    query_options = _resolve_query_options(payload, APP_CONFIG)

    result = system.run(
        user_question=payload.question,
        source_id=payload.source_id,
        security_context=user_context,
        **query_options,
    )

    duration_ms = round((perf_counter() - started_at) * 1000, 2)
    if not result["success"]:
        error_type = result.get("error_type", "internal_server_error")
        status_code = 500
        if error_type == "validation":
            status_code = 400
        elif error_type == "llm":
            status_code = 502
        elif error_type == "security":
            status_code = 403
        elif error_type == "database_sql_syntax":
            status_code = 422
        elif error_type == "database_connection_error":
            status_code = 503
        elif error_type == "database_query_timeout":
            status_code = 504
        raise HTTPException(status_code=status_code, detail=result["error"])

    metadata = {**result.get("metadata", {}), "duration_ms": duration_ms}
    logger.info("Question handled successfully in %.2f ms", duration_ms)
    return QuerySuccessResponse(
        question=payload.question,
        sql=result["sql"],
        columns=result["columns"],
        rows=_rows_to_dicts(result["columns"], result["results"]),
        formatted=result["formatted"],
        metadata=metadata,
    )


@router.post("/api/v1/query/stream", tags=["查询"], summary="SSE 流式查询（逐步推送）")
async def query_chatbi_stream(payload: QueryRequest, request: Request) -> StreamingResponse:
    """执行自然语言查询，以 SSE 流式返回结果。"""
    logger.info("Stream request received: %s", payload.question)
    user_context = _build_user_context(request, payload)
    query_options = _resolve_query_options(payload, APP_CONFIG)

    def event_generator():
        yield from system.run_stream(
            user_question=payload.question,
            source_id=payload.source_id,
            security_context=user_context,
            **query_options,
        )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
