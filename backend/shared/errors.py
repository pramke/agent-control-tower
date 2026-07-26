"""
模块: 后端 - 共享错误定义
功能: 统一的 HTTP 异常和错误码定义
"""

from fastapi import HTTPException


def raise_error(status_code: int, code: str, message: str, details: dict | None = None) -> None:
    """
    统一错误抛出函数——所有端点应使用此函数而非原始 HTTPException
    返回格式: {"code": "...", "message": "...", "details": {...}}
    """
    raise HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, "details": details or {}},
    )


def not_found(resource: str, identifier: int | str) -> None:
    """快捷函数：资源不存在 404 错误"""
    raise_error(404, "NOT_FOUND", f"{resource} {identifier} not found")


def conflict(message: str) -> None:
    """快捷函数：资源冲突 409 错误（如重复创建）"""
    raise_error(409, "CONFLICT", message)


def forbidden(message: str = "Insufficient permissions") -> None:
    """快捷函数：权限不足 403 错误"""
    raise_error(403, "FORBIDDEN", message)


def bad_request(message: str) -> None:
    """快捷函数：请求参数错误 400 错误"""
    raise_error(400, "BAD_REQUEST", message)
