"""
模块: 后端 - 用户模型
功能: 用户数据库模型，包含登录锁定、密码加密、角色管理
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import String, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column

from backend.modules.models.base import Base

# --- 登录安全策略常量 ---
MAX_FAILED_LOGINS = 5  # 最大连续失败次数
LOCKOUT_DURATION_MINUTES = 15  # 锁定持续时间（分钟）


def _utcnow() -> datetime:
    """返回不含时区信息的当前 UTC 时间（用于 SQLAlchemy default 回调）"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    """用户模型 — 存储账号凭证、角色和登录锁定状态"""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)  # bcrypt 哈希密文
    role: Mapped[str] = mapped_column(String(20), default="user")  # user / admin
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0)  # 连续失败计数
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)  # 锁定到期时间
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    def is_locked(self) -> bool:
        """检查用户是否在锁定期内；若已过期则自动复位"""
        if self.locked_until is None:
            return False
        if self.locked_until > _utcnow():
            return True
        # 锁定已过期 -> 自动复位
        self.locked_until = None
        self.failed_login_attempts = 0
        return False

    def record_failed_login(self) -> None:
        """记录一次登录失败，达到阈值时锁定账户"""
        self.failed_login_attempts += 1
        # 仅在跨越阈值时设置锁定时间，避免每次失败都重置锁定倒计时
        if self.failed_login_attempts >= MAX_FAILED_LOGINS:
            self.locked_until = _utcnow() + timedelta(minutes=LOCKOUT_DURATION_MINUTES)

    def clear_failed_logins(self) -> None:
        """登录成功后清除失败计数及锁定状态"""
        self.failed_login_attempts = 0
        self.locked_until = None
