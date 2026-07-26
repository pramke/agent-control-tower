"""
模块: 后端 - API调用记录模型
功能: 记录每次 LLM API 调用的详细信息（Token数、费用、延迟等）
"""
from datetime import datetime

from sqlalchemy import String, Integer, Float, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from backend.modules.models.base import Base


class ApiCall(Base):
    """API 调用记录模型 — 记录每一次 LLM 代理请求的 Token、延迟、费用明细"""
    __tablename__ = "api_calls"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(100), nullable=False)  # 使用的模型名称
    endpoint: Mapped[str] = mapped_column(String(50), nullable=False)  # 调用端点（chat / completions 等）
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)  # 输入 Token 数
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)  # 输出 Token 数
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)  # 缓存读取 Token 数
    cache_creation_tokens: Mapped[int] = mapped_column(Integer, default=0)  # 缓存创建 Token 数
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)  # 请求延迟（毫秒）
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 上游 HTTP 状态码
    cost: Mapped[float] = mapped_column(Float, nullable=False)  # 本次调用费用
    request_hash: Mapped[str] = mapped_column(String(64), index=True)  # 请求内容哈希（用于去重检测；索引但不唯一，允许重复）
    prompt_preview: Mapped[str | None] = mapped_column(String(500), nullable=True)  # 提示词前 500 字符预览
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)  # 调用时间

    __table_args__ = (
        Index("ix_project_timestamp", "project_id", "timestamp"),  # 按项目+时间快速检索
    )
