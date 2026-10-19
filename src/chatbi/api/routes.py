"""ChatBI API 路由。"""

import json
import logging
from dataclasses import replace
from decimal import Decimal
from time import perf_counter

import pymysql
from fastapi import APIRouter, HTTPException, Request, Response
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
    DataSourceCreateRequest,
    DataSourceConnectionRequest,
    DataSourceKnowledgeRequest,
    QueryRequest,
    QuerySuccessResponse,
)
from chatbi.core.auth import UserNotFoundError, UsernameAlreadyExistsError, create_token, get_user_store
from chatbi.core.config import APP_CONFIG
from chatbi.infrastructure.datasource_store import get_datasource_store
from chatbi.infrastructure.database_schema import read_schema
from chatbi.infrastructure.datasource_knowledge import merge_knowledge
from chatbi.core.security import UserContext
from chatbi.infrastructure.audit_store import get_trace_events, record_event
from chatbi.retrieval.index_manager import indexes_status

logger = logging.getLogger("chatbi.api")
router = APIRouter()


@router.get("/", tags=["系统"])
def read_root() -> dict[str, str]:
    """服务说明入口。"""
    return {
        "name": "ChatBI MVP API",
        "docs": "/docs",
        "health": "/health",
        "live": "/live",
        "query": "/api/v1/query",
        "query_stream": "/api/v1/query/stream",
        "analyze_stream": "/api/v1/analyze/stream",
    }


@router.get("/health", response_model=HealthResponse, tags=["系统"])
def health_check(response: Response) -> HealthResponse:
    """只读检查数据库与启用功能的索引；未就绪返回 503。"""
    try:
        connected = system._get_runtime().db.validate_connection()
    except Exception:
        connected = False
    features = APP_CONFIG["features"]
    # Schema 索引按数据源延迟构建，未准备好时允许使用真实全量结构。
    # 健康检查只读，不触发结构读取、向量化或索引创建。
    states = indexes_status({"indicator_rag": features.get("indicator_rag", False)})
    retrieval_ready = all(state["status"] == "ready" for state in states.values())
    if features.get("schema_linking", False):
        from chatbi.retrieval.schema_index import schema_index_status
        store = get_datasource_store()
        source_id = APP_CONFIG["database"]["default_source"]
        states["schema"] = {**schema_index_status(source_id, store.tables(source_id)),
                            "required": False, "fallback": "current_full_schema"}
    ready = connected and retrieval_ready
    response.status_code = 200 if ready else 503
    return HealthResponse(
        status="ok" if ready else "degraded", database_connected=connected,
        retrieval_ready=retrieval_ready, indexes=states,
        message=None if ready else ("数据库连接异常" if not connected else "检索索引未就绪，请先初始化"),
    )


@router.get("/live", tags=["系统"])
def liveness() -> dict[str, str]:
    """API 进程存活检查，不访问数据库、索引或模型。"""
    return {"status": "ok"}


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
        raise HTTPException(status_code=403, detail="仅管理员可以执行此操作")
    return current_user


def _audit_identity(user: UserContext, source_id: str | None, session_id: str | None) -> dict:
    return {"trace_id": user.trace_id, "user_id": user.user_id, "role": user.role,
            "source_id": source_id or APP_CONFIG["database"]["default_source"],
            "session_id": session_id}


def _authorize_source(user: UserContext, source_id: str | None) -> UserContext:
    """每次请求都重查启停状态和授权，不能依赖前端数据源列表。"""
    resolved = source_id or APP_CONFIG["database"]["default_source"]
    if resolved == APP_CONFIG["database"]["default_source"]:
        return user
    store = get_datasource_store()
    source = store.get(resolved)
    if not source or not source["enabled"]:
        raise HTTPException(status_code=403, detail="数据源不存在或已停用")
    if user.role == "sales":
        raise HTTPException(status_code=403, detail="新数据源尚未配置销售区域约束，暂不向销售角色开放")
    if user.role == "admin":
        # 管理员使用本次实际结构，避免旧快照把后来新增的表排除在外。
        return user
    tables = store.allowed_tables(resolved, user.user_id, user.role == "admin")
    if not tables:
        raise HTTPException(status_code=403, detail="当前账号未获授权使用此数据源")
    return replace(user, allowed_tables=tables)


@router.get("/api/v1/traces/{trace_id}", tags=["系统"], summary="查询执行链路（管理员）")
def read_trace(trace_id: str, request: Request) -> dict:
    _require_admin(request)
    if len(trace_id) != 32 or any(char not in "0123456789abcdef" for char in trace_id):
        raise HTTPException(status_code=400, detail="追踪编号不合法")
    events = get_trace_events(trace_id)
    if not events:
        raise HTTPException(status_code=404, detail="未找到执行链路")
    return {"trace_id": trace_id, "events": events}


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


@router.get("/api/v1/data-sources", tags=["数据源"], summary="列出可用数据源")
def list_data_sources(request: Request) -> dict:
    user = _build_user_context(request)
    store = get_datasource_store()
    dynamic = store.list(user.user_id, admin=user.role == "admin")
    demo_id = APP_CONFIG["database"]["default_source"]
    demo = {"source_id": demo_id, "name": "演示数据源", "enabled": True, "config_version": 1, "is_default": True}
    return {"data_sources": [demo, *[item for item in dynamic if item["source_id"] != demo_id]]}


def _connection_config(payload: DataSourceConnectionRequest) -> dict:
    return {"host": payload.host, "port": payload.port, "database": payload.database,
              "user": payload.user, "charset": payload.charset, "autocommit": True,
              "connect_timeout": 5, "read_timeout": 8, "write_timeout": 8}


def _probe_connection(config: dict, password: str) -> list[dict]:
    """测试和保存使用同一结构读取流程；这里只读 MySQL，不写入本地配置。"""
    conn = None
    try:
        conn = pymysql.connect(**config, password=password)
        return read_schema(conn, config["database"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("数据源连接或结构读取失败 type=%s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="连接或结构读取失败，请检查账号、权限和网络") from exc
    finally:
        if conn:
            conn.close()


@router.post("/api/v1/data-sources/test-connection", tags=["数据源"], summary="测试未保存的 MySQL 连接（管理员）")
def test_unsaved_data_source(payload: DataSourceConnectionRequest, request: Request) -> dict:
    _require_admin(request)
    tables = _probe_connection(_connection_config(payload), payload.password)
    return {"success": True, "visible_tables": len(tables)}


@router.post("/api/v1/data-sources", status_code=201, tags=["数据源"], summary="保存 MySQL 数据源（管理员）")
def create_data_source(payload: DataSourceCreateRequest, request: Request) -> dict:
    admin = _require_admin(request)
    config = _connection_config(payload)
    # 保存前重新验证；连接和全部普通表结构在同一事务中落盘。
    tables = _probe_connection(config, payload.password)
    try:
        created = get_datasource_store().create(payload.name, config, payload.password, admin.user_id, tables=tables)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {**created, "visible_tables": len(tables)}


@router.get("/api/v1/data-sources/{source_id}/knowledge", tags=["数据源"], summary="读取数据源业务知识（管理员）")
def get_data_source_knowledge(source_id: str, request: Request) -> dict:
    _require_admin(request)
    store = get_datasource_store()
    if source_id != APP_CONFIG["database"]["default_source"] and not store.get(source_id):
        raise HTTPException(status_code=404, detail="数据源不存在")
    return {"source_id": source_id, "knowledge": store.knowledge(source_id)}


@router.put("/api/v1/data-sources/{source_id}/knowledge", tags=["数据源"], summary="保存业务规则、错误防护和 SQL 示例（管理员）")
def update_data_source_knowledge(source_id: str, payload: DataSourceKnowledgeRequest, request: Request) -> dict:
    _require_admin(request)
    store = get_datasource_store()
    if source_id != APP_CONFIG["database"]["default_source"] and not store.get(source_id):
        raise HTTPException(status_code=404, detail="数据源不存在")
    try:
        store.set_knowledge(source_id, merge_knowledge(store.knowledge(source_id), payload.knowledge))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"source_id": source_id, "knowledge": store.knowledge(source_id)}


@router.post(
    "/api/v1/query",
    response_model=QuerySuccessResponse,
    tags=["查询"],
    summary="同步查询（一次性返回）",
    responses={
        400: {"model": ErrorResponse, "description": "输入问题不合法"},
        403: {"model": ErrorResponse, "description": "权限不足或安全策略拒绝"},
        413: {"model": ErrorResponse, "description": "查询结果超过行数或字节限制"},
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
    user_context = _authorize_source(_build_user_context(request), payload.source_id)
    audit = _audit_identity(user_context, payload.source_id, payload.session_id)
    logger.info("Query received trace_id=%s", user_context.trace_id)
    record_event(**audit, event="query_started")
    query_options = _resolve_query_options(payload, APP_CONFIG)

    try:
        result = system.run(
            user_question=payload.question,
            source_id=payload.source_id,
            security_context=user_context,
            session_id=payload.session_id,
            **query_options,
        )
    except Exception as exc:
        record_event(**audit, event="query_failed",
                     duration_ms=round((perf_counter() - started_at) * 1000, 2),
                     error_type=getattr(exc, "error_type", type(exc).__name__))
        raise

    duration_ms = round((perf_counter() - started_at) * 1000, 2)
    if not result["success"]:
        error_type = result.get("error_type", "internal_server_error")
        record_event(**audit, event="query_failed", duration_ms=duration_ms, error_type=error_type)
        status_code = 500
        if error_type == "validation":
            status_code = 400
        elif error_type == "llm":
            status_code = 502
        elif error_type in {"security", "database_permission_denied"}:
            status_code = 403
        elif error_type in {"database_sql_syntax", "sql_generation"}:
            status_code = 422
        elif error_type in {"database_connection_error", "database_schema_error"}:
            status_code = 503
        elif error_type in {"database_query_timeout", "database_budget_exceeded"}:
            status_code = 504
        elif error_type == "database_result_limit":
            status_code = 413
        elif error_type == "database_pool_timeout":
            status_code = 503
        elif error_type == "retrieval_not_ready":
            status_code = 503
        raise HTTPException(status_code=status_code, detail=result["error"])

    record_event(**audit, event="query_succeeded", duration_ms=duration_ms,
                 row_count=len(result["results"]))
    metadata = {**result.get("metadata", {}), "duration_ms": duration_ms,
                "trace_id": user_context.trace_id}
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
    user_context = _authorize_source(_build_user_context(request), payload.source_id)
    audit = _audit_identity(user_context, payload.source_id, payload.session_id)
    logger.info("Stream query received trace_id=%s", user_context.trace_id)
    query_options = _resolve_query_options(payload, APP_CONFIG)

    def event_generator():
        started_at = perf_counter()
        record_event(**audit, event="query_started")
        outcome = "query_succeeded"
        error_type = None
        try:
            for event_type, data in system.run_stream_events(
                user_question=payload.question,
                source_id=payload.source_id,
                security_context=user_context,
                session_id=payload.session_id,
                **query_options,
            ):
                if event_type == "error":
                    outcome = "query_failed"
                    error_type = data.get("error_type", "unknown")
                yield _encode_sse(event_type, {**data, "trace_id": user_context.trace_id})
        except Exception as exc:
            outcome = "query_failed"
            error_type = getattr(exc, "error_type", type(exc).__name__)
            yield _encode_sse("error", {"error": "查询执行失败", "error_type": error_type,
                                        "trace_id": user_context.trace_id})
        finally:
            record_event(**audit, event=outcome,
                         duration_ms=round((perf_counter() - started_at) * 1000, 2),
                         error_type=error_type)

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
def list_sessions(request: Request, source_id: str | None = None) -> dict:
    """侧边栏数据源：当前登录用户的全部会话，按最后活动倒序。"""
    resolved_source = source_id or APP_CONFIG["database"]["default_source"]
    user_context = _authorize_source(_build_user_context(request), resolved_source)
    sessions = system.session_store.list_sessions(user_context.user_id, resolved_source)
    return {"sessions": sessions}


@router.get("/api/v1/session/{session_id}/turns", tags=["查询"], summary="取某会话的全部轮次")
def get_session_turns(session_id: str, request: Request, source_id: str | None = None) -> dict:
    """切换会话时回填历史对话用；只含问题与 SQL，不含结果行。

    answer_text 仅归因分析轮次有值（归因报告 markdown），
    普通查询轮次为 null。
    """
    resolved_source = source_id or APP_CONFIG["database"]["default_source"]
    user_context = _authorize_source(_build_user_context(request), resolved_source)
    turns = system.session_store.get_turns(session_id, user_context.user_id, resolved_source)
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
def clear_session(session_id: str, request: Request, source_id: str | None = None) -> dict:
    """删除该会话在当前用户下的全部历史记录。

    前端「新会话」时必须调用：只切换 session_id 而不删数据，
    旧查询记录（含 SQL）会一直留在磁盘上直到过期清理，
    用户以为清了其实还在。
    """
    resolved_source = source_id or APP_CONFIG["database"]["default_source"]
    user_context = _authorize_source(_build_user_context(request), resolved_source)
    deleted = system.session_store.delete_session(session_id, user_context.user_id, resolved_source)
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
    user_context = _authorize_source(_build_user_context(request), payload.source_id)
    if (payload.source_id or APP_CONFIG["database"]["default_source"]) != APP_CONFIG["database"]["default_source"]:
        raise HTTPException(status_code=409, detail="动态数据源的归因分析尚未接入，请先使用基础查询")
    audit = _audit_identity(user_context, payload.source_id, payload.session_id)
    logger.info("Analyze received trace_id=%s", user_context.trace_id)
    analyze_options = _resolve_analyze_options(payload, APP_CONFIG)

    def event_generator():
        started_at = perf_counter()
        record_event(**audit, event="analysis_started")
        outcome = "analysis_succeeded"
        error_type = None
        try:
            for event_type, data in analysis_service.run_stream_events(
                user_question=payload.question,
                session_id=payload.session_id,
                max_steps=payload.max_steps,
                source_id=payload.source_id,
                security_context=user_context,
                chatbi_run_options=analyze_options,
            ):
                if event_type == "error":
                    outcome = "analysis_failed"
                    error_type = data.get("error_type", "unknown")
                yield _encode_sse(event_type, {**data, "trace_id": user_context.trace_id})
        except Exception as exc:
            outcome = "analysis_failed"
            error_type = getattr(exc, "error_type", type(exc).__name__)
            yield _encode_sse("error", {"error": "分析执行失败", "error_type": error_type,
                                        "trace_id": user_context.trace_id})
        finally:
            record_event(**audit, event=outcome,
                         duration_ms=round((perf_counter() - started_at) * 1000, 2),
                         error_type=error_type)

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
