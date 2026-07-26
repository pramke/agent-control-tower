"""
模块: 后端 - 共享数据模型
功能: Pydantic 数据模型，定义 API 请求和响应的数据结构
"""
from typing import Literal

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    """统一错误响应格式——所有 API 错误均返回此结构"""
    code: str                # 错误码（如 "NOT_FOUND", "UNAUTHORIZED"）
    message: str             # 人类可读的错误描述
    details: dict = {}       # 可选的详细错误信息


class TokenResponse(BaseModel):
    """认证令牌响应——登录成功后返回 access + refresh 令牌对"""
    access_token: str        # 短生命周期访问令牌（默认 30 分钟）
    refresh_token: str       # 长生命周期刷新令牌（默认 7 天）
    token_type: str = "bearer"


class UserCreate(BaseModel):
    """创建用户请求体"""
    username: str                                                  # 用户名
    password: str                                                  # 密码（明文传输，后端哈希存储）
    role: Literal["user", "admin"] = "user"  # 默认普通用户，禁止注册时自提为管理员
