"""API 请求与响应模型。"""

from typing import Any

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    """查询请求体。"""

    question: str = Field(..., min_length=1, description="业务人员的自然语言问题")
    use_few_shot: bool | None = Field(default=None, description="是否启用 Few-shot 示例")
    use_rules: bool | None = Field(default=None, description="是否启用业务规则约束")
    use_guards: bool | None = Field(default=None, description="是否启用错误防护")
    use_indicator_knowledge: bool | None = Field(default=None, description="是否注入指标知识")
    use_schema_linking: bool | None = Field(default=None, description="是否启用 Schema Linking")
    use_indicator_rag: bool | None = Field(default=None, description="是否启用指标 RAG")
    source_id: str | None = Field(default=None, description="数据源标识；未传时使用系统默认数据源")
    user_id: str | None = Field(default=None, description="用户 ID，可选；未传时优先走请求头")
    user_role: str | None = Field(default=None, description="用户角色：admin / finance / sales")
    user_region: str | None = Field(default=None, description="用户所属区域，行级权限过滤")


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
