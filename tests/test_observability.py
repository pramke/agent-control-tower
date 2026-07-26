"""测试可观测性：链路追踪、日志、告警列表与确认。"""

import pytest


@pytest.mark.asyncio
async def test_list_traces(client, admin_token):
    resp = await client.get("/api/traces", headers={
        "Authorization": f"Bearer {admin_token}",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_list_traces_requires_auth(client):
    resp = await client.get("/api/traces")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_trace_not_found(client, admin_token):
    resp = await client.get("/api/traces/nonexistent-id", headers={
        "Authorization": f"Bearer {admin_token}",
    })
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_replay_not_found(client, admin_token):
    resp = await client.get("/api/traces/nonexistent-id/replay", headers={
        "Authorization": f"Bearer {admin_token}",
    })
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_compare_empty_body(client, admin_token):
    resp = await client.post("/api/traces/compare", json={
        "trace_ids": [],
    }, headers={"Authorization": f"Bearer {admin_token}"})
    # empty comparison should return 400 or an empty result
    assert resp.status_code in (200, 400, 422)


@pytest.mark.asyncio
async def test_list_logs(client, admin_token):
    resp = await client.get("/api/logs", headers={
        "Authorization": f"Bearer {admin_token}",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_list_alerts(client, admin_token):
    resp = await client.get("/api/alerts", headers={
        "Authorization": f"Bearer {admin_token}",
    })
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_ack_alert_not_found(client, admin_token):
    resp = await client.post("/api/alerts/99999/ack", headers={
        "Authorization": f"Bearer {admin_token}",
    })
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_ack_alert_by_user(client, user_token):
    resp = await client.post("/api/alerts/1/ack", headers={
        "Authorization": f"Bearer {user_token}",
    })
    assert resp.status_code == 404
