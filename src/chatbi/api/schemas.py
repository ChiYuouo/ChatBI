"""API 请求与响应模型。"""

from typing import Any

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    """查询请求体。"""

    question: str = Field(..., min_length=1, description="业务人员的自然语言问题")
    session_id: str | None = Field(
        default=None,
        max_length=128,
        description=(
            "会话标识；多次查询传同一值即可共享上下文，支持「那2月呢」这类追问。"
            "不传则本次查询无历史，行为与之前完全一致"
        ),
    )
    use_few_shot: bool | None = Field(default=None, description="是否启用 Few-shot 示例")
    use_rules: bool | None = Field(default=None, description="是否启用业务规则约束")
    use_guards: bool | None = Field(default=None, description="是否启用错误防护")
    use_indicator_knowledge: bool | None = Field(default=None, description="是否注入指标知识")
    use_schema_linking: bool | None = Field(default=None, description="是否启用 Schema Linking")
    use_indicator_rag: bool | None = Field(default=None, description="是否启用指标 RAG")
    use_query_rewrite: bool | None = Field(
        default=None,
        description="是否启用提问改写（仅在带 session_id 且已有历史时生效）",
    )
    source_id: str | None = Field(default=None, description="数据源标识；未传时使用系统默认数据源")
    # 注意：这里刻意没有 user_id / user_role / user_region 字段。
    # 身份只来自登录后签发的 token（中间件验签），请求体自报身份是伪造入口。


class AnalyzeRequest(BaseModel):
    """归因分析请求体。"""

    question: str = Field(
        ...,
        min_length=1,
        description="需要归因的业务问题，例如「最近三个月利润为什么下降」",
    )
    max_steps: int | None = Field(
        default=None,
        ge=1,
        le=10,
        description="限制实际执行的子步骤数量，便于控制耗时；未传时执行全部步骤",
    )
    use_indicator_knowledge: bool | None = Field(default=None, description="是否注入指标知识")
    use_schema_linking: bool | None = Field(default=None, description="是否启用 Schema Linking")
    use_indicator_rag: bool | None = Field(default=None, description="是否启用指标 RAG")
    source_id: str | None = Field(default=None, description="数据源标识；未传时使用系统默认数据源")
    # 与 QueryRequest 相同：身份只来自 token，不接受请求体自报


class LoginRequest(BaseModel):
    """登录请求体。"""

    username: str = Field(..., min_length=1, description="用户名")
    password: str = Field(..., min_length=1, description="密码")


class HealthResponse(BaseModel):
    """健康检查响应。"""

    status: str
    database_connected: bool


class QuerySuccessResponse(BaseModel):
    """成功响应。"""

    success: bool = True
    question: str
    sql: str
    columns: list[str]
    rows: list[dict[str, Any]]
    formatted: str
    metadata: dict[str, Any]


class ErrorResponse(BaseModel):
    """错误响应。"""

    success: bool = False
    error: str
    error_type: str
    metadata: dict[str, Any] = Field(default_factory=dict)
