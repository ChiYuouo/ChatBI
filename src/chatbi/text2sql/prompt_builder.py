"""组装 SQL 生成提示词；规则、防护和示例仅来自当前数据源已保存的配置。"""

SYSTEM_PROMPT = "你是一个专业的 SQL 生成助手，擅长根据业务问题生成标准 MySQL 查询语句。"

# SQL 执行能力属于固定技术约束，业务口径由用户配置。
QUERY_REQUIREMENTS = (
    "只输出 SQL 语句，不需要解释",
    "只使用执行层支持的 MySQL 查询语法；合并结果集使用 LEFT JOIN、UNION 与 COALESCE",
    "确保字段名和表名与 Schema 一致",
    "如果涉及多表查询，使用 JOIN 连接",
    "SQL 必须完整闭合，CTE、SELECT、GROUP BY、ORDER BY 不得省略，不要输出截断的半句 SQL",
    "执行层只支持普通聚合、INNER/LEFT JOIN、非相关子查询、非递归 CTE 和 UNION；"
    "不要生成窗口函数、相关子查询或 RIGHT/FULL/CROSS JOIN。多表查询的字段应写明表别名；"
    "优先使用 COUNT、SUM、AVG、MIN、MAX、ROUND、COALESCE、IFNULL、NULLIF、"
    "DATE_FORMAT、DATE_SUB、CURDATE 等已支持的函数；自定义顺序可用 FIELD(列, 常量...)",
)


def build_prompt(
    user_question: str,
    use_few_shot: bool = True,
    use_rules: bool = False,
    use_guards: bool = False,
    indicator_knowledge: str = "",
    history: str = "",
    schema_text: str | None = None,
    rules_text: str | None = None,
    guards_text: str | None = None,
    examples_text: str | None = None,
) -> tuple[str, str]:
    """没有填写的业务内容直接跳过，不回退到内置规则或示例。"""
    if not schema_text or not schema_text.strip():
        raise ValueError("当前数据源没有可用的数据库结构")
    sections = [f"【数据库Schema】\n{schema_text}"]
    if use_rules and rules_text and rules_text.strip():
        sections.append(rules_text.strip())
    if use_guards and guards_text and guards_text.strip():
        sections.append(guards_text.strip())
    if use_few_shot and examples_text and examples_text.strip():
        sections.append(f"【示例】\n{examples_text.strip()}")
    if indicator_knowledge:
        sections.append(indicator_knowledge)
    if history:
        sections.append(f"""【对话历史】
{history}

以上是本会话此前的问答记录。若当前问题包含「那」「这个」「刚才」等指代，
请先结合历史理解其真实含义，再生成 SQL。
当前问题明确给出的时间和范围优先；若要求「所有」「全部」，不要继承历史中的时间筛选。""")
    technical_requirements = "\n".join(f"{number}. {text}" for number, text in enumerate(QUERY_REQUIREMENTS, 1))
    sections.extend([f"【要求】\n{technical_requirements}", f"【用户问题】\n{user_question}", "请直接输出 SQL："])
    return SYSTEM_PROMPT, "\n\n".join(sections)
