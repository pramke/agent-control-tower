"""Anthropic Messages API 与 OpenAI Chat Completions API 之间的请求/响应/流式 SSE 双向格式转换。"""
import json
import uuid
import logging
from typing import AsyncIterator

logger = logging.getLogger(__name__)

# ── finish_reason ↔ stop_reason 映射 ──────────────────────────────────
_FINISH_TO_STOP = {
    "stop": "end_turn",
    "length": "max_tokens",
    "tool_calls": "tool_use",
    "content_filter": "end_turn",
}
_STOP_TO_FINISH = {
    "end_turn": "stop",
    "max_tokens": "length",
    "tool_use": "tool_calls",
    "stop_sequence": "stop",
    "refusal": "content_filter",
}

# ── 请求转换 ──────────────────────────────────────────────────────────

def anthropic_to_openai_request(body: bytes, target_model: str | None = None) -> bytes:
    """将 Anthropic Messages API 请求体转换为 OpenAI Chat Completions 格式。"""
    data = json.loads(body.decode("utf-8", errors="replace"))

    # ── target_model 替换 ──
    if target_model:
        data["model"] = target_model

    # ── system 从顶层移入 messages ──
    # Anthropic 将 system 作为顶层字段；OpenAI 则作为 messages 数组中的 role=system 消息
    system = data.pop("system", None)
    if system:
        if isinstance(system, list):
            system = "\n\n".join(
                b.get("text", "") for b in system if isinstance(b, dict) and b.get("type") == "text"
            )
        if system and isinstance(system, str):
            data.setdefault("messages", [])
            data["messages"].insert(0, {"role": "system", "content": system})

    # ── messages 转换 ──
    if "messages" in data:
        data["messages"] = _convert_messages_forward(data["messages"])

    # ── tools 转换 ──
    if "tools" in data:
        data["tools"] = _convert_tools_forward(data["tools"])

    # ── tool_choice 转换 ──
    if "tool_choice" in data:
        data["tool_choice"] = _convert_tool_choice_forward(data["tool_choice"])

    # ── stop_sequences → stop ──
    if "stop_sequences" in data:
        data["stop"] = data.pop("stop_sequences")

    # ── 移除 Anthropic 独有字段 ──
    for key in ("top_k", "thinking", "output_config"):
        data.pop(key, None)

    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def _convert_messages_forward(messages: list[dict]) -> list[dict]:
    """Anthropic messages → OpenAI messages。"""
    result = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")

        if role == "user":
            if isinstance(content, str):
                result.append({"role": "user", "content": content})
            elif isinstance(content, list):
                text_parts = []
                tool_results = []
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_result":
                        tool_results.append(block)
                    elif block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                if text_parts:
                    result.append({"role": "user", "content": "\n".join(text_parts)})
                for tr in tool_results:
                    tr_content = tr.get("content", "")
                    if isinstance(tr_content, list):
                        tr_content = "\n".join(
                            b.get("text", "") for b in tr_content
                            if isinstance(b, dict) and b.get("type") == "text"
                        )
                    result.append({
                        "role": "tool",
                        "tool_call_id": tr.get("tool_use_id", ""),
                        "content": str(tr_content),
                    })

        elif role == "assistant":
            if isinstance(content, str):
                result.append({"role": "assistant", "content": content})
            elif isinstance(content, list):
                text_parts = []
                tool_calls = []
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_use":
                        tool_calls.append({
                            "id": block.get("id", ""),
                            "type": "function",
                            "function": {
                                "name": block.get("name", ""),
                                "arguments": json.dumps(block.get("input", {}), ensure_ascii=False),
                            },
                        })
                entry: dict = {"role": "assistant"}
                if text_parts:
                    entry["content"] = "\n".join(text_parts)
                elif tool_calls:
                    entry["content"] = None
                if tool_calls:
                    entry["tool_calls"] = tool_calls
                result.append(entry)
        else:
            result.append(msg)

    return result


def _convert_tools_forward(tools: list[dict]) -> list[dict]:
    """Anthropic tools → OpenAI tools（外覆 type: function 信封，input_schema → parameters）。"""
    converted = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        converted.append({
            "type": "function",
            "function": {
                "name": tool.get("name", ""),
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema", {}),
            },
        })
    return converted


def _convert_tool_choice_forward(tc: dict) -> str | dict:
    """Anthropic tool_choice → OpenAI tool_choice。"""
    t = tc.get("type", "auto") if isinstance(tc, dict) else "auto"
    if t == "auto":
        return "auto"
    if t == "any":
        return "required"
    if t == "tool":
        return {"type": "function", "function": {"name": tc.get("name", "")}}
    return "auto"


# ── 非流式响应转换 ────────────────────────────────────────────────────

def openai_to_anthropic_response(data: dict, model: str = "unknown") -> dict:
    """将 OpenAI Chat Completions 响应转换为 Anthropic Messages 格式。"""
    # 错误响应直接透传
    if "error" in data:
        return data

    choices = data.get("choices", [])
    choice = choices[0] if choices else {}
    message = choice.get("message", {})

    # ── content blocks ──
    content_blocks = []
    text = message.get("content")
    if text:
        content_blocks.append({"type": "text", "text": text})

    # ── tool_calls → tool_use blocks ──
    tool_calls = message.get("tool_calls") or []
    for tc in tool_calls:
        fn = tc.get("function", {})
        try:
            args = json.loads(fn.get("arguments", "{}"))
        except (json.JSONDecodeError, TypeError):
            args = {}
        content_blocks.append({
            "type": "tool_use",
            "id": tc.get("id", ""),
            "name": fn.get("name", ""),
            "input": args,
        })

    # ── stop_reason ──
    finish_reason = choice.get("finish_reason")
    stop_reason = _FINISH_TO_STOP.get(finish_reason or "", "end_turn")

    # ── usage ──
    usage_src = data.get("usage", {})
    usage = {}
    if isinstance(usage_src, dict):
        if "prompt_tokens" in usage_src:
            usage["input_tokens"] = int(usage_src["prompt_tokens"])
        if "completion_tokens" in usage_src:
            usage["output_tokens"] = int(usage_src["completion_tokens"])
        details = usage_src.get("prompt_tokens_details", {})
        if isinstance(details, dict) and details.get("cached_tokens"):
            usage["cache_read_input_tokens"] = int(details["cached_tokens"])

    return {
        "id": f"msg_{uuid.uuid4().hex[:24]}",
        "type": "message",
        "role": "assistant",
        "model": data.get("model", model),
        "content": content_blocks if content_blocks else [{"type": "text", "text": ""}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": usage,
    }


# ── 流式 SSE 适配器 ──────────────────────────────────────────────────

class OpenAIStreamToAnthropic:
    """将 OpenAI SSE 字节流转换为 Anthropic SSE 事件流。"""

    def __init__(self, source: AsyncIterator[bytes], message_id: str, model: str):
        self._source = source
        self._message_id = message_id
        self._model = model
        self._buffer = b""
        self._sent_message_start = False
        # 追踪已开始的 content block 类型及索引，Anthropic 要求每个 block 以 start → delta → stop 为生命周期
        self._content_blocks_started: list[str] = []  # "text" | "tool_use"
        self._tool_states: dict[int, dict] = {}       # index → {id, name, active}
        self._current_tool_index: int = -1  # 最后一个活跃 tool call index，用于检测工具切换时关闭前一个 block
        self._input_tokens = 0
        self._output_tokens = 0
        self._finish_reason: str | None = None

    def __aiter__(self):
        return self._run()

    async def _run(self) -> AsyncIterator[bytes]:
        async for chunk in self._source:
            self._buffer += chunk
            while b"\n" in self._buffer:
                line, self._buffer = self._buffer.split(b"\n", 1)
                line = line.strip()
                if not line.startswith(b"data: "):
                    continue
                payload_str = line[6:]
                if payload_str == b"[DONE]":
                    for event_bytes in self._emit_final_events():
                        yield event_bytes
                    return
                try:
                    event = json.loads(payload_str.decode("utf-8", errors="replace"))
                except (json.JSONDecodeError, TypeError):
                    continue
                if not isinstance(event, dict):
                    continue
                for event_bytes in self._handle_chunk(event):
                    yield event_bytes

    def _handle_chunk(self, event: dict):
        """处理单个 OpenAI chunk，yield 对应的 Anthropic SSE 事件字节。"""
        choices = event.get("choices", [])
        choice = choices[0] if choices else {}
        delta = choice.get("delta", {})
        finish_reason = choice.get("finish_reason")

        # ── 首个 chunk：message_start ──
        if not self._sent_message_start:
            usage_src = event.get("usage", {})
            if isinstance(usage_src, dict):
                self._input_tokens = int(usage_src.get("prompt_tokens", 0))
            yield _sse("message_start", {
                "type": "message_start",
                "message": {
                    "id": self._message_id,
                    "type": "message",
                    "role": "assistant",
                    "model": self._model,
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": self._input_tokens},
                },
            })
            self._sent_message_start = True

        # ── text delta ──
        text = delta.get("content")
        if isinstance(text, str) and text:
            if "text" not in self._content_blocks_started:
                self._content_blocks_started.append("text")
                idx = len(self._content_blocks_started) - 1
                yield _sse("content_block_start", {
                    "type": "content_block_start",
                    "index": idx,
                    "content_block": {"type": "text", "text": ""},
                })
            idx = self._content_blocks_started.index("text")
            yield _sse("content_block_delta", {
                "type": "content_block_delta",
                "index": idx,
                "delta": {"type": "text_delta", "text": text},
            })

        # ── tool_calls delta ──
        tool_calls = delta.get("tool_calls") or []
        for tc in tool_calls:
            ti = tc.get("index", 0)
            fn = tc.get("function", {})

            # Close previous tool block if we switched to a new index
            if self._current_tool_index >= 0 and ti != self._current_tool_index:
                yield _sse("content_block_stop", {
                    "type": "content_block_stop",
                    "index": self._content_blocks_started.index("tool_use") if "tool_use" in self._content_blocks_started else 0,
                })

            if ti not in self._tool_states:
                self._tool_states[ti] = {
                    "id": tc.get("id") or fn.get("name", ""),
                    "name": fn.get("name", ""),
                    "active": True,
                }
                self._current_tool_index = ti
                if "tool_use" not in self._content_blocks_started:
                    self._content_blocks_started.append("tool_use")
                idx = self._content_blocks_started.index("tool_use")
                yield _sse("content_block_start", {
                    "type": "content_block_start",
                    "index": idx,
                    "content_block": {
                        "type": "tool_use",
                        "id": self._tool_states[ti]["id"],
                        "name": self._tool_states[ti]["name"],
                        "input": {},
                    },
                })

            args = fn.get("arguments", "")
            if args:
                idx = self._content_blocks_started.index("tool_use") if "tool_use" in self._content_blocks_started else 0
                yield _sse("content_block_delta", {
                    "type": "content_block_delta",
                    "index": idx,
                    "delta": {"type": "input_json_delta", "partial_json": args},
                })

        # ── usage ──
        event_usage = event.get("usage", {})
        if isinstance(event_usage, dict):
            if event_usage.get("completion_tokens"):
                self._output_tokens = int(event_usage["completion_tokens"])

        # ── finish_reason ──
        if finish_reason:
            self._finish_reason = finish_reason

    def _emit_final_events(self):
        """流结束时，输出最后的 content_block_stop + message_delta + message_stop。"""
        stop_reason = _FINISH_TO_STOP.get(self._finish_reason or "", "end_turn")

        # 关闭所有已开始的 content block
        for i, block_type in enumerate(self._content_blocks_started):
            yield _sse("content_block_stop", {
                "type": "content_block_stop",
                "index": i,
            })

        # 关闭某些 tool block 可能还没 close（如果最后一个 chunk 就是 tool call）
        if self._current_tool_index >= 0 and "tool_use" in self._content_blocks_started:
            pass  # content_block_stop already emitted above via the loop

        yield _sse("message_delta", {
            "type": "message_delta",
            "delta": {"stop_reason": stop_reason, "stop_sequence": None},
            "usage": {"output_tokens": self._output_tokens},
        })

        yield _sse("message_stop", {"type": "message_stop"})


def _sse(event_type: str, data: dict) -> bytes:
    """格式化一条 Anthropic SSE 事件。"""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {payload}\n\n".encode("utf-8")
