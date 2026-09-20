"""ChatBI API 路由。"""

import json
import logging
from decimal import Decimal
from time import perf_counter

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from chatbi.api.dependencies import (
    _build_user_context,
    _resolve_analyze_options,
    _resolve_query_options,
    _rows_to_dicts,
    analysis_service,
    system,
)
from chatbi.api.schemas import (
    AnalyzeRequest,
    ErrorResponse,
    HealthResponse,
    LoginRequest,
    QueryRequest,
    QuerySuccessResponse,
)
from chatbi.core.auth import UserStore, create_token
from chatbi.core.config import APP_CONFIG
from chatbi.core.security import UserContext

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
        "analyze_stream": "/api/v1/analyze/stream",
    }


@router.get("/health", response_model=HealthResponse, tags=["系统"])
def health_check() -> HealthResponse:
    """检查 API 服务和数据库连通性。"""
    runtime = system._get_runtime()
    return HealthResponse(
        status="ok",
        database_connected=runtime.db.validate_connection(),
    )


_auth_store: UserStore | None = None


def _get_auth_store() -> UserStore:
    """懒加载用户存储：仅 import 本模块不应在工作区落下 users.db。"""
    global _auth_store
    if _auth_store is None:
        _auth_store = UserStore()
    return _auth_store


@router.post("/api/v1/login", tags=["系统"], summary="登录")
def login(payload: LoginRequest) -> dict:
    """用户名密码换身份 token。

    token 内含 user_id / role / region，之后所有请求凭它确定身份；
    请求体自报身份的通道已删除。
    """
    user = _get_auth_store().authenticate(payload.username, payload.password)
    if user is None:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return {
        "token": create_token(user),
        "user": {
            "user_id": user.user_id,
            "username": user.username,
            "role": user.role,
            "region": user.region,
        },
    }


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
    user_context = _build_user_context(request)
    query_options = _resolve_query_options(payload, APP_CONFIG)

    result = system.run(
        user_question=payload.question,
        source_id=payload.source_id,
        security_context=user_context,
        session_id=payload.session_id,
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
    user_context = _build_user_context(request)
    query_options = _resolve_query_options(payload, APP_CONFIG)

    def event_generator():
        yield from system.run_stream(
            user_question=payload.question,
            source_id=payload.source_id,
            security_context=user_context,
            session_id=payload.session_id,
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


@router.delete(
    "/api/v1/session/{session_id}",
    tags=["查询"],
    summary="清空指定会话的历史上下文",
)
def clear_session(session_id: str, request: Request) -> dict:
    """删除该会话在当前用户下的全部历史记录。

    前端「新会话」时必须调用：只切换 session_id 而不删数据，
    旧查询记录（含 SQL）会一直留在磁盘上直到过期清理，
    用户以为清了其实还在。
    """
    user_context = getattr(request.state, "user_context", UserContext.demo_admin())
    deleted = system.session_store.delete_session(session_id, user_context.user_id)
    logger.info(
        "会话历史清除: session=%s user=%s deleted=%s",
        session_id,
        user_context.user_id,
        deleted,
    )
    return {"session_id": session_id, "deleted": deleted}


@router.post(
    "/api/v1/analyze/stream",
    tags=["分析"],
    summary="SSE 流式归因分析（多步执行 + 结论）",
)
async def analyze_chatbi_stream(payload: AnalyzeRequest, request: Request) -> StreamingResponse:
    """对复杂业务问题做归因分析，以 SSE 流式返回全流程进展。

    事件类型见 `chatbi.analysis.analysis_service.AnalysisService.run_stream_events`。
    归因链路包含拆解、多步 SQL 与报告生成，耗时明显长于单次查询，
    因此只提供流式接口，前端可实时看到每一步的进展。
    """
    logger.info("Analyze request received: %s", payload.question)
    user_context = _build_user_context(request)
    analyze_options = _resolve_analyze_options(payload, APP_CONFIG)

    def event_generator():
        for event_type, data in analysis_service.run_stream_events(
            user_question=payload.question,
            max_steps=payload.max_steps,
            source_id=payload.source_id,
            security_context=user_context,
            chatbi_run_options=analyze_options,
        ):
            yield _encode_sse(event_type, data)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _encode_sse(event_type: str, data: dict) -> str:
    """把归因事件编码为 SSE 字符串。

    归因链路的中间结果包含 Decimal 等非标准 JSON 类型，这里统一兜底序列化。
    """
    payload = json.dumps(
        data,
        ensure_ascii=False,
        default=_json_default,
    )
    return f"event: {event_type}\ndata: {payload}\n\n"


def _json_default(value):
    if isinstance(value, Decimal):
        return float(value)
    return str(value)
