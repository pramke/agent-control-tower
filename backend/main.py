"""
模块: 后端 - 应用主入口
功能: FastAPI 应用初始化，注册所有路由、中间件、启动事件、Prometheus 指标
"""

import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from backend.config import settings
from backend.core.database import engine
from backend.core.rate_limit import limiter
from backend.modules.models.base import Base

# ── 模块注册（确保所有模型表被 Base.metadata 追踪）───────────────
import backend.modules.models.user  # noqa
import backend.modules.models.project  # noqa
import backend.modules.models.api_call  # noqa
import backend.modules.detector.models  # noqa
import backend.modules.observability.models  # noqa
import backend.modules.observability.prompts  # noqa
import backend.modules.evaluation.eval_model  # noqa

# ── 路由注册 ───────────────────────────────────────────────────
from backend.modules.proxy.router import router as proxy_router
from backend.modules.auth.router import router as auth_router
from backend.modules.api_routes.projects import router as projects_router
from backend.modules.api_routes.stats import router as stats_router
from backend.modules.api_routes.calls import router as calls_router
from backend.modules.api_routes.admin import router as admin_router
from backend.modules.api_routes.detection import router as detection_router
from backend.modules.observability.router import router as observability_router
from backend.modules.observability.alerts import (
    start_alert_monitor,
    stop_alert_monitor,
    ws_router as alerts_ws_router,
)
from backend.modules.evaluation.eval_router import router as eval_router
from backend.healthcheck import router as healthcheck_router
from backend.modules.observability.ingest import router as ingest_router
from backend.modules.observability.pruner import start_pruner, stop_pruner
from backend.modules.security.router import router as security_router

# ---------------------------------------------------------------------------
# JSON 结构化日志 + trace_id 注入
# ---------------------------------------------------------------------------
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="-")


class JSONFormatter(logging.Formatter):
    """JSON 格式日志格式化器——输出结构化日志，便于日志收集系统解析"""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "trace_id": getattr(record, "trace_id", "-"),
        }
        if record.exc_info and record.exc_info[0]:
            log_entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, ensure_ascii=False)


class TraceIdFilter(logging.Filter):
    """日志过滤器：为每条日志注入当前请求的 trace_id"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = trace_id_var.get()
        return True


# 配置全局日志处理
_handler = logging.StreamHandler()
_handler.setFormatter(JSONFormatter())
_handler.addFilter(TraceIdFilter())

# 替换根 logger 的处理器为 JSON 格式
_root = logging.getLogger()
_root.handlers = []
_root.addHandler(_handler)
_root.setLevel(settings.log_level)

# 统一第三方库的日志格式
for _name in ("uvicorn", "uvicorn.access", "sqlalchemy.engine"):
    _logger = logging.getLogger(_name)
    _logger.handlers = []
    _logger.addHandler(_handler)
    _logger.propagate = False

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 应用生命周期——启动时建表 + 启动后台任务，关闭时清理资源
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)  # 自动建表
        # SQLite 兼容迁移 — 新字段
        for col, spec in [("target_model", "VARCHAR(100)"), ("provider_type", "VARCHAR(20) DEFAULT 'anthropic'")]:
            try:
                await conn.run_sync(
                    lambda c, col=col, spec=spec: c.exec_driver_sql(
                        f"ALTER TABLE projects ADD COLUMN {col} {spec}"
                    )
                )
            except Exception:
                pass  # 字段已存在
        # 角色迁移：将旧 member/manager 角色转为 user
        try:
            await conn.run_sync(
                lambda c: c.exec_driver_sql(
                    "UPDATE users SET role = 'user' WHERE role IN ('member', 'manager')"
                )
            )
        except Exception:
            pass  # 迁移已执行过（列/表已存在），静默跳过

    start_alert_monitor()     # 启动告警监控
    start_pruner()            # 启动 Trace 数据定期清理
    logger.info("Agent Control Tower started")
    yield
    await stop_alert_monitor()
    await stop_pruner()
    await engine.dispose()


# ---------------------------------------------------------------------------
# FastAPI 应用实例
# ---------------------------------------------------------------------------
app = FastAPI(
    title="智能体控制塔",
    description="企业级 AI Agent 管理平台",
    version="0.3.0",
    lifespan=lifespan,
    swagger_ui_parameters={
        "defaultModelsExpandDepth": -1,
        "docExpansion": "list",
        "filter": True,
    },
)

oauth2_scheme = HTTPBearer()     # Bearer Token 鉴权方案
app.swagger_ui_init_oauth = None  # 禁用 Swagger OAuth 弹窗

# ---------------------------------------------------------------------------
# 中间件栈（外层 → 内层）
# ---------------------------------------------------------------------------

# 1. 速率限制——最外层
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# 2. Trace-ID 注入——每个请求分配唯一追踪 ID
@app.middleware("http")
async def trace_id_middleware(request: Request, call_next):
    trace_id = request.headers.get("X-Trace-Id", str(uuid.uuid4())[:8])
    request.state.trace_id = trace_id
    token = trace_id_var.set(trace_id)
    try:
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id
        return response
    finally:
        trace_id_var.reset(token)


# 3. CORS 跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:3001").split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["Authorization", "Content-Type"],
)

# 4. Prometheus 指标——自动检测所有路由，暴露 /metrics 端点
instrumentator = Instrumentator(
    should_group_status_codes=False,
    should_ignore_untemplated=True,
)
instrumentator.add(app).expose(app, endpoint="/metrics", include_in_schema=True)


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------
@app.get("/api/config/public", tags=["config"])
async def public_config():
    """返回平台公开配置（代理地址等），无需认证"""
    return {"proxy_url": settings.proxy_url}


@app.get("/api/me", tags=["auth"])
async def whoami(credentials=Depends(oauth2_scheme)):
    """返回当前登录用户的身份信息"""
    from backend.core.security import get_current_user
    from backend.core.database import get_db
    async for db in get_db():
        user = await get_current_user(credentials, db)
        return {"id": user.id, "username": user.username, "role": user.role}


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """全局未捕获异常处理器——开发环境返回详细信息，生产环境返回脱敏信息"""
    logger.exception("Unhandled exception: %s", exc)
    is_dev = os.getenv("ENVIRONMENT", "production") == "development"  # 开发环境返回详细错误便于调试，生产环境脱敏
    return JSONResponse(
        status_code=500,
        content={
            "code": "INTERNAL_ERROR",
            "message": str(exc) if is_dev else "服务器内部错误",
            "details": {},
        },
    )


# ---------------------------------------------------------------------------
# 注册所有路由
# ---------------------------------------------------------------------------
app.include_router(proxy_router)          # LLM 代理转发
app.include_router(auth_router)           # 认证（登录/注册/刷新 Token）
app.include_router(admin_router)          # 用户管理（管理员） — 必须在 projects 前，避免 /admin/users 被 /{path} 捕获
app.include_router(projects_router)       # 项目管理 CRUD
app.include_router(stats_router)          # 统计数据分析
app.include_router(calls_router)          # API 调用记录
app.include_router(detection_router)      # 安全检测与告警
app.include_router(observability_router)  # 可观测性（监控/日志）
app.include_router(alerts_ws_router)      # 告警 WebSocket
app.include_router(eval_router)           # 模型评测
app.include_router(healthcheck_router)    # 健康检查
app.include_router(security_router)       # 安全策略管理
app.include_router(ingest_router)         # SDK Trace 接收 + Prompt 管理


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host=settings.host, port=settings.port, reload=True)
