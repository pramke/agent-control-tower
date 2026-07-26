"""模块: 后端 - 种子数据 / 功能: 创建默认管理员和演示用户，仅当数据库为空时执行"""
import asyncio
import os

from backend.core.database import engine, async_session
from backend.core.security import hash_password
from backend.modules.models.base import Base
from backend.modules.models.user import User
from sqlalchemy import select


async def seed():
    # 确保表存在
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as db:
        # 检查是否已有用户（避免重复创建）
        existing = (await db.execute(select(User))).scalars().all()
        if existing:
            print(f"数据库已有 {len(existing)} 个用户，跳过种子数据。")
            for u in existing:
                print(f"  - {u.username} ({u.role})")
            return

        admin = User(
            username="admin",
            password_hash=hash_password("admin123"),
            role="admin",
        )
        manager = User(
            username="demo",
            password_hash=hash_password("demo123"),
            role="user",
        )
        db.add_all([admin, manager])
        await db.commit()
        print("种子数据创建完成:")
        print("  管理员  admin / admin123  (role: admin)")
        print("  用户    demo  / demo123   (role: user)")
        print()
        print("注册新用户默认角色为 user。")
        print("管理员可在用户管理面板中升级为 admin。")


if __name__ == "__main__":
    # 快速校验环境变量
    if not os.getenv("DATABASE_URL"):
        print("错误: 未设置 DATABASE_URL 环境变量")
        print("示例: $env:DATABASE_URL='sqlite+aiosqlite:///./act2.db'")
        exit(1)
    if not os.getenv("SECRET_KEY"):
        print("错误: 未设置 SECRET_KEY 环境变量")
        print("生成: python -c \"import secrets; print(secrets.token_hex(32))\"")
        exit(1)

    asyncio.run(seed())
