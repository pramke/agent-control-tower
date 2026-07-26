"""提示注入检测与防护：识别系统提示覆盖、指令注入、分隔符越狱等攻击模式。"""

import logging
import re
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class GuardAction(str, Enum):
    """安全护栏响应动作枚举。"""
    block = "block"       # 拒绝请求
    warn = "warn"         # 仅记录日志，不阻断
    sanitize = "sanitize"  # 过滤掉恶意内容后放行


@dataclass
class InjectionResult:
    """一次注入检测的结果。"""
    detected: bool = False
    action: str = "warn"
    severity: str = "low"  # low, medium, high, critical
    pattern: str = ""
    matched_text: str = ""
    sanitized_text: str = ""
    reason: str = ""


# ---------------------------------------------------------------------------
# Injection patterns: (regex, severity, action, description)
# ---------------------------------------------------------------------------

INJECTION_PATTERNS: list[tuple[str, str, str, str]] = [
    # 忽略前置指令注入
    (r"ignore\s+(all\s+)?(previous|above|prior)\s+(instructions?|prompts?|directives?)",
     "high", "block", "Ignore-previous-instructions injection"),
    # DAN / Jailbreak 角色扮演
    (r"(you\s+are|act\s+as|pretend\s+to\s+be)\s+(now\s+)?(a\s+)?(DAN|jailbreak|evil|unethical)",
     "critical", "block", "Role-play jailbreak (DAN/evil persona)"),
    # 系统/指令分隔符注入
    (r"\[SYSTEM\]|\[INST\]|\[ASSISTANT\]|<\s*\|?\s*(system|instruction|prompt|endoftext)\s*\|?\s*>",
     "high", "block", "System/instruction delimiter injection"),
    # 系统提示覆盖尝试
    (r"(disregard|override|overwrite|delete)\s+(the\s+)?(system\s+)?(prompt|instructions?|rules?)",
     "high", "block", "System prompt override attempt"),
    # XSS / HTML 注入
    (r"<script\b[^>]*>|javascript\s*:|on\w+\s*=\s*\"",
     "medium", "sanitize", "XSS/HTML injection in user input"),
    # 提权短语
    (r"(sudo|root|admin)\s+(mode|access|privilege)",
     "medium", "warn", "Privilege escalation phrase"),
    # 系统提示提取尝试
    (r"(reveal|show|print|tell\s+me)\s+(your|the)\s+(system\s+)?(prompt|instructions?|rules?|initial)",
     "high", "block", "System prompt extraction attempt"),
    # 模板引擎注入（Jinja2 / Liquid）
    (r"(\{\{.*?\}\}|\{\%.*?\%\})",
     "medium", "warn", "Template injection (Jinja2/Liquid)"),
    # 编码混淆内容（十六进制 / URL 编码多次重复）
    (r"(\\x[0-9a-fA-F]{2}|%[0-9a-fA-F]{2}){4,}",
     "low", "sanitize", "Encoded/obfuscated content"),
]


def detect_injection(text: str, default_action: GuardAction = GuardAction.warn) -> InjectionResult:
    """Scan text for injection patterns. Returns the first high-severity match found."""
    if not text:
        return InjectionResult()

    highest: InjectionResult | None = None
    for pattern, severity, action, description in INJECTION_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            result = InjectionResult(
                detected=True,
                action=action,
                severity=severity,
                pattern=pattern,
                matched_text=match.group(0),
                reason=description,
            )
            # critical 级别命中即判定为攻击，无需继续扫描其余模式
            if severity == "critical":
                return result
            # 非 critical 时继续匹配，最终返回严重度最高的结果
            if highest is None or _severity_rank(severity) > _severity_rank(highest.severity):
                highest = result

    return highest or InjectionResult()


def _severity_rank(s: str) -> int:
    """严重等级 → 数值排序（用于比较）。"""
    return {"low": 0, "medium": 1, "high": 2, "critical": 3}.get(s, 0)


def sanitize_injection(text: str) -> str:
    """Remove known injection patterns from text."""
    for pattern, severity, action, _description in INJECTION_PATTERNS:
        if action in ("block", "sanitize"):
            text = re.sub(pattern, "[FILTERED]", text, flags=re.IGNORECASE | re.DOTALL)
    return text


def check_prompt(prompt: str, block_on: str = "high") -> tuple[bool, str, str | None]:
    """Check a user prompt for prompt injection. Returns (safe, sanitized_prompt, reason).

    - block_on="critical": only block critical-level injections
    - block_on="high":      block high and critical
    - block_on="medium":    block medium and above
    """
    result = detect_injection(prompt)
    if not result.detected:
        return True, prompt, None

    severity_rank = _severity_rank(result.severity)
    block_rank = _severity_rank(block_on)

    # sanitize 动作：移除恶意内容后放行，不阻断用户请求
    if result.action == "sanitize":
        sanitized = sanitize_injection(prompt)
        logger.info("Sanitized injection pattern '%s' in prompt", result.reason)
        return True, sanitized, result.reason

    # 严重度超过 block_on 阈值：直接拒绝请求
    if severity_rank >= block_rank:
        logger.warning("Blocked prompt with %s severity injection: %s", result.severity, result.reason)
        return False, prompt, f"{result.reason}: {result.matched_text[:100]}"

    # 低于阈值：仅记录日志
    logger.info("Warn: detected %s injection: %s", result.severity, result.reason)
    return True, prompt, None
