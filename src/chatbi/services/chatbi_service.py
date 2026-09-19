"""
主入口模块

整合所有模块，提供命令行交互界面。
这是 ChatBI Text2SQL 系统的统一入口，串联 query_parser → prompt_builder → llm_client → database → result_formatter 完整链路，
并整合规则修复、指标知识注入、Schema Linking 和指标 RAG 能力。

新增 run_stream 流式方法，按阶段 yield 事件，
为 SSE 推送提供业务层能力。保留原有 run 方法不动，确保向后兼容。

新增 use_schema_linking 和 use_indicator_rag 参数，
支持 Schema Linking（动态 Schema 注入）+ 指标 RAG（语义检索指标知识）。
两者可独立开关，均有 fallback 机制保障稳定性。

新增 run_stream_events 结构化事件流方法，
把原先只面向 SSE 字符串的流式链路拆出「事件字典」层，
供 Agent 归因链路在子步骤中复用并附带 step_id、step_name 等上下文。
run_stream 保持原行为不变，内部改为复用 run_stream_events。
"""

import json
import re
from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Generator

from chatbi.bootstrap.runtime_factory import build_runtime
from chatbi.core.config import APP_CONFIG, LLM_CONFIG
from chatbi.core.security import SecurityError, UserContext
from chatbi.infrastructure.database import QueryExecutionError
from chatbi.infrastructure.session_store import SessionStore
from chatbi.retrieval.indicator_knowledge import IndicatorKnowledge
from chatbi.text2sql.prompt_builder import build_prompt


@dataclass(slots=True)
class _PreparedQuery:
    runtime: Any
    options: dict[str, bool]
    user_context: UserContext
    detected_indicators: list[str]
    system_msg: str
    prompt: str


class ChatBISystem:
    """ChatBI 系统主类"""

    def __init__(
        self,
        runtime=None,
        app_config: dict | None = None,
        runtime_factory=build_runtime,
        session_store: SessionStore | None = None,
    ):
        self.app_config = app_config or APP_CONFIG
        self.runtime_factory = runtime_factory
        self.runtime = runtime or self.runtime_factory(self.app_config)
        self.parser = self.runtime.parser
        self.llm = self.runtime.llm
        self.db = self.runtime.db
        self.formatter = self.runtime.formatter
        self.indicator_knowledge = self.runtime.indicator_knowledge
        self._session_store = session_store

    @property
    def session_store(self) -> SessionStore:
        """懒创建会话存储。

        仅 import 本模块不应在工作区落下 SQLite 文件，
        因此在真正需要多轮上下文时才初始化。
        """
        if self._session_store is None:
            self._session_store = SessionStore()
        return self._session_store

    def rebind_runtime(self, runtime) -> None:
        """切换到外部已构建的运行时，避免同一次请求重复创建连接池。

        Agent 执行链路会复用同一个 runtime 跑多个子步骤，
        若每步都新建 ChatBISystem 会为每个子步骤各建一个连接池，
        既拖慢链路也会迅速打满 MySQL 连接数。
        """
        self.runtime = runtime
        self.parser = runtime.parser
        self.llm = runtime.llm
        self.db = runtime.db
        self.formatter = runtime.formatter
        self.indicator_knowledge = runtime.indicator_knowledge

    def _get_runtime(self, source_id: str | None = None):
        if source_id is None or source_id == self.runtime.source_id:
            return SimpleNamespace(
                source_id=self.runtime.source_id,
                parser=self.parser,
                llm=self.llm,
                db=self.db,
                formatter=self.formatter,
                indicator_knowledge=self.indicator_knowledge,
            )
        return self.runtime_factory(self.app_config, source_id=source_id)

    def _resolve_feature_options(self, overrides: dict[str, bool | None]) -> dict[str, bool]:
        feature_defaults = self.app_config.get("features", {})
        resolved = {}
        for option_name, value in overrides.items():
            feature_key = option_name.removeprefix("use_")
            resolved[option_name] = value if value is not None else feature_defaults.get(feature_key, False)
        return resolved

    def _resolve_indicator_context(
        self,
        user_question: str,
        use_indicator_knowledge: bool,
        use_indicator_rag: bool,
        indicator_knowledge: IndicatorKnowledge,
    ) -> tuple[list[str], str]:
        """统一解析指标上下文，避免 RAG/关键词路径重复执行同一检索逻辑。"""
        detected_indicators = []
        indicator_block = ""

        if use_indicator_rag:
            try:
                from chatbi.retrieval.indicator_retriever import retrieve_indicator_context

                context = retrieve_indicator_context(user_question)
                detected_indicators = context["detected_indicators"]
                indicator_block = context["indicator_block"]
            except Exception:
                detected_indicators = []
                indicator_block = ""

            if use_indicator_knowledge and not indicator_block:
                context = indicator_knowledge.get_indicator_context(user_question)
                detected_indicators = context["detected_indicators"]
                indicator_block = context["indicator_block"]
        elif use_indicator_knowledge:
            context = indicator_knowledge.get_indicator_context(user_question)
            detected_indicators = context["detected_indicators"]
            indicator_block = context["indicator_block"]

        return detected_indicators, indicator_block

    def _prepare_query(
        self,
        user_question: str,
        use_few_shot: bool | None,
        use_rules: bool | None,
        use_guards: bool | None,
        use_indicator_knowledge: bool | None,
        use_schema_linking: bool | None,
        use_indicator_rag: bool | None,
        source_id: str | None,
        security_context: UserContext | None,
        session_id: str | None = None,
    ) -> _PreparedQuery | None:
        """完成同步与流式查询共用的解析、知识检索和 Prompt 构造。"""
        runtime = self._get_runtime(source_id)
        options = self._resolve_feature_options(
            {
                "use_few_shot": use_few_shot,
                "use_rules": use_rules,
                "use_guards": use_guards,
                "use_indicator_knowledge": use_indicator_knowledge,
                "use_schema_linking": use_schema_linking,
                "use_indicator_rag": use_indicator_rag,
            }
        )
        user_context = security_context or UserContext.demo_admin()

        parsed = runtime.parser.parse(user_question)
        if not runtime.parser.validate(parsed):
            return None

        detected_indicators, indicator_block = self._resolve_indicator_context(
            user_question=user_question,
            use_indicator_knowledge=options["use_indicator_knowledge"],
            use_indicator_rag=options["use_indicator_rag"],
            indicator_knowledge=runtime.indicator_knowledge,
        )
        # 多轮上下文：只有传了 session_id 才读历史。
        # 未传时不触碰会话存储，行为与单轮查询完全一致。
        history = ""
        if session_id:
            history = self.session_store.render_history(
                session_id,
                user_context.user_id,
            )

        system_msg, prompt = build_prompt(
            user_question,
            use_few_shot=options["use_few_shot"],
            use_rules=options["use_rules"],
            use_guards=options["use_guards"],
            indicator_knowledge=indicator_block,
            use_schema_linking=options["use_schema_linking"],
            history=history,
        )
        return _PreparedQuery(
            runtime=runtime,
            options=options,
            user_context=user_context,
            detected_indicators=detected_indicators,
            system_msg=system_msg,
            prompt=prompt,
        )

    def run(
        self,
        user_question: str,
        use_few_shot: bool | None = None,
        use_rules: bool | None = None,
        use_guards: bool | None = None,
        use_indicator_knowledge: bool | None = None,
        use_schema_linking: bool | None = None,
        use_indicator_rag: bool | None = None,
        source_id: str | None = None,
        security_context: UserContext | None = None,
        session_id: str | None = None,
    ) -> dict:
        """
        运行完整链路

        Args:
            user_question: 用户自然语言问题
            use_few_shot: 是否使用 Few-shot
            use_rules: 是否启用业务规则
            use_guards: 是否启用错误防护
            use_indicator_knowledge: 是否启用指标知识注入（关键词匹配）
            use_schema_linking: 是否启用 Schema Linking 动态注入
            use_indicator_rag: 是否启用指标 RAG 语义检索（替代关键词匹配）
            security_context: 当前请求的权限上下文

        Returns:
            包含 SQL、结果或错误信息的字典
        """
        prepared = self._prepare_query(
            user_question=user_question,
            use_few_shot=use_few_shot,
            use_rules=use_rules,
            use_guards=use_guards,
            use_indicator_knowledge=use_indicator_knowledge,
            use_schema_linking=use_schema_linking,
            use_indicator_rag=use_indicator_rag,
            source_id=source_id,
            security_context=security_context,
            session_id=session_id,
        )
        if prepared is None:
            return {
                "success": False,
                "error": "输入问题为空",
                "error_type": "validation"
            }

        runtime = prepared.runtime
        options = prepared.options
        use_few_shot = options["use_few_shot"]
        use_rules = options["use_rules"]
        use_guards = options["use_guards"]
        use_indicator_knowledge = options["use_indicator_knowledge"]
        use_schema_linking = options["use_schema_linking"]
        use_indicator_rag = options["use_indicator_rag"]
        user_context = prepared.user_context
        detected_indicators = prepared.detected_indicators
        system_msg = prepared.system_msg
        prompt = prepared.prompt

        # 4. 生成 SQL
        try:
            sql = runtime.llm.generate_sql(system_msg, prompt)
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "error_type": "llm",
                "metadata": {
                    "detected_indicators": detected_indicators,
                    "model": LLM_CONFIG["model"],
                    "used_rules": use_rules,
                    "used_guards": use_guards,
                    "used_indicator_knowledge": use_indicator_knowledge,
                    "used_schema_linking": use_schema_linking,
                    "used_indicator_rag": use_indicator_rag,
                    "source_id": runtime.source_id,
                    "security_role": user_context.role,
                    "security_region": user_context.region,
                }
            }

        # 5. 执行 SQL
        try:
            columns, results = runtime.db.execute(sql, user=user_context)
            db_info = getattr(runtime.db, "last_query_info", {})
            formatted = runtime.formatter.format(columns, results)
            # 只在成功时记录本轮问答。失败的 SQL 不进历史，
            # 免得后续轮次被上一条错 SQL 带偏。
            if session_id:
                self.session_store.append_turn(
                    session_id=session_id,
                    user_id=user_context.user_id,
                    question=user_question,
                    sql=sql,
                )
            return {
                "success": True,
                "sql": sql,
                "columns": columns,
                "results": results,
                "formatted": formatted,
                "metadata": {
                    "detected_indicators": detected_indicators,
                    "model": LLM_CONFIG["model"],
                    "used_few_shot": use_few_shot,
                    "used_rules": use_rules,
                    "used_guards": use_guards,
                    "used_indicator_knowledge": use_indicator_knowledge,
                    "used_schema_linking": use_schema_linking,
                    "used_indicator_rag": use_indicator_rag,
                    "source_id": runtime.source_id,
                    "security_role": user_context.role,
                    "security_region": user_context.region,
                    "row_count": len(results),
                    "db_duration_ms": db_info.get("duration_ms"),
                    "db_slow_query": db_info.get("slow_query", False),
                    "db_explain_plan": db_info.get("explain_plan", []),
                }
            }
        except SecurityError as e:
            return {
                "success": False,
                "sql": sql,
                "error": str(e),
                "error_type": "security",
                "metadata": {
                    "detected_indicators": detected_indicators,
                    "model": LLM_CONFIG["model"],
                    "used_few_shot": use_few_shot,
                    "used_rules": use_rules,
                    "used_guards": use_guards,
                    "used_indicator_knowledge": use_indicator_knowledge,
                    "used_schema_linking": use_schema_linking,
                    "used_indicator_rag": use_indicator_rag,
                    "source_id": runtime.source_id,
                    "security_role": user_context.role,
                    "security_region": user_context.region,
                }
            }
        except QueryExecutionError as e:
            return {
                "success": False,
                "sql": sql,
                "error": str(e),
                "error_type": f"database_{e.error_type}",
                "metadata": {
                    "detected_indicators": detected_indicators,
                    "model": LLM_CONFIG["model"],
                    "used_few_shot": use_few_shot,
                    "used_rules": use_rules,
                    "used_guards": use_guards,
                    "used_indicator_knowledge": use_indicator_knowledge,
                    "used_schema_linking": use_schema_linking,
                    "used_indicator_rag": use_indicator_rag,
                    "source_id": runtime.source_id,
                    "security_role": user_context.role,
                    "security_region": user_context.region,
                    "db_duration_ms": e.metadata.get("duration_ms"),
                    "db_error_code": e.metadata.get("error_code"),
                    "db_raw_error": e.metadata.get("raw_error"),
                }
            }
        except Exception as e:
            return {
                "success": False,
                "sql": sql,
                "error": str(e),
                "error_type": "database",
                "metadata": {
                    "detected_indicators": detected_indicators,
                    "model": LLM_CONFIG["model"],
                    "used_few_shot": use_few_shot,
                    "used_rules": use_rules,
                    "used_guards": use_guards,
                    "used_indicator_knowledge": use_indicator_knowledge,
                    "used_schema_linking": use_schema_linking,
                    "used_indicator_rag": use_indicator_rag,
                    "source_id": runtime.source_id,
                    "security_role": user_context.role,
                    "security_region": user_context.region,
                }
            }

    def run_stream(
        self,
        user_question: str,
        use_few_shot: bool | None = None,
        use_rules: bool | None = None,
        use_guards: bool | None = None,
        use_indicator_knowledge: bool | None = None,
        use_schema_linking: bool | None = None,
        use_indicator_rag: bool | None = None,
        source_id: str | None = None,
        security_context: UserContext | None = None,
        session_id: str | None = None,
    ) -> Generator[str, None, None]:
        """
        流式运行完整链路，按阶段 yield SSE 事件字符串

        事件类型：
        - sql_chunk: LLM 流式产出的 SQL 片段
        - sql_done: SQL 完整输出 + 执行结果
        - result: 查询结果（columns + rows）
        - error: 异常信息

        每个 yield 的字符串格式为 "event: <type>\\ndata: <json>\\n\\n"，
        可直接作为 SSE 推送内容。

        Args:
            user_question: 用户自然语言问题
            use_few_shot: 是否使用 Few-shot
            use_rules: 是否启用业务规则
            use_guards: 是否启用错误防护
            use_indicator_knowledge: 是否启用指标知识注入（关键词匹配）
            use_schema_linking: 是否启用 Schema Linking 动态注入
            use_indicator_rag: 是否启用指标 RAG 语义检索
            security_context: 当前请求的权限上下文

        Yields:
            SSE 格式的事件字符串
        """
        for event_type, data in self.run_stream_events(
            user_question=user_question,
            use_few_shot=use_few_shot,
            use_rules=use_rules,
            use_guards=use_guards,
            use_indicator_knowledge=use_indicator_knowledge,
            use_schema_linking=use_schema_linking,
            use_indicator_rag=use_indicator_rag,
            source_id=source_id,
            security_context=security_context,
            session_id=session_id,
        ):
            yield _sse_event(event_type, data)

    def run_stream_events(
        self,
        user_question: str,
        use_few_shot: bool | None = None,
        use_rules: bool | None = None,
        use_guards: bool | None = None,
        use_indicator_knowledge: bool | None = None,
        use_schema_linking: bool | None = None,
        use_indicator_rag: bool | None = None,
        source_id: str | None = None,
        security_context: UserContext | None = None,
        session_id: str | None = None,
    ) -> Generator[tuple[str, dict], None, None]:
        """流式运行完整链路，产出 (事件类型, 事件数据) 二元组。

        与 run_stream 的区别是不做 SSE 字符串编码，
        以便上层（如 Agent 归因链路）在事件上附加 step_id 等上下文，
        或直接消费结构化结果。
        """
        prepared = self._prepare_query(
            user_question=user_question,
            use_few_shot=use_few_shot,
            use_rules=use_rules,
            use_guards=use_guards,
            use_indicator_knowledge=use_indicator_knowledge,
            use_schema_linking=use_schema_linking,
            use_indicator_rag=use_indicator_rag,
            source_id=source_id,
            security_context=security_context,
            session_id=session_id,
        )
        if prepared is None:
            yield "error", {
                "error": "输入问题为空",
                "error_type": "validation"
            }
            return

        runtime = prepared.runtime
        options = prepared.options
        use_few_shot = options["use_few_shot"]
        use_rules = options["use_rules"]
        use_guards = options["use_guards"]
        use_indicator_knowledge = options["use_indicator_knowledge"]
        use_schema_linking = options["use_schema_linking"]
        use_indicator_rag = options["use_indicator_rag"]
        user_context = prepared.user_context
        detected_indicators = prepared.detected_indicators
        system_msg = prepared.system_msg
        prompt = prepared.prompt

        # 4. 流式生成 SQL —— 逐 chunk 推送（过滤空内容）
        sql_parts = []
        try:
            for chunk_text in runtime.llm.generate_sql_stream(system_msg, prompt):
                if not chunk_text:
                    continue  # 跳过空 chunk（部分模型会返回空字符串的 delta）
                sql_parts.append(chunk_text)
                yield "sql_chunk", {"content": chunk_text}
        except Exception as e:
            yield "error", {
                "error": str(e),
                "error_type": "llm",
                "metadata": {
                    "detected_indicators": detected_indicators,
                    "model": LLM_CONFIG["model"],
                    "used_indicator_knowledge": use_indicator_knowledge,
                    "used_schema_linking": use_schema_linking,
                    "used_indicator_rag": use_indicator_rag,
                    "source_id": runtime.source_id,
                    "security_role": user_context.role,
                    "security_region": user_context.region,
                }
            }
            return

        # 5. 拼接完整 SQL 并清理 markdown 标记
        raw_sql = "".join(sql_parts)
        sql = re.sub(r'```sql|```', '', raw_sql).strip()

        yield "sql_done", {"sql": sql}

        # 6. 执行 SQL
        try:
            columns, results = runtime.db.execute(sql, user=user_context)
            db_info = getattr(runtime.db, "last_query_info", {})
            rows_dict = [dict(zip(columns, row)) for row in results]
            # 只在成功时记录本轮问答，与 run 保持一致
            if session_id:
                self.session_store.append_turn(
                    session_id=session_id,
                    user_id=user_context.user_id,
                    question=user_question,
                    sql=sql,
                )
            yield "result", {
                "columns": columns,
                "rows": rows_dict,
                "sql": sql,
                "row_count": len(results),
                "metadata": {
                    "detected_indicators": detected_indicators,
                    "model": LLM_CONFIG["model"],
                    "used_few_shot": use_few_shot,
                    "used_rules": use_rules,
                    "used_guards": use_guards,
                    "used_indicator_knowledge": use_indicator_knowledge,
                    "used_schema_linking": use_schema_linking,
                    "used_indicator_rag": use_indicator_rag,
                    "source_id": runtime.source_id,
                    "security_role": user_context.role,
                    "security_region": user_context.region,
                    "db_duration_ms": db_info.get("duration_ms"),
                    "db_slow_query": db_info.get("slow_query", False),
                    "db_explain_plan": db_info.get("explain_plan", []),
                }
            }
        except SecurityError as e:
            yield "error", {
                "error": str(e),
                "error_type": "security",
                "sql": sql,
                "metadata": {
                    "detected_indicators": detected_indicators,
                    "model": LLM_CONFIG["model"],
                    "used_indicator_knowledge": use_indicator_knowledge,
                    "used_schema_linking": use_schema_linking,
                    "used_indicator_rag": use_indicator_rag,
                    "source_id": runtime.source_id,
                    "security_role": user_context.role,
                    "security_region": user_context.region,
                }
            }
        except QueryExecutionError as e:
            yield "error", {
                "error": str(e),
                "error_type": f"database_{e.error_type}",
                "sql": sql,
                "metadata": {
                    "detected_indicators": detected_indicators,
                    "model": LLM_CONFIG["model"],
                    "used_indicator_knowledge": use_indicator_knowledge,
                    "used_schema_linking": use_schema_linking,
                    "used_indicator_rag": use_indicator_rag,
                    "source_id": runtime.source_id,
                    "security_role": user_context.role,
                    "security_region": user_context.region,
                    "db_duration_ms": e.metadata.get("duration_ms"),
                    "db_error_code": e.metadata.get("error_code"),
                    "db_raw_error": e.metadata.get("raw_error"),
                }
            }
        except Exception as e:
            yield "error", {
                "error": str(e),
                "error_type": "database",
                "sql": sql,
                "metadata": {
                    "detected_indicators": detected_indicators,
                    "model": LLM_CONFIG["model"],
                    "used_indicator_knowledge": use_indicator_knowledge,
                    "used_schema_linking": use_schema_linking,
                    "used_indicator_rag": use_indicator_rag,
                    "source_id": runtime.source_id,
                    "security_role": user_context.role,
                    "security_region": user_context.region,
                }
            }


def _sse_event(event_type: str, data: dict) -> str:
    """构造 SSE 格式的事件字符串"""
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False, default=_json_serializer)}\n\n"


def _json_serializer(obj):
    """JSON 序列化补充：处理 Decimal 等非标准类型"""
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")
