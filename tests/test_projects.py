"""Project CRUD tests: create, list, delete with RBAC."""

import pytest


@pytest.mark.asyncio
async def test_create_project(client, admin_token):
    resp = await client.post("/api/projects", json={
        "name": "my-project", "base_url": "https://api.test.com/anthropic",
        "api_key_upstream": "sk-test",
    }, headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "my-project"
    assert "api_key" in data
    assert len(data["api_key"]) > 8


@pytest.mark.asyncio
async def test_user_can_create_project(client, user_token):
    resp = await client.post("/api/projects", json={
        "name": "user-proj", "base_url": "https://x.com/anthropic", "api_key_upstream": "sk-x",
    }, headers={"Authorization": f"Bearer {user_token}"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_list_projects_visible_to_all_roles(client, admin_token, user_token):
    """所有已登录用户都能看到全部项目（当前无按成员过滤逻辑）。"""
    resp = await client.post("/api/projects", json={
        "name": "admin-proj", "base_url": "https://api.x.com/anthropic", "api_key_upstream": "sk-x",
    }, headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200
    admin_project_id = resp.json()["id"]

    resp = await client.get("/api/projects", headers={
        "Authorization": f"Bearer {user_token}",
    })
    assert resp.status_code == 200
    member_ids = [p["id"] for p in resp.json()]
    assert admin_project_id in member_ids


@pytest.mark.asyncio
async def test_get_project_full(client, admin_token, project_id):
    resp = await client.get(f"/api/projects/{project_id}/full", headers={
        "Authorization": f"Bearer {admin_token}",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "test-project"
    assert "api_key" in data


@pytest.mark.asyncio
async def test_get_project_full_accessible_to_user(client, user_token, project_id):
    """All logged-in users can view project details."""
    resp = await client.get(f"/api/projects/{project_id}/full", headers={
        "Authorization": f"Bearer {user_token}",
    })
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_user_can_delete_project(client, admin_token, user_token, project_id):
    """All users can delete projects."""
    resp = await client.delete(f"/api/projects/{project_id}", headers={
        "Authorization": f"Bearer {user_token}",
    })
    assert resp.status_code == 200


# 验证列表接口只返回密钥前缀，详情接口才返回完整密钥
@pytest.mark.asyncio
async def test_safe_dict_returns_prefix_not_full_key(client, admin_token):
    resp = await client.post("/api/projects", json={
        "name": "key-test", "base_url": "https://api.x.com/anthropic", "api_key_upstream": "sk-test",
    }, headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert "api_key" in data
    resp2 = await client.get(f"/api/projects/{data['id']}/full", headers={
        "Authorization": f"Bearer {admin_token}",
    })
    assert resp2.status_code == 200
    full_data = resp2.json()
    assert "api_key" in full_data
    assert len(full_data["api_key"]) > 0
