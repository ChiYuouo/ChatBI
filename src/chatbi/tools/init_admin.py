"""向独立的 SQLite 账户库写入初始管理员账号。"""

from __future__ import annotations

import argparse
import sqlite3
import uuid
from datetime import datetime, timezone

from chatbi.core.auth import UserStore, hash_password


def init_admin(db_path: str | None = None) -> bool:
    """首次创建 admin/admin；同名账号已存在时不修改它。"""
    store = UserStore(db_path)
    with sqlite3.connect(store.db_path) as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO sys_user "
            "(user_id, username, password_hash, role, region, enabled, created_at) "
            "VALUES (?, 'admin', ?, 'admin', NULL, 1, ?)",
            (
                uuid.uuid4().hex,
                hash_password("admin"),
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        )
        return cursor.rowcount == 1


def main() -> None:
    parser = argparse.ArgumentParser(description="初始化 admin/admin 管理员账号")
    parser.add_argument(
        "--db-path",
        help="账户 SQLite 文件；默认使用 USERS_DB_PATH 或 data/users.db",
    )
    args = parser.parse_args()

    if init_admin(args.db_path):
        print("Created admin account: admin / admin")
    else:
        print("Admin account already exists; password and role were not changed")


if __name__ == "__main__":
    main()
