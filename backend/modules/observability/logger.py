"""Structured logging for agent steps: every log line carries a trace_id.

Logs go both to the Python logging system (as JSON lines) and to the
`agent_logs` table so they can be searched via GET /api/logs.

log_step() 是核心函数，每个 Agent 节点执行完毕后调用一次，
写入 JSON 到 stdout（可被日志收集系统摄入）并持久化到 DB。
"""

import json
import logging
from datetime import datetime

from backend.core.database import async_session
from backend.modules.observability.models import AgentLog

logger = logging.getLogger("agent.observability")

# 常见错误类型 → 中文故障排查建议
ERROR_SUGGESTIONS: dict[str, str] = {
    "ConnectionRefused": "数据库连接被拒绝，请检查 PostgreSQL 是否运行",
    "ToolCooldown": "工具连续失败已达上限，请检查工具配置和上游服务",
    "MaxIterations": "Agent 达到最大循环次数，可能陷入死循环。建议增加 max_iterations 或简化任务",
    "AuthenticationError": "API Key 无效或过期，请检查上游提供商配置",
    "Timeout": "请求超时，可能是上游服务响应慢或网络问题",
    "PermissionDenied": "权限被拒绝，请检查工具调用权限配置",
    "SchemaValidation": "LLM 输出格式不符合预期，请检查 Prompt 中的输出格式要求",
    "AgentTimeout": "节点执行超时，检查模型/工具响应速度或调大超时时间",
    "RateLimit": "API 速率限制已达上限，请稍后重试或联系提供商提升配额",
    "ContextLength": "输入 Token 超过模型上下文窗口，请精简输入或分段处理",
    "InvalidRequest": "请求格式不正确，请检查请求参数是否符合 API 规范",
    "InternalError": "上游服务内部错误，请稍后重试或联系提供商",
    "OutOfMemory": "内存不足，请减少并发 Agent 数量或增大容器内存",
    "NetworkError": "网络连接失败，请检查 DNS 配置和防火墙规则",
}


def _normalize(text: str) -> str:
    """移除文本中的空格和下划线，实现容错模糊匹配。"""
    return text.lower().replace(" ", "").replace("_", "")


def suggest_for_error(error_text: str | None) -> str | None:
    """根据错误信息返回可读的中文排查建议（子串模糊匹配）。"""
    if not error_text:
        return None
    # 归一化后做子串匹配，让 ToolCooldown 能匹配 "tool_cooldown_exceeded"
    normalized = _normalize(error_text)
    for pattern, suggestion in ERROR_SUGGESTIONS.items():
        if _normalize(pattern) in normalized:
            return suggestion
    return None


async def log_step(
    trace_id: str | None,
    message: str,
    *,
    level: str = "INFO",
    project_id: int | None = None,
    node_name: str | None = None,
    context: dict | None = None,
) -> None:
    """Write one structured log entry (stdout JSON + agent_logs table).

    写入日志记录（双写：stdout JSON + DB），异常不抛以避免影响主流程。
    """
    record = {
        "ts": datetime.now().isoformat(),
        "level": level,
        "trace_id": trace_id,
        "project_id": project_id,
        "node_name": node_name,
        "message": message,
    }
    if context:
        record["context"] = context
    log_fn = getattr(logger, level.lower(), logger.info)
    log_fn(json.dumps(record, ensure_ascii=False, default=str))

    # 写入 DB（失败不影响主流程）
    try:
        async with async_session() as session:
            session.add(
                AgentLog(
                    project_id=project_id,
                    trace_id=trace_id,
                    level=level.upper(),
                    node_name=node_name,
                    message=message[:8000],
                    context=context,
                )
            )
            await session.commit()
    except Exception as exc:  # logging must never break the agent run
        logger.warning("Failed to persist agent log: %s", exc)
