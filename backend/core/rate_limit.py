"""
模块: 后端 - API限流
功能: 使用 slowapi 对所有 API 进行速率限制，防止滥用
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

# 全局限流器——默认速率 120 次/分钟，基于客户端 IP
limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])
