import re

from chatbi.analysis.agent_planner import (
    PlanAndExecuteAgent,
    PlanGenerator,
    ResultSummarizer,
    StepExecutor,
    StepExecutionResult,
    TempTableResultStore,
)
from chatbi.analysis.report_generator import ReportGenerator


class FakeTempCursor:
    def __init__(self, connection):
        self.connection = connection
        self.description = None
        self._results = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.connection.executed.append((sql, params))
        sql_upper = " ".join(sql.upper().split())
        identifiers = re.findall(r"`([^`]+)`", sql)

        if sql_upper.startswith("DROP TEMPORARY TABLE IF EXISTS"):
            table_name = identifiers[0]
            self.connection.tables.pop(table_name, None)
            self.description = None
            self._results = []
            return

        if sql_upper.startswith("CREATE TEMPORARY TABLE"):
            table_name = identifiers[0]
            columns = identifiers[1:]
            self.connection.tables[table_name] = {"columns": columns, "rows": []}
            self.description = None
            self._results = []
            return

        if sql_upper.startswith("SELECT * FROM"):
            table_name = identifiers[0]
            table = self.connection.tables[table_name]
            columns = table["columns"]
            rows = table["rows"]
            self.description = [(column,) for column in columns]
            self._results = [tuple(row.get(column) for column in columns) for row in rows]
            return

        raise AssertionError(f"未处理的 SQL: {sql}")

    def executemany(self, sql, params_seq):
        params_list = list(params_seq)
        self.connection.executed.append((sql, params_list))
        identifiers = re.findall(r"`([^`]+)`", sql)
        table_name = identifiers[0]
        columns = identifiers[1:]
        table = self.connection.tables[table_name]
        table["rows"].extend(dict(zip(columns, params)) for params in params_list)

    def fetchall(self):
        return self._results


class FakeTempConnection:
    def __init__(self):
        self.tables = {}
        self.executed = []
        self.open = True

    def cursor(self):
        return FakeTempCursor(self)

    def commit(self):
        self.executed.append(("COMMIT", None))

    def close(self):
        self.open = False


def sample_decomposition() -> dict:
    return {
        "question_type": "profit_decline_analysis",
        "analysis_goal": "定位最近三个月利润下降的主要驱动因素",
        "subtasks": [
            {
                "task_id": "task_1",
                "task_name": "查看最近三个月利润趋势",
                "task_type": "trend_analysis",
                "description": "先找出利润下降最明显的月份",
                "depends_on": [],
                "dimensions": ["月份"],
                "metrics": ["利润"],
            },
            {
                "task_id": "task_2",
                "task_name": "拆解收入与成本变化",
                "task_type": "metric_decomposition",
                "description": "围绕利润 = 收入 - 成本，确认是哪一端拖累了利润",
                "depends_on": ["task_1"],
                "dimensions": ["月份"],
                "metrics": ["收入", "成本", "利润"],
            },
            {
                "task_id": "task_3",
                "task_name": "定位利润下滑最严重的区域",
                "task_type": "dimension_drilldown",
                "description": "结合前两步结果，观察哪个区域的利润恶化更明显",
                "depends_on": ["task_2"],
                "dimensions": ["区域"],
                "metrics": ["利润", "收入", "成本"],
            },
        ],
    }


def test_plan_generator_builds_ordered_steps():
    decomposition = sample_decomposition()
    planner = PlanGenerator()

    plan = planner.build_plan(
        original_question="最近三个月利润为什么下降？",
        decomposition=decomposition,
    )

    assert plan.analysis_goal == "定位最近三个月利润下降的主要驱动因素"
    assert [step.step_id for step in plan.steps] == ["step_1", "step_2", "step_3"]
    assert plan.steps[1].depends_on == ["step_1"]
    assert "关注指标：收入、成本、利润" in plan.steps[1].question


def test_step_executor_passes_dependency_context_to_later_steps():
    decomposition = sample_decomposition()
    planner = PlanGenerator()
    plan = planner.build_plan("最近三个月利润为什么下降？", decomposition)
    captured_questions: list[str] = []

    def fake_runner(question: str) -> dict:
        captured_questions.append(question)
        return {
            "success": True,
            "sql": "SELECT 1",
            "columns": ["value"],
            "rows": [{"value": 1}],
            "formatted": "模拟执行成功",
        }

    executor = StepExecutor(step_runner=fake_runner)
    results = executor.execute_plan(plan)

    assert len(results) == 3
    assert "前置步骤关键结果如下" not in captured_questions[0]
    assert "查看最近三个月利润趋势" in captured_questions[1]
    assert "拆解收入与成本变化" in captured_questions[2]


def test_step_executor_dependency_context_uses_structured_rows_instead_of_table_border():
    decomposition = sample_decomposition()
    plan = PlanGenerator().build_plan("最近三个月利润为什么下降？", decomposition)
    captured_questions: list[str] = []

    def fake_runner(question: str) -> dict:
        captured_questions.append(question)
        if len(captured_questions) == 1:
            return {
                "success": True,
                "sql": "SELECT month, profit FROM monthly_profit",
                "columns": ["month", "profit"],
                "rows": [{"month": "2026-04-01", "profit": -1886156}],
                "formatted": (
                    "------------+------------\n"
                    "month       |profit      \n"
                    "------------+------------\n"
                    "2026-04-01  |-1886156    \n"
                    "------------+------------"
                ),
            }
        return {
            "success": True,
            "sql": "SELECT 1",
            "columns": ["value"],
            "rows": [{"value": 1}],
            "formatted": "模拟执行成功",
        }

    executor = StepExecutor(step_runner=fake_runner)
    executor.execute_plan(plan)

    assert "------------+" not in captured_questions[1]
    assert '"rows": [{"month": "2026-04-01", "profit": -1886156}]' in captured_questions[1]


def test_agent_returns_summary_after_execution():
    decomposition = sample_decomposition()

    def fake_runner(question: str) -> dict:
        return {
            "success": True,
            "sql": "SELECT 1",
            "columns": ["value"],
            "rows": [{"value": 1}],
            "formatted": f"已执行：{question.splitlines()[0]}",
        }

    agent = PlanAndExecuteAgent(
        planner=PlanGenerator(),
        executor=StepExecutor(step_runner=fake_runner),
        summarizer=ResultSummarizer(),
    )

    result = agent.run(
        "最近三个月利润为什么下降？",
        decomposition_override=decomposition,
    )

    assert result["summary"]["completed_steps"] == 3
    assert result["summary"]["failed_steps"] == 0
    assert len(result["summary"]["key_findings"]) == 3
    assert result["plan"]["steps"][2]["depends_on"] == ["step_2"]


def test_agent_returns_business_report_after_execution():
    decomposition = sample_decomposition()

    def fake_runner(question: str) -> dict:
        return {
            "success": True,
            "sql": "SELECT 1",
            "columns": ["value"],
            "rows": [{"value": 1}],
            "formatted": f"已执行：{question.splitlines()[0]}",
        }

    report_generator = ReportGenerator(
        text_generator=lambda _system_msg, _prompt: """
        {
          "title": "利润下降分析报告",
          "executive_summary": "利润下降主要来自收入回落。",
          "key_findings": ["最近一个月利润明显走低。"],
          "root_causes": ["收入下降快于成本下降。"],
          "trend_judgment": "短期仍需跟踪。",
          "action_suggestions": ["继续观察核心产品线订单恢复情况。"]
        }
        """
    )

    agent = PlanAndExecuteAgent(
        planner=PlanGenerator(),
        executor=StepExecutor(step_runner=fake_runner),
        summarizer=ResultSummarizer(),
        report_generator=report_generator,
    )


def test_agent_logs_main_chain_progress(capsys):
    decomposition = sample_decomposition()

    def fake_runner(question: str) -> dict:
        return {
            "success": True,
            "sql": "SELECT 1",
            "columns": ["value"],
            "rows": [{"value": 1}],
            "formatted": "模拟执行成功",
        }

    report_generator = ReportGenerator(
        text_generator=lambda _system_msg, _prompt: """
        {
          "title": "利润下降分析报告",
          "executive_summary": "利润下降主要来自收入回落。",
          "key_findings": ["最近一个月利润明显走低。"],
          "root_causes": ["收入下降快于成本下降。"],
          "trend_judgment": "短期仍需跟踪。",
          "action_suggestions": ["继续观察核心产品线订单恢复情况。"]
        }
        """
    )

    agent = PlanAndExecuteAgent(
        planner=PlanGenerator(),
        executor=StepExecutor(step_runner=fake_runner),
        summarizer=ResultSummarizer(),
        report_generator=report_generator,
    )

    agent.run(
        "最近三个月利润为什么下降？",
        decomposition_override=decomposition,
    )

    captured = capsys.readouterr()
    stderr = captured.err

    assert "开始生成执行计划" in stderr
    assert "开始执行计划，共 3 个步骤" in stderr
    assert "开始执行 step_1" in stderr
    assert "step_3 执行完成" in stderr
    assert "开始生成执行摘要" in stderr
    assert "开始生成分析报告" in stderr

    result = agent.run(
        "最近三个月利润为什么下降？",
        decomposition_override=decomposition,
    )

    assert result["report"]["title"] == "利润下降分析报告"
    assert "## 关键发现" in result["report"]["markdown"]


def test_step_executor_retries_failed_step_and_records_result_reference():
    decomposition = sample_decomposition()
    plan = PlanGenerator().build_plan("最近三个月利润为什么下降？", decomposition)
    attempts = {"step_1": 0}

    def flaky_runner(question: str) -> dict:
        primary_instruction = question.splitlines()[0]
        if "查看最近三个月利润趋势" in primary_instruction:
            attempts["step_1"] += 1
            if attempts["step_1"] == 1:
                return {
                    "success": False,
                    "error": "数据库连接超时",
                    "formatted": "第一次执行失败",
                }

        return {
            "success": True,
            "sql": "SELECT 1",
            "columns": ["value"],
            "rows": [{"value": 1}],
            "formatted": "重试后执行成功",
        }

    executor = StepExecutor(
        step_runner=flaky_runner,
        max_retries=1,
        failure_policy="abort",
        storage_backend="memory",
    )
    results = executor.execute_plan(plan)

    assert attempts["step_1"] == 2
    assert results[0].success is True
    assert results[0].attempts == 2
    assert results[0].status == "completed"
    assert results[0].result_reference == "memory://step_1"


def test_step_executor_skips_downstream_steps_after_failed_dependency():
    decomposition = sample_decomposition()
    plan = PlanGenerator().build_plan("最近三个月利润为什么下降？", decomposition)

    def failing_runner(question: str) -> dict:
        primary_instruction = question.splitlines()[0]
        if "查看最近三个月利润趋势" in primary_instruction:
            return {
                "success": False,
                "error": "SQL 语法错误",
                "formatted": "首步失败",
            }

        return {
            "success": True,
            "sql": "SELECT 1",
            "columns": ["value"],
            "rows": [{"value": 1}],
            "formatted": "后续不应执行到这里",
        }

    executor = StepExecutor(
        step_runner=failing_runner,
        max_retries=0,
        failure_policy="skip",
    )
    results = executor.execute_plan(plan)

    assert results[0].status == "failed"
    assert results[1].status == "skipped"
    assert results[1].success is False
    assert "依赖步骤失败" in results[1].error
    assert results[2].status == "skipped"


def test_result_summarizer_counts_skipped_steps_separately():
    decomposition = sample_decomposition()
    plan = PlanGenerator().build_plan("最近三个月利润为什么下降？", decomposition)

    def failing_runner(question: str) -> dict:
        primary_instruction = question.splitlines()[0]
        if "查看最近三个月利润趋势" in primary_instruction:
            return {
                "success": False,
                "error": "SQL 语法错误",
                "formatted": "首步失败",
            }
        return {
            "success": True,
            "sql": "SELECT 1",
            "columns": ["value"],
            "rows": [{"value": 1}],
            "formatted": "后续不应执行到这里",
        }

    executor = StepExecutor(step_runner=failing_runner, failure_policy="skip")
    step_results = executor.execute_plan(plan)
    summary = ResultSummarizer().summarize(
        original_question="最近三个月利润为什么下降？",
        plan=plan,
        step_results=step_results,
    )

    assert summary.completed_steps == 0
    assert summary.failed_steps == 1
    assert summary.skipped_steps == 2


def test_temp_table_result_store_put_get_and_cleanup():
    fake_connection = FakeTempConnection()
    store = TempTableResultStore(connection_factory=lambda: fake_connection)

    reference = store.put(
        step_id="step_1",
        columns=["month", "profit"],
        rows=[{"month": "2026-05", "profit": 920000}],
    )
    loaded_rows = store.get(reference)

    assert reference == "temp_table://tmp_agent_step_1"
    assert loaded_rows == [{"month": "2026-05", "profit": 920000}]

    store.cleanup()

    assert fake_connection.open is False
    assert fake_connection.tables == {}


def test_step_executor_can_load_rows_from_temp_table_reference():
    decomposition = sample_decomposition()
    plan = PlanGenerator().build_plan("最近三个月利润为什么下降？", decomposition)
    fake_connection = FakeTempConnection()
    captured_questions: list[str] = []

    def runner(question: str) -> dict:
        captured_questions.append(question)
        primary_instruction = question.splitlines()[0]
        if "查看最近三个月利润趋势" in primary_instruction:
            return {
                "success": True,
                "sql": "SELECT month, profit FROM profit_trend",
                "columns": ["month", "profit"],
                "rows": [{"month": "2026-05", "profit": 920000}],
                "formatted": "",
            }

        return {
            "success": True,
            "sql": "SELECT 1",
            "columns": ["value"],
            "rows": [{"value": 1}],
            "formatted": "后续执行成功",
        }

    executor = StepExecutor(
        step_runner=runner,
        storage_backend="temp_table",
        storage_connection_factory=lambda: fake_connection,
    )
    results = executor.execute_plan(plan, max_steps=2)
    loaded_rows = executor.get_intermediate_result(results[0].result_reference)

    assert results[0].result_reference == "temp_table://tmp_agent_step_1"
    assert loaded_rows == [{"month": "2026-05", "profit": 920000}]
    assert '"rows": [{"month": "2026-05", "profit": 920000}]' in captured_questions[1]


# ==================== SQL 失败后按报错重写 ====================


def test_step_executor_rewrites_sql_with_previous_error_on_syntax_failure():
    """SQL 写错时，重试应带上上一次的 SQL 与报错，而不是原样重发。"""
    plan = PlanGenerator().build_plan("最近三个月利润为什么下降？", sample_decomposition())
    questions: list[str] = []

    def runner(question: str) -> dict:
        questions.append(question)
        if len(questions) == 1:
            return {
                "success": False,
                "sql": "SELECT month, SUM(a) - COALESCE(f.total, 0) FROM t GROUP BY month",
                "error": (
                    "SQL 执行失败：(1055, \"Expression #2 of SELECT list is not in "
                    "GROUP BY clause and contains nonaggregated column 'f.total'\")"
                ),
                "error_type": "sql_syntax",
            }
        return {
            "success": True,
            "sql": "SELECT month, SUM(a) - COALESCE(MAX(f.total), 0) FROM t GROUP BY month",
            "columns": ["month", "profit"],
            "rows": [{"month": "2026-03", "profit": -554450}],
            "formatted": "重写后执行成功",
        }

    executor = StepExecutor(step_runner=runner, max_retries=2)
    results = executor.execute_plan(plan, max_steps=1)

    assert len(questions) == 2
    assert results[0].success is True
    assert results[0].repaired is True

    # 第二次提问必须携带上一次的 SQL 和数据库原始报错
    repair_question = questions[1]
    assert "COALESCE(f.total, 0)" in repair_question
    assert "1055" in repair_question
    assert "ONLY_FULL_GROUP_BY" in repair_question
    # 原始问题本身仍要保留，避免重写时丢失分析意图
    assert "查看最近三个月利润趋势" in repair_question.splitlines()[0]


def test_step_executor_retries_without_rewrite_on_transient_failure():
    """瞬时故障（如连接超时）应原样重试，而不是走 SQL 重写。"""
    plan = PlanGenerator().build_plan("最近三个月利润为什么下降？", sample_decomposition())
    questions: list[str] = []

    def runner(question: str) -> dict:
        questions.append(question)
        if len(questions) == 1:
            return {
                "success": False,
                "error": "数据库连接失败，请检查连接池和数据库状态",
                "error_type": "connection_error",
            }
        return {
            "success": True,
            "sql": "SELECT 1",
            "columns": ["value"],
            "rows": [{"value": 1}],
            "formatted": "重试成功",
        }

    executor = StepExecutor(step_runner=runner, max_retries=1)
    results = executor.execute_plan(plan, max_steps=1)

    assert len(questions) == 2
    assert results[0].success is True
    # 瞬时故障不该被塞入 SQL 修正上下文
    assert questions[1] == questions[0]
    assert "上一次尝试失败" not in questions[1]


def test_step_executor_keeps_original_question_when_rewrite_also_fails():
    """重写后仍失败时，要保留最后一次的错误信息，不能丢失失败原因。"""
    plan = PlanGenerator().build_plan("最近三个月利润为什么下降？", sample_decomposition())

    def runner(question: str) -> dict:
        return {
            "success": False,
            "sql": "SELECT bad_sql",
            "error": "SQL 执行失败：(1054, \"Unknown column 'bad_sql'\")",
            "error_type": "sql_syntax",
        }

    executor = StepExecutor(step_runner=runner, max_retries=1)
    results = executor.execute_plan(plan, max_steps=1)

    assert results[0].success is False
    assert results[0].status == "failed"
    assert results[0].attempts == 2
    assert results[0].error_type == "sql_syntax"
    assert "1054" in (results[0].error or "")


def test_step_executor_marks_repaired_step_and_emits_retry_event():
    """流式路径下重写要推送 step_retry 事件，供前端提示用户。"""
    plan = PlanGenerator().build_plan("最近三个月利润为什么下降？", sample_decomposition())
    calls = {"n": 0}

    def runner(question: str) -> dict:
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "success": False,
                "sql": "SELECT bad",
                "error": "SQL 执行失败：(1055, only_full_group_by)",
                "error_type": "sql_syntax",
            }
        return {
            "success": True,
            "sql": "SELECT good",
            "columns": ["a"],
            "rows": [{"a": 1}],
            "formatted": "ok",
        }

    executor = StepExecutor(step_runner=runner, max_retries=1, failure_policy="skip")
    events = list(executor.execute_plan_streaming(plan, max_steps=1))

    retry_events = [data for name, data in events if name == "step_retry"]
    assert len(retry_events) == 1
    assert retry_events[0]["step_id"] == "step_1"
    assert retry_events[0]["mode"] == "rewrite"
    assert retry_events[0]["attempt"] == 2
    assert "1055" in retry_events[0]["previous_error"]

    done = [data for name, data in events if name == "step_done"][0]
    assert done["repaired"] is True
    assert done["error_type"] is None


def test_step_executor_rewrites_on_database_prefixed_error_type():
    """真实链路的 error_type 带 database_ 前缀（如 database_sql_syntax），
    必须同样触发带错误上下文的重写 —— 历史上只匹配裸值，
    导致归因链路全部退化为原样重试（FULL OUTER JOIN 事故的根因）。"""
    plan = PlanGenerator().build_plan("最近三个月利润为什么下降？", sample_decomposition())
    questions_seen: list[str] = []

    def runner(question: str) -> dict:
        questions_seen.append(question)
        if len(questions_seen) == 1:
            return {
                "success": False,
                "sql": "SELECT ... FULL OUTER JOIN ...",
                "error": "SQL 语法错误，请检查字段、聚合和别名是否正确",
                "error_type": "database_sql_syntax",
                "raw_error": "You have an error in your SQL syntax near 'FULL'",
            }
        return {
            "success": True,
            "sql": "SELECT good",
            "columns": ["a"],
            "rows": [{"a": 1}],
            "formatted": "ok",
        }

    executor = StepExecutor(step_runner=runner, max_retries=1, failure_policy="skip")
    results = executor.execute_plan(plan, max_steps=1)

    assert results[0].success is True
    assert results[0].repaired is True
    # 第二次调用必须携带修复上下文（rewrite），而不是原样重发同一问题
    assert len(questions_seen) == 2
    assert "上一次尝试失败" in questions_seen[1]
    # 回灌的是数据库原始报错（含出错位置），不只是泛化文案
    assert "near 'FULL'" in questions_seen[1]


def test_repair_question_falls_back_without_raw_error():
    """步骤结果没有 raw_error 时（如自定义 step_runner 未提供），
    修复问题要降级为泛化错误信息，不能把空文本回灌给模型。"""
    failed = StepExecutionResult(
        step_id="step_1",
        task_id="task_1",
        step_name="查询月度毛利",
        success=False,
        question="查询月度毛利",
        sql="SELECT bad",
        error="SQL 语法错误，请检查字段、聚合和别名是否正确",
        error_type="sql_syntax",
        raw_error=None,
    )

    question = StepExecutor._build_repair_question("查询月度毛利", failed)

    assert "数据库返回的错误" in question
    assert "数据库原始报错" not in question
    assert "SQL 语法错误" in question
