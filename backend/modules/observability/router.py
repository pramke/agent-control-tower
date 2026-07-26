"""Observability API: traces, replay, compare, log search, alerts.

端点：
- GET  /api/traces            — 列出追踪记录
- GET  /api/traces/{id}       — 获取追踪详情（含节点列表）
- GET  /api/traces/{id}/replay — 逐步回放
- POST /api/traces/compare    — 对比两个追踪
- GET  /api/logs              — 日志搜索
- GET  /api/alerts            — 告警列表
- POST /api/alerts/{id}/ack   — 确认告警
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.security import get_current_user
from backend.modules.observability.models import AgentLog, AgentNodeTrace, AgentRun, Alert
from backend.modules.observability.trace import (
    AgentTrace,
    NodeTrace,
    node_row_to_model,
    run_row_to_model,
)

router = APIRouter(prefix="/api", tags=["observability"])


def _not_found(trace_id: str) -> HTTPException:
    """统一 404 响应格式，避免各端点重复定义相同的错误结构。"""
    return HTTPException(
        status_code=404,
        detail={"code": "TRACE_NOT_FOUND", "message": f"Trace {trace_id} not found", "details": {}},
    )


async def _get_run(db: AsyncSession, trace_id: str) -> AgentRun:
    """根据 trace_id 获取 AgentRun，不存在则抛 404。"""
    run = (
        await db.execute(select(AgentRun).where(AgentRun.trace_id == trace_id))
    ).scalar_one_or_none()
    if run is None:
        raise _not_found(trace_id)
    return run


async def _get_nodes(db: AsyncSession, trace_id: str) -> list[AgentNodeTrace]:
    """获取指定 trace 的所有节点记录，按 sequence 排序。"""
    rows = (
        await db.execute(
            select(AgentNodeTrace)
            .where(AgentNodeTrace.trace_id == trace_id)
            .order_by(AgentNodeTrace.sequence)
        )
    ).scalars()
    return list(rows.all())


@router.get("/traces")
async def list_traces(
    project_id: int | None = None,
    status: str | None = None,
    from_time: datetime | None = Query(default=None, alias="from"),
    to_time: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _user = Depends(get_current_user),
) -> list[dict]:
    """列出追踪记录，支持按项目、状态、时间范围过滤。"""
    query = select(AgentRun).order_by(AgentRun.started_at.desc())
    if project_id is not None:
        query = query.where(AgentRun.project_id == project_id)
    if status:
        query = query.where(AgentRun.status == status)
    if from_time:
        query = query.where(AgentRun.started_at >= from_time)
    if to_time:
        query = query.where(AgentRun.started_at <= to_time)
    rows = (await db.execute(query.limit(limit).offset(offset))).scalars().all()
    return [
        {
            "trace_id": str(r.trace_id),
            "project_id": r.project_id,
            "agent_name": r.agent_name,
            "status": r.status,
            "started_at": r.started_at.isoformat(),
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "duration_ms": r.duration_ms,
            "total_tokens": r.total_tokens,
            "total_cost": float(r.total_cost or 0),
            "input": r.input,
        }
        for r in rows
    ]


@router.get("/traces/{trace_id}", response_model=AgentTrace)
async def get_trace(trace_id: str, db: AsyncSession = Depends(get_db), _user = Depends(get_current_user)) -> AgentTrace:
    """获取单个追踪的完整详情（含所有节点数据）。"""
    run = await _get_run(db, trace_id)
    nodes = await _get_nodes(db, trace_id)
    return run_row_to_model(run, nodes)


@router.get("/traces/{trace_id}/replay")
async def replay_trace(trace_id: str, db: AsyncSession = Depends(get_db), _user = Depends(get_current_user)) -> dict:
    """Step-by-step replay: nodes in order with cumulative timeline offsets.

    返回按时间偏移排列的节点列表，用于前端逐步回放。
    """
    run = await _get_run(db, trace_id)
    nodes = await _get_nodes(db, trace_id)
    steps = []
    offset_ms = 0
    for row in nodes:
        node = node_row_to_model(row)
        steps.append(
            {
                "step": node.sequence,
                "offset_ms": offset_ms,
                "node": node.model_dump(),
            }
        )
        offset_ms += node.duration_ms
    return {
        "trace_id": trace_id,
        "agent_name": run.agent_name,
        "status": run.status,
        "total_steps": len(steps),
        "total_duration_ms": run.duration_ms or offset_ms,
        "steps": steps,
    }


class CompareRequest(BaseModel):
    trace_id_a: str
    trace_id_b: str


def _node_diff(a: NodeTrace | None, b: NodeTrace | None) -> list[str]:
    """比较两个节点，返回差异描述列表。

    仅标记显著差异：状态不同、耗偏差 > 50% 且 > 500ms、输出内容不同等。
    """
    reasons: list[str] = []
    if a is None or b is None:
        reasons.append("missing" if a is None else "extra")
        return reasons
    if a.node_name != b.node_name:
        reasons.append(f"node: {a.node_name} vs {b.node_name}")
    if a.status != b.status:
        reasons.append(f"status: {a.status} vs {b.status}")
    if (a.error is None) != (b.error is None):
        reasons.append("error only in " + ("A" if a.error else "B"))
    # 耗时差异需同时满足比例和绝对值条件，避免对小耗时节点的过度敏感
    slower = max(a.duration_ms, b.duration_ms)
    faster = min(a.duration_ms, b.duration_ms)
    if faster > 0 and slower / faster > 1.5 and slower - faster > 500:
        reasons.append(f"duration: {a.duration_ms}ms vs {b.duration_ms}ms")
    if a.output != b.output:
        reasons.append("output differs")
    return reasons


@router.post("/traces/compare")
async def compare_traces(req: CompareRequest, db: AsyncSession = Depends(get_db), _user = Depends(get_current_user)) -> dict:
    """对比两个追踪记录，输出节点级差异和汇总统计。"""
    run_a = await _get_run(db, req.trace_id_a)
    run_b = await _get_run(db, req.trace_id_b)
    nodes_a = [node_row_to_model(n) for n in await _get_nodes(db, req.trace_id_a)]
    nodes_b = [node_row_to_model(n) for n in await _get_nodes(db, req.trace_id_b)]

    # 按序列号逐节点对齐比对，记录首次出现差异的位置
    aligned = []
    first_divergence: int | None = None
    for i in range(max(len(nodes_a), len(nodes_b))):
        a = nodes_a[i] if i < len(nodes_a) else None
        b = nodes_b[i] if i < len(nodes_b) else None
        reasons = _node_diff(a, b)
        if reasons and first_divergence is None:
            first_divergence = i + 1
        aligned.append(
            {
                "sequence": i + 1,
                "a": a.model_dump() if a else None,
                "b": b.model_dump() if b else None,
                "different": bool(reasons),
                "reasons": reasons,
            }
        )

    summary = {
        "status": {"a": run_a.status, "b": run_b.status, "different": run_a.status != run_b.status},
        "duration_ms": {
            "a": run_a.duration_ms or 0,
            "b": run_b.duration_ms or 0,
            "delta": (run_b.duration_ms or 0) - (run_a.duration_ms or 0),
        },
        "total_tokens": {
            "a": run_a.total_tokens,
            "b": run_b.total_tokens,
            "delta": run_b.total_tokens - run_a.total_tokens,
        },
        "total_cost": {
            "a": float(run_a.total_cost or 0),
            "b": float(run_b.total_cost or 0),
        },
        "node_count": {"a": len(nodes_a), "b": len(nodes_b)},
        "first_divergence_step": first_divergence,
        "differing_steps": sum(1 for row in aligned if row["different"]),
    }
    return {
        "a": run_row_to_model(run_a).model_dump(exclude={"nodes"}),
        "b": run_row_to_model(run_b).model_dump(exclude={"nodes"}),
        "summary": summary,
        "aligned": aligned,
    }


@router.get("/logs")
async def search_logs(
    project_id: int | None = None,
    level: str | None = None,
    trace_id: str | None = None,
    q: str | None = None,
    from_time: datetime | None = Query(default=None, alias="from"),
    to_time: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _user = Depends(get_current_user),
) -> list[dict]:
    """搜索日志记录，支持按项目、级别、trace、关键词、时间范围过滤。"""
    query = select(AgentLog).order_by(AgentLog.created_at.desc())
    if project_id is not None:
        query = query.where(AgentLog.project_id == project_id)
    if level:
        query = query.where(AgentLog.level == level.upper())
    if trace_id:
        query = query.where(AgentLog.trace_id == trace_id)
    if q:
        query = query.where(AgentLog.message.ilike(f"%{q}%"))
    if from_time:
        query = query.where(AgentLog.created_at >= from_time)
    if to_time:
        query = query.where(AgentLog.created_at <= to_time)
    rows = (await db.execute(query.limit(limit).offset(offset))).scalars().all()
    return [
        {
            "id": r.id,
            "project_id": r.project_id,
            "trace_id": str(r.trace_id) if r.trace_id else None,
            "level": r.level,
            "node_name": r.node_name,
            "message": r.message,
            "context": r.context,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/alerts")
async def list_alerts(
    project_id: int | None = None,
    acknowledged: bool | None = None,
    limit: int = Query(default=50, le=200),
    db: AsyncSession = Depends(get_db),
    _user = Depends(get_current_user),
) -> list[dict]:
    """列出告警记录，支持按项目和已确认状态过滤。"""
    query = select(Alert).order_by(Alert.created_at.desc())
    if project_id is not None:
        query = query.where(Alert.project_id == project_id)
    if acknowledged is not None:
        query = query.where(Alert.acknowledged == acknowledged)
    rows = (await db.execute(query.limit(limit))).scalars().all()
    return [
        {
            "id": r.id,
            "project_id": r.project_id,
            "trace_id": str(r.trace_id) if r.trace_id else None,
            "level": r.level,
            "category": r.category,
            "message": r.message,
            "suggestion": r.suggestion,
            "acknowledged": r.acknowledged,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.post("/alerts/{alert_id}/ack")
async def acknowledge_alert(alert_id: int, db: AsyncSession = Depends(get_db), _user = Depends(get_current_user)) -> dict:
    """确认告警（标记为已处理）。"""
    alert = await db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "ALERT_NOT_FOUND", "message": f"Alert {alert_id} not found", "details": {}},
        )
    alert.acknowledged = True
    await db.commit()
    return {"ok": True}
