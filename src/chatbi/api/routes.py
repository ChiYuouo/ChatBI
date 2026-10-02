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
    RegisterRequest,
    AuthorizeUserRequest,
    QueryRequest,
    QuerySuccessResponse,
)
from chatbi.core.auth import UserNotFoundError, UsernameAlreadyExistsError, create_token, get_user_store
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


@router.post("/api/v1/login", tags=["系统"], summary="登录")
def login(payload: LoginRequest) -> dict:
    """用户名密码换身份 token。

    token 内含 user_id / role / region，后续请求会重新核对当前账号；
    请求体自报身份的通道已删除。
    """
    user = get_user_store().authenticate(payload.username, payload.password)
    if user is None:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if user.role == "pending":
        raise HTTPException(status_code=403, detail="账号待授权，请联系管理员")
    return {
        "token": create_token(user),
        "user": {
            "user_id": user.user_id,
            "username": user.username,
            "role": user.role,
            "region": user.region,
        },
    }


@router.post("/api/v1/register", status_code=201, tags=["系统"], summary="注册")
def register(payload: RegisterRequest) -> dict:
    """创建待授权账号；公开注册不能自行取得查询权限。"""
    try:
        get_user_store().register(payload.username, payload.password)
    except UsernameAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"message": "注册成功，请等待管理员授权"}


def _user_response(user) -> dict:
    return {
        "user_id": user.user_id,
        "username": user.username,
        "role": user.role,
        "region": user.region,
    }


def _require_admin(request: Request) -> UserContext:
    current_user = _build_user_context(request)
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可以管理用户授权")
    return current_user


@router.get("/api/v1/me", tags=["系统"], summary="当前用户")
def current_user(request: Request) -> dict:
    user = get_user_store().get(_build_user_context(request).user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="用户不存在")
    return _user_response(user)


@router.get("/api/v1/users", tags=["系统"], summary="用户列表（管理员）")
def list_users(request: Request) -> list[dict]:
    _require_admin(request)
    return [_user_response(user) for user in get_user_store().list_users()]


@router.patch("/api/v1/users/{user_id}/authorization", tags=["系统"], summary="分配用户角色和区域（管理员）")
def authorize_user(user_id: str, payload: AuthorizeUserRequest, request: Request) -> dict:
    admin = _require_admin(request)
    if user_id == admin.user_id:
        raise HTTPException(status_code=400, detail="不能修改自己的角色")
    try:
        user = get_user_store().set_authorization(user_id, payload.role, payload.region)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _user_response(user)


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


@router.get("/api/v1/sessions", tags=["查询"], summary="列出当前用户的会话")
def list_sessions(request: Request) -> dict:
    """侧边栏数据源：当前登录用户的全部会话，按最后活动倒序。"""
    user_context = _build_user_context(request)
    sessions = system.session_store.list_sessions(user_context.user_id)
    return {"sessions": sessions}


@router.get("/api/v1/session/{session_id}/turns", tags=["查询"], summary="取某会话的全部轮次")
def get_session_turns(session_id: str, request: Request) -> dict:
    """切换会话时回填历史对话用；只含问题与 SQL，不含结果行。

    answer_text 仅归因分析轮次有值（归因报告 markdown），
    普通查询轮次为 null。
    """
    user_context = _build_user_context(request)
    turns = system.session_store.get_turns(session_id, user_context.user_id)
    return {
        "session_id": session_id,
        "turns": [
            {
                "question": t.question,
                "sql": t.sql,
                "answer": t.answer,
                "created_at": t.created_at,
            }
            for t in turns
        ],
    }


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
            session_id=payload.session_id,
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
