"""
模块: 后端 - 用户认证路由
功能: 注册、登录、刷新 Token 接口，含登录锁定和速率限制
"""
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.core.database import get_db
from backend.core.rate_limit import limiter
from backend.core.security import (
    verify_password,
    hash_password,
    create_access_token,
    create_refresh_token,
)
from backend.shared.schemas import UserCreate, TokenResponse
from backend.modules.models.user import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse)
@limiter.limit("3/minute")  # 注册速率限制：每 IP 每分钟最多 3 次
async def register(request: Request, req: UserCreate, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    """用户注册 — 校验用户名唯一性，创建用户并返回 access_token + refresh_token"""
    existing = await db.execute(select(User).where(User.username == req.username))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=400,
            detail={"code": "USER_EXISTS", "message": "Username already taken", "details": {}},
        )
    # First user in the system gets admin role
    from sqlalchemy import func
    user_count = (await db.execute(select(func.count(User.id)))).scalar_one()
    role = "admin" if user_count == 0 else "user"
    user = User(
        username=req.username,
        password_hash=hash_password(req.password),
        role=role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return TokenResponse(
        access_token=create_access_token({"sub": str(user.id), "role": user.role}),
        refresh_token=create_refresh_token({"sub": str(user.id), "role": user.role}),
    )


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")  # 登录速率限制：每 IP 每分钟最多 10 次
async def login(request: Request, req: UserCreate, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    """用户登录 — 验证凭证、检查锁定状态，成功后返回 token 对"""
    result = await db.execute(select(User).where(User.username == req.username))
    user = result.scalar_one_or_none()

    # 检查账户是否因多次失败而被锁定
    if user is not None and user.is_locked():
        raise HTTPException(
            status_code=423,
            detail={
                "code": "ACCOUNT_LOCKED",
                "message": "Account locked due to too many failed attempts. Try again later.",
                "details": {},
            },
        )

    # 验证密码，失败时记录并抛出 401
    if user is None or not verify_password(req.password, user.password_hash):
        if user is not None:
            user.record_failed_login()
            await db.commit()
        raise HTTPException(
            status_code=401,
            detail={"code": "INVALID_CREDENTIALS", "message": "Invalid username or password", "details": {}},
        )

    # 登录成功 -> 清除失败计数，签发 Token
    user.clear_failed_logins()
    await db.commit()
    return TokenResponse(
        access_token=create_access_token({"sub": str(user.id), "role": user.role}),
        refresh_token=create_refresh_token({"sub": str(user.id), "role": user.role}),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token_endpoint(
    refresh_token: str = Body(..., embed=True),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """刷新令牌 — 用 refresh_token 换取新的 access_token + refresh_token"""
    try:
        payload = jwt.decode(refresh_token, settings.secret_key, algorithms=["HS256"])
        # 防止 access_token 被误用于 refresh 端点（两类 token 的 type 声明不同）
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=401,
                detail={"code": "INVALID_TOKEN", "message": "Invalid token type", "details": {}},
            )
    except JWTError:
        raise HTTPException(
            status_code=401,
            detail={"code": "INVALID_TOKEN", "message": "Invalid or expired refresh token", "details": {}},
        )
    # 从 Token payload 中提取用户 ID，并验证用户仍然存在
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "INVALID_TOKEN", "message": "Token missing subject", "details": {}},
        )
    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "USER_NOT_FOUND", "message": "User not found", "details": {}},
        )
    return TokenResponse(
        access_token=create_access_token({"sub": str(user.id), "role": user.role}),
        refresh_token=create_refresh_token({"sub": str(user.id), "role": user.role}),
    )
