"""Auth tests: register, login, token validation, RBAC."""

import pytest


@pytest.mark.asyncio
async def test_register_and_login(client):
    # register
    resp = await client.post("/api/auth/register", json={
        "username": "testuser", "password": "testpass", "role": "admin",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data

    # login with same creds
    resp = await client.post("/api/auth/login", json={
        "username": "testuser", "password": "testpass",
    })
    assert resp.status_code == 200
    assert "access_token" in resp.json()


@pytest.mark.asyncio
async def test_login_invalid_password(client):
    await client.post("/api/auth/register", json={
        "username": "badlogin", "password": "realpass", "role": "admin",
    })
    resp = await client.post("/api/auth/login", json={
        "username": "badlogin", "password": "wrongpass",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_register_duplicate(client):
    """重复用户名应被拒绝。直接调用 _create_user 以绕过注册 API 的速率限制。"""
    from tests.conftest import _create_user
    await _create_user("dup", "pass1", "user")
    resp = await client.post("/api/auth/register", json={
        "username": "dup", "password": "pass2", "role": "user",
    })
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_me_endpoint(client, admin_token):
    resp = await client.get("/api/me", headers={
        "Authorization": f"Bearer {admin_token}",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "admin_test"
    assert data["role"] == "admin"


@pytest.mark.asyncio
async def test_me_unauthorized(client):
    resp = await client.get("/api/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_user_can_create_project(client, user_token):
    resp = await client.post("/api/projects", json={
        "name": "user-proj", "base_url": "https://x.com/anthropic", "api_key_upstream": "sk-x",
    }, headers={"Authorization": f"Bearer {user_token}"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_admin_can_create_project(client, admin_token):
    resp = await client.post("/api/projects", json={
        "name": "proj", "base_url": "https://x.com/anthropic", "api_key_upstream": "sk-x",
    }, headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200
    assert "api_key" in resp.json()
