"""API 依赖与请求上下文组装。"""

from typing import Any

from fastapi import Request

from chatbi.analysis.analysis_service import AnalysisService
from chatbi.api.schemas import AnalyzeRequest, QueryRequest
from chatbi.core.config import APP_CONFIG
from chatbi.core.security import UserContext
from chatbi.services.chatbi_service import ChatBISystem

system = ChatBISystem(app_config=APP_CONFIG)

# 归因链路涉及多次 LLM 调用与多步 SQL，实例内只保留无状态编排器，
# 真实的 runtime 与 LLM 客户端在每次请求时按需构建。
analysis_service = AnalysisService()


def _rows_to_dicts(columns: list[str], results: list[tuple]) -> list[dict[str, Any]]:
    """将数据库元组结果转换为 JSON 可直接返回的字典列表。"""
    return [dict(zip(columns, row)) for row in results]


def _build_user_context(
    request: Request,
    payload: QueryRequest | AnalyzeRequest,
) -> UserContext:
    state_context = getattr(request.state, "user_context", UserContext.demo_admin())
    return UserContext(
        user_id=payload.user_id or state_context.user_id,
        role=payload.user_role or state_context.role,
        region=payload.user_region or state_context.region,
    )


def _resolve_query_options(payload: QueryRequest, app_config: dict) -> dict[str, bool]:
    feature_defaults = app_config.get("features", {})
    return {
        "use_few_shot": payload.use_few_shot if payload.use_few_shot is not None else feature_defaults.get("few_shot", False),
        "use_rules": payload.use_rules if payload.use_rules is not None else feature_defaults.get("rules", False),
        "use_guards": payload.use_guards if payload.use_guards is not None else feature_defaults.get("guards", False),
        "use_indicator_knowledge": (
            payload.use_indicator_knowledge
            if payload.use_indicator_knowledge is not None
            else feature_defaults.get("indicator_knowledge", False)
        ),
        "use_schema_linking": (
            payload.use_schema_linking
            if payload.use_schema_linking is not None
            else feature_defaults.get("schema_linking", False)
        ),
        "use_indicator_rag": (
            payload.use_indicator_rag
            if payload.use_indicator_rag is not None
            else feature_defaults.get("indicator_rag", False)
        ),
        "use_query_rewrite": (
            payload.use_query_rewrite
            if payload.use_query_rewrite is not None
            else feature_defaults.get("query_rewrite", True)
        ),
    }


def _resolve_analyze_options(payload: AnalyzeRequest, app_config: dict) -> dict[str, bool]:
    """解析归因链路的子步骤执行选项。

    归因链路由多个子步骤组成，每次子步骤都要走一遍检索与指标注入，
    因此这里默认开启 Schema Linking 与指标 RAG 以提升 SQL 质量，
    可通过请求参数或环境变量单独关闭。
    """
    feature_defaults = app_config.get("features", {})
    return {
        "use_indicator_knowledge": (
            payload.use_indicator_knowledge
            if payload.use_indicator_knowledge is not None
            else feature_defaults.get("indicator_knowledge", True)
        ),
        "use_schema_linking": (
            payload.use_schema_linking
            if payload.use_schema_linking is not None
            else feature_defaults.get("schema_linking", True)
        ),
        "use_indicator_rag": (
            payload.use_indicator_rag
            if payload.use_indicator_rag is not None
            else feature_defaults.get("indicator_rag", True)
        ),
    }


async def attach_user_context(request: Request, call_next):
    """把最小权限上下文挂到 request.state，供查询链路复用。"""
    request.state.user_context = UserContext(
        user_id=request.headers.get("x-user-id", "demo_admin"),
        role=request.headers.get("x-user-role", "admin"),
        region=request.headers.get("x-user-region"),
    )
    return await call_next(request)
