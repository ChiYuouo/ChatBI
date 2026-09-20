"""
归因分析编排服务

把「复杂问题 -> 任务拆解 -> 执行计划 -> 多步流式执行 -> 结果汇总 -> 归因报告」
整条链路封装为可流式消费的事件源，供 API 层直接转发为 SSE。

与 agent_planner.PlanAndExecuteAgent 的区别：
- PlanAndExecuteAgent 是阻塞式 CLI 入口，跑完才返回全部结果；
- AnalysisService 是流式编排层，每完成一个阶段就立即产出事件，
  前端因此能看到「正在拆解」「第 2 步正在写 SQL」「正在归因」的实时进展。
"""

from __future__ import annotations

import logging
from typing import Any, Generator

from chatbi.analysis.agent_planner import (
    ExecutionPlan,
    PlanAndExecuteAgent,
    PlanGenerator,
    ResultSummarizer,
    StepExecutor,
    StepExecutionResult,
)
from chatbi.analysis.query_decomposer import QueryDecomposer
from chatbi.analysis.report_generator import ReportGenerator
from chatbi.bootstrap.runtime_factory import build_runtime
from chatbi.core.config import APP_CONFIG
from chatbi.core.security import UserContext
from chatbi.services.chatbi_service import ChatBISystem

logger = logging.getLogger("chatbi.analysis")

_UNBOUND_LLM_MESSAGE = "归因链路的 LLM 客户端尚未绑定，请先通过 runtime 注入"


def _unbound_text_generator(system_msg: str, prompt: str) -> str:
    """占位文本生成器：在 LLM 绑定前被调用说明链路装配有误。"""
    raise RuntimeError(_UNBOUND_LLM_MESSAGE)


class _UnboundLLM:
    """占位 LLM：仅用于满足拆解器的构造参数，实际调用前必被真实实现替换。"""

    def generate_text(self, system_msg: str, prompt: str) -> str:
        raise RuntimeError(_UNBOUND_LLM_MESSAGE)


class AnalysisService:
    """归因分析的流式编排入口。"""

    def __init__(
        self,
        decomposer: QueryDecomposer | None = None,
        planner: PlanGenerator | None = None,
        summarizer: ResultSummarizer | None = None,
        report_generator: ReportGenerator | None = None,
        runtime_factory=build_runtime,
        session_store: Any | None = None,
    ):
        # 拆解器与报告生成器最终都复用 runtime 里的 LLM（见 _bind_llm），
        # 因此这里用占位实现，避免构造时白建两个真实 LLMClient。
        self.decomposer = decomposer or QueryDecomposer(
            llm_client=_UnboundLLM(),
            response_generator=_unbound_text_generator,
        )
        self.planner = planner or PlanGenerator()
        self.summarizer = summarizer or ResultSummarizer()
        self.report_generator = report_generator or ReportGenerator(
            text_generator=_unbound_text_generator,
        )
        self.runtime_factory = runtime_factory
        # 会话存储：传入后，带 session_id 的归因请求会在完成时写入一轮记录。
        # None 时跳过保存（测试与直接调用场景兼容）。
        self.session_store = session_store

    def _bind_llm(self, runtime: Any) -> None:
        """把链路各阶段的 LLM 客户端统一绑定到当前 runtime 的实例上。

        拆解器和报告生成器若各自新建 LLMClient，会绕过传入的 runtime，
        导致同一次请求里出现多个模型客户端（测试时也无法注入假实现）。
        这里显式对齐，保证整条归因链路共用同一个 LLM 客户端。
        """
        llm = getattr(runtime, "llm", None)
        if llm is None:
            return

        def _generate_text(system_msg: str, prompt: str) -> str:
            return llm.generate_text(system_msg=system_msg, prompt=prompt)

        if isinstance(self.decomposer, QueryDecomposer):
            self.decomposer.llm = llm
            # 真实 LLMClient 支持 client.chat(...) 的 JSON 模式，优先走原生实现；
            # 注入的假实现没有该结构，则回退到 generate_text，保证可注入性。
            if hasattr(getattr(llm, "client", None), "chat"):
                self.decomposer.response_generator = self.decomposer._generate_response
            else:
                self.decomposer.response_generator = _generate_text

        if isinstance(self.report_generator, ReportGenerator):
            self.report_generator.text_generator = _generate_text

    def run_stream_events(
        self,
        user_question: str,
        max_steps: int | None = None,
        source_id: str | None = None,
        security_context: UserContext | None = None,
        chatbi_run_options: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> Generator[tuple[str, dict[str, Any]], None, None]:
        """流式执行完整归因链路，产出 (事件类型, 事件数据) 二元组。

        事件类型：
        - start: 链路开始
        - decomposition_start / decomposition_done: 问题拆解
        - plan_ready: 执行计划就绪
        - step_start / step_sql_chunk / step_sql_done / step_result / step_retry / step_done: 各步骤
        - summary_done: 多步结果摘要
        - report_start / report_done: 归因报告
        - error: 链路异常
        - done: 链路结束

        session_id 的语义与单跳查询不同：只用于**完成后落一条记录**，
        不会透传给各子步骤 —— 子步骤的问题是机器生成的中间产物，
        逐条落库会污染会话历史与后续提问改写。
        """
        question = (user_question or "").strip()
        if not question:
            yield "error", {"error": "输入问题为空", "error_type": "validation"}
            return

        user_context = security_context or UserContext.demo_admin()
        run_options = chatbi_run_options or {
            "use_schema_linking": True,
            "use_indicator_rag": True,
            "use_indicator_knowledge": True,
        }

        # 整条链路复用同一个 runtime，避免每个子步骤各建一个数据库连接池
        runtime = self.runtime_factory(APP_CONFIG, source_id=source_id)
        system = ChatBISystem(runtime=runtime)
        self._bind_llm(runtime)

        yield "start", {
            "question": question,
            "source_id": runtime.source_id,
            "max_steps": max_steps,
        }

        # 1. 任务拆解
        yield "decomposition_start", {"message": "正在拆解分析问题"}
        try:
            decomposition = self.decomposer.decompose(question)
        except Exception as exc:  # noqa: BLE001 - 拆解失败要作为业务错误回传前端
            logger.warning("任务拆解失败: %s", exc)
            yield "error", {
                "error": f"任务拆解失败：{exc}",
                "error_type": "decomposition",
            }
            return

        subtasks = decomposition.get("subtasks", [])
        yield "decomposition_done", {
            "question_type": decomposition.get("question_type"),
            "analysis_goal": decomposition.get("analysis_goal"),
            "subtasks": subtasks,
            "subtask_count": len(subtasks),
        }

        # 2. 生成执行计划
        plan: ExecutionPlan = self.planner.build_plan(question, decomposition)

        # 3. 流式执行计划
        # max_retries=2：SQL 执行失败时把报错回灌给模型重写，最多重写两次。
        # 归因链路里任何一步失败都会连带跳过它的下游步骤，代价很高，
        # 因此这里默认开启重试（单跳查询链路不重试）。
        executor = StepExecutor(
            chatbi_system=system,
            chatbi_run_options=run_options,
            failure_policy="skip",
            max_retries=2,
            # 把请求者的身份传下去：行级过滤与脱敏都在 DatabaseClient 里按身份执行，
            # 不传的话子步骤会以 demo_admin（admin）身份跑完整条归因链路。
            security_context=user_context,
        )
        step_results: list[StepExecutionResult] = []
        results_by_step: dict[str, StepExecutionResult] = {}

        try:
            for event_type, data in executor.execute_plan_streaming(
                plan,
                max_steps=max_steps,
            ):
                if event_type != "step_done":
                    yield event_type, data
                    continue

                normalized = self._to_step_result(data)
                step_results.append(normalized)
                results_by_step[data["step_id"]] = normalized
                yield "step_done", data
        except Exception as exc:  # noqa: BLE001 - 执行异常要有明确收尾
            logger.exception("计划执行失败: %s", exc)
            yield "error", {
                "error": f"计划执行失败：{exc}",
                "error_type": "execution",
            }
            return
        finally:
            executor.cleanup()

        # 4. 结果汇总
        summary = self.summarizer.summarize(question, plan, step_results)
        yield "summary_done", summary.model_dump()

        # 5. 归因报告
        yield "report_start", {"message": "正在生成归因分析报告"}
        report = self.report_generator.generate(
            original_question=question,
            analysis_goal=plan.analysis_goal,
            step_results=[result.model_dump() for result in step_results],
            summary=summary.model_dump(),
        )
        yield "report_done", report.model_dump()

        # 6. 会话落库
        # 只存原始问题 + 报告结论：子步骤 SQL 属于中间产物，逐条落库冗余，
        # 挑"关键 SQL"也没有稳定标准；归因卡片前端只渲染报告。
        # append_turn 内部自带失败兜底，不影响归因结果返回。
        if session_id and self.session_store is not None:
            self.session_store.append_turn(
                session_id=session_id,
                user_id=user_context.user_id,
                question=question,
                answer=report.markdown or None,
            )

        yield "done", {
            "question": question,
            "completed_steps": summary.completed_steps,
            "failed_steps": summary.failed_steps,
            "skipped_steps": summary.skipped_steps,
            "total_steps": len(plan.steps),
        }

    @staticmethod
    def _to_step_result(data: dict[str, Any]) -> StepExecutionResult:
        """把 step_done 事件数据还原为步骤结果对象，供汇总与报告使用。"""
        return StepExecutionResult(
            step_id=data.get("step_id", ""),
            task_id=data.get("task_id", ""),
            step_name=data.get("step_name", ""),
            success=bool(data.get("success")),
            status=data.get("status", "failed"),
            attempts=data.get("attempts", 1),
            question=data.get("question", ""),
            sql=data.get("sql"),
            columns=data.get("columns") or [],
            rows=data.get("rows") or [],
            formatted=data.get("formatted") or "",
            result_reference=data.get("result_reference"),
            error=data.get("error"),
            error_type=data.get("error_type"),
            repaired=bool(data.get("repaired")),
        )


__all__ = ["AnalysisService", "PlanAndExecuteAgent"]
