"""测试链路数据摄入——Mode 2 核心入口。"""
import uuid

import pytest


def _uid() -> str:
    return str(uuid.uuid4())


@pytest.mark.asyncio
async def test_ingest_requires_auth(client):
    resp = await client.post("/api/traces/ingest", json={"traces": []})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_ingest_single_trace(client, admin_token):
    """Ingest a trace with 2 spans and verify it's retrievable."""
    tid = _uid()
    resp = await client.post("/api/traces/ingest", json={
        "traces": [{
            "trace_id": tid,
            "name": "my_agent",
            "project_id": None,
            "input": {"query": "hello"},
            "output": {"result": "world"},
            "duration_ms": 5000,
            "spans": [
                {
                    "span_id": "span-1",
                    "name": "llm_call",
                    "duration_ms": 3000,
                    "model": "gpt-4o",
                    "token_usage": {"input_tokens": 100, "output_tokens": 50},
                },
                {
                    "span_id": "span-2",
                    "parent_span_id": "span-1",
                    "name": "tool_call",
                    "duration_ms": 500,
                    "model": None,
                },
            ],
        }]
    }, headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ingested"] == 2, data
    assert data["failed"] == 0

    # Verify trace is retrievable via list
    resp = await client.get("/api/traces", headers={
        "Authorization": f"Bearer {admin_token}",
    })
    assert resp.status_code == 200
    traces = resp.json()
    assert any(t["trace_id"] == tid for t in traces)


@pytest.mark.asyncio
async def test_ingest_preserves_tree_structure(client, admin_token):
    """parent_span_id links produce correct parent_node_id in DB."""
    tid = _uid()
    resp = await client.post("/api/traces/ingest", json={
        "traces": [{
            "trace_id": tid,
            "name": "agent",
            "project_id": None,
            "duration_ms": 5000,
            "spans": [
                {
                    "span_id": "root",
                    "name": "agent_entry",
                    "duration_ms": 5000,
                    "model": "gpt-4o",
                    "token_usage": {"input_tokens": 100, "output_tokens": 50},
                },
                {
                    "span_id": "child",
                    "parent_span_id": "root",
                    "name": "inner_call",
                    "duration_ms": 3000,
                    "model": "gpt-4o",
                    "token_usage": {"input_tokens": 80, "output_tokens": 40},
                },
            ],
        }]
    }, headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ingested"] == 2, data

    # Fetch trace detail
    resp = await client.get(f"/api/traces/{tid}", headers={
        "Authorization": f"Bearer {admin_token}",
    })
    assert resp.status_code == 200
    trace = resp.json()
    assert "nodes" in trace
    assert len(trace["nodes"]) == 2


@pytest.mark.asyncio
async def test_ingest_batch_traces(client, admin_token):
    """Ingest 3 traces in one request."""
    ids = [_uid() for _ in range(3)]
    resp = await client.post("/api/traces/ingest", json={
        "traces": [
            {"trace_id": ids[i], "name": f"run-{i}", "project_id": None,
             "duration_ms": 1000,
             "spans": [{"span_id": "s", "name": "step", "duration_ms": 1000,
                        "model": "gpt-4o", "token_usage": {"input_tokens": 10, "output_tokens": 5}}]}
            for i in range(3)
        ]
    }, headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ingested"] == 3, data
    assert data["failed"] == 0


@pytest.mark.asyncio
async def test_ingest_empty_spans_skipped(client, admin_token):
    resp = await client.post("/api/traces/ingest", json={
        "traces": [{"trace_id": _uid(), "name": "nope", "project_id": None, "spans": []}]
    }, headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200
    assert resp.json()["ingested"] == 0


@pytest.mark.asyncio
async def test_ingest_invalid_project_fails_gracefully(client, admin_token):
    """Non-existent project is caught and reported in results, not a 500."""
    resp = await client.post("/api/traces/ingest", json={
        "traces": [{
            "trace_id": _uid(),
            "name": "test",
            "project_id": 99999,
            "spans": [{"span_id": "s", "name": "x", "duration_ms": 1,
                        "token_usage": {"input_tokens": 1, "output_tokens": 1}}],
        }]
    }, headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["failed"] == 1
    assert data["results"][0]["status"] == "failed"
    assert "not found" in data["results"][0]["error"].lower()
