"""基于关键词的内容审核：检测色情、暴力、仇恨言论、政治敏感、自残等内容。"""

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ContentFlag:
    """一条内容标记：包含分类、严重度、匹配关键词和推荐动作。"""
    category: str
    severity: str  # low, medium, high
    matched_keywords: list[str]
    action: str  # block, warn, log


# ---------------------------------------------------------------------------
# Keyword dictionaries (minimal sample sets — extend for production)
# ---------------------------------------------------------------------------

# Note: these are minimal representative sets. Production should use a proper
# moderation model or comprehensive keyword lists from a content safety vendor.

SEXUAL_KEYWORDS: list[str] = [
    "色情", "裸体", "性交", "性爱",
    "porn", "xxx", "adult content",
]

VIOLENCE_KEYWORDS: list[str] = [
    "恐怖主义", "炸弹制作", "杀人",
    "terrorism", "bomb making", "how to kill",
]

HATE_SPEECH_KEYWORDS: list[str] = [
    "种族歧视", "种族灭绝",
    "hate speech", "racial slur",
]

SELF_HARM_KEYWORDS: list[str] = [
    "自杀", "自残", "割腕",
    "suicide", "self-harm", "kill myself",
]

POLITICAL_KEYWORDS: list[str] = [
    "推翻政府", "政变",
    "overthrow government", "coup d'etat",
]

ILLEGAL_KEYWORDS: list[str] = [
    "黑客攻击", "DDoS", "钓鱼网站",
    "hacking tutorial", "phishing", "malware creation",
]

# category → (keywords, default_action)
CATEGORIES: dict[str, tuple[list[str], str]] = {
    "sexual": (SEXUAL_KEYWORDS, "block"),
    "violence": (VIOLENCE_KEYWORDS, "block"),
    "hate_speech": (HATE_SPEECH_KEYWORDS, "block"),
    "self_harm": (SELF_HARM_KEYWORDS, "block"),
    "political": (POLITICAL_KEYWORDS, "warn"),
    "illegal": (ILLEGAL_KEYWORDS, "block"),
}


def check_content(text: str) -> list[ContentFlag]:
    """Scan text for sensitive/unsafe content. Returns list of flags found."""
    if not text:
        return []

    text_lower = text.lower()
    flags: list[ContentFlag] = []

    for category, (keywords, default_action) in CATEGORIES.items():
        matched = [kw for kw in keywords if kw.lower() in text_lower]
        if matched:
            # 匹配关键词越多，内容越可疑，严重度越高
            severity = "high" if len(matched) >= 3 else ("medium" if len(matched) >= 2 else "low")
            flags.append(ContentFlag(
                category=category,
                severity=severity,
                matched_keywords=matched,
                action=default_action if severity != "low" else "warn",
            ))

    return flags


def is_safe(text: str) -> tuple[bool, list[ContentFlag]]:
    """Check if content is safe. Returns (is_safe, flags)."""
    flags = check_content(text)
    blocked = [f for f in flags if f.action == "block"]
    return len(blocked) == 0, flags


def filter_content(text: str) -> tuple[bool, str, list[ContentFlag]]:
    """Filter content. Returns (allowed, result_text, flags).

    If blocked, result_text contains the reason.
    """
    flags = check_content(text)
    blocked = [f for f in flags if f.action == "block"]
    warnings = [f for f in flags if f.action == "warn"]

    # warn 级别不阻断，但记录日志供审计回溯
    for f in warnings:
        logger.warning("Content warning [%s/%s]: %s", f.category, f.severity, f.matched_keywords)

    if blocked:
        reasons = [f"{f.category}: {', '.join(f.matched_keywords)}" for f in blocked]
        logger.warning("Content blocked: %s", reasons)
        return False, f"内容被安全策略拦截: {'; '.join(reasons)}", flags

    return True, text, flags
