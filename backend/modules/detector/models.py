"""检测模块数据模型：DetectionAlert（告警记录）与 BaitCredential（诱饵凭证），用于安全检测结果的持久化存储。"""

from datetime import datetime

from sqlalchemy import String, Integer, Text, Boolean, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from backend.modules.models.base import Base


class DetectionAlert(Base):
    """检测告警记录，由 detector/engine.py 中的 run_detection 创建。"""
    __tablename__ = "detection_alerts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    alert_type: Mapped[str] = mapped_column(String(30), nullable=False)  # model_watering, json_injection, bait_key_theft
    severity: Mapped[str] = mapped_column(String(10), nullable=False)    # low, medium, high, critical
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence: Mapped[str] = mapped_column(Text, nullable=False, default="")  # JSON string with detection details
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    endpoint: Mapped[str | None] = mapped_column(String(50), nullable=True)
    request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)

    __table_args__ = (
        Index("ix_detection_project_time", "project_id", "detected_at"),
        Index("ix_detection_type", "project_id", "alert_type"),
    )


class BaitCredential(Base):
    """诱饵凭证：嵌入项目中的假密钥，用于检测凭证泄露/窃取。"""
    __tablename__ = "bait_credentials"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    key_type: Mapped[str] = mapped_column(String(30), nullable=False)     # openai, anthropic, aws, etc.
    key_value: Mapped[str] = mapped_column(String(256), nullable=False)   # 诱饵密钥的原始值
    label: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
