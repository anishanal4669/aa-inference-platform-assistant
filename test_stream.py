import json

import httpx
import pytest

from app.main import create_app


def parse_sse(raw: str) -> list[tuple[str, dict]]:
    events = []
    for block in raw.split("\n\n"):
        name, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if name:
            events.append((name, data))
    return events


@pytest.fixture
def client():
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_stream_emits_start_deltas_usage_done(client):
    async with client as c:
        res = await c.post(
            "/v1/stream",
            json={"model": "swift-8b", "input": "hello there", "max_tokens": 20},
        )
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/event-stream")
        events = parse_sse(res.text)

    names = [n for n, _ in events]
    assert names[0] == "start"
    assert names[-1] == "done"
    assert "delta" in names

    usage = next(d for n, d in events if n == "usage")
    assert usage["output_tokens"] > 0
    assert usage["ttft_ms"] > 0
    assert usage["cost_usd"] >= 0
    assert usage["finish_reason"] == "stop"


async def test_max_tokens_is_respected(client):
    async with client as c:
        res = await c.post("/v1/stream", json={"model": "swift-8b", "input": "hi", "max_tokens": 5})
    usage = next(d for n, d in parse_sse(res.text) if n == "usage")
    assert usage["output_tokens"] <= 5


async def test_unknown_model_is_404(client):
    async with client as c:
        res = await c.post("/v1/stream", json={"model": "nope", "input": "hi"})
    assert res.status_code == 404


async def test_missing_input_is_422(client):
    async with client as c:
        res = await c.post("/v1/stream", json={"model": "swift-8b"})
    assert res.status_code == 422


async def test_usage_ledger_accumulates(client):
    async with client as c:
        await c.post("/v1/stream", json={"model": "core-70b", "input": "one", "max_tokens": 10})
        res = await c.get("/v1/usage")
    body = res.json()
    assert body["totals"]["requests"] >= 1
    assert body["recent"][0]["model"] == "core-70b"


async def test_models_catalog(client):
    async with client as c:
        res = await c.get("/v1/models")
    ids = [m["id"] for m in res.json()["data"]]
    assert {"swift-8b", "core-70b", "dense-400b"} <= set(ids)
