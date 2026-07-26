"""Trace recording: persists AgentTrace / NodeTrace data to PostgreSQL.

The pydantic models mirror the wire format returned by the trace API; the
TraceRecorder is used by the orchestration runtime to persist progress while
a run executes in a background task (it opens its own DB sessions).

TraceRecorder 的生命周期：
start() → record_node() ... record_node() ... → set_status() → finish()
"""

import logging
from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import select, update

from backend.core.database import async_session
from backend.modules.observability.logger import log_step, suggest_for_error
from backend.modules.observability.models import AgentNodeTrace, AgentRun

logger = logging.getLogger(__name__)


class NodeTrace(BaseModel):
    """单个 Agent 节点的追踪数据：包括输入、输出、耗时、Token 用量等。"""
    id: int | None = None
    parent_node_id: int | None = None
    node_name: str
    node_type: str  # llm_call, tool_execution, conditional, human_review
    sequence: int = 0
    input: dict = {}
    output: dict = {}
    llm_thought: str | None = None  # What the LLM was "thinking" at this step
    error: str | None = None
    suggestion: str | None = None
    duration_ms: int = 0
    token_usage: dict = {}
    status: str = "success"  # success, failed, skipped


class AgentTrace(BaseModel):
    """完整的一次 Agent 运行追踪：元数据 + 节点列表。"""
    trace_id: str
    project_id: int | None = None
    agent_name: str
    status: str  # running, success, failed, awaiting_human
    start_time: datetime
    end_time: datetime | None = None
    total_duration_ms: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    input: dict = {}
    output: dict = {}
    nodes: list[NodeTrace] = []


def node_row_to_model(row: AgentNodeTrace) -> NodeTrace:
    """将 DB 中的 AgentNodeTrace 记录转为 Pydantic NodeTrace。"""
    return NodeTrace(
        id=row.id,
        parent_node_id=row.parent_node_id,
        node_name=row.node_name,
        node_type=row.node_type,
        sequence=row.sequence,
        input=row.input or {},
        output=row.output or {},
        llm_thought=row.llm_thought,
        error=row.error,
        suggestion=row.suggestion,
        duration_ms=row.duration_ms,
        token_usage=row.token_usage or {},
        status=row.status,
    )


def run_row_to_model(row: AgentRun, nodes: list[AgentNodeTrace] | None = None) -> AgentTrace:
    """将 DB 中的 AgentRun + AgentNodeTrace 转为 Pydantic AgentTrace。"""
    return AgentTrace(
        trace_id=str(row.trace_id),
        project_id=row.project_id,
        agent_name=row.agent_name,
        status=row.status,
        start_time=row.started_at,
        end_time=row.finished_at,
        total_duration_ms=row.duration_ms or 0,
        total_tokens=row.total_tokens or 0,
        total_cost=float(row.total_cost or 0),
        input=row.input or {},
        output=row.output or {},
        nodes=[node_row_to_model(n) for n in (nodes or [])],
    )


class TraceRecorder:
    """Persists one agent run's trace while it executes.

    由 orchestration 运行时在后台任务中调用，每次打开独立的 DB session。
    """

    def __init__(
        self,
        trace_id: str,
        agent_name: str,
        project_id: int | None = None,
        config_id: int | None = None,
    ) -> None:
        self.trace_id = trace_id
        self.agent_name = agent_name
        self.project_id = project_id
        self.config_id = config_id
        self.sequence = 0
        self.started_at: datetime | None = None

    async def start(self, run_input: dict) -> None:
        """记录 Agent 运行的开始。"""
        self.started_at = datetime.now()
        async with async_session() as session:
            session.add(
                AgentRun(
                    trace_id=self.trace_id,
                    config_id=self.config_id,
                    project_id=self.project_id,
                    agent_name=self.agent_name,
                    status="running",
                    input=run_input,
                    started_at=self.started_at,
                )
            )
            await session.commit()
        await log_step(
            self.trace_id,
            f"Agent run started: {self.agent_name}",
            project_id=self.project_id,
            context={"input": run_input},
        )

    async def record_node(self, node: NodeTrace) -> NodeTrace:
        """记录一次节点执行的结果。"""
        self.sequence += 1
        node.sequence = self.sequence
        # 自动生成修复建议，方便前端展示排查方向
        if node.error and not node.suggestion:
            node.suggestion = suggest_for_error(node.error)
        async with async_session() as session:
            session.add(
                AgentNodeTrace(
                    trace_id=self.trace_id,
                    node_name=node.node_name,
                    node_type=node.node_type,
                    sequence=node.sequence,
                    input=node.input,
                    output=node.output,
                    llm_thought=node.llm_thought,
                    error=node.error,
                    suggestion=node.suggestion,
                    duration_ms=node.duration_ms,
                    token_usage=node.token_usage,
                    status=node.status,
                )
            )
            await session.commit()
        await log_step(
            self.trace_id,
            f"Node '{node.node_name}' ({node.node_type}) {node.status} in {node.duration_ms}ms"
            + (f" — error: {node.error}" if node.error else ""),
            level="ERROR" if node.status == "failed" else "INFO",
            project_id=self.project_id,
            node_name=node.node_name,
            context={"sequence": node.sequence, "token_usage": node.token_usage},
        )
        return node

    async def set_status(self, status: str) -> None:
        """更新 Agent 运行的当前状态（不完成运行）。"""
        async with async_session() as session:
            await session.execute(
                update(AgentRun).where(AgentRun.trace_id == self.trace_id).values(status=status)
            )
            await session.commit()

    async def finish(
        self,
        status: str,
        output: dict,
        total_tokens: int = 0,
        total_cost: float = 0.0,
    ) -> None:
        """记录 Agent 运行的结束，更新汇总数据。"""
        finished = datetime.now()
        # 基于 start() 记录的时间戳计算整体耗时，避免依赖外部传入
        duration_ms = (
            int((finished - self.started_at).total_seconds() * 1000) if self.started_at else 0
        )
        async with async_session() as session:
            await session.execute(
                update(AgentRun)
                .where(AgentRun.trace_id == self.trace_id)
                .values(
                    status=status,
                    output=output,
                    finished_at=finished,
                    duration_ms=duration_ms,
                    total_tokens=total_tokens,
                    total_cost=total_cost,
                )
            )
            await session.commit()
        await log_step(
            self.trace_id,
            f"Agent run finished: status={status}, duration={duration_ms}ms, tokens={total_tokens}",
            level="ERROR" if status == "failed" else "INFO",
            project_id=self.project_id,
            context={"output": output},
        )


async def load_trace(trace_id: str) -> AgentTrace | None:
    """从 DB 加载完整的追踪记录（含节点数据）。"""
    async with async_session() as session:
        run = (
            await session.execute(select(AgentRun).where(AgentRun.trace_id == trace_id))
        ).scalar_one_or_none()
        if run is None:
            return None
        nodes = (
            (
                await session.execute(
                    select(AgentNodeTrace)
                    .where(AgentNodeTrace.trace_id == trace_id)
                    .order_by(AgentNodeTrace.sequence)
                )
            )
            .scalars()
            .all()
        )
        return run_row_to_model(run, list(nodes))
