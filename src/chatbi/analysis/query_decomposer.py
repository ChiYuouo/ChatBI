"""
Query 拆解器模块

将复杂分析问题拆解为结构化子任务列表，为后续 Planner 提供稳定输入。
"""

import json
from pathlib import Path
import re
from typing import Callable

from pydantic import BaseModel, Field, ValidationError

from chatbi.infrastructure.llm_client import LLMClient


class DecomposedTask(BaseModel):
    """单个子任务定义。"""

    task_id: str
    task_name: str
    task_type: str
    description: str
    depends_on: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)


class DecompositionPlan(BaseModel):
    """复杂查询拆解结果。"""

    question_type: str
    analysis_goal: str
    subtasks: list[DecomposedTask]


def build_dimension_catalog(schema_text: str, schema_tables: list[dict] | None = None) -> dict[str, str]:
    """维度候选来自当前可见字段；注释用于说明，表名.字段名用于消除同名歧义。"""
    if schema_tables is not None:
        return {f"{table['table_name']}.{column['name']}": column.get("comment") or column["name"]
                for table in schema_tables for column in table["columns"]}

    catalog = {}
    table_name = ""
    for line in schema_text.splitlines():
        table = re.match(r"^表：([^（]+?)(?:（.*)?$", line.strip())
        if table:
            table_name = table.group(1).strip()
            continue
        column = re.match(r"^- (\S+) .+? (?:可空|不可空)；(.*)$", line.strip())
        if table_name and column:
            catalog[f"{table_name}.{column.group(1)}"] = column.group(2).strip() or column.group(1)
        compact = re.fullmatch(r"\s*([\w]+)\(([^()]*)\)\s*", line)
        if compact:
            for field in compact.group(2).split(","):
                name = field.strip().split()
                if name:
                    catalog[f"{compact.group(1)}.{name[0]}"] = name[0]
    return catalog


def _load_indicator_catalog() -> list[str]:
    config_path = Path(__file__).resolve().parents[3] / "indicators_full.json"
    with config_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    names: list[str] = []
    for indicator in data.get("indicators", []):
        names.append(indicator["name"])
        names.extend(indicator.get("aliases", []))
    return names


def _max_tasks_for_question_type(question_type: str) -> int:
    normalized = question_type.lower()
    if "trend" in normalized or "趋势" in question_type:
        return 6
    if "diagnosis" in normalized or "原因" in question_type or "下降" in question_type:
        return 6
    if "dimension" in normalized or "维度" in question_type:
        return 5
    return 8


def build_decomposition_prompt(user_question: str, schema_text: str,
                               dimension_catalog: dict[str, str] | None = None) -> tuple[str, str]:
    """构造 Query 拆解 Prompt。"""
    indicator_catalog = "、".join(_load_indicator_catalog())
    dimensions = build_dimension_catalog(schema_text) if dimension_catalog is None else dimension_catalog
    dimension_text = "\n".join(f"- {name}：{description}" for name, description in dimensions.items())
    system_msg = (
        "你是企业级 ChatBI 系统中的任务拆解器。"
        "请把复杂分析问题拆成可执行的子任务列表，"
        "输出必须是 JSON，不要输出额外解释。"
    )
    prompt = f"""
【数据库 Schema】
{schema_text}

【可用分析维度】
{dimension_text or '当前结构没有可识别的维度字段，不得自行补充业务维度'}

【可用指标】
{indicator_catalog}

请将下面的复杂分析问题拆解为结构化子任务，并严格输出 JSON：

用户问题：{user_question}

输出要求：
1. 顶层字段包含 question_type、analysis_goal、subtasks
2. subtasks 是有序数组，每个任务必须包含：
   - task_id
   - task_name
   - task_type
   - description
   - depends_on
   - dimensions
   - metrics
3. task_id 使用 task_1、task_2 这类格式
4. depends_on 只能引用前面已经出现的 task_id
5. 每个子任务都应尽量对应一条简单 SQL 或一个单独分析动作，不要把多个分析都塞进同一步
6. 仅返回 JSON 对象，不要使用 Markdown
7. dimensions 只能从【可用分析维度】中选择，填写完整的“表名.字段名”；字段注释用于理解业务含义，不能凭空增加维度，也不能把缺失维度替换成含义不同的字段。无需分组的任务可以填写空数组
8. 指标优先复用【可用指标】中的名称或别名
9. 如果一个任务同时要求多个维度或多个驱动因素，请拆成多个更简单的子任务
10. 每个查询子任务的 description 必须保留原问题的时间、筛选条件、统计范围与单位要求；“所有”仅指原范围内的记录。按月、按年等时间粒度写入 description，dimensions 填写实际使用的日期字段
11. 子任务按业务指标组织；能够用一条 SQL 完成的统计，不要拆成仅过滤记录、关联表、再汇总的技术步骤

【常见分析类型拆解策略】
1. 趋势分析：优先拆成“主指标趋势 + 关键驱动项趋势 + 异常时间段定位 + 原因归纳”，通常不超过 6 个子任务
2. 原因诊断：优先拆成“结果趋势 + 构成拆解 + 关键维度定位 + 必要专项分析 + 结论汇总”，通常不超过 6 个子任务
3. 维度对比：优先拆成“核心维度排名/贡献 + 必要补充维度 + 结论汇总”，通常不超过 5 个子任务
""".strip()
    return system_msg, prompt


class QueryDecomposer:
    """复杂问题拆解器。"""

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        response_generator: Callable[[str, str], str] | None = None,
        schema_text: str = "",
        schema_tables: list[dict] | None = None,
    ):
        self.llm = llm_client or LLMClient()
        self.response_generator = response_generator or self._generate_response
        self.schema_text = schema_text
        self.schema_tables = schema_tables

    def decompose(self, user_question: str) -> dict:
        """将复杂问题拆解为结构化子任务。"""
        question = user_question.strip()
        if not question:
            raise ValueError("输入问题不能为空")

        schema_text = self.schema_text
        schema_tables = self.schema_tables
        if not schema_text:
            # 独立调用拆解器时也读取真实结构；API 路径直接传入当前运行环境的结构。
            from chatbi.bootstrap.runtime_factory import build_database_client
            from chatbi.infrastructure.database_schema import render_schema
            if schema_tables is None:
                db = build_database_client()
                try:
                    schema_tables = db.describe_schema()
                finally:
                    db.close()
            schema_text = render_schema(schema_tables)
        dimensions = build_dimension_catalog(schema_text, schema_tables)
        if not dimensions:
            raise ValueError("当前 Schema 没有可识别的分析字段，请提供结构化元数据")
        system_msg, prompt = build_decomposition_prompt(question, schema_text, dimensions)
        last_error: ValueError | None = None

        for attempt in range(2):
            raw_response = self.response_generator(system_msg, prompt)
            print(f"LLM 原始输出: \n{raw_response}")
            plan = self._parse_plan(raw_response)
            print(f"解析后的子任务: \n{plan}")

            try:
                self._validate_dependencies(plan)
                self._validate_dimensions(plan, dimensions)
                self._validate_plan_complexity(plan)
                return plan.model_dump()
            except ValueError as exc:
                last_error = exc
                if attempt == 1:
                    raise
                prompt = self._build_retry_prompt(prompt, str(exc))

        assert last_error is not None
        raise last_error

    def _generate_response(self, system_msg: str, prompt: str) -> str:
        """默认通过 LLM 生成 JSON 结果。"""
        client = self.llm.request_client() if isinstance(self.llm, LLMClient) else self.llm.client
        response = client.chat.completions.create(
            model=self.llm.model,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            max_tokens=self.llm.max_tokens,
            response_format={"type": "json_object"},
            extra_body={"enable_thinking": False},
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("LLM 没有返回可用的拆解结果")
        return content

    def _parse_plan(self, raw_response: str) -> DecompositionPlan:
        """解析 LLM 返回结果，兼容 Markdown 代码块。"""
        json_text = self._extract_json(raw_response)
        try:
            return DecompositionPlan.model_validate_json(json_text)
        except ValidationError as exc:
            raise ValueError(f"拆解结果结构不合法: {exc}") from exc

    @staticmethod
    def _extract_json(raw_response: str) -> str:
        """从模型输出中提取 JSON 文本。"""
        text = raw_response.strip()
        fence_match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
        if fence_match:
            return fence_match.group(1).strip()

        try:
            json.loads(text)
            return text
        except json.JSONDecodeError as exc:
            raise ValueError("LLM 返回的内容不是合法 JSON") from exc

    @staticmethod
    def _validate_dependencies(plan: DecompositionPlan) -> None:
        """校验依赖任务是否存在且顺序合法。"""
        seen_ids: set[str] = set()
        for task in plan.subtasks:
            for dep_id in task.depends_on:
                if dep_id not in seen_ids:
                    raise ValueError(f"任务 {task.task_id} 依赖了不存在的任务: {dep_id}")
            seen_ids.add(task.task_id)

    def _normalize_plan(
        self,
        user_question: str,
        plan: DecompositionPlan,
    ) -> DecompositionPlan:
        return plan

    @staticmethod
    def _validate_dimensions(plan: DecompositionPlan, dimension_catalog: dict[str, str]) -> None:
        unsupported = sorted(
            {
                dimension
                for task in plan.subtasks
                for dimension in task.dimensions
                if dimension not in dimension_catalog
            }
        )
        if unsupported:
            raise ValueError(f"不支持的分析维度: {', '.join(unsupported)}；只能填写当前 Schema 的表名.字段名")

    @staticmethod
    def _validate_plan_complexity(plan: DecompositionPlan) -> None:
        max_tasks = _max_tasks_for_question_type(plan.question_type)
        if len(plan.subtasks) > max_tasks:
            raise ValueError(
                f"子任务过多：当前 question_type={plan.question_type} 最多允许 {max_tasks} 个子任务，"
                f"实际返回 {len(plan.subtasks)} 个。请合并重复任务并保持每步简单。"
            )

    @staticmethod
    def _build_retry_prompt(prompt: str, error_message: str) -> str:
        return (
            f"{prompt}\n\n"
            "上一次拆解结果不合法，存在以下问题：\n"
            f"{error_message}\n"
            "请重新拆解，并严格修正上述问题后只返回 JSON。"
        )
