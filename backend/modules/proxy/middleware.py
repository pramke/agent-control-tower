"""代理认证中间件，通过 Bearer Token + API Key 哈希校验项目身份。"""

import logging

from fastapi import Request, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.modules.models.project import Project

logger = logging.getLogger(__name__)


async def authenticate_project(request: Request, db: AsyncSession) -> Project:
    """从请求的 Authorization 头中认证项目身份。

    流程：提取 Bearer Token → 哈希 API Key → 在数据库中查找匹配的项目。
    返回 Project 对象，认证失败则抛出 HTTPException(401)。
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED", "message": "Missing or invalid Authorization header", "details": {}})

    # 先哈希再查库 — 数据库不存明文，仅存哈希
    api_key = auth.removeprefix("Bearer ").strip()
    api_key_hash = Project.hash_key(api_key)

    # 通过哈希值匹配项目
    result = await db.execute(select(Project).where(Project.api_key_hash == api_key_hash))
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED", "message": "Invalid API key", "details": {}})

    return project
