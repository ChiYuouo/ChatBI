"""检索当前数据源的相关表/字段，补齐指标依赖与真实外键路径后再拼接。"""
from __future__ import annotations

from collections import deque
import re

from chatbi.retrieval.schema_index import recall_schema


def _mentioned(name: str, text: str) -> bool:
    # 使用标识符边界，避免 id 错误匹配到 order_id；允许中文紧接标识符。
    return bool(re.search(r"(?<![a-zA-Z0-9_])" + re.escape(name) + r"(?![a-zA-Z0-9_])", text, re.IGNORECASE))


def _connect_tables(selected: set[str], tables: dict[str, dict]) -> set[str] | None:
    """只使用当前数据库的外键补桥接表；无法连通时回退全量，不推测业务 JOIN。"""
    graph = {name: set() for name in tables}
    for name, table in tables.items():
        for key in table.get("keys", []):
            target = (key.get("referenced_table") or "").lower()
            if key["kind"] == "FOREIGN KEY" and target in graph:
                graph[name].add(target)
                graph[target].add(name)
    connected = {min(selected)}
    for target in sorted(selected - connected):
        queue = deque([(name, [name]) for name in sorted(connected)])
        seen = set(connected)
        while queue:
            node, path = queue.popleft()
            if node == target:
                connected.update(path)
                break
            for neighbor in sorted(graph[node] - seen):
                seen.add(neighbor)
                queue.append((neighbor, path + [neighbor]))
        else:
            return None
    return connected


def link_schema(question: str, source_id: str, all_tables: list[dict], visible_tables: list[dict], *,
                required_context: str = "", budget=None) -> list[dict]:
    """向量只负责定位名称；最终结构、字段类型和关联始终取自本次读取的元数据。"""
    tables = {table["table_name"].lower(): table for table in visible_tables}
    hits = recall_schema(question + ("\n" + required_context if required_context else ""), source_id,
                         all_tables, [table["table_name"] for table in visible_tables], budget=budget)
    selected = set()
    fields: dict[str, set[str]] = {}
    for hit in hits:
        name = hit["table_name"].lower()
        if name in tables:
            selected.add(name)
            if hit["kind"] == "field":
                fields.setdefault(name, set()).add(hit["field_name"].lower())

    # 指标公式、强制过滤和业务规则中的明确引用必须保留，不能被向量排名裁掉。
    context = question + "\n" + required_context
    required_tables = set()
    for name, table in tables.items():
        if _mentioned(table["table_name"], context):
            required_tables.add(name)
        for column in table["columns"]:
            if _mentioned(column["name"], context):
                selected.add(name)
                fields.setdefault(name, set()).add(column["name"].lower())
    selected.update(required_tables)
    if not selected:
        return visible_tables
    connected = _connect_tables(selected, tables)
    if connected is None:
        return visible_tables

    # 保留主键、唯一键和两端关联字段；桥接表也来自授权范围，不扩大可见表。
    for name in connected:
        for key in tables[name].get("keys", []):
            fields.setdefault(name, set()).add(key["column"].lower())
            target = (key.get("referenced_table") or "").lower()
            if target in connected and key.get("referenced_column"):
                fields.setdefault(target, set()).add(key["referenced_column"].lower())
    result = []
    for name, table in tables.items():
        if name not in connected:
            continue
        # 明确引用的表保留全字段；召回只有表、没有字段命中时也保留完整结构。
        matched = fields.get(name, set())
        columns = table["columns"]
        if name not in required_tables and any(hit["table_name"].lower() == name and hit["kind"] == "field" for hit in hits):
            columns = [column for column in columns if column["name"].lower() in matched]
        if not columns:
            return visible_tables
        result.append({**table, "columns": columns})
    return result
