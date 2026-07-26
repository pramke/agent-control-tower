"""诱饵密钥泄露检测，根据密钥出现在请求/响应中的位置区分被动泄露与主动窃取。"""

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.modules.detector.models import DetectionAlert, BaitCredential

logger = logging.getLogger(__name__)


async def detect_bait_key_theft(
    session: AsyncSession,
    project_id: int,
    model: str,
    endpoint: str,
    request_body: bytes,
    response_data: dict,
    request_hash: str,
) -> DetectionAlert | None:
    """检查响应中是否泄露了诱饵凭证，以及请求中是否包含已泄露的凭证。"""
    result = await session.execute(
        select(BaitCredential).where(
            BaitCredential.project_id == project_id,
            BaitCredential.active == True,
        )
    )
    bait_keys = result.scalars().all()
    if not bait_keys:
        return None

    request_text = request_body.decode("utf-8", errors="replace")
    response_text = json.dumps(response_data, ensure_ascii=False)

    findings = []
    for bk in bait_keys:
        in_request = bk.key_value in request_text
        in_response = bk.key_value in response_text

        # 仅响应中出现 = 被动泄露 (模型吐出了密钥)；同时出现于请求 = 疑似用户主动利用泄露凭证 (更严重)
        # 如果仅存在于请求中不视为泄露 — 那只是用户正常发送给模型的内容
        if not in_response:
            continue

        findings.append({
            "bait_id": bk.id,
            "key_type": bk.key_type,
            "label": bk.label,
            "in_request": in_request,
            "in_response": True,
        })

    if not findings:
        return None

    # 如果有诱饵密钥在请求中也出现过，说明用户在主动窃取
    exfiltrated = [f for f in findings if f["in_request"]]
    severity = "critical" if exfiltrated else "high"

    leaked = exfiltrated if exfiltrated else findings
    key_names = ", ".join(f"{f['key_type']}({f['label'] or '无标签'})" for f in leaked)

    return DetectionAlert(
        project_id=project_id,
        alert_type="bait_key_theft",
        severity=severity,
        title=f"诱饵凭证泄露: {key_names}",
        description=(
            f"检测到 {len(findings)} 个诱饵凭证出现在响应中"
            + (f"，其中 {len(exfiltrated)} 个曾在请求中出现（疑似窃取）" if exfiltrated else "（被动泄露）")
        ),
        evidence=json.dumps(findings, ensure_ascii=False),
        model=model,
        endpoint=endpoint,
        request_hash=request_hash,
    )
