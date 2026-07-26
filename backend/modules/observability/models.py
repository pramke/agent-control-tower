"""SQLAlchemy models for agent orchestration + observability (Phase 2).

包含以下模型：
- AgentConfig:   Agent 配置文件（模型、工具、系统提示等）
- AgentRun:      Agent 运行记录（状态、耗时、Token、费用）
- AgentNodeTrace: 单次 Agent 节点的执行追踪
- Alert:         告警记录（错误率、成本异常、死 Agent）
- AgentLog:      日志记录（每个节点的详细日志）
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    JSON,
    Uuid,
)
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column

from backend.modules.models.base import Base


class AgentConfig(Base):
    """Agent 配置模板：定义模型、工具、系统提示、超时等参数。"""
    __tablename__ = "agent_configs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="react")  # react, plan_execute, supervisor
    model: Mapped[str] = mapped_column(String(50), nullable=False)
    tools: Mapped[list | None] = mapped_column(JSON, nullable=True, default=list)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_iterations: Mapped[int] = mapped_column(Integer, default=10)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=60)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class AgentRun(Base):
    """Agent 运行记录：每次 Agent 执行对应一条记录。"""
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), unique=True, nullable=False, index=True)
    # 唯一约束防止 duplicate 消费，index=True 加速 join 查询
    config_id: Mapped[int | None] = mapped_column(ForeignKey("agent_configs.id"), nullable=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False, default="agent")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running", index=True)
    input: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 8), nullable=True, default=0)
    # Numeric(14,8) 精度足以覆盖每日数百万次调用的累计费用

    __table_args__ = (
        Index("ix_agent_runs_project_started", "project_id", "started_at"),
    )


class AgentNodeTrace(Base):
    """Agent 节点追踪：记录一次 Agent 运行中各节点的执行详情。"""
    __tablename__ = "agent_node_traces"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("agent_runs.trace_id"), nullable=False, index=True
    )
    node_name: Mapped[str] = mapped_column(String(100), nullable=False)
    node_type: Mapped[str] = mapped_column(String(50), nullable=False)  # llm_call, tool_execution, conditional, human_review
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    input: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    llm_thought: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    parent_node_id: Mapped[int | None] = mapped_column(ForeignKey("agent_node_traces.id"), nullable=True)
    token_usage: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="success")  # success, failed, skipped
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("ix_node_traces_trace_seq", "trace_id", "sequence"),
    )


class Alert(Base):
    """告警记录：由 alerts.py 中的定时任务或 regression.py 等模块创建。"""
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    trace_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), nullable=True)
    level: Mapped[str] = mapped_column(String(20), nullable=False, default="info")  # info, warning, critical
    category: Mapped[str] = mapped_column(String(50), nullable=False)  # error_rate, cost_anomaly, dead_agent
    message: Mapped[str] = mapped_column(Text, nullable=False)
    suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)


class AgentLog(Base):
    """Agent 日志：记录每个节点的详细信息，可全文搜索。"""
    __tablename__ = "agent_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    level: Mapped[str] = mapped_column(String(10), nullable=False, default="INFO", index=True)
    node_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
