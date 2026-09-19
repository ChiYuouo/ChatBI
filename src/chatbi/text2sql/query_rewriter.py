"""
提问改写模块

把带指代或省略的追问（「那2月呢？」）改写为自包含的问题
（「2026年2月各地区的订单数量和净销售额」），再交给 Text2SQL 生成 SQL。

与「把历史塞进 Prompt 让模型自己领会」的隐式方案相比，显式改写的价值在于：
改写结果可以直接展示给用户、可以单独写测试、出问题好定位。

两条硬约束：
1. 只在有对话历史时启用 —— 单轮查询没有指代可消解，改写纯属浪费一次模型调用。
2. 任何异常都降级为原问题，绝不阻断查询主链路。
"""

from __future__ import annotations

import logging
import re
from typing import Callable

logger = logging.getLogger("chatbi.rewrite")

# 超过这个长度基本可判定模型在自由发挥，按失败处理
_MAX_REWRITE_CHARS = 200

_SYSTEM_MSG = (
    "你是 ChatBI 系统中的提问改写器。"
    "你的任务是把带指代或省略的追问，改写成一个可以独立理解的问题。"
)

_PROMPT_TEMPLATE = """【对话历史】
{history}

【当前问题】
{question}

请把「当前问题」改写为自包含的完整问题，要求：
1. 补全代词与省略（例如「那2月呢？」应改写为「2026年2月各地区的订单数量和净销售额」）
2. 保持原意，不要添加历史中并不存在的限定条件
3. 只输出改写后的问题本身，不要解释、不要加引号
4. 若当前问题本身已经自包含，原样输出
"""


def _unbound_generator(system_msg: str, prompt: str) -> str:
    """占位生成器：在注入真实 LLM 之前被调用说明装配有误。"""
    raise RuntimeError("提问改写器的文本生成器尚未绑定，请先通过 runtime 注入")


def _sanitize(raw: str) -> str:
    """清洗模型输出；无法得到可信结果时返回空串。"""
    text = (raw or "").strip()
    if not text:
        return ""

    # 去掉 markdown 代码块
    text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text).strip()
    # 去掉「改写后的问题：」这类前缀
    text = re.sub(r"^(改写后的问题|改写结果|问题)\s*[:：]\s*", "", text).strip()
    # 模型偶尔会自作主张加引号
    if len(text) >= 2 and text[0] in "\"“'" and text[-1] in "\"”'":
        text = text[1:-1].strip()

    # 多行时只取第一行 —— 后面多半是模型附带的解释
    first_line = text.splitlines()[0].strip() if text else ""
    if not first_line or len(first_line) > _MAX_REWRITE_CHARS:
        return ""
    return first_line


class QueryRewriter:
    """基于对话历史做指代消解式改写。"""

    def __init__(self, text_generator: Callable[[str, str], str] | None = None):
        self.text_generator = text_generator or _unbound_generator

    def rewrite(
        self,
        question: str,
        history: str,
        text_generator: Callable[[str, str], str] | None = None,
    ) -> str:
        """返回改写后的问题。

        text_generator 用于临时覆盖：主链路把当前 runtime 的 LLM 传进来，
        省得每个请求都重新装配一个改写器。

        无历史、改写失败、或结果不可信时，一律返回原问题。
        """
        if not history or not (question or "").strip():
            return question

        generator = text_generator or self.text_generator
        prompt = _PROMPT_TEMPLATE.format(history=history, question=question)
        try:
            raw = generator(_SYSTEM_MSG, prompt)
        except Exception as exc:  # noqa: BLE001 - 改写失败不能影响查询
            logger.warning("提问改写失败，本次使用原问题: %s", exc)
            return question

        rewritten = _sanitize(raw)
        if not rewritten or rewritten == question:
            return question
        logger.info("提问改写: %r -> %r", question, rewritten)
        return rewritten


__all__ = ["QueryRewriter"]
