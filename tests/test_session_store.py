"""多轮会话上下文的测试。

覆盖存储层、Prompt 注入与 ChatBISystem 集成三部分。
按项目约定，全程使用假 Provider，不依赖真实模型服务与数据库。
"""

import os
import tempfile
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from chatbi.api.schemas import QueryRequest
from chatbi.infrastructure.session_store import SessionStore
from chatbi.services.chatbi_service import ChatBISystem
from chatbi.text2sql.prompt_builder import build_prompt
from chatbi.text2sql.query_rewriter import QueryRewriter

FAKE_SQL = "SELECT region, SUM(net_amount) FROM sales_orders GROUP BY region;"


class CapturingLLM:
    """记录收到的 Prompt，便于断言历史是否真的注入了。"""

    def __init__(self, sql: str = FAKE_SQL):
        self.prompts: list[str] = []
        self._sql = sql

    def generate_sql(self, system_msg, prompt):
        self.prompts.append(prompt)
        return self._sql

    def generate_sql_stream(self, system_msg, prompt):
        self.prompts.append(prompt)
        yield self._sql


class FakeDB:
    last_query_info = {"duration_ms": 1}

    def execute(self, sql, user=None):
        return ["region"], [("欧洲",)]


class FakeParser:
    def parse(self, question):
        return {"original_question": question, "is_valid": bool(question.strip())}

    def validate(self, parsed):
        return parsed.get("is_valid", False)


class FakeFormatter:
    def format(self, columns, results):
        return "欧洲"


# 关闭所有会触发向量检索 / 网络调用的开关，保持测试无外部依赖
HERMETIC_OPTIONS = {
    "use_few_shot": False,
    "use_rules": False,
    "use_guards": False,
    "use_indicator_knowledge": False,
    "use_schema_linking": False,
    "use_indicator_rag": False,
}


def build_runtime(llm=None):
    return SimpleNamespace(
        source_id="mysql_main",
        parser=FakeParser(),
        llm=llm or CapturingLLM(),
        db=FakeDB(),
        formatter=FakeFormatter(),
        indicator_knowledge=None,
    )


def build_system(llm=None, with_store: bool = True, query_rewriter=None):
    """构造 ChatBISystem；会话库落在临时目录，不污染工作区。"""
    runtime = build_runtime(llm)
    store = SessionStore(os.path.join(tempfile.mkdtemp(), "sessions.db")) if with_store else None
    system = ChatBISystem(
        runtime=runtime,
        session_store=store,
        query_rewriter=query_rewriter,
    )
    return system, runtime.llm, store


# ==================== 存储层 ====================


def test_store_records_and_reads_back():
    store = SessionStore(os.path.join(tempfile.mkdtemp(), "sessions.db"))

    store.append_turn("s1", "u1", "各区域收入是多少", FAKE_SQL)
    turns = store.recent_turns("s1", "u1")

    assert len(turns) == 1
    assert turns[0].question == "各区域收入是多少"
    assert turns[0].sql == FAKE_SQL


def test_store_keeps_only_recent_turns_in_chronological_order():
    store = SessionStore(os.path.join(tempfile.mkdtemp(), "sessions.db"), history_turns=3)
    for index in range(1, 6):
        store.append_turn("s1", "u1", f"问题{index}", f"SELECT {index}")

    questions = [turn.question for turn in store.recent_turns("s1", "u1")]

    # 只保留最近 3 轮，且按时间正序（旧 → 新）返回
    assert questions == ["问题3", "问题4", "问题5"]


def test_store_isolates_by_user():
    store = SessionStore(os.path.join(tempfile.mkdtemp(), "sessions.db"))
    store.append_turn("s1", "u1", "u1 的问题", FAKE_SQL)

    # 拿到会话 ID 但换了用户，必须读不到别人的历史
    assert store.recent_turns("s1", "u2") == []
    assert store.render_history("s1", "u2") == ""


def test_store_without_session_id_returns_empty():
    store = SessionStore(os.path.join(tempfile.mkdtemp(), "sessions.db"))

    assert store.recent_turns(None, "u1") == []
    assert store.render_history(None, "u1") == ""
    # 没有 session_id 时写入也应被忽略，避免产生无主记录
    store.append_turn(None, "u1", "会被丢弃的问题")
    assert store.render_history(None, "u1") == ""


def test_render_history_formats_question_and_sql():
    store = SessionStore(os.path.join(tempfile.mkdtemp(), "sessions.db"))
    store.append_turn("s1", "u1", "各区域收入是多少", FAKE_SQL)

    rendered = store.render_history("s1", "u1")

    assert "各区域收入是多少" in rendered
    assert FAKE_SQL in rendered
    assert "用户问" in rendered and "生成SQL" in rendered


def test_render_history_omits_sql_line_when_absent():
    store = SessionStore(os.path.join(tempfile.mkdtemp(), "sessions.db"))
    store.append_turn("s1", "u1", "没有 SQL 的问题", None)

    rendered = store.render_history("s1", "u1")

    assert "没有 SQL 的问题" in rendered
    assert "生成SQL" not in rendered


# ==================== 清理机制 ====================


def test_store_caps_turns_per_session():
    store = SessionStore(
        os.path.join(tempfile.mkdtemp(), "sessions.db"),
        max_turns_per_session=3,
    )
    for index in range(1, 6):
        store.append_turn("s1", "u1", f"问题{index}", f"SELECT {index}")

    # 超出上限后只留最近的，不会无限堆积
    questions = [turn.question for turn in store.recent_turns("s1", "u1")]
    assert questions == ["问题3", "问题4", "问题5"]


def test_store_prunes_expired_records_on_init():
    db_path = os.path.join(tempfile.mkdtemp(), "sessions.db")
    writer = SessionStore(db_path)
    writer.append_turn("s1", "u1", "老问题", FAKE_SQL)

    # retention_days=-1 表示保留期已过，初始化时应把旧记录清掉
    SessionStore(db_path, retention_days=-1)

    assert writer.recent_turns("s1", "u1") == []


def test_store_reads_limits_from_env(monkeypatch):
    monkeypatch.setenv("SESSION_MAX_TURNS", "7")
    monkeypatch.setenv("SESSION_RETENTION_DAYS", "5")

    store = SessionStore(os.path.join(tempfile.mkdtemp(), "sessions.db"))

    assert store.max_turns_per_session == 7
    assert store.retention_days == 5


def test_store_default_history_window_is_eight():
    store = SessionStore(os.path.join(tempfile.mkdtemp(), "sessions.db"))

    assert store.history_turns == 8


def test_store_reads_history_turns_from_env(monkeypatch):
    monkeypatch.setenv("SESSION_HISTORY_TURNS", "12")

    store = SessionStore(os.path.join(tempfile.mkdtemp(), "sessions.db"))

    assert store.history_turns == 12


def test_store_history_turns_argument_beats_env(monkeypatch):
    """显式传参优先于环境变量。"""
    monkeypatch.setenv("SESSION_HISTORY_TURNS", "12")

    store = SessionStore(os.path.join(tempfile.mkdtemp(), "sessions.db"), history_turns=2)

    assert store.history_turns == 2


def test_store_falls_back_on_invalid_env(monkeypatch):
    monkeypatch.setenv("SESSION_MAX_TURNS", "not-a-number")

    store = SessionStore(os.path.join(tempfile.mkdtemp(), "sessions.db"))

    assert store.max_turns_per_session == 100


# ==================== 删除会话 ====================


def test_store_deletes_session_records():
    store = SessionStore(os.path.join(tempfile.mkdtemp(), "sessions.db"))
    store.append_turn("s1", "u1", "问题1", FAKE_SQL)
    store.append_turn("s1", "u1", "问题2", FAKE_SQL)
    store.append_turn("s2", "u1", "别的会话", FAKE_SQL)

    deleted = store.delete_session("s1", "u1")

    assert deleted == 2
    assert store.recent_turns("s1", "u1") == []
    # 其它会话不受影响
    assert len(store.recent_turns("s2", "u1")) == 1


def test_store_delete_does_not_touch_other_user():
    store = SessionStore(os.path.join(tempfile.mkdtemp(), "sessions.db"))
    store.append_turn("s1", "u1", "u1 的问题", FAKE_SQL)
    store.append_turn("s1", "u2", "u2 的问题", FAKE_SQL)

    store.delete_session("s1", "u1")

    # 同 session_id 下另一个用户的记录不能被误删
    assert len(store.recent_turns("s1", "u2")) == 1


def test_store_delete_without_session_id_is_noop():
    store = SessionStore(os.path.join(tempfile.mkdtemp(), "sessions.db"))
    store.append_turn("s1", "u1", "问题", FAKE_SQL)

    assert store.delete_session(None, "u1") == 0
    assert len(store.recent_turns("s1", "u1")) == 1


def test_new_session_stops_using_previous_history():
    """「新会话」的效果：旧上下文不再参与后续查询。"""
    system, llm, store = build_system()

    system.run(user_question="各区域的订单量是多少", session_id="s1", **HERMETIC_OPTIONS)
    # 模拟前端点「新会话」：删服务端历史 + 换新 session_id
    store.delete_session("s1", "demo_admin")
    system.run(user_question="那2月呢？", session_id="s2", **HERMETIC_OPTIONS)

    assert "【对话历史】" not in llm.prompts[1]
    assert store.recent_turns("s1", "demo_admin") == []


# ==================== Prompt 层 ====================


def test_prompt_includes_history_block():
    _, prompt = build_prompt("那2月呢？", history="第1轮 用户问：利润趋势\n      生成SQL：SELECT 1")

    assert "【对话历史】" in prompt
    assert "第1轮 用户问：利润趋势" in prompt
    # 历史必须出现在用户问题之前
    assert prompt.index("【对话历史】") < prompt.index("【用户问题】")


def test_prompt_without_history_has_no_block():
    _, prompt = build_prompt("各区域收入是多少")

    assert "【对话历史】" not in prompt
    assert "【用户问题】" in prompt


# ==================== ChatBISystem 集成 ====================


def test_second_turn_prompt_carries_previous_question_and_sql():
    system, llm, _ = build_system()

    system.run(user_question="各区域收入是多少", session_id="s1", **HERMETIC_OPTIONS)
    system.run(user_question="那2月呢？", session_id="s1", **HERMETIC_OPTIONS)

    assert len(llm.prompts) == 2
    # 第一轮无历史
    assert "【对话历史】" not in llm.prompts[0]
    # 第二轮带上了第一轮的问题与 SQL
    assert "【对话历史】" in llm.prompts[1]
    assert "各区域收入是多少" in llm.prompts[1]
    assert FAKE_SQL in llm.prompts[1]


def test_streaming_second_turn_also_carries_history():
    system, llm, _ = build_system()

    list(system.run_stream_events("各区域收入是多少", session_id="s1", **HERMETIC_OPTIONS))
    list(system.run_stream_events("那2月呢？", session_id="s1", **HERMETIC_OPTIONS))

    assert "各区域收入是多少" in llm.prompts[1]


def test_different_sessions_do_not_share_history():
    system, llm, _ = build_system()

    system.run(user_question="各区域收入是多少", session_id="s1", **HERMETIC_OPTIONS)
    system.run(user_question="毛利率是多少", session_id="s2", **HERMETIC_OPTIONS)

    # 换了会话，第二轮不应看到第一轮的历史
    assert "【对话历史】" not in llm.prompts[1]


def test_without_session_id_behaviour_is_unchanged():
    """回归：不传 session_id 时完全等同此前的单轮查询。"""
    system, llm, store = build_system()

    system.run(user_question="各区域收入是多少", **HERMETIC_OPTIONS)
    system.run(user_question="那2月呢？", **HERMETIC_OPTIONS)

    for prompt in llm.prompts:
        assert "【对话历史】" not in prompt
    # 也不应往会话库里写任何东西
    assert store.recent_turns("s1", "demo_admin") == []


def test_without_session_id_does_not_initialise_store():
    """回归：不传 session_id 时连 SessionStore 都不该被创建。"""
    system = ChatBISystem(runtime=build_runtime())

    system.run(user_question="各区域收入是多少", **HERMETIC_OPTIONS)

    assert system._session_store is None


# ==================== 提问改写与会话的联动 ====================


def test_follow_up_is_rewritten_before_generating_sql():
    """有历史时，改写后的问题会进入 Prompt。"""
    rewriter = QueryRewriter(lambda system_msg, prompt: "2026年2月各区域的订单量")
    system, llm, _ = build_system(query_rewriter=rewriter)

    system.run(user_question="各区域订单量是多少", session_id="s1", **HERMETIC_OPTIONS)
    system.run(user_question="那2月呢？", session_id="s1", **HERMETIC_OPTIONS)

    assert "2026年2月各区域的订单量" in llm.prompts[1]


def test_rewrite_can_be_disabled_per_request():
    rewriter = QueryRewriter(lambda system_msg, prompt: "2026年2月各区域的订单量")
    system, llm, _ = build_system(query_rewriter=rewriter)

    system.run(user_question="各区域订单量是多少", session_id="s1", **HERMETIC_OPTIONS)
    system.run(
        user_question="那2月呢？",
        session_id="s1",
        use_query_rewrite=False,
        **HERMETIC_OPTIONS,
    )

    assert "2026年2月各区域的订单量" not in llm.prompts[1]


def test_rewrite_is_skipped_without_history():
    """单轮查询不该触发改写 —— 没有指代可消解，纯属浪费一次模型调用。"""
    calls = {"count": 0}

    def generator(system_msg, prompt):
        calls["count"] += 1
        return "改写结果"

    system, _, _ = build_system(query_rewriter=QueryRewriter(generator))
    system.run(user_question="各区域订单量是多少", **HERMETIC_OPTIONS)

    assert calls["count"] == 0


def test_streaming_emits_rewrite_done_event():
    rewriter = QueryRewriter(lambda system_msg, prompt: "2026年2月各区域的订单量")
    system, _, _ = build_system(query_rewriter=rewriter)

    list(system.run_stream_events("各区域订单量是多少", session_id="s1", **HERMETIC_OPTIONS))
    events = list(system.run_stream_events("那2月呢？", session_id="s1", **HERMETIC_OPTIONS))
    rewrite_events = [data for name, data in events if name == "rewrite_done"]

    assert len(rewrite_events) == 1
    assert rewrite_events[0]["original_question"] == "那2月呢？"
    assert rewrite_events[0]["rewritten_question"] == "2026年2月各区域的订单量"


def test_no_rewrite_event_when_question_unchanged():
    """改写结果与原问题相同时不该发事件，避免界面出现无意义的提示。"""
    rewriter = QueryRewriter(lambda system_msg, prompt: "那2月呢？")
    system, _, _ = build_system(query_rewriter=rewriter)

    list(system.run_stream_events("各区域订单量是多少", session_id="s1", **HERMETIC_OPTIONS))
    events = list(system.run_stream_events("那2月呢？", session_id="s1", **HERMETIC_OPTIONS))

    assert [name for name, _ in events if name == "rewrite_done"] == []


# ==================== 请求模型 ====================


def test_query_request_session_id_is_optional():
    assert QueryRequest(question="各区域收入是多少").session_id is None
    assert QueryRequest(question="各区域收入是多少", session_id="abc").session_id == "abc"


def test_query_request_rejects_overlong_session_id():
    with pytest.raises(ValidationError):
        QueryRequest(question="各区域收入是多少", session_id="x" * 129)


# ==================== 会话列表与轮次回填（侧边栏） ====================


def test_list_sessions_aggregates_by_session():
    store = SessionStore(os.path.join(tempfile.mkdtemp(), "sessions.db"))
    store.append_turn("sA", "u1", "第一个问题", FAKE_SQL)
    store.append_turn("sA", "u1", "追问", FAKE_SQL)
    store.append_turn("sB", "u1", "另一个会话", FAKE_SQL)

    sessions = store.list_sessions("u1")

    # 按最后活动倒序；标题取该会话的第一个问题
    assert [s["session_id"] for s in sessions] == ["sB", "sA"]
    session_a = next(s for s in sessions if s["session_id"] == "sA")
    assert session_a["title"] == "第一个问题"
    assert session_a["turns"] == 2


def test_list_sessions_isolates_by_user():
    store = SessionStore(os.path.join(tempfile.mkdtemp(), "sessions.db"))
    store.append_turn("sA", "u1", "u1 的问题", FAKE_SQL)
    store.append_turn("sC", "u2", "u2 的问题", FAKE_SQL)

    assert [s["session_id"] for s in store.list_sessions("u1")] == ["sA"]
    assert [s["session_id"] for s in store.list_sessions("u2")] == ["sC"]


def test_get_turns_returns_all_turns_in_chronological_order():
    store = SessionStore(os.path.join(tempfile.mkdtemp(), "sessions.db"))
    store.append_turn("sA", "u1", "第一问", FAKE_SQL)
    store.append_turn("sA", "u1", "第二问", FAKE_SQL)

    turns = store.get_turns("sA", "u1")

    assert [t.question for t in turns] == ["第一问", "第二问"]
    assert all(t.created_at for t in turns)


def test_get_turns_does_not_cross_users():
    store = SessionStore(os.path.join(tempfile.mkdtemp(), "sessions.db"))
    store.append_turn("sA", "u1", "u1 的问题", FAKE_SQL)

    assert store.get_turns("sA", "u2") == []


def test_append_turn_with_answer_roundtrip():
    """归因分析落库：answer 写入后 get_turns / recent_turns 都能读回。"""
    store = SessionStore(os.path.join(tempfile.mkdtemp(), "sessions.db"))

    store.append_turn("sA", "u1", "最近三个月利润为什么下降？", FAKE_SQL, answer="# 归因报告\n欧洲区下滑是主因")
    store.append_turn("sA", "u1", "普通追问", FAKE_SQL)

    turns = store.get_turns("sA", "u1")
    assert turns[0].answer and "归因报告" in turns[0].answer
    # 普通查询轮次 answer 为 None
    assert turns[1].answer is None


def test_render_history_keeps_answer_summary_only():
    """历史注入 Prompt 时，回答文本只取摘要，报告全文不能撑爆上下文。"""
    store = SessionStore(os.path.join(tempfile.mkdtemp(), "sessions.db"))
    long_answer = "结论" + "细节" * 2000  # 4000+ 字符，远超 400 字摘要上限

    store.append_turn("sA", "u1", "利润为什么下降", FAKE_SQL, answer=long_answer)

    history = store.render_history("sA", "u1")
    assert "分析结论（摘要）" in history
    # 全文被截断：完整内容不会出现在历史里
    assert long_answer not in history


def test_migration_adds_answer_text_column_idempotently():
    """存量库升级：旧结构表（无 answer_text）初始化后自动补列，
    旧数据保留，且重复初始化不报错。"""
    import sqlite3

    db_path = os.path.join(tempfile.mkdtemp(), "sessions.db")
    # 手工造一个旧版本的表结构并写入一条数据
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE chat_turn ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " session_id TEXT NOT NULL, user_id TEXT NOT NULL,"
        " question TEXT NOT NULL, sql_text TEXT,"
        " created_at TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO chat_turn (session_id, user_id, question, sql_text, created_at)"
        " VALUES ('sOld', 'u1', '旧问题', 'SELECT 1',"
        " datetime('now', 'localtime'))"  # 最近时间，避免被启动时的过期清理删除
    )
    conn.commit()
    conn.close()

    # 第一次初始化触发迁移，第二次验证幂等
    store = SessionStore(db_path)
    SessionStore(db_path)

    turns = store.get_turns("sOld", "u1")
    assert len(turns) == 1
    assert turns[0].question == "旧问题"
    assert turns[0].answer is None

    # 迁移后的表支持写入 answer
    store.append_turn("sOld", "u1", "新问题", FAKE_SQL, answer="新结论")
    refreshed = store.get_turns("sOld", "u1")
    assert refreshed[-1].answer == "新结论"
