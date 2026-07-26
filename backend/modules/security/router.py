"""Security API: guardrails testing, sanitization demo, and content filter status.

提供三个端点供前端或外部系统调用：
- POST /api/security/guardrails/check   — 提示注入检测
- POST /api/security/sanitize           — 敏感数据脱敏
- POST /api/security/content/check      — 不安全内容检测
"""

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.core.security import get_current_user

from backend.modules.security.guardrails import check_prompt, detect_injection
from backend.modules.security.sanitizer import sanitize, has_sensitive_data
from backend.modules.security.content_filter import check_content, is_safe

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/security", tags=["security"])


class CheckPromptRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=10000)
    block_on: str = "high"


class SanitizeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=50000)


class ContentFilterRequest(BaseModel):
    text: str = Field(min_length=1, max_length=10000)


@router.post("/guardrails/check")
async def check_prompt_safety(req: CheckPromptRequest, _user = Depends(get_current_user)) -> dict:
    """Check a prompt for injection attacks."""
    # 并行调用 check_prompt（含阻断逻辑）和 detect_injection（仅检测）供前端展示
    safe, sanitized, reason = check_prompt(req.prompt, block_on=req.block_on)
    injection = detect_injection(req.prompt)
    return {
        "safe": safe,
        "sanitized": sanitized if not safe else req.prompt,
        "block_reason": reason,
        "injection_detected": injection.detected,
        "injection_severity": injection.severity,
        "injection_pattern": injection.pattern,
        "injection_reason": injection.reason,
    }


@router.post("/sanitize")
async def sanitize_text(req: SanitizeRequest, _user = Depends(get_current_user)) -> dict:
    """Sanitize text: mask sensitive data like phones, emails, IDs, API keys."""
    result, stats = sanitize(req.text)
    return {
        "original_length": len(req.text),
        "sanitized_text": result,
        "sanitized_length": len(result),
        "has_sensitive": has_sensitive_data(req.text),
        "stats": stats,
    }


@router.post("/content/check")
async def filter_content_endpoint(req: ContentFilterRequest, _user = Depends(get_current_user)) -> dict:
    """Check text for sensitive/unsafe content."""
    allowed, flags = is_safe(req.text)
    detailed = check_content(req.text)
    return {
        "safe": allowed,
        "flags_count": len(flags),
        "flags": [
            {
                "category": f.category,
                "severity": f.severity,
                "matched_keywords": f.matched_keywords,
                "action": f.action,
            }
            for f in flags
        ],
    }
