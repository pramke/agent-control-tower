"""测试夹具与工具函数 — 数据库初始化、用户 Token 生成、项目预置。"""
import os
import sys
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# 在所有导入之前设置环境变量，确保数据库 URL 和密钥在模块加载时生效
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test.db"
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production-use"

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from backend.main import app
from backend.core.database import engine, async_session
from backend.core.security import hash_password, create_access_token
from backend.modules.models.base import Base
from backend.modules.models.user import User


@pytest_asyncio.fixture(loop_scope="function")
async def client():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _create_user(username: str, password: str, role: str) -> str:
    """直接插入用户到数据库并生成 JWT，绕过登录 API 的速率限制。"""
    async with async_session() as db:
        user = User(username=username, password_hash=hash_password(password), role=role)
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return create_access_token({"sub": str(user.id), "role": user.role, "username": user.username})


@pytest_asyncio.fixture(loop_scope="function")
async def admin_token(client):
    return await _create_user("admin_test", "admin123", "admin")


@pytest_asyncio.fixture(loop_scope="function")
async def user_token(client):
    return await _create_user("user_test", "user123", "user")


# 预置一个测试项目，供依赖该 fixture 的测试用例复用
@pytest_asyncio.fixture(loop_scope="function")
async def project_id(client, admin_token):
    resp = await client.post("/api/projects", json={
        "name": "test-project",
        "base_url": "https://api.test.com/anthropic",
        "api_key_upstream": "sk-test",
    }, headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200
    return resp.json()["id"]
