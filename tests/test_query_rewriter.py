"""提问改写（指代消解）的测试。

按项目约定，全程使用假的文本生成器，不依赖真实模型服务。
"""

from chatbi.text2sql.query_rewriter import QueryRewriter

HISTORY = (
    "第1轮 用户问：统计各地区的订单数量和净销售额\n"
    "      生成SQL：SELECT o.region, COUNT(*) FROM sales_orders GROUP BY o.region;"
)


def make_rewriter(reply):
    """reply 为字符串时返回它，为异常实例时抛出。"""

    def generator(system_msg, prompt):
        if isinstance(reply, Exception):
            raise reply
        return reply

    return QueryRewriter(generator)


# ==================== 正常路径 ====================


def test_rewrites_follow_up_question():
    rewriter = make_rewriter("2026年2月各地区的订单数量和净销售额")

    assert rewriter.rewrite("那2月呢？", HISTORY) == "2026年2月各地区的订单数量和净销售额"


def test_override_generator_takes_precedence():
    rewriter = QueryRewriter()  # 默认生成器会抛异常
    captured = {}

    def override(system_msg, prompt):
        captured["prompt"] = prompt
        return "改写后的结果"

    result = rewriter.rewrite("那2月呢？", HISTORY, text_generator=override)

    assert result == "改写后的结果"
    # 改写 Prompt 里必须同时带上历史与原问题，否则无从消解指代
    assert "那2月呢？" in captured["prompt"]
    assert "统计各地区的订单数量和净销售额" in captured["prompt"]


# ==================== 降级路径（都不能抛异常） ====================


def test_without_history_returns_original():
    rewriter = make_rewriter("不应被调用")

    assert rewriter.rewrite("那2月呢？", "") == "那2月呢？"


def test_blank_question_returns_original():
    rewriter = make_rewriter("不应被调用")

    assert rewriter.rewrite("   ", HISTORY) == "   "


def test_generator_failure_falls_back_to_original():
    rewriter = make_rewriter(RuntimeError("模型超时"))

    assert rewriter.rewrite("那2月呢？", HISTORY) == "那2月呢？"


def test_unbound_generator_falls_back_instead_of_raising():
    rewriter = QueryRewriter()

    assert rewriter.rewrite("那2月呢？", HISTORY) == "那2月呢？"


def test_blank_reply_falls_back_to_original():
    assert make_rewriter("   ").rewrite("那2月呢？", HISTORY) == "那2月呢？"


def test_overlong_reply_is_rejected():
    # 超过长度上限基本可判定模型在自由发挥，宁可不用
    assert make_rewriter("很长的解释" * 100).rewrite("那2月呢？", HISTORY) == "那2月呢？"


def test_unchanged_reply_returns_original():
    assert make_rewriter("那2月呢？").rewrite("那2月呢？", HISTORY) == "那2月呢？"


# ==================== 输出清洗 ====================


def test_strips_code_fence_and_prefix():
    rewriter = make_rewriter("```\n改写后的问题：2026年2月订单数\n```")

    assert rewriter.rewrite("那2月呢？", HISTORY) == "2026年2月订单数"


def test_strips_surrounding_quotes():
    rewriter = make_rewriter('"2026年2月订单数"')

    assert rewriter.rewrite("那2月呢？", HISTORY) == "2026年2月订单数"


def test_takes_first_line_only():
    rewriter = make_rewriter("2026年2月订单数\n这里是我这么改的原因")

    assert rewriter.rewrite("那2月呢？", HISTORY) == "2026年2月订单数"
