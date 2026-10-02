"""初始管理员脚本与登录存储的集成验证。"""

import sqlite3

from chatbi.core.auth import UserStore
from chatbi.tools.init_admin import init_admin


def test_init_admin_creates_login_and_is_idempotent(tmp_path):
    db_path = str(tmp_path / "users.db")

    assert init_admin(db_path)
    user = UserStore(db_path).authenticate("admin", "admin")
    assert user is not None
    assert user.role == "admin"
    with sqlite3.connect(db_path) as conn:
        password_hash = conn.execute(
            "SELECT password_hash FROM sys_user WHERE username = 'admin'"
        ).fetchone()[0]
    assert password_hash != "admin"

    assert not init_admin(db_path)
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sys_user").fetchone()[0] == 1
        assert conn.execute(
            "SELECT password_hash FROM sys_user WHERE username = 'admin'"
        ).fetchone()[0] == password_hash
