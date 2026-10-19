from chatbi.contracts.execution import QueryExecutionResult
from types import SimpleNamespace

def test_build_runtime_uses_requested_database_source(monkeypatch):
    import chatbi.bootstrap.runtime_factory as runtime_factory

    captured = {}

    class FakeParser:
        pass

    class FakeLLM:
        pass

    class FakeFormatter:
        pass

    class FakeIndicatorKnowledge:
        def __init__(self, config_path=None):
            pass

    class FakeDatabaseClient:
        def __init__(self, db_config=None, source_id=None, runtime_config=None, schema=None):
            captured["db_config"] = db_config
            captured["source_id"] = source_id

    monkeypatch.setattr(runtime_factory, "QueryParser", FakeParser)
    monkeypatch.setattr(runtime_factory, "LLMClient", FakeLLM)
    monkeypatch.setattr(runtime_factory, "ResultFormatter", FakeFormatter)
    monkeypatch.setattr(runtime_factory, "IndicatorKnowledge", FakeIndicatorKnowledge)
    monkeypatch.setattr(runtime_factory, "DatabaseClient", FakeDatabaseClient)

    app_config = {
        "database": {
            "default_source": "mysql_main",
            "sources": {
                "mysql_main": {"driver": "mysql", "host": "localhost", "port": 3307},
                "finance_pg": {"driver": "postgresql", "host": "localhost", "port": 5432},
            },
        }
    }

    runtime = runtime_factory.build_runtime(app_config, source_id="finance_pg")

    assert runtime.source_id == "finance_pg"
    assert captured["source_id"] == "finance_pg"
    assert captured["db_config"]["driver"] == "postgresql"


def test_chatbi_system_run_uses_runtime_factory_for_source_id():
    from chatbi.core.security import UserContext
    from chatbi.services.chatbi_service import ChatBISystem

    captured = {}

    class FakeParser:
        def parse(self, question: str) -> str:
            return question

        def validate(self, parsed: str) -> bool:
            return True

    class FakeLLM:
        def generate_sql(self, _system_msg: str, _prompt: str) -> str:
            return "SELECT 1"

    class FakeDB:
        def execute_query(self, sql: str, user=None, budget=None):
            captured["sql"] = sql
            captured["user"] = user
            return QueryExecutionResult(sql, sql, "finance_pg", ["value"], [(1,)], 12.5)

    class FakeFormatter:
        def format(self, columns, rows) -> str:
            return "ok"

    class FakeIndicatorKnowledge:
        def get_indicator_context(self, question: str):
            return {"detected_indicators": [], "indicator_block": ""}

    def fake_runtime_factory(app_config, source_id=None):
        captured["source_id"] = source_id
        return SimpleNamespace(
            source_id=source_id or "mysql_main",
            parser=FakeParser(),
            llm=FakeLLM(),
            db=FakeDB(),
            formatter=FakeFormatter(),
            indicator_knowledge=FakeIndicatorKnowledge(),
        schema_text="sales_orders(order_id, order_date, region, net_amount)")

    system = ChatBISystem(app_config={"features": {}}, runtime_factory=fake_runtime_factory)

    result = system.run(
        "查看总订单数",
        source_id="finance_pg",
        security_context=UserContext(user_id="u1", role="finance"),
    )

    assert result["success"] is True
    assert captured["source_id"] == "finance_pg"
    assert result["metadata"]["source_id"] == "finance_pg"


def test_chatbi_system_reuses_source_runtime_and_closes_all_pools():
    from chatbi.services.chatbi_service import ChatBISystem
    created, closed = [], []
    def factory(config, source_id=None):
        source = source_id or "default"
        created.append(source)
        return SimpleNamespace(source_id=source, parser=None, formatter=None, indicator_knowledge=None,
            db=SimpleNamespace(close=lambda: closed.append(source)), llm=SimpleNamespace(), schema_text="sales_orders(order_id, order_date, region, net_amount)")
    system = ChatBISystem(app_config={"features": {}}, runtime_factory=factory)
    assert system._get_runtime("another") is system._get_runtime("another")
    assert created == ["default", "another"]
    system.close()
    assert closed == ["default", "another"]
