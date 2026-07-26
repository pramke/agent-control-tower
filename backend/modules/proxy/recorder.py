"""LLM 调用记录器，解析 usage 计算费用并持久化到 ApiCall 表，项目启用 enable_trace 时自动创建 Trace。"""

import json
import logging
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.modules.models.api_call import ApiCall
from backend.pricing.table import calculate_cost

logger = logging.getLogger(__name__)

# 会话级缓存：trace 开关一般不频繁变动，缓存后可减少每次请求的 DB 查询
_traced_projects: set[int] = set()


async def _is_tracing_enabled(db: AsyncSession, project_id: int) -> bool:
    """Check if project has enable_trace=True (with simple cache)."""
    if project_id in _traced_projects:
        return True
    from backend.modules.models.project import Project
    result = await db.execute(
        select(Project.enable_trace).where(Project.id == project_id)
    )
    row = result.scalar_one_or_none()
    enabled = bool(row) if row is not None else False
    if enabled:
        _traced_projects.add(project_id)
    return enabled


def _extract_usage(usage: dict) -> tuple[int, int, int, int]:
    """从各厂商的 usage 对象中提取 token 用量，返回 (input, output, cache_read, cache_create)。

    覆盖 Anthropic / OpenAI / DeepSeek / GLM / Qwen / Moonshot / Gemini 等格式。
    各厂商字段名不统一（如 prompt_tokens vs input_tokens），此处按优先级逐一尝试。
    """
    # 输入 token：尝试所有已知字段名
    input_tokens: int = 0
    for key in ("input_tokens", "prompt_tokens", "promptTokenCount"):
        v = usage.get(key)
        if v:
            input_tokens = int(v)
            break

    # 输出 token
    output_tokens: int = 0
    for key in ("output_tokens", "completion_tokens", "candidatesTokenCount"):
        v = usage.get(key)
        if v:
            output_tokens = int(v)
            break

    # 缓存命中（读取）
    cache_read: int = 0
    for key in ("cache_read_input_tokens", "prompt_cache_hit_tokens", "cache_hit_tokens"):
        v = usage.get(key)
        if v:
            cache_read = int(v)
            break
    if not cache_read:
        details = usage.get("prompt_tokens_details", {})
        if isinstance(details, dict):
            v = details.get("cached_tokens")
            if v:
                cache_read = int(v)

    # 缓存写入
    cache_create: int = 0
    for key in ("cache_creation_input_tokens", "prompt_cache_miss_tokens", "cache_miss_tokens"):
        v = usage.get(key)
        if v:
            cache_create = int(v)
            break
    if not cache_create:
        details = usage.get("prompt_tokens_details", {})
        if isinstance(details, dict):
            v = details.get("cache_write_tokens")
            if v:
                cache_create = int(v)

    return input_tokens, output_tokens, cache_read, cache_create


async def record_call(
    db: AsyncSession,
    project_id: int,
    model: str,
    endpoint: str,
    response_data: dict,
    latency_ms: float,
    request_hash: str,
    request_body: bytes,
    status_code: int | None = None,
) -> None:
    """Record an LLM API call and optionally create a Trace node."""
    usage = response_data.get("usage", {})
    if not isinstance(usage, dict):
        usage = {}

    input_tokens, output_tokens, cache_read, cache_create = _extract_usage(usage)
    logger.info("record_call model=%s usage=%s -> in=%d out=%d cr=%d cc=%d",
                model, usage, input_tokens, output_tokens, cache_read, cache_create)
    if not usage:
        logger.warning("record_call: usage is empty! response_data keys=%s",
                       list(response_data.keys()) if isinstance(response_data, dict) else type(response_data))

    cost = calculate_cost(model, input_tokens, output_tokens, cache_read, cache_create)
    preview = request_body.decode("utf-8", errors="replace")[:500]

    call = ApiCall(
        project_id=project_id,
        model=model,
        endpoint=endpoint,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read,
        cache_creation_tokens=cache_create,
        latency_ms=latency_ms,
        status_code=status_code,
        cost=cost,
        request_hash=request_hash,
        prompt_preview=preview,
    )
    db.add(call)
    await db.commit()

    # ── Optional: auto-create Trace for this proxy call ────────────
    if not await _is_tracing_enabled(db, project_id):
        return

    try:
        from backend.modules.observability.trace_writer import create_run, add_node, finish_run

        trace_id = str(uuid4())
        request_data = {"body": preview}
        try:
            request_data = json.loads(preview)
        except Exception:
            pass

        usage_data = {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "model": model,
        }

        await create_run(
            db,
            trace_id=trace_id,
            project_id=project_id,
            agent_name="proxy",
            input_data=request_data,
        )

        await add_node(
            db,
            trace_id=trace_id,
            node_name=f"proxy:{model}",
            node_type="llm_call",
            sequence=0,
            input_data=request_data,
            output_data=response_data,
            duration_ms=int(latency_ms),
            token_usage=usage_data,
        )

        await finish_run(db, trace_id=trace_id, output_data=response_data, model=model)

        await db.commit()
    except Exception as exc:
        logger.warning("Trace auto-create failed (project=%s): %s", project_id, exc)
