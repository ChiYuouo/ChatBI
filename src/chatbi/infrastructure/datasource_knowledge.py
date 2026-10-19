"""将历史整段提示词迁为条目；查询链路继续读取自动汇总的文本。"""
from __future__ import annotations

from copy import deepcopy
import re


RULE_SECTIONS = {
    "business_rule_items": "business_rules",
    "error_guard_items": "error_guards",
    "requirement_items": "prompt_requirements",
}
SECTION_HEADINGS = {
    "business_rule_items": "关键业务规则",
    "error_guard_items": "常见错误防护",
}
_LEADING_MARKER = re.compile(r"^(?:\d+[.、)）](?!\d)\s*|[-*•]\s+)")
_OLD_SECTION = re.compile(r"^【(?:关键业务规则|业务规则|常见错误防护|错误防护|本数据源补充要求|回答与查询要求|查询要求)】\s*")


def clean_rule_item(item: dict) -> dict:
    """仅移除条目外层的旧排版，不改正文内部的换行、子步骤或 SQL。"""
    result = deepcopy(item)
    title = _LEADING_MARKER.sub("", result["title"].strip())
    body = result["content"].strip()
    body = _OLD_SECTION.sub("", body)
    body = _LEADING_MARKER.sub("", body)
    # 标题已经单独保存，正文不再重复“收入口径：”这一类前缀。
    body = re.sub(r"^" + re.escape(title) + r"\s*[:：]\s*", "", body, count=1)
    result.update(title=title, content=body or result["content"].strip())
    return result


def render_rules(items: list[dict], heading: str | None = None) -> str:
    if not items:
        return ""
    blocks = []
    for number, item in enumerate(items, 1):
        title, content = item["title"], item["content"]
        text = content if title == content else f"{title}：{content}"
        blocks.append(f"{number}. {text}")
    prefix = f"【{heading}】\n\n" if heading else ""
    return prefix + "\n\n".join(blocks)


def split_rules(text: str) -> list[dict]:
    if not text.strip():
        return []
    # 只在行首的一级编号/项目符号处分割，保留每条内部的换行和 SQL。
    starts = list(re.finditer(r"(?m)^(?:\d+[.、)]\s*|-\s+)", text))
    if starts:
        chunks = [text[match.start():starts[i + 1].start() if i + 1 < len(starts) else len(text)]
                  for i, match in enumerate(starts)]
        prefix = text[:starts[0].start()].strip()
        if prefix:
            chunks[0] = prefix + "\n\n" + chunks[0]
    else:
        chunks = [text]
    items = []
    for i, chunk in enumerate(chunks):
        content = chunk.strip()
        lines = [line for line in content.splitlines() if line.strip() and not line.startswith("【")]
        first = re.sub(r"^(?:\d+[.、)]\s*|-\s+)", "", lines[0]) if lines else content
        title = re.split(r"[:：]", first, maxsplit=1)[0][:50]
        items.append(clean_rule_item({"title": title or f"规则 {i + 1}", "content": content}))
    return items


def split_examples(text: str) -> list[dict]:
    if not text.strip():
        return []
    chunks = re.split(r"(?m)^\s*示例\s*\d+\s*[:：]\s*\n?", text)
    result = []
    for chunk in chunks:
        if not chunk.strip():
            continue
        match = re.fullmatch(r"\s*问题\s*[:：]\s*(.*?)\n\s*SQL\s*[:：]\s*(.+?)\s*", chunk, re.DOTALL | re.IGNORECASE)
        if match:
            result.append({"question": match[1].strip(), "sql": match[2].strip()})
        else:
            # 无法可靠识别的历史内容完整保留，交给管理员逐条整理。
            result.append({"kind": "legacy", "content": chunk.strip()})
    return result


def normalize_knowledge(knowledge: dict) -> dict:
    result = deepcopy(knowledge)
    if not result:
        return result  # 未配置业务知识时保持为空。
    originals = result.setdefault("legacy_texts", {})
    old_items = result.get("rule_items_version", 1) != 2
    for items_key, text_key in RULE_SECTIONS.items():
        if items_key not in result:
            raw = result.get(text_key, "")
            result[items_key] = split_rules(raw)
            if raw:
                originals.setdefault(text_key, raw)
        elif old_items:
            cleaned = [clean_rule_item(item) for item in result[items_key]]
            if cleaned != result[items_key]:
                # 上个版本已经拆条但带有编号：同时备份条目，防止覆盖人工调整。
                result.setdefault("legacy_rule_items", {}).setdefault(items_key, deepcopy(result[items_key]))
            result[items_key] = cleaned
        result[text_key] = render_rules(result[items_key], SECTION_HEADINGS.get(items_key))
    result["rule_items_version"] = 2
    requirements = result["requirement_items"]
    if requirements:
        # 合并旧的“回答与查询要求”，只去除标题和正文完全相同的重复条目。
        result.setdefault("legacy_rule_items", {}).setdefault("requirement_items", deepcopy(requirements))
        existing = {(item["title"].strip(), item["content"].strip()) for item in result["business_rule_items"]}
        for item in requirements:
            identity = (item["title"].strip(), item["content"].strip())
            if identity not in existing:
                result["business_rule_items"].append(item)
                existing.add(identity)
    # 保留空兼容键，避免下一次读取又从历史文本中恢复已迁移/删除的规则。
    result["requirement_items"] = []
    result["prompt_requirements"] = ""
    result["business_rules"] = render_rules(result["business_rule_items"], SECTION_HEADINGS["business_rule_items"])
    if "system_prompt" in result:
        originals.setdefault("system_prompt", result.pop("system_prompt"))
    if "sql_examples" not in result:
        raw = result.get("few_shot_examples", "")
        result["sql_examples"] = split_examples(raw)
        if raw:
            originals.setdefault("few_shot_examples", raw)
    result["few_shot_examples"] = "\n\n".join(
        item["content"] if item.get("kind") == "legacy" else f"示例 {number}：\n问题：{item['question']}\nSQL：{item['sql']}"
        for number, item in enumerate(result["sql_examples"], 1)
    )
    return result


def merge_knowledge(current: dict, changes: dict) -> dict:
    """只更新三类业务知识，兼容旧文本提交并保留备份及其他历史配置。"""
    sections = {**RULE_SECTIONS, "sql_examples": "few_shot_examples"}
    editable = {*sections, *sections.values(), "system_prompt"}
    updates = {key: value for key, value in changes.items() if key in editable}
    result = deepcopy(current)
    for items_key, text_key in sections.items():
        if text_key in updates and items_key not in updates:
            # 旧客户端只提交整段文本时，重新拆条，不能被已有条目覆盖。
            result.pop(items_key, None)
    result.update(updates)
    return result


def validate_knowledge_entries(knowledge: dict) -> None:
    """先校验条目再汇总，避免不合法列表造成保存或运行时异常。"""
    if "legacy_texts" in knowledge and not isinstance(knowledge["legacy_texts"], dict):
        raise ValueError("历史文本备份格式不正确")
    for key in (*RULE_SECTIONS.values(), "few_shot_examples", "system_prompt"):
        if key in knowledge and not isinstance(knowledge[key], str):
            raise ValueError(f"{key} 必须是文本")
    for key in RULE_SECTIONS:
        if key not in knowledge:
            continue
        items = knowledge[key]
        if not isinstance(items, list):
            raise ValueError("规则必须是条目列表")
        for item in items:
            if not isinstance(item, dict) or any(not isinstance(item.get(field), str) or not item[field].strip() for field in ("title", "content")):
                raise ValueError("每条规则都需要填写标题和内容")
    if "sql_examples" in knowledge:
        if not isinstance(knowledge["sql_examples"], list):
            raise ValueError("SQL 示例必须是条目列表")
        for item in knowledge["sql_examples"]:
            if not isinstance(item, dict):
                raise ValueError("SQL 示例格式不正确")
            fields = ("content",) if item.get("kind") == "legacy" else ("question", "sql")
            if any(not isinstance(item.get(field), str) or not item[field].strip() for field in fields):
                raise ValueError("每条 SQL 示例都需要填写问题和 SQL；历史文本不能留空")
