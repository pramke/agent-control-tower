"""
模块: 后端 - API调用查询路由
功能: 查询历史 API 调用记录、用量统计
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.security import get_current_user
from backend.modules.models.api_call import ApiCall

router = APIRouter(prefix="/api/calls", tags=["calls"])


@router.get("")
async def list_calls(
    project_id: int = Query(...),
    days: int = Query(default=7, ge=1, le=90),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _user = Depends(get_current_user),
):
    """分页查询指定项目的 API 调用记录，按时间倒序排列"""
    since = datetime.now() - timedelta(days=days)

    # 基础查询条件：项目 ID + 时间范围
    base = select(ApiCall).where(
        and_(ApiCall.project_id == project_id, ApiCall.timestamp >= since)
    )

    # 查询总条数用于前端分页 — 通过 subquery 复用基础过滤条件，避免重复定义 where 子句
    count_result = await db.execute(
        select(func.count()).select_from(base.subquery())
    )
    total = count_result.scalar() or 0

    # 分页取数，按时间倒序
    result = await db.execute(
        base.order_by(desc(ApiCall.timestamp))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    calls = result.scalars().all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": c.id,
                "model": c.model,
                "endpoint": c.endpoint,
                "input_tokens": c.input_tokens,
                "output_tokens": c.output_tokens,
                "cache_read_tokens": c.cache_read_tokens,
                "cache_creation_tokens": c.cache_creation_tokens,
                "latency_ms": round(c.latency_ms, 1),
                "status_code": c.status_code,
                "cost": round(c.cost, 6),
                "request_hash": c.request_hash[:16] + "..." if c.request_hash else "",
                "prompt_preview": (c.prompt_preview or "")[:100],
                "timestamp": c.timestamp.isoformat() if c.timestamp else "",
            }
            for c in calls
        ],
    }
