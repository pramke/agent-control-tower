"""
模块: 后端 - 项目模型
功能: 项目数据库模型，每个项目有独立的 API Key 和 Base URL
"""
import hashlib
import secrets
from datetime import datetime

from sqlalchemy import String, Text, DateTime, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from backend.modules.models.base import Base


class Project(Base):
    """项目模型 — 每个项目对应一组上游 LLM 配置（API Key、Base URL、Agent 设置）"""
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)  # 项目名称（全局唯一）
    api_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)  # 明文 API Key
    api_key_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)  # SHA256 哈希
    base_url: Mapped[str] = mapped_column(String(256), nullable=False)  # 代理服务自身地址
    api_key_upstream: Mapped[str] = mapped_column(String(256), nullable=False)  # 上游 LLM 的 API Key
    agent_model: Mapped[str | None] = mapped_column(String(100), nullable=True, default=None)  # 项目级 Agent 模型覆盖
    agent_api_key: Mapped[str | None] = mapped_column(String(256), nullable=True, default=None)  # 项目级 Agent API Key
    agent_base_url: Mapped[str | None] = mapped_column(String(512), nullable=True, default=None)  # 项目级 Agent Base URL
    detection_config: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)  # 安全检测配置（JSON）
    project_type: Mapped[str] = mapped_column(String(20), nullable=False, default="monitor")  # monitor / agent / production
    enable_trace: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # auto-create traces for proxy calls
    target_model: Mapped[str | None] = mapped_column(String(100), nullable=True, default=None)  # 代理目标模型（覆盖默认映射规则）
    provider_type: Mapped[str] = mapped_column(String(20), nullable=False, default="anthropic")  # 上游 API 格式：anthropic | openai
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    @staticmethod
    def generate_api_key() -> tuple[str, str]:
        """生成一对 (明文密钥, SHA256 哈希)，用于项目 API Key 的自动签发"""
        # "tg_" 前缀用于在日志/审计中快速识别项目密钥（区别于其他类型的 token）
        key = "tg_" + secrets.token_hex(30)
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        return key, key_hash

    @staticmethod
    def hash_key(key: str) -> str:
        """对明文密钥做 SHA256 摘要（用于验证时比对）"""
        return hashlib.sha256(key.encode()).hexdigest()

    def safe_dict(self) -> dict:
        """返回项目摘要字典（前端列表展示用，不暴露完整密钥）"""
        return {
            "id": self.id,
            "name": self.name,
            "api_key": (self.api_key[:14] + "…") if self.api_key else "N/A",
            "base_url": self.base_url,
            "project_type": self.project_type,
            "provider_type": self.provider_type,
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }
