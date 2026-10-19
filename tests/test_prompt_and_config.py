from types import SimpleNamespace

from chatbi.infrastructure.llm_client import LLMClient
from chatbi.text2sql.prompt_builder import build_prompt


def test_build_prompt_keeps_curdate_rule_for_recent_months():
    _system_msg, prompt = build_prompt("最近三个月利润为什么下降？", use_rules=True, schema_text="sales_orders(order_date, net_amount)",
                                       rules_text="最近 N 个月使用 DATE_SUB(CURDATE(), INTERVAL N MONTH) 作为起始边界")

    assert "DATE_SUB(CURDATE(), INTERVAL N MONTH)" in prompt


def test_llm_client_allows_longer_sql_output():
    client = LLMClient()

    assert client.max_tokens >= 4000


def test_sql_stream_skips_chunks_without_choices(monkeypatch):
    class FakeStream:
        closed = False

        def __iter__(self):
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="SELECT "))])
            yield SimpleNamespace(choices=[])
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="1"))])

        def close(self):
            self.closed = True

    stream = FakeStream()
    completions = SimpleNamespace(create=lambda **kwargs: stream)
    request_client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    client = LLMClient()
    monkeypatch.setattr(client, "request_client", lambda budget=None: request_client)

    assert "".join(client.generate_sql_stream("system", "question")) == "SELECT 1"
    assert stream.closed
