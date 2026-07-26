"""
模块: 后端 - 数据库核心
功能: 数据库连接、会话管理、异步引擎初始化
"""
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from backend.config import settings

# 异步数据库引擎——连接池大小 20，echo=False 避免 SQL 日志泄露
engine = create_async_engine(settings.database_url, echo=False, pool_size=20)

# SQLite: enable WAL mode + foreign keys on every new connection
@event.listens_for(engine.sync_engine, "connect")
def _on_connect(dbapi_connection, _connection_record):
    if hasattr(dbapi_connection, "execute"):
        dbapi_connection.execute("PRAGMA journal_mode=WAL")
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

# 异步会话工厂——expire_on_commit=False 防止提交后对象过期导致懒加载异常
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncSession:
    """FastAPI 依赖注入：获取数据库会话，请求结束时自动关闭"""
    async with async_session() as session:
        yield session
