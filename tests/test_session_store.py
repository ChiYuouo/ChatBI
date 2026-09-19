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


def build_system(llm=None, with_store: bool = True):
    """构造 ChatBISystem；会话库落在临时目录，不污染工作区。"""
    runtime = build_runtime(llm)
    store = SessionStore(os.path.join(tempfile.mkdtemp(), "sessions.db")) if with_store else None
    system = ChatBISystem(runtime=runtime, session_store=store)
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


# ==================== 请求模型 ====================


def test_query_request_session_id_is_optional():
    assert QueryRequest(question="各区域收入是多少").session_id is None
    assert QueryRequest(question="各区域收入是多少", session_id="abc").session_id == "abc"


def test_query_request_rejects_overlong_session_id():
    with pytest.raises(ValidationError):
        QueryRequest(question="各区域收入是多少", session_id="x" * 129)
