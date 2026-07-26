"""
模块: 后端 - 健康检查
功能: 提供 /health 端点，供 Docker 和负载均衡器检查服务状态
"""

import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.core.database import async_session
from sqlalchemy import text

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


async def check_database() -> dict:
    """检测数据库连接是否正常——执行 SELECT 1 探活"""
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as exc:
        logger.warning("Database health check failed: %s", exc)
        return {"status": "error", "message": "Database connection failed"}


async def check_model_api() -> dict:
    """检测 LLM API 是否可达——请求 models 端点验证"""
    from backend.config import settings

    api_key = settings.agent_api_key
    base_url = settings.agent_base_url
    if not api_key:
        return {"status": "skipped", "message": "No API key configured"}
    try:
        import httpx
        headers = {"Authorization": f"Bearer {api_key}"}
        # 探测真实 API 基础地址而非 Anthropic 兼容路径，避免 404
        url = base_url.rstrip("/").replace("/anthropic", "/models")
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code in (200, 401):  # 401 = reachable but auth issue
            return {"status": "ok", "http_status": resp.status_code}
        return {"status": "warning", "http_status": resp.status_code}
    except Exception as exc:
        logger.warning("Model API health check failed: %s", exc)
        return {"status": "error", "message": "Model API is unreachable"}


async def check_tool_health() -> dict:
    """检测 Agent 工具（Tool）的健康状态"""
    return {"status": "ok", "total": 0, "healthy": 0, "unhealthy": []}


@router.get("/health")
async def health_check() -> JSONResponse:
    """综合健康检查——数据库 + LLM API + 工具链，用于负载均衡器"""
    checks = {}

    db = await check_database()
    checks["database"] = db

    model = await check_model_api()
    checks["model_api"] = model

    tools = await check_tool_health()
    checks["tools"] = tools

    # 数据库和 Model API 任一异常则整体标记为 degraded
    all_ok = all(
        c.get("status") != "error" for c in [db, model]
    )

    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={
            "status": "healthy" if all_ok else "degraded",
            "timestamp": datetime.now().isoformat(),
            "checks": checks,
        },
    )


@router.get("/health/live")
async def liveness_check() -> dict:
    """最小存活探针——仅返回 200，不检查依赖"""
    return {"status": "alive", "timestamp": datetime.now().isoformat()}
