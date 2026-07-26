"""Trace write layer — single entry point for all trace data.

Both SDK ingest and Proxy recorder write through this module to ensure
consistent AgentRun + AgentNodeTrace creation.
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.modules.observability.models import AgentRun, AgentNodeTrace

logger = logging.getLogger(__name__)

# ── 各模型定价（美元/千 Token），(input_price, output_price) ────────
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o": (0.0025, 0.01),
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4-turbo": (0.01, 0.03),
    "gpt-3.5-turbo": (0.0005, 0.0015),
    "claude-sonnet-4-6": (0.003, 0.015),
    "claude-opus-4-7": (0.015, 0.075),
    "claude-haiku-4-5": (0.0008, 0.004),
    "deepseek-v4-pro": (0.0014, 0.0056),
}


def _estimate_cost(model: str, token_usage: dict) -> float:
    """根据模型名称和 token 用量估算费用（美元）。"""
    # 兼容不同 LLM 厂商的字段名差异（prompt_tokens / input_tokens）
    prompt_tokens = token_usage.get("prompt_tokens", 0) or token_usage.get("input_tokens", 0)
    completion_tokens = token_usage.get("completion_tokens", 0) or token_usage.get("output_tokens", 0)
    prices = _MODEL_PRICING.get(model)
    if not prices or (prompt_tokens + completion_tokens) == 0:
        return 0.0
    input_price, output_price = prices
    return (prompt_tokens / 1000) * input_price + (completion_tokens / 1000) * output_price


async def create_run(
    db: AsyncSession,
    trace_id: str,
    project_id: int | None = None,
    agent_name: str = "trace",
    input_data: dict | None = None,
) -> AgentRun:
    """Create an AgentRun for a new trace. Caller must commit."""
    # 确保 project_id 有效，避免孤立数据
    if project_id is not None:
        from backend.modules.models.project import Project
        exists = (await db.execute(select(Project.id).where(Project.id == project_id))).scalar_one_or_none()
        if exists is None:
            raise ValueError(f"Project {project_id} not found")

    run = AgentRun(
        trace_id=trace_id,
        project_id=project_id,
        agent_name=agent_name,
        status="running",
        input=input_data or {},
        started_at=datetime.now(timezone.utc),
    )
    db.add(run)
    await db.flush()
    return run


async def add_node(
    db: AsyncSession,
    trace_id: str,
    node_name: str,
    node_type: str,
    sequence: int,
    input_data: dict | None = None,
    output_data: dict | None = None,
    duration_ms: int = 0,
    token_usage: dict | None = None,
    status: str = "success",
    parent_node_id: int | None = None,
    model: str | None = None,
    error: str | None = None,
) -> AgentNodeTrace:
    """Add a node to a trace. Caller must commit."""
    node = AgentNodeTrace(
        trace_id=trace_id,
        node_name=node_name,
        node_type=node_type,
        sequence=sequence,
        input=input_data or {},
        output=output_data or {},
        duration_ms=duration_ms,
        token_usage=token_usage,
        status=status,
        parent_node_id=parent_node_id,
        error=error,
    )
    db.add(node)
    await db.flush()
    return node


async def finish_run(
    db: AsyncSession,
    trace_id: str,
    output_data: dict | None = None,
    status: str = "success",
    model: str | None = None,
) -> AgentRun | None:
    """结束一条 trace：汇总各 node 的 token/cost，写入 AgentRun。

    Reads all nodes belonging to trace_id, sums token_usage and cost,
    updates the AgentRun row. Caller must commit.
    """
    run = (await db.execute(select(AgentRun).where(AgentRun.trace_id == trace_id))).scalar_one_or_none()
    if run is None:
        logger.warning("finish_run: no AgentRun for trace_id=%s", trace_id)
        return None

    nodes = (await db.execute(
        select(AgentNodeTrace).where(AgentNodeTrace.trace_id == trace_id)
    )).scalars().all()

    total_tokens = 0
    total_cost = 0.0
    for n in nodes:
        usage = n.token_usage or {}
        total_tokens += usage.get("total_tokens", 0)
        node_model = model or (usage.get("model", ""))
        total_cost += _estimate_cost(node_model, usage)

    run.status = status
    run.output = output_data or {}
    run.finished_at = datetime.now(timezone.utc)
    if run.started_at:
        run.duration_ms = int((run.finished_at - run.started_at).total_seconds() * 1000)
    run.total_tokens = total_tokens
    run.total_cost = Decimal(str(round(total_cost, 8)))
    await db.flush()
    return run
