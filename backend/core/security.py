"""
模块: 后端 - 安全工具
功能: JWT 令牌生成/验证、密码哈希、用户角色验证
"""

from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.core.database import get_db
from backend.modules.models.user import User

# Bearer Token 解析器——auto_error=False 让业务层决定未认证时的行为
security_scheme = HTTPBearer(auto_error=False)

# Token 有效期
ACCESS_TOKEN_EXPIRE_MINUTES = 30   # 访问令牌 30 分钟过期
REFRESH_TOKEN_EXPIRE_DAYS = 7      # 刷新令牌 7 天过期


def verify_password(plain: str, hashed: str) -> bool:
    """验证明文密码与 bcrypt 哈希是否匹配"""
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def hash_password(plain: str) -> str:
    """使用 bcrypt 对密码进行哈希处理（自动加盐）"""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def create_access_token(data: dict) -> str:
    """生成 JWT 访问令牌（短有效期，用于 API 鉴权）"""
    to_encode = data.copy()
    to_encode.update({
        "exp": datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
        "type": "access",
    })
    return jwt.encode(to_encode, settings.secret_key, algorithm="HS256")


def create_refresh_token(data: dict) -> str:
    """生成 JWT 刷新令牌（长有效期，用于续签访问令牌）"""
    to_encode = data.copy()
    to_encode.update({
        "exp": datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        "type": "refresh",
    })
    return jwt.encode(to_encode, settings.secret_key, algorithm="HS256")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """从请求头中的 Bearer Token 解析当前用户（FastAPI 依赖注入）"""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "Not authenticated", "details": {}},
        )
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        # 拒绝 refresh 类型令牌用于 API 鉴权
        if payload.get("type") != "access":
            raise HTTPException(
                status_code=401,
                detail={"code": "INVALID_TOKEN", "message": "Invalid token type", "details": {}},
            )
    except JWTError:
        raise HTTPException(
            status_code=401,
            detail={"code": "INVALID_TOKEN", "message": "Invalid or expired token", "details": {}},
        )
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
    return user


def require_role(*roles: str):
    """
    角色权限验证装饰器/依赖
    用法: Depends(require_role("admin")) 或 Depends(require_role("manager", "admin"))
    """
    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "FORBIDDEN",
                    "message": f"Requires one of {roles} role",
                    "details": {},
                },
            )
        return current_user
    return role_checker
