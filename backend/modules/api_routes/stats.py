"""
模块: 后端 - 统计数据路由
功能: 提供 Token 用量、费用、重复请求等统计接口
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.security import get_current_user
from backend.modules.models.api_call import ApiCall

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/{project_id}/summary")
async def get_summary(
    project_id: int,
    days: int = Query(default=7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    _user = Depends(get_current_user),
):
    """获取项目用量总览 — 总调用次数、各类 Token、费用、缓存命中率、平均延迟"""
    since = datetime.now() - timedelta(days=days)

    # 一次性聚合查询：计数、Token 汇总、费用、平均延迟
    result = await db.execute(
        select(
            func.count(ApiCall.id),
            func.coalesce(func.sum(ApiCall.input_tokens), 0),
            func.coalesce(func.sum(ApiCall.output_tokens), 0),
            func.coalesce(func.sum(ApiCall.cache_read_tokens), 0),
            func.coalesce(func.sum(ApiCall.cache_creation_tokens), 0),
            func.coalesce(func.sum(ApiCall.cost), 0),
            func.coalesce(func.avg(ApiCall.latency_ms), 0),
        ).where(
            and_(ApiCall.project_id == project_id, ApiCall.timestamp >= since)
        )
    )
    cnt, inp, out, cache_read, cache_create, cost, avg_latency = result.one()

    # 总输入 = 常规输入 + 缓存读取 + 缓存创建（缓存 token 本质上也是输入侧流量）
    total_input = inp + cache_read + cache_create
    # 缓存命中率 = 缓存读取 / 总输入（反映 prompt cache 利用率）
    cache_hit_rate = round(cache_read / total_input * 100, 1) if total_input > 0 else 0.0

    return {
        "total_calls": cnt,
        "total_input_tokens": inp,
        "total_output_tokens": out,
        "total_cache_read_tokens": cache_read,
        "total_cache_creation_tokens": cache_create,
        "cache_hit_rate": cache_hit_rate,
        "total_cost": round(cost, 6),
        "avg_latency_ms": round(avg_latency, 1),
        "period_days": days,
    }


@router.get("/{project_id}/daily")
async def get_daily_breakdown(
    project_id: int,
    days: int = Query(default=7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    _user = Depends(get_current_user),
):
    """获取每日调用量趋势 — 按天分组统计调用次数和费用"""
    since = datetime.now() - timedelta(days=days)

    result = await db.execute(
        select(
            func.date(ApiCall.timestamp).label("day"),
            func.count(ApiCall.id),
            func.coalesce(func.sum(ApiCall.cost), 0),
        )
        .where(and_(ApiCall.project_id == project_id, ApiCall.timestamp >= since))
        .group_by(func.date(ApiCall.timestamp))
        .order_by("day")
    )
    rows = result.all()
    return [{"date": str(r.day), "calls": r[1], "cost": round(r[2], 6)} for r in rows]


@router.get("/{project_id}/by_model")
async def get_by_model(
    project_id: int,
    days: int = Query(default=7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    _user = Depends(get_current_user),
):
    """获取按模型分组的用量统计 — 各模型的调用次数和费用"""
    since = datetime.now() - timedelta(days=days)

    result = await db.execute(
        select(
            ApiCall.model,
            func.count(ApiCall.id),
            func.coalesce(func.sum(ApiCall.input_tokens + ApiCall.output_tokens), 0),
            func.coalesce(func.sum(ApiCall.cost), 0),
        )
        .where(and_(ApiCall.project_id == project_id, ApiCall.timestamp >= since))
        .group_by(ApiCall.model)
    )
    rows = result.all()
    return [{"model": r.model, "calls": r[1], "total_tokens": r[2], "total_cost": round(r[3], 6)} for r in rows]


@router.get("/{project_id}/duplicates")
async def get_duplicate_requests(
    project_id: int,
    days: int = Query(default=7, ge=1, le=90),
    min_count: int = Query(default=3, ge=2),
    db: AsyncSession = Depends(get_db),
    _user = Depends(get_current_user),
):
    """检测重复请求 — 按请求哈希分组统计，找出频繁重复的冗余调用"""
    since = datetime.now() - timedelta(days=days)

    # 子查询：按 request_hash 分组，统计出现次数和总费用
    sub = (
        select(
            ApiCall.request_hash,
            func.count(ApiCall.id).label("cnt"),
            func.coalesce(func.sum(ApiCall.cost), 0).label("total_cost"),
            func.min(ApiCall.prompt_preview).label("preview"),
        )
        .where(and_(ApiCall.project_id == project_id, ApiCall.timestamp >= since))
        .group_by(ApiCall.request_hash)
        .having(func.count(ApiCall.id) >= min_count)  # 仅保留超过重复阈值的请求
        .subquery()
    )

    result = await db.execute(
        select(sub).order_by(sub.c.cnt.desc()).limit(20)
    )
    rows = result.all()
    return [
        {
            "hash": r.request_hash[:12] + "...",
            "count": r.cnt,
            "total_cost": round(r.total_cost, 6),
            "preview": (r.preview or "")[:100],
        }
        for r in rows
    ]
