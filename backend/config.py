"""
模块: 后端 - 配置管理
功能: 从环境变量和 .env 文件读取项目配置（数据库、JWT、API Key 等）
"""
from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── 基础配置 ──────────────────────────────────────────────
    database_url: str = ""   # 数据库连接字符串（如 sqlite+aiosqlite:///./act2.db）
    secret_key: str = ""     # JWT 签名密钥（生产环境必须设置为强随机字符串）
    host: str = "0.0.0.0"   # 服务器监听地址
    port: int = 8001         # 服务器监听端口
    log_level: str = "INFO"  # 日志级别

    # ── 代理服务配置 ───────────────────────────────────────────
    proxy_url: str = "http://127.0.0.1:8001/proxy"  # 本平台的代理地址（供客户端接入使用）

    # ── AI Agent 配置 ─────────────────────────────────────────
    agent_model: str = "deepseek-v4-pro"          # 默认使用的 LLM 模型
    agent_api_key: str = ""                       # LLM API 密钥
    agent_base_url: str = "https://api.deepseek.com/anthropic"  # LLM API 基础地址

    # ── 定时报告配置 ───────────────────────────────────────────
    daily_report_hour: int = 0    # 日报发送时间（小时，0-23）
    weekly_report_day: int = 0    # 周报发送日（0=周一, 6=周日）
    weekly_report_hour: int = 1   # 周报发送时间（小时，0-23）

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @model_validator(mode="after")
    def validate_security(self):
        """启动时校验安全配置：拒绝弱密钥和空数据库连接"""
        weak_keys = {"change-me-in-production", "changeme", "secret", "dev", ""}
        if self.secret_key in weak_keys:
            raise ValueError(
                "SECRET_KEY 未设置或使用了弱默认值。"
                "请生成强随机密钥: python -c \"import secrets; print(secrets.token_hex(32))\""
                " 并设置环境变量 SECRET_KEY"
            )
        if not self.database_url:
            raise ValueError("DATABASE_URL 未设置。请设置环境变量 DATABASE_URL")
        return self


settings = Settings()  # 全局单例配置实例
