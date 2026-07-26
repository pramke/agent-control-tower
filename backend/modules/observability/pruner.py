"""Prune old traces to prevent table bloat from proxy auto-tracing."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from backend.core.database import async_session
from backend.modules.observability.models import AgentRun, AgentNodeTrace

logger = logging.getLogger(__name__)

_RETENTION_DAYS = 30  # Trace 保留 30 天，过期后由 prune loop 清理
_PRUNE_INTERVAL_SECONDS = 3600  # 每小时检查一次，避免频繁 I/O 影响业务

_task: asyncio.Task | None = None


async def _prune_loop():
    """Background loop: delete expired AgentRuns and their nodes."""
    while True:
        await asyncio.sleep(_PRUNE_INTERVAL_SECONDS)
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=_RETENTION_DAYS)

            async with async_session() as db:
                # 先删子节点（AgentNodeTrace）再删父记录（AgentRun），保证外键约束
                expired = (await db.execute(
                    select(AgentRun.id).where(AgentRun.started_at < cutoff)
                )).scalars().all()

                if not expired:
                    continue

                expired_ids = list(expired)

                # Delete nodes belonging to expired runs
                node_result = await db.execute(
                    delete(AgentNodeTrace).where(AgentNodeTrace.trace_id.in_(
                        select(AgentRun.trace_id).where(AgentRun.id.in_(expired_ids))
                    ))
                )
                # Delete the runs themselves
                run_result = await db.execute(
                    delete(AgentRun).where(AgentRun.id.in_(expired_ids))
                )
                await db.commit()

                total = node_result.rowcount + run_result.rowcount
                if total > 0:
                    logger.info("Pruned %d old trace records (cutoff: %s)", total, cutoff.date().isoformat())
        except Exception:
            logger.warning("Trace pruner error", exc_info=True)


def start_pruner():
    global _task
    if _task is not None:
        return
    _task = asyncio.ensure_future(_prune_loop())
    logger.info("Trace pruner started (retention: %s days, interval: %ss)", _RETENTION_DAYS, _PRUNE_INTERVAL_SECONDS)


async def stop_pruner():
    global _task
    if _task is not None:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None
    logger.info("Trace pruner stopped")
