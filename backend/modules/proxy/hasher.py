"""请求内容哈希工具，对 messages 归一化后计算 SHA256，用于重复请求检测。"""

import hashlib
import json


def compute_request_hash(body: bytes) -> str:
    """计算请求体的 SHA256 哈希值。

    通过排序 messages（按 role:content 归一化），消除消息顺序差异，
    使完全相同的请求产生相同的哈希值。
    """
    try:
        data = json.loads(body)
        messages = data.get("messages", [])
        # 按 role:content 排序后再拼接，消除消息顺序差异（同一轮对话的不同排列产生相同哈希）
        normalized = sorted(
            [f"{m.get('role', '')}:{m.get('content', '')}" for m in messages]
        )
        raw = "|".join(normalized)
    except (json.JSONDecodeError, KeyError):
        raw = body.decode("utf-8", errors="replace")

    return hashlib.sha256(raw.encode()).hexdigest()
