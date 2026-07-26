"""Alerting: periodic health checks + alerts table + WebSocket push.

Checks every 60s:
- P1 error rate over last 5 min > 5%  -> critical
- Day-over-day cost increase > 50%    -> warning (P1 if >200% hour-over-hour)
- Agent still running after 10 min    -> warning, after 30 min -> critical

告警的冷却机制：
- 普通告警 30 分钟冷却（ALERT_COOLDOWN_SECONDS）
- P1 告警 10 分钟冷却（P1_COOLDOWN_SECONDS），确保高优先级问题持续通知
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from jose import JWTError, jwt
from sqlalchemy import func, select

from backend.config import settings

from backend.core.database import async_session
from backend.modules.models.api_call import ApiCall
from backend.modules.observability.logger import ERROR_SUGGESTIONS
from backend.modules.observability.models import AgentRun, Alert

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 60
ERROR_RATE_THRESHOLD = 0.05
ERROR_RATE_MIN_RUNS = 5
ERROR_RATE_WINDOW_MINUTES = 5  # P1 alert window
COST_INCREASE_DAILY_THRESHOLD = 0.5  # 50% day-over-day
COST_INCREASE_HOURLY_THRESHOLD = 2.0  # P1 escalation at 200% hour-over-hour
DEAD_AGENT_MINUTES = 10
DEAD_AGENT_CRITICAL_MINUTES = 30
ALERT_COOLDOWN_SECONDS = 1800  # don't repeat the same alert for 30 min
P1_COOLDOWN_SECONDS = 600  # P1 alerts re-fire every 10 min if condition persists

ws_router = APIRouter()


class AlertBroadcaster:
    """WebSocket 广播器，将新告警实时推送到前端。"""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self._connections:
            self._connections.remove(ws)

    async def broadcast(self, payload: dict) -> None:
        """向所有已连接的 WebSocket 客户端广播消息。"""
        dead: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


broadcaster = AlertBroadcaster()


@ws_router.websocket("/ws/alerts")
async def alerts_websocket(ws: WebSocket, token: str = Query(...)) -> None:
    """WebSocket 端点：前端通过此通道实时接收告警推送。"""
    # Validate token
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        if payload.get("type") != "access":
            await ws.close(code=4001, reason="Invalid token type")
            return
    except JWTError:
        await ws.close(code=4001, reason="Invalid token")
        return

    # Origin check
    origin = ws.headers.get("origin", "")
    allowed_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    if origin and origin not in allowed_origins:
        await ws.close(code=4003, reason="Origin not allowed")
        return

    await broadcaster.connect(ws)
    try:
        while True:
            await ws.receive_text()  # keepalive; client payloads are ignored
    except WebSocketDisconnect:
        broadcaster.disconnect(ws)


# 内存级别的告警去重 — 避免同一问题在短时间内重复推送（告警键 → 上次推送时间戳）
_last_alerted: dict[str, float] = {}


def _cooldown_ok(key: str) -> bool:
    """判断是否已过冷却期（普通告警 30 分钟）。"""
    now = time.monotonic()
    last = _last_alerted.get(key)
    if last is not None and now - last < ALERT_COOLDOWN_SECONDS:
        return False
    _last_alerted[key] = now
    return True


def _p1_cooldown_ok(key: str) -> bool:
    """判断是否已过 P1 冷却期（P1 告警 10 分钟）。

    P1 冷却期比普通告警更短，确保持续性问题能更频繁地通知。"""
    now = time.monotonic()
    last = _last_alerted.get(key)
    if last is not None and now - last < P1_COOLDOWN_SECONDS:
        return False
    _last_alerted[key] = now
    return True


async def create_alert(
    category: str,
    level: str,
    message: str,
    *,
    project_id: int | None = None,
    trace_id: str | None = None,
    suggestion: str | None = None,
) -> None:
    """创建一条告警记录并广播到 WebSocket 通道。"""
    async with async_session() as session:
        alert = Alert(
            project_id=project_id,
            trace_id=trace_id,
            level=level,
            category=category,
            message=message,
            suggestion=suggestion,
        )
        session.add(alert)
        await session.commit()
        await session.refresh(alert)
    logger.warning("ALERT [%s/%s] %s", level, category, message)
    # 先写 DB 再广播 — 确保前端收到的 alert 已可查询
    await broadcaster.broadcast(
        {
            "type": "alert",
            "id": alert.id,
            "project_id": project_id,
            "trace_id": trace_id,
            "level": level,
            "category": category,
            "message": message,
            "suggestion": suggestion,
            "created_at": alert.created_at.isoformat(),
        }
    )


async def check_error_rate() -> None:
    """检查 Agent 错误率。

    - P1 critical: 最近 5 分钟 > 5%
    - Warning:     最近 1 小时 > 5%
    """
    # P1 优先检查（5 分钟窗口），命中则直接返回，跳过低优先级 warning
    since_p1 = datetime.now() - timedelta(minutes=ERROR_RATE_WINDOW_MINUTES)
    async with async_session() as session:
        total_p1 = (
            await session.execute(
                select(func.count()).select_from(AgentRun).where(AgentRun.started_at >= since_p1)
            )
        ).scalar_one()
        failed_p1 = (
            await session.execute(
                select(func.count())
                .select_from(AgentRun)
                .where(AgentRun.started_at >= since_p1, AgentRun.status == "failed")
            )
        ).scalar_one()

    if total_p1 >= ERROR_RATE_MIN_RUNS:
        rate_p1 = failed_p1 / total_p1
        if rate_p1 > ERROR_RATE_THRESHOLD and _p1_cooldown_ok("p1_error_rate"):
            await create_alert(
                "error_rate",
                "critical",
                f"P1 告警：最近 {ERROR_RATE_WINDOW_MINUTES} 分钟 {failed_p1}/{total_p1} 次运行失败（{rate_p1:.1%}，阈值 5%）",
                suggestion="立即检查最近失败 trace 的错误详情，定位共同原因",
            )
            return

    # Hourly warning check
    since_hourly = datetime.now() - timedelta(hours=1)
    async with async_session() as session:
        total = (
            await session.execute(
                select(func.count()).select_from(AgentRun).where(AgentRun.started_at >= since_hourly)
            )
        ).scalar_one()
        failed = (
            await session.execute(
                select(func.count())
                .select_from(AgentRun)
                .where(AgentRun.started_at >= since_hourly, AgentRun.status == "failed")
            )
        ).scalar_one()
    if total < ERROR_RATE_MIN_RUNS:
        return
    rate = failed / total
    if rate > ERROR_RATE_THRESHOLD and _cooldown_ok("error_rate"):
        await create_alert(
            "error_rate",
            "warning",
            f"Agent 错误率过高：最近 1 小时 {failed}/{total} 次运行失败（{rate:.1%}，阈值 5%）",
            suggestion="检查最近失败 trace 的错误详情，定位共同原因",
        )


async def check_cost_anomaly() -> None:
    """检查成本异常。

    - P1 critical: 小时环比突增 > 200%
    - Warning:     日环比增长 > 50%
    """
    now = datetime.now()
    # 小时环比尖峰检查（P1），命中则跳过日环比 warning
    hour_ago = now - timedelta(hours=1)
    two_hours_ago = now - timedelta(hours=2)
    async with async_session() as session:
        current_hour = float(
            (
                await session.execute(
                    select(func.coalesce(func.sum(AgentRun.total_cost), 0)).where(
                        AgentRun.started_at >= hour_ago
                    )
                )
            ).scalar_one()
        )
        previous_hour = float(
            (
                await session.execute(
                    select(func.coalesce(func.sum(AgentRun.total_cost), 0)).where(
                        AgentRun.started_at >= two_hours_ago, AgentRun.started_at < hour_ago
                    )
                )
            ).scalar_one()
        )

    if previous_hour > 0:
        hourly_increase = (current_hour - previous_hour) / previous_hour
        if hourly_increase > COST_INCREASE_HOURLY_THRESHOLD and _p1_cooldown_ok("p1_cost_spike"):
            await create_alert(
                "cost_anomaly",
                "critical",
                f"P1 成本异常：最近 1 小时成本 ${current_hour:.4f}，环比上一小时（${previous_hour:.4f}）"
                f"暴涨 {hourly_increase:.0%}",
                suggestion="立即检查是否有失控 Agent 或死循环",
            )
            return

    # Daily check
    day_ago = now - timedelta(days=1)
    two_days_ago = now - timedelta(days=2)
    async with async_session() as session:
        current = float(
            (
                await session.execute(
                    select(func.coalesce(func.sum(AgentRun.total_cost), 0)).where(
                        AgentRun.started_at >= day_ago
                    )
                )
            ).scalar_one()
        )
        previous = float(
            (
                await session.execute(
                    select(func.coalesce(func.sum(AgentRun.total_cost), 0)).where(
                        AgentRun.started_at >= two_days_ago, AgentRun.started_at < day_ago
                    )
                )
            ).scalar_one()
        )
    if previous <= 0:
        return
    increase = (current - previous) / previous
    if increase > COST_INCREASE_DAILY_THRESHOLD and _cooldown_ok("cost_anomaly"):
        await create_alert(
            "cost_anomaly",
            "warning",
            f"成本异常：最近 24 小时成本 ${current:.4f}，环比上一个 24 小时（${previous:.4f}）"
            f"上涨 {increase:.0%}（阈值 50%）",
            suggestion="检查是否有 Agent 死循环或异常高频调用",
        )


async def check_dead_agents() -> None:
    """检查挂死的 Agent。

    - P2 (warning): 运行超过 10 分钟
    - P1 (critical): 运行超过 30 分钟
    """
    # 先处理 P1（>=30分钟），再处理 P2（>=10 但 <30），避免一条 run 产生两条告警
    cutoff_warn = datetime.now() - timedelta(minutes=DEAD_AGENT_MINUTES)
    cutoff_crit = datetime.now() - timedelta(minutes=DEAD_AGENT_CRITICAL_MINUTES)

    async with async_session() as session:
        rows_crit = (
            (await session.execute(
                select(AgentRun).where(
                    AgentRun.status.in_(["running", "awaiting_human"]),
                    AgentRun.started_at < cutoff_crit,
                )
            )).scalars().all()
        )
        rows_warn = (
            (await session.execute(
                select(AgentRun).where(
                    AgentRun.status.in_(["running", "awaiting_human"]),
                    AgentRun.started_at < cutoff_warn,
                    AgentRun.started_at >= cutoff_crit,
                )
            )).scalars().all()
        )

    # P1 critical for >30 min
    for run in rows_crit:
        trace_id = str(run.trace_id)
        if not _p1_cooldown_ok(f"p1_dead_agent:{trace_id}"):
            continue
        await create_alert(
            "dead_agent",
            "critical",
            f"P1 告警：Agent '{run.agent_name}'（trace {trace_id[:8]}…）已挂死超过 {DEAD_AGENT_CRITICAL_MINUTES} 分钟",
            project_id=run.project_id,
            trace_id=trace_id,
            suggestion=ERROR_SUGGESTIONS.get("MaxIterations"),
        )

    # P2 warning for >10 min
    for run in rows_warn:
        trace_id = str(run.trace_id)
        if not _cooldown_ok(f"dead_agent:{trace_id}"):
            continue
        await create_alert(
            "dead_agent",
            "warning",
            f"Agent '{run.agent_name}'（trace {trace_id[:8]}…）已运行超过 {DEAD_AGENT_MINUTES} 分钟仍未结束",
            project_id=run.project_id,
            trace_id=trace_id,
            suggestion=ERROR_SUGGESTIONS.get("MaxIterations"),
        )


async def check_proxy_error_rate() -> None:
    """检查代理调用错误率（基于 ApiCall 表，面向 monitor 模式项目）。

    - P1 critical: 最近 5 分钟 status_code >= 400 比例 > 10%
    - Warning:     最近 1 小时 status_code >= 400 比例 > 10%
    """
    since_p1 = datetime.now() - timedelta(minutes=ERROR_RATE_WINDOW_MINUTES)
    async with async_session() as session:
        total_p1 = (
            await session.execute(
                select(func.count()).select_from(ApiCall).where(ApiCall.timestamp >= since_p1)
            )
        ).scalar_one()
        failed_p1 = (
            await session.execute(
                select(func.count())
                .select_from(ApiCall)
                .where(ApiCall.timestamp >= since_p1, ApiCall.status_code >= 400)
            )
        ).scalar_one()

    if total_p1 >= ERROR_RATE_MIN_RUNS:
        rate_p1 = failed_p1 / total_p1
        if rate_p1 > 0.10 and _p1_cooldown_ok("p1_proxy_error_rate"):
            await create_alert(
                "proxy_error_rate",
                "critical",
                f"P1 告警：最近 {ERROR_RATE_WINDOW_MINUTES} 分钟代理调用 {failed_p1}/{total_p1} 次返回错误（{rate_p1:.1%}）",
                suggestion="检查上游 LLM 服务状态和项目 API Key 配置",
            )
            return

    since_hourly = datetime.now() - timedelta(hours=1)
    async with async_session() as session:
        total = (
            await session.execute(
                select(func.count()).select_from(ApiCall).where(ApiCall.timestamp >= since_hourly)
            )
        ).scalar_one()
        failed = (
            await session.execute(
                select(func.count())
                .select_from(ApiCall)
                .where(ApiCall.timestamp >= since_hourly, ApiCall.status_code >= 400)
            )
        ).scalar_one()
    if total < ERROR_RATE_MIN_RUNS:
        return
    rate = failed / total
    if rate > 0.10 and _cooldown_ok("proxy_error_rate"):
        await create_alert(
            "proxy_error_rate",
            "warning",
            f"代理调用错误率过高：最近 1 小时 {failed}/{total} 次返回错误（{rate:.1%}）",
            suggestion="检查上游 LLM 服务状态和项目 API Key 配置",
        )


async def check_proxy_cost_spike() -> None:
    """检查代理调用成本异常（基于 ApiCall 表）。

    - P1 critical: 小时环比突增 > 200%
    - Warning:     日环比增长 > 50%
    """
    now = datetime.now()
    hour_ago = now - timedelta(hours=1)
    two_hours_ago = now - timedelta(hours=2)
    async with async_session() as session:
        current_hour = float(
            (
                await session.execute(
                    select(func.coalesce(func.sum(ApiCall.cost), 0)).where(
                        ApiCall.timestamp >= hour_ago
                    )
                )
            ).scalar_one()
        )
        previous_hour = float(
            (
                await session.execute(
                    select(func.coalesce(func.sum(ApiCall.cost), 0)).where(
                        ApiCall.timestamp >= two_hours_ago, ApiCall.timestamp < hour_ago
                    )
                )
            ).scalar_one()
        )

    if previous_hour > 0:
        hourly_increase = (current_hour - previous_hour) / previous_hour
        if hourly_increase > COST_INCREASE_HOURLY_THRESHOLD and _p1_cooldown_ok("p1_proxy_cost_spike"):
            await create_alert(
                "proxy_cost_anomaly",
                "critical",
                f"P1 代理成本异常：最近 1 小时费用 ${current_hour:.4f}，环比上一小时（${previous_hour:.4f}）"
                f"暴涨 {hourly_increase:.0%}",
                suggestion="检查是否有项目异常高频调用或模型配置错误",
            )
            return

    day_ago = now - timedelta(days=1)
    two_days_ago = now - timedelta(days=2)
    async with async_session() as session:
        current = float(
            (
                await session.execute(
                    select(func.coalesce(func.sum(ApiCall.cost), 0)).where(
                        ApiCall.timestamp >= day_ago
                    )
                )
            ).scalar_one()
        )
        previous = float(
            (
                await session.execute(
                    select(func.coalesce(func.sum(ApiCall.cost), 0)).where(
                        ApiCall.timestamp >= two_days_ago, ApiCall.timestamp < day_ago
                    )
                )
            ).scalar_one()
        )
    if previous <= 0:
        return
    increase = (current - previous) / previous
    if increase > COST_INCREASE_DAILY_THRESHOLD and _cooldown_ok("proxy_cost_anomaly"):
        await create_alert(
            "proxy_cost_anomaly",
            "warning",
            f"代理成本异常：最近 24 小时费用 ${current:.4f}，环比上一个 24 小时（${previous:.4f}）"
            f"上涨 {increase:.0%}（阈值 50%）",
            suggestion="检查是否有项目异常高频调用",
        )


async def check_proxy_latency() -> None:
    """检查代理调用延迟异常（基于 ApiCall 表）。

    - Warning: 最近 5 分钟平均延迟超过 10 秒
    """
    since = datetime.now() - timedelta(minutes=ERROR_RATE_WINDOW_MINUTES)
    async with async_session() as session:
        avg_latency = (
            await session.execute(
                select(func.avg(ApiCall.latency_ms)).where(ApiCall.timestamp >= since)
            )
        ).scalar()
        count = (
            await session.execute(
                select(func.count()).select_from(ApiCall).where(ApiCall.timestamp >= since)
            )
        ).scalar_one()

    if count >= ERROR_RATE_MIN_RUNS and avg_latency is not None and avg_latency > 10_000:
        if _cooldown_ok("proxy_latency"):
            await create_alert(
                "proxy_latency",
                "warning",
                f"代理延迟异常：最近 {ERROR_RATE_WINDOW_MINUTES} 分钟平均延迟 {avg_latency/1000:.1f}s（{count} 次调用）",
                suggestion="检查上游 LLM 服务状态和网络连接",
            )


async def alert_monitor_loop() -> None:
    """告警监控主循环：每隔 CHECK_INTERVAL_SECONDS 执行一次各检查。"""
    logger.info("Alert monitor started (every %ss)", CHECK_INTERVAL_SECONDS)
    while True:
        try:
            await check_error_rate()
            await check_cost_anomaly()
            await check_dead_agents()
            await check_proxy_error_rate()
            await check_proxy_cost_spike()
            await check_proxy_latency()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Alert check failed: %s", exc)
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


_monitor_task: asyncio.Task | None = None


def start_alert_monitor() -> None:
    """启动告警监控后台任务。"""
    global _monitor_task
    if _monitor_task is None or _monitor_task.done():
        _monitor_task = asyncio.create_task(alert_monitor_loop())


async def stop_alert_monitor() -> None:
    """停止告警监控后台任务。"""
    global _monitor_task
    if _monitor_task is not None:
        _monitor_task.cancel()
        try:
            await _monitor_task
        except asyncio.CancelledError:
            pass
        _monitor_task = None
