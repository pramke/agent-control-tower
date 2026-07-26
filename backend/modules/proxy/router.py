"""代理模块 API 路由入口，处理 LLM 代理请求的认证、模型映射、安全校验和供应商故障转移。"""

import asyncio
import hashlib
import json
import logging
import os
import re
import uuid

from fastapi import APIRouter, Request, BackgroundTasks
from fastapi.responses import JSONResponse, StreamingResponse

from backend.core.database import async_session
from backend.modules.proxy.middleware import authenticate_project
from backend.modules.proxy.hasher import compute_request_hash
from backend.modules.proxy.forwarder import forward_request, StreamForwarder
from backend.modules.proxy.recorder import record_call
from backend.modules.detector.engine import run_detection
from backend.modules.security.guardrails import check_prompt
from backend.modules.security.sanitizer import sanitize
from backend.modules.security.content_filter import filter_content

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/proxy")

# 匹配 "model": "..." 的原始字节（用于项目级目标模型替换）
_MODEL_FIELD_RE = re.compile(rb'"model"\s*:\s*"([^"]*)"')


def _remap_to_target(body: bytes, target: str) -> tuple[bytes, str | None]:
    """将请求体中的模型名替换为项目指定的目标模型。"""
    m = _MODEL_FIELD_RE.search(body)
    if not m:
        return body, None
    raw_original = m.group(1)
    original = raw_original.decode("utf-8", errors="replace")
    replacement = b'"model": "' + target.encode() + b'"'
    new_body = body[: m.start()] + replacement + body[m.end():]
    logger.info("Model override: %s -> %s", original, target)
    return new_body, original


# Claude 模型名 → DeepSeek 模型名的映射规则（项目未设置 target_model 时使用）
MODEL_REMAP_RULES = [
    (re.compile(r"claude.*haiku", re.I), "deepseek-v4-flash"),
    (re.compile(r"claude.*sonnet", re.I), "deepseek-v4-pro"),
    (re.compile(r"claude.*opus", re.I), "deepseek-v4-pro"),
    (re.compile(r"claude", re.I), "deepseek-v4-pro"),
]


def _load_providers() -> dict:
    """从环境变量加载提供商配置。"""
    providers_json = os.getenv("TOKENGUARD_PROVIDERS", "{}")
    try:
        return json.loads(providers_json)
    except json.JSONDecodeError:
        logger.warning("Invalid TOKENGUARD_PROVIDERS format, using empty routing")
        return {}


PROVIDER_ROUTES = _load_providers()


def _resolve_upstream(project, model: str) -> list[tuple[str, str]]:
    """解析上游提供商列表（有序）。

    返回有序的 (base_url, api_key) 列表 — 项目默认在前，备用提供商在后。
    """
    providers: list[tuple[str, str]] = [(project.base_url, project.api_key_upstream)]
    for name, cfg in PROVIDER_ROUTES.items():
        models = cfg.get("models", ["*"])
        for pattern in models:
            if pattern == "*" or re.search(pattern.replace("*", ".*"), model, re.I):
                providers.append((cfg.get("base_url"), cfg.get("api_key")))
                break
    return providers


# 匹配 "model": "*claude*" 的原始字节（保留 JSON 深层结构完整性）
_REMAP_RE = re.compile(rb'"model"\s*:\s*"([^"]*[cC][lL][aA][uU][dD][eE][^"]*)"')


def _remap_model(body: bytes) -> tuple[bytes, str | None]:
    """用正则替换请求中的模型名，保留原始 JSON 结构。"""
    m = _REMAP_RE.search(body)
    if not m:
        return body, None

    raw_original = m.group(1)
    original = raw_original.decode("utf-8", errors="replace")
    target: str | None = None

    for pattern, t in MODEL_REMAP_RULES:
        if pattern.search(original):
            target = t
            break

    if not target:
        return body, None

    replacement = b'"model": "' + target.encode() + b'"'
    new_body = body[: m.start()] + replacement + body[m.end():]
    logger.info("Model remap: %s -> %s", original, target)
    return new_body, original


async def _record_background(
    project_id: int,
    model: str,
    endpoint: str,
    response_data: dict,
    latency_ms: float,
    request_hash: str,
    body: bytes,
    status_code: int | None = None,
) -> None:
    """后台任务：记录 API 调用数据到数据库。"""
    async with async_session() as session:
        try:
            await record_call(
                session, project_id, model, endpoint,
                response_data, latency_ms, request_hash, body, status_code,
            )
        except Exception:
            logger.exception("Failed to record API call")


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy_catchall(request: Request, background_tasks: BackgroundTasks, path: str):
    """通用代理端点：处理所有 LLM API 请求的转发。"""
    body = await request.body()
    full_path = "/" + path

    # 项目认证（提前到模型映射之前，以便用项目级 target_model 覆盖）
    async with async_session() as session:
        project = await authenticate_project(request, session)

    provider_type = getattr(project, 'provider_type', 'anthropic')

    # openai 项目如未设 target_model 则直接透传原始模型名，跳过 Claude→DeepSeek 自动映射（因其本身已是目标供应商）
    # 模型名映射 — 项目级 target_model 优先；openai 项目跳过 Claude 正则规则
    logger.debug("Body BEFORE model remap: %d bytes, md5=%s",
                 len(body), hashlib.md5(body).hexdigest())
    if project.target_model:
        body, original_model = _remap_to_target(body, project.target_model)
    elif provider_type == "anthropic":
        body, original_model = _remap_model(body)
    else:
        # openai 项目且未设 target_model：提取原始模型名用于记录
        original_model = None
        try:
            original_model = json.loads(body).get("model")
        except Exception:
            pass
    logger.debug("Body AFTER model remap: %d bytes, md5=%s",
                 len(body), hashlib.md5(body).hexdigest())

    # 仅处理 POST /v1/messages 的详细代理逻辑
    if request.method == "POST" and full_path == "/v1/messages":
        # 计算请求哈希（用于重复检测）
        request_hash = compute_request_hash(body)
        try:
            req_data = json.loads(body)
            model = req_data.get("model", "unknown")
            is_stream = req_data.get("stream", False)
        except (json.JSONDecodeError, KeyError):
            model = "unknown"
            is_stream = False
            req_data = None

        # -- 安全校验：安全护栏 + PII 净化 --
        # 在原始字符串上做文本替换而非先解析再序列化，因为 json.dumps 可能:
        #   1) 打乱字段顺序  2) 改变数字精度  3) 丢失 JSON 中不规范的空白/换行
        # 这些都可能破坏上游签名校验或导致模型行为差异
        body_str = body.decode("utf-8", errors="replace")

        if isinstance(req_data, dict):
            for msg in req_data.get("messages", []):
                if isinstance(msg, dict) and msg.get("role") == "user":
                    content = msg.get("content", "")
                    if isinstance(content, str) and content:
                        # 护栏检测
                        safe, sanitized, reason = check_prompt(content)
                        if not safe:
                            logger.warning("Guardrails blocked prompt: %s", reason)
                            return JSONResponse(
                                content={"error": {"type": "content_filter", "message": f"提示词被安全策略拦截: {reason}"}},
                                status_code=400,
                            )
                        # PII 脱敏（仅作用于消息内容，不触碰 JSON 结构）
                        pii_sanitized, pii_stats = sanitize(sanitized)
                        if any(pii_stats.values()):
                            sanitized = pii_sanitized
                            logger.info("PII sanitized in user message: %s", pii_stats)
                        if sanitized != content:
                            old_encoded = json.dumps(content, ensure_ascii=False)
                            new_encoded = json.dumps(sanitized, ensure_ascii=False)
                            body_str = body_str.replace(old_encoded, new_encoded, 1)
                            logger.info("Guardrails sanitized prompt")

        body = body_str.encode("utf-8")
        logger.debug("Body AFTER security: %d bytes, md5=%s",
                     len(body), hashlib.md5(body).hexdigest())
        # 验证 body 仍为合法 JSON，捕获异常时记录上下文
        try:
            json.loads(body)
        except json.JSONDecodeError as e:
            logger.error("Body is INVALID JSON after security section! pos=%d, context: ...%s...",
                         e.pos, body_str[max(0, e.pos - 80):e.pos + 80])
        # -- 安全校验结束 --

        # -- 格式转换（openai 项目：Anthropic → OpenAI）--
        # openai 项目接收的是 Anthropic 格式请求但后端是 OpenAI API，
        # 需在请求/响应两个方向都做格式互转，让客户端无感知
        forward_path = full_path
        if provider_type == "openai":
            from backend.modules.proxy.adapter import anthropic_to_openai_request
            forward_path = "/v1/chat/completions" if full_path == "/v1/messages" else full_path
            body = anthropic_to_openai_request(body, project.target_model)
            logger.debug("Body AFTER openai conversion: %d bytes, md5=%s",
                         len(body), hashlib.md5(body).hexdigest())
            # 重新读取模型名（已被 target_model 或适配器替换）
            try:
                model = json.loads(body).get("model", model)
            except Exception:
                pass

        # 解析上游提供商列表
        providers = _resolve_upstream(project, model)
        upstream_url, upstream_key = providers[0]
        if len(providers) > 1:
            logger.info("Using primary provider: %s (alt providers: %d)", upstream_url, len(providers) - 1)

        if is_stream:
            # 流式请求：使用 StreamForwarder 逐块转发
            async def stream_and_record():
                # openai 项目：创建 SSE 流转换器
                response_transformer = None
                if provider_type == "openai":
                    from backend.modules.proxy.adapter import OpenAIStreamToAnthropic
                    msg_id = f"msg_{uuid.uuid4().hex[:24]}"
                    def _transform(source):
                        return OpenAIStreamToAnthropic(source, msg_id, model)
                    response_transformer = _transform

                fw = StreamForwarder(
                    base_url=upstream_url,
                    path=forward_path,
                    api_key_upstream=upstream_key,
                    method=request.method,
                    body=body,
                    headers=dict(request.headers),
                    response_transformer=response_transformer,
                )
                async for chunk in fw:
                    yield chunk
                if fw.result is not None:
                    response_data, latency_ms, status_code = fw.result
                    asyncio.create_task(_record_background(
                        project.id, model, full_path,
                        response_data, latency_ms, request_hash, body, status_code,
                    ))
                    asyncio.create_task(run_detection(
                        project.id, original_model, full_path,
                        response_data, latency_ms, request_hash, body,
                    ))

            return StreamingResponse(
                stream_and_record(),
                media_type="text/event-stream",
                status_code=200,
            )

        # 非流式请求：按 providers 顺序逐个尝试，任一成功即跳出循环
        last_error: Exception | None = None
        for provider_idx, (upstream_url, upstream_key) in enumerate(providers):
            try:
                response_data, latency_ms, status_code = await forward_request(
                    base_url=upstream_url,
                    path=forward_path,
                    api_key_upstream=upstream_key,
                    method=request.method,
                    body=body,
                    headers=dict(request.headers),
                )
                break
            except Exception as exc:
                last_error = exc
                if provider_idx < len(providers) - 1:
                    logger.warning("Provider %s failed (%s), trying next...", upstream_url, exc)
                else:
                    logger.error("All providers exhausted for %s: %s", full_path, exc)
                    return JSONResponse(
                        content={"error": {"type": "upstream_error", "message": "All upstream providers failed"}},
                        status_code=502,
                    )
        # -- 格式回转（openai 项目：OpenAI → Anthropic）--
        if provider_type == "openai":
            from backend.modules.proxy.adapter import openai_to_anthropic_response
            response_data = openai_to_anthropic_response(response_data, model)

        # -- 响应内容安全过滤 --
        allowed, filtered_text, flags = filter_content(json.dumps(response_data, ensure_ascii=False))
        if not allowed:
            logger.warning("Content filter blocked response: %s", [f.category for f in flags])
            response_data = {
                "error": {"type": "content_filter", "message": filtered_text}
            }
        # -- 内容过滤结束 --

        # 后台记录调用数据和运行检测
        background_tasks.add_task(
            _record_background,
            project.id, model, full_path,
            response_data, latency_ms, request_hash, body, status_code,
        )
        background_tasks.add_task(
            run_detection,
            project.id, original_model, full_path,
            response_data, latency_ms, request_hash, body,
        )
        return JSONResponse(content=response_data, status_code=status_code)

    # 非 /v1/messages 的请求：直接转发到项目默认供应商
    non_msg_providers = _resolve_upstream(project, "default")
    non_msg_url, non_msg_key = non_msg_providers[0]
    response_data, latency_ms, status_code = await forward_request(
        base_url=non_msg_url,
        path=full_path,
        api_key_upstream=non_msg_key,
        method=request.method,
        body=body,
        headers=dict(request.headers),
    )
    return JSONResponse(content=response_data, status_code=status_code)
