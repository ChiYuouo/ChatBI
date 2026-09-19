"""归因分析编排链路的测试。

按项目约定，全程使用假 Provider，不依赖真实模型服务与数据库。
"""

from types import SimpleNamespace

from chatbi.analysis.analysis_service import AnalysisService


class FakeLLM:
    """按提示词特征返回拆解结果或归因报告，避免真实模型调用。"""

    def __init__(self):
        self.sql_calls = 0

    def generate_sql_stream(self, system_msg, prompt):
        self.sql_calls += 1
        yield "SELECT region, "
        yield "SUM(net_amount) AS amt "
        yield "FROM sales_orders "
        yield "GROUP BY region;"

    def generate_sql(self, system_msg, prompt):
        return "SELECT region, SUM(net_amount) AS amt FROM sales_orders GROUP BY region;"

    def generate_text(self, system_msg=None, prompt=None):
        blob = f"{system_msg}\n{prompt}"
        if "企业经营分析师" in blob or "结构化分析报告" in blob:
            return (
                '{"title": "利润下降归因", "executive_summary": "欧洲区下滑是主因", '
                '"key_findings": ["欧洲区环比下降 30%"], '
                '"root_causes": ["欧洲区单价下跌"], '
                '"trend_judgment": "趋势向下", '
                '"action_suggestions": ["核查欧洲定价"]}'
            )
        return (
            '{"question_type": "原因诊断", "analysis_goal": "定位利润下降驱动因素", '
            '"subtasks": ['
            '{"task_id": "task_1", "task_name": "利润趋势", "task_type": "trend", '
            '"description": "按月看利润变化", "depends_on": [], '
            '"dimensions": ["月份"], "metrics": ["利润"]}, '
            '{"task_id": "task_2", "task_name": "区域拆解", "task_type": "dimension", '
            '"description": "按区域看贡献", "depends_on": ["task_1"], '
            '"dimensions": ["区域"], "metrics": ["利润"]}'
            "]}"
        )


class FakeDB:
    last_query_info = {"duration_ms": 5}

    def execute(self, sql, user=None):
        return ["region", "amt"], [("欧洲", 100), ("北美", 300)]


class FakeParser:
    def parse(self, question):
        return {"original_question": question, "is_valid": bool(question.strip())}

    def validate(self, parsed):
        return parsed.get("is_valid", False)


class FakeFormatter:
    def format(self, columns, results):
        return " | ".join(columns)


def build_fake_runtime_factory(llm=None):
    llm = llm or FakeLLM()

    def factory(app_config, source_id=None):
        return SimpleNamespace(
            source_id=source_id or "mysql_main",
            parser=FakeParser(),
            llm=llm,
            db=FakeDB(),
            formatter=FakeFormatter(),
            indicator_knowledge=None,
        )

    return factory


# Schema Linking 与指标 RAG 会触发向量检索与 embedding 调用，
# 测试按项目约定必须与真实模型服务隔离，因此显式关闭。
HERMETIC_RUN_OPTIONS = {
    "use_schema_linking": False,
    "use_indicator_rag": False,
    "use_indicator_knowledge": False,
}


def collect_events(question="最近三个月利润为什么下降？"):
    service = AnalysisService(runtime_factory=build_fake_runtime_factory())
    return list(
        service.run_stream_events(question, chatbi_run_options=HERMETIC_RUN_OPTIONS)
    )


def test_analysis_service_emits_full_stage_sequence():
    event_types = [event_type for event_type, _ in collect_events()]

    assert event_types[0] == "start"
    assert "decomposition_done" in event_types
    assert "plan_ready" in event_types
    assert "summary_done" in event_types
    assert event_types[-2:] == ["report_done", "done"]


def test_analysis_service_streams_sql_chunks_inside_each_step():
    events = collect_events()
    event_types = [event_type for event_type, _ in events]

    # 每个步骤内部都应实时透传 SQL 片段，且片段归属到对应 step_id
    assert event_types.count("step_sql_chunk") == 8  # 2 个步骤 × 4 个片段
    chunk_events = [data for name, data in events if name == "step_sql_chunk"]
    assert {data["step_id"] for data in chunk_events} == {"step_1", "step_2"}
    assert all(data["content"] for data in chunk_events)


def test_analysis_service_step_events_carry_step_identity():
    events = collect_events()
    start_events = [data for name, data in events if name == "step_start"]

    assert [data["step_id"] for data in start_events] == ["step_1", "step_2"]
    assert start_events[0]["step_name"] == "利润趋势"
    assert start_events[0]["total_steps"] == 2
    # 后置步骤的依赖信息要一起下发，前端才能画出依赖关系
    assert start_events[1]["depends_on"] == ["step_1"]


def test_analysis_service_produces_attribution_report():
    events = collect_events()
    report = dict(events)["report_done"]

    assert report["title"] == "利润下降归因"
    assert report["root_causes"] == ["欧洲区单价下跌"]
    assert report["action_suggestions"] == ["核查欧洲定价"]


def test_analysis_service_reports_done_summary():
    events = collect_events()
    done = dict(events)["done"]

    assert done["completed_steps"] == 2
    assert done["failed_steps"] == 0
    assert done["skipped_steps"] == 0
    assert done["total_steps"] == 2


def test_analysis_service_rejects_blank_question():
    events = collect_events("   ")

    assert events == [("error", {"error": "输入问题为空", "error_type": "validation"})]


def test_analysis_service_degrades_when_decomposition_is_invalid():
    class BrokenLLM(FakeLLM):
        def generate_text(self, system_msg=None, prompt=None):
            return "这不是 JSON"

    service = AnalysisService(
        runtime_factory=build_fake_runtime_factory(BrokenLLM())
    )
    events = list(
        service.run_stream_events("利润为什么下降？", chatbi_run_options=HERMETIC_RUN_OPTIONS)
    )
    error_event = dict(events)["error"]

    # 拆解失败要作为可定位的业务错误回传，而不是抛异常打断服务
    assert error_event["error_type"] == "decomposition"
    assert "拆解失败" in error_event["error"]


def test_analysis_service_binds_llm_client_to_injected_runtime():
    llm = FakeLLM()
    service = AnalysisService(runtime_factory=build_fake_runtime_factory(llm))
    list(
        service.run_stream_events("利润为什么下降？", chatbi_run_options=HERMETIC_RUN_OPTIONS)
    )

    # 拆解与报告都必须走注入的 LLM，避免链路里出现多个模型客户端
    assert llm.sql_calls == 2


def test_step_done_status_uses_backend_vocabulary():
    """步骤状态词必须固定为 completed / failed / skipped。

    前端把它当成契约来做状态映射（AnalysisStepStatus）。曾经因为前端按
    'success' 判断而后端发 'completed'，导致步骤全部显示「等待中」、
    进度条也不推进。这里把取值钉住，防止再次漂移。
    """
    events = collect_events()
    done_events = [data for name, data in events if name == "step_done"]

    assert done_events, "至少应有一个步骤结束事件"

    allowed = {"completed", "failed", "skipped"}
    statuses = {data["status"] for data in done_events}
    assert statuses <= allowed, f"出现了未约定的步骤状态: {statuses - allowed}"

    # 成功的步骤必须是 completed，不能是 success
    success_statuses = {data["status"] for data in done_events if data["success"]}
    assert success_statuses == {"completed"}


def test_step_done_payload_exposes_fields_frontend_depends_on():
    """step_done 载荷必须带上前端渲染所需字段，缺一个就会出现空白或错状态。"""
    events = collect_events()
    done = [data for name, data in events if name == "step_done"][0]

    for field in ("step_id", "step_name", "status", "success", "rows", "columns"):
        assert field in done, f"step_done 缺少字段 {field}"
