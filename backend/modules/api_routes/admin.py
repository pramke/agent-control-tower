"""
模块: 后端 - 管理员路由
功能: 用户列表查询、角色变更、删除用户等管理员专属操作
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.security import get_current_user, require_role
from backend.modules.models.user import User

router = APIRouter(prefix="/api/admin", tags=["admin"])


class UserRow(BaseModel):
    id: int
    username: str
    role: str
    created_at: str | None

    model_config = {"from_attributes": True}


class RoleUpdate(BaseModel):
    role: str  # "admin" | "user"


@router.get("/users", response_model=list[UserRow])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
):
    """列出所有用户。"""
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()
    return [
        UserRow(
            id=u.id,
            username=u.username,
            role=u.role,
            created_at=u.created_at.isoformat() if u.created_at else None,
        )
        for u in users
    ]


@router.put("/users/{user_id}/role")
async def update_user_role(
    user_id: int,
    req: RoleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """修改用户角色。"""
    # 仅允许这两种角色值，防止注入非法角色字符串
    if req.role not in ("admin", "user"):
        raise HTTPException(status_code=400, detail="无效角色")

    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 不能修改自己的角色
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能修改自己的角色")

    # 防止系统失去所有管理员：至少保留一个 admin 账号
    if user.role == "admin" and req.role == "user":
        admin_count = (
            await db.execute(select(func.count(User.id)).where(User.role == "admin"))
        ).scalar_one()
        # 当前用户是唯一的 admin，禁止降级
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="不能将最后一个管理员降级为用户")

    user.role = req.role
    await db.commit()
    return {"ok": True}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """删除用户。不能删除自己，不能删除最后一个 admin。"""
    # 防止误删自己导致无法继续操作
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能删除自己")

    # 检查是否是最后一个 admin
    admin_count = (
        await db.execute(select(func.count(User.id)).where(User.role == "admin"))
    ).scalar_one()
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.role == "admin" and admin_count <= 1:
        raise HTTPException(status_code=400, detail="不能删除最后一个管理员")

    await db.delete(user)
    await db.commit()
    return {"ok": True}
