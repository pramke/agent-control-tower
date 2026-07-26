"""检测 LLM 响应中的可疑内容：密钥泄露、脚本注入、非预期字段等。"""

import json
import re
import logging

from backend.modules.detector.models import DetectionAlert

logger = logging.getLogger(__name__)

# (pattern_name, regex, severity) — 按风险等级从高到低排列，早匹配早阻断
SUSPICIOUS_PATTERNS: list[tuple[str, str, str]] = [
    ("eval_exec", r"\b(eval|exec|system|popen|subprocess|os\.system|__import__)\s*\(", "high"),
    ("script_tag", r"<script[^>]*>.*?</script>", "high"),
    ("event_handler", r"\bon\w+\s*=\s*['\"].*?['\"]", "high"),
    ("aws_key", r"AKIA[0-9A-Z]{16}", "critical"),
    ("openai_key", r"sk-[a-zA-Z0-9]{20,}", "critical"),
    ("github_token", r"ghp_[a-zA-Z0-9]{36}", "critical"),
    ("generic_api_key", r"(?i)(api[_-]?key|apikey|secret)[=:]['\"]?[a-zA-Z0-9_\-]{16,}", "high"),
    ("webhook_url", r"https?://[^\s'\")\]]*webhook[^\s'\")\]]*", "medium"),
    ("tunnel_url", r"https?://[^\s'\")\]]*\.(ngrok|poke|requestbin|trycloudflare)\.(io|com)[^\s'\")\]]*", "high"),
    ("base64_long", r"[A-Za-z0-9+/]{60,}={0,2}", "medium"),
]

# 标准 Anthropic Messages API 响应字段白名单
EXPECTED_RESPONSE_KEYS = {
    "id", "type", "role", "content", "model", "stop_reason",
    "stop_sequence", "usage", "input_tokens", "output_tokens",
    "raw",
}
# content[] 中每个 block 的标准字段
EXPECTED_CONTENT_BLOCK_KEYS = {
    "type", "text", "id", "name", "input", "content",
    "tool_use_id", "tool_name", "tool_input",
    "thinking", "signature",
}


def _check_unexpected_fields(response_data: dict) -> list[str]:
    """检查响应中是否存在白名单之外的字段（可能为模型"幻觉"字段）。"""
    # 逐层检查 root、content[]、usage 三个层级的字段是否在白名单内
    unexpected = []
    for key in response_data:
        if key not in EXPECTED_RESPONSE_KEYS and not key.startswith("_"):
            unexpected.append(f"root.{key}")

    content = response_data.get("content", [])
    if isinstance(content, list):
        for i, block in enumerate(content):
            if isinstance(block, dict):
                for key in block:
                    if key not in EXPECTED_CONTENT_BLOCK_KEYS:
                        unexpected.append(f"content[{i}].{key}")

    usage = response_data.get("usage")
    if isinstance(usage, dict):
        for key in usage:
            if key not in {"input_tokens", "output_tokens", "cache_read_input_tokens",
                            "cache_creation_input_tokens", "cache_creation_output_tokens",
                            "service_tier"}:
                unexpected.append(f"usage.{key}")

    return unexpected


async def detect_json_injection(
    project_id: int,
    model: str,
    endpoint: str,
    response_data: dict,
    request_body: bytes,
    request_hash: str,
) -> DetectionAlert | None:
    """检测 LLM 响应中的注入内容。返回 DetectionAlert 或 None。"""
    response_text = json.dumps(response_data, ensure_ascii=False)

    findings = []
    for name, pattern, severity in SUSPICIOUS_PATTERNS:
        matches = re.findall(pattern, response_text)
        if matches:
            findings.append({
                "pattern_name": name,
                "severity": severity,
                "match_count": len(matches),
                "samples": [m[:80] for m in matches[:3]],
            })

    extra_fields = _check_unexpected_fields(response_data)
    if extra_fields:
        findings.append({
            "pattern_name": "unexpected_fields",
            "severity": "medium",
            "match_count": len(extra_fields),
            "samples": extra_fields[:5],
        })

    if not findings:
        return None

    # 告警严重度取所有匹配项中的最高级别，避免多个低危项掩盖高危项
    severity_map = {"critical": "critical", "high": "high", "medium": "medium", "low": "low"}
    max_sev = max(f["severity"] for f in findings)

    pattern_summary = "; ".join(
        f"{f['pattern_name']}: {f['match_count']} 处"
        for f in findings
    )

    return DetectionAlert(
        project_id=project_id,
        alert_type="json_injection",
        severity=severity_map.get(max_sev, "medium"),
        title=f"响应中发现可疑内容: {', '.join(f['pattern_name'] for f in findings)}",
        description=f"扫描发现 {len(findings)} 类可疑模式: {pattern_summary}",
        evidence=json.dumps(findings, ensure_ascii=False),
        model=model,
        endpoint=endpoint,
        request_hash=request_hash,
    )
