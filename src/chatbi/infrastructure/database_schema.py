"""从当前 MySQL 读取结构事实，并拼接成提示词；不包含业务口径。"""
from __future__ import annotations


def read_schema(conn, database: str, budget=None) -> list[dict]:
    def execute(cursor, sql):
        if budget is not None:
            budget.remaining()
        cursor.execute(sql, (database,))
        return cursor.fetchall()

    with conn.cursor() as cursor:
        rows = execute(cursor, """SELECT TABLE_NAME,TABLE_COMMENT FROM information_schema.TABLES
            WHERE TABLE_SCHEMA=%s AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME""")
        tables = {name: {"table_name": name, "comment": comment or "", "columns": [], "keys": []}
                  for name, comment in rows}
        if not tables:
            raise ValueError("未发现可用普通表，请检查数据库名和账号权限")
        rows = execute(cursor, """SELECT TABLE_NAME,COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,
            COLUMN_COMMENT,COLUMN_KEY,ORDINAL_POSITION FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME,ORDINAL_POSITION""")
        for table, name, kind, nullable, comment, key, position in rows:
            if table in tables:
                tables[table]["columns"].append({"name": name, "type": kind, "nullable": nullable == "YES",
                                                 "comment": comment or "", "key": key, "position": position})
        if any(not table["columns"] for table in tables.values()):
            raise ValueError("部分表无法读取字段结构，请检查数据库权限")
        rows = execute(cursor, """SELECT k.TABLE_NAME,k.COLUMN_NAME,k.CONSTRAINT_NAME,k.REFERENCED_TABLE_NAME,
            k.REFERENCED_COLUMN_NAME,k.ORDINAL_POSITION,c.CONSTRAINT_TYPE
            FROM information_schema.KEY_COLUMN_USAGE k
            JOIN information_schema.TABLE_CONSTRAINTS c
              ON c.CONSTRAINT_SCHEMA=k.CONSTRAINT_SCHEMA AND c.TABLE_NAME=k.TABLE_NAME
             AND c.CONSTRAINT_NAME=k.CONSTRAINT_NAME
            WHERE k.TABLE_SCHEMA=%s AND c.CONSTRAINT_TYPE IN ('PRIMARY KEY','UNIQUE','FOREIGN KEY')
            ORDER BY k.TABLE_NAME,k.CONSTRAINT_NAME,k.ORDINAL_POSITION""")
        for table, column, constraint, referenced_table, referenced_column, position, kind in rows:
            if table in tables:
                tables[table]["keys"].append({"column": column, "constraint": constraint, "kind": kind,
                                              "referenced_table": referenced_table, "referenced_column": referenced_column,
                                              "position": position})
    return list(tables.values())


def render_schema(tables: list[dict]) -> str:
    blocks = []
    names = {table["table_name"] for table in tables}
    for table in tables:
        comment = table.get("comment", "")
        lines = [f"表：{table['table_name']}" + (f"（{comment}）" if comment else "")]
        for column in table["columns"]:
            nullable = "可空" if column.get("nullable") else "不可空"
            description = column.get("comment") or "数据库未提供字段说明"
            lines.append(f"- {column['name']} {column['type']} {nullable}；{description}")
        for key in table.get("keys", []):
            if key["kind"] == "FOREIGN KEY" and key.get("referenced_table") in names:
                lines.append(f"- 外键：{key['column']} → {key['referenced_table']}.{key['referenced_column']}")
            elif key["kind"] in {"PRIMARY KEY", "UNIQUE"}:
                lines.append(f"- {key['kind']}：{key['column']}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
