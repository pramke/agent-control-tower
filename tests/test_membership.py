"""测试角色权限与项目访问控制。"""

import pytest


@pytest.mark.asyncio
async def test_admin_can_access_project(client, admin_token, project_id):
    """Admin can view project details."""
    resp = await client.get(f"/api/projects/{project_id}/full", headers={
        "Authorization": f"Bearer {admin_token}",
    })
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_user_can_see_all_projects(client, user_token, project_id):
    """All users can see projects."""
    resp = await client.get(f"/api/projects/{project_id}/full", headers={
        "Authorization": f"Bearer {user_token}",
    })
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_all_roles_see_same_project_list(client, admin_token, user_token):
    """Admin and member see the same project list."""
    resp = await client.post("/api/projects", json={
        "name": "shared-proj", "base_url": "https://api.x.com/anthropic", "api_key_upstream": "sk-x",
    }, headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200
    new_id = resp.json()["id"]

    admin_resp = await client.get("/api/projects", headers={"Authorization": f"Bearer {admin_token}"})
    admin_ids = [p["id"] for p in admin_resp.json()]
    assert new_id in admin_ids

    member_resp = await client.get("/api/projects", headers={"Authorization": f"Bearer {user_token}"})
    member_ids = [p["id"] for p in member_resp.json()]
    assert new_id in member_ids


@pytest.mark.asyncio
async def test_user_can_create_project(client, user_token):
    """All users can create projects."""
    resp = await client.post("/api/projects", json={
        "name": "user-proj", "base_url": "https://api.x.com/anthropic", "api_key_upstream": "sk-x",
    }, headers={"Authorization": f"Bearer {user_token}"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_user_can_delete_project(client, user_token, project_id):
    """All users can delete projects."""
    resp = await client.delete(f"/api/projects/{project_id}", headers={
        "Authorization": f"Bearer {user_token}",
    })
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_stats_requires_auth(client, project_id):
    resp = await client.get(f"/api/stats/{project_id}/summary")
    assert resp.status_code == 401
