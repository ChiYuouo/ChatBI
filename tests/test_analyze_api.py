"""归因分析 API 的接口测试。

用假 AnalysisService 替换真实链路，只验证路由、SSE 编码与参数解析，
不依赖模型服务与数据库。
"""

import json

import pytest
from fastapi.testclient import TestClient

from chatbi.api import dependencies, routes
from chatbi.api.app import app


def _parse_sse(raw: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in raw.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event_type = ""
        data: dict = {}
        for line in block.split("\n"):
            if line.startswith("event: "):
                event_type = line[len("event: "):].strip()
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        if event_type:
            events.append((event_type, data))
    return events


@pytest.fixture()
def client():
    return TestClient(app)


def test_analyze_stream_returns_sse_events(client, monkeypatch):
    def fake_run_stream_events(**kwargs):
        yield "start", {"question": kwargs["user_question"]}
        yield "plan_ready", {"total_steps": 2, "steps": []}
        yield "report_done", {"title": "利润下降归因", "root_causes": ["欧洲区单价下跌"]}
        yield "done", {"completed_steps": 2}

    monkeypatch.setattr(
        routes.analysis_service,
        "run_stream_events",
        fake_run_stream_events,
    )

    response = client.post(
        "/api/v1/analyze/stream",
        json={"question": "最近三个月利润为什么下降？"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(response.text)
    assert [name for name, _ in events] == ["start", "plan_ready", "report_done", "done"]
    assert dict(events)["report_done"]["root_causes"] == ["欧洲区单价下跌"]


def test_analyze_stream_forwards_max_steps_and_options(client, monkeypatch):
    captured: dict = {}

    def fake_run_stream_events(**kwargs):
        captured.update(kwargs)
        yield "done", {}

    monkeypatch.setattr(
        routes.analysis_service,
        "run_stream_events",
        fake_run_stream_events,
    )

    client.post(
        "/api/v1/analyze/stream",
        json={
            "question": "利润为什么下降",
            "max_steps": 3,
            "use_indicator_rag": False,
            "use_schema_linking": False,
        },
    )

    assert captured["max_steps"] == 3
    assert captured["chatbi_run_options"]["use_indicator_rag"] is False
    assert captured["chatbi_run_options"]["use_schema_linking"] is False
    # 未显式传入的选项回落到配置默认值
    assert "use_indicator_knowledge" in captured["chatbi_run_options"]


def test_analyze_stream_serializes_decimal_rows(client, monkeypatch):
    from decimal import Decimal

    def fake_run_stream_events(**kwargs):
        yield "step_done", {
            "step_id": "step_1",
            "rows": [{"region": "欧洲", "amt": Decimal("123.45")}],
        }
        yield "done", {}

    monkeypatch.setattr(
        routes.analysis_service,
        "run_stream_events",
        fake_run_stream_events,
    )

    response = client.post(
        "/api/v1/analyze/stream",
        json={"question": "利润为什么下降"},
    )

    assert response.status_code == 200
    row = dict(_parse_sse(response.text))["step_done"]["rows"][0]
    assert row["amt"] == 123.45


def test_analyze_stream_rejects_blank_question(client):
    response = client.post("/api/v1/analyze/stream", json={"question": ""})

    assert response.status_code == 422
    body = response.json()
    assert body["error_type"] == "request_validation"


def test_analyze_stream_rejects_too_many_steps(client):
    response = client.post(
        "/api/v1/analyze/stream",
        json={"question": "利润为什么下降", "max_steps": 99},
    )

    assert response.status_code == 422


def test_read_root_lists_analyze_endpoint(client):
    body = client.get("/").json()

    assert body["analyze_stream"] == "/api/v1/analyze/stream"
