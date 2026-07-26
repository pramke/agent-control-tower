"""LLM 请求转发层，支持普通/流式转发及指数退避重试。"""

import json
import time
import logging
import asyncio

import httpx

logger = logging.getLogger(__name__)

MAX_RETRIES = 3                       # 最大重试次数
RETRY_BACKOFF_BASE = 1.0              # 退避基值（秒）；每次重试翻倍
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}  # 可重试的 HTTP 状态码


async def forward_request(
    base_url: str,
    path: str,
    api_key_upstream: str,
    method: str,
    body: bytes,
    headers: dict[str, str],
    *,
    max_retries: int = MAX_RETRIES,
) -> tuple[dict, float, int]:
    """将请求转发到上游 LLM 提供商，带指数退避重试。

    返回: (响应数据字典, 延迟毫秒数, HTTP 状态码)
    """
    url = base_url.rstrip("/") + path
    upstream_headers = {
        "Authorization": f"Bearer {api_key_upstream}",
        "Content-Type": headers.get("content-type", "application/json"),
    }

    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.request(
                    method=method, url=url, content=body, headers=upstream_headers,
                )
            latency_ms = (time.perf_counter() - start) * 1000

            # 可重试状态码且还有重试次数 → 等待后重试
            if response.status_code in RETRYABLE_STATUSES and attempt < max_retries:
                delay = RETRY_BACKOFF_BASE * (2 ** attempt)
                logger.warning("LLM upstream %s returned %s, retry %d/%d after %.1fs",
                               base_url, response.status_code, attempt + 1, max_retries, delay)
                await asyncio.sleep(delay)
                continue

            try:
                response_data = response.json()
            except Exception:
                response_data = {"raw": response.text}

            return response_data, latency_ms, response.status_code

        except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError) as exc:
            last_error = exc
            if attempt < max_retries:
                delay = RETRY_BACKOFF_BASE * (2 ** attempt)
                logger.warning("LLM upstream %s connection error: %s, retry %d/%d after %.1fs",
                               base_url, exc, attempt + 1, max_retries, delay)
                await asyncio.sleep(delay)
                continue
            raise

    raise last_error or RuntimeError("forward_request exhausted retries")


class StreamForwarder:
    """流式转发器：将请求转发到上游并逐块返回响应。"""

    def __init__(
        self,
        base_url: str,
        path: str,
        api_key_upstream: str,
        method: str,
        body: bytes,
        headers: dict[str, str],
        *,
        response_transformer=None,  # Callable[[AsyncIterator[bytes]], AsyncIterator[bytes]] | None
    ) -> None:
        self._base_url = base_url
        self._path = path
        self._api_key_upstream = api_key_upstream
        self._method = method
        self._body = body
        self._headers = headers
        self._response_transformer = response_transformer
        self.result: tuple[dict, float, int] | None = None  # 流结束后的完整结果

    async def __aiter__(self):
        """异步迭代器：逐块 yield 上游的流式响应字节，最后保存结果。"""
        url = self._base_url.rstrip("/") + self._path
        upstream_headers = {
            "Authorization": f"Bearer {self._api_key_upstream}",
            "Content-Type": self._headers.get("content-type", "application/json"),
        }

        start = time.perf_counter()
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                method=self._method, url=url, content=self._body, headers=upstream_headers,
            ) as response:
                self._status_code = response.status_code
                body_chunks: list[bytes] = []
                stream = response.aiter_bytes()
                if self._response_transformer:
                    stream = self._response_transformer(stream)
                async for chunk in stream:
                    body_chunks.append(chunk)
                    yield chunk
        latency_ms = (time.perf_counter() - start) * 1000

        # 流结束后拼接所有分块。非流式响应可直接 json.loads；
        # SSE 流式响应无法直接 JSON 反序列化，需从事件行中提取 usage
        full_body = b"".join(body_chunks)
        try:
            response_data = json.loads(full_body)
        except Exception:
            response_data = {"raw": full_body.decode(errors="replace")}
            # SSE 流式响应：从事件中提取 usage
            usage = _extract_usage_from_sse(full_body)
            if usage:
                response_data["usage"] = usage

        self.result = (response_data, latency_ms, self._status_code)


def _extract_usage_from_sse(raw: bytes) -> dict:
    """Parse SSE stream bytes to extract token usage from Anthropic-format events.

    input_tokens 出现在 message_start 事件中，output_tokens 出现在 message_delta 中。
    两者分布在不同事件类型上，因此需要遍历全部事件收集，而非从单事件取。
    """
    usage: dict = {}
    text = raw.decode("utf-8", errors="replace")
    for line in text.split("\n"):
        line = line.strip()
        if not line.startswith("data: "):
            continue
        payload_str = line[6:]
        if payload_str == "[DONE]":
            continue
        try:
            event = json.loads(payload_str)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(event, dict):
            continue
        event_usage = event.get("usage") or event.get("message", {}).get("usage")
        if isinstance(event_usage, dict):
            for k in ("input_tokens", "output_tokens"):
                v = event_usage.get(k)
                if v:
                    usage[k] = int(v)
    return usage
