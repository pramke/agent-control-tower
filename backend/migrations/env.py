"""Alembic 迁移环境配置——连接数据库、加载模型元数据、执行在线/离线迁移"""
from logging.config import fileConfig
import os

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# 加载项目的 Base 元数据，用于 autogenerate 支持
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from backend.config import settings
from backend.modules.models.base import Base
# 导入所有模型，确保 Base.metadata 包含所有表
import backend.modules.models.user  # noqa
import backend.modules.models.project  # noqa
import backend.modules.models.api_call  # noqa
import backend.modules.detector.models  # noqa
import backend.modules.observability.models  # noqa
import backend.modules.evaluation.eval_model  # noqa

config = context.config

# 从设置中读取数据库 URL（环境变量或 .env）
# SQLite 需要将异步 URL 转为同步 URL
db_url = settings.database_url
if db_url.startswith("sqlite+aiosqlite://"):
    db_url = db_url.replace("sqlite+aiosqlite://", "sqlite:///")
elif "asyncpg" in db_url:
    db_url = db_url.replace("+asyncpg", "")

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata  # 数据库迁移的目标元数据


def run_migrations_offline() -> None:
    """离线模式运行迁移——仅生成 SQL 脚本，不连接数据库"""
    url = db_url
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式运行迁移——直接连接数据库执行 DDL"""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = db_url
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # 迁移使用独立连接，不池化
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
