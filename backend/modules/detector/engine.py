"""安全检测引擎核心，按 model_watering → json_injection → bait_key_theft 顺序调度检测器，结果经去重后写入告警表。"""

import json
import logging
from datetime import datetime

from sqlalchemy import select, desc

from backend.core.database import async_session
from backend.modules.detector.config import load_detector_config
from backend.modules.detector.watering import detect_model_watering
from backend.modules.detector.json_injection import detect_json_injection
from backend.modules.detector.bait_keys import detect_bait_key_theft
from backend.modules.detector.models import DetectionAlert

logger = logging.getLogger(__name__)

# 去重窗口因类型而异：模型掺水是持续行为用长窗口(1h)，JSON 注入是瞬时攻击用短窗口(10min)
DEDUP_WINDOWS = {
    "model_watering": 3600,
    "json_injection": 600,
    "bait_key_theft": 3600,
}


def _alert_signature(alert: DetectionAlert) -> str:
    """为告警生成唯一签名，用于去重判断。"""
    base = f"{alert.alert_type}:{alert.project_id}"
    if alert.alert_type == "model_watering" and alert.model:
        return f"{base}:{alert.model}"
    if alert.alert_type == "json_injection" and alert.evidence:
        try:
            ev = json.loads(alert.evidence) if isinstance(alert.evidence, str) else alert.evidence
            if isinstance(ev, list):
                patterns = sorted(f.get("pattern_name", "") for f in ev if isinstance(f, dict))
                return f"{base}:" + ",".join(patterns)
        except (json.JSONDecodeError, TypeError):
            pass
    return base


async def _dedup_or_update(session, alert: DetectionAlert) -> DetectionAlert | None:
    """检查 DEDUP_WINDOWS 内是否已有同签名告警。
    
    若存在则更新其内容（title/description/evidence/severity/detected_at），
    返回 None 表示"已合并"；若不存在则返回 alert 本身供后续写入。
    """
    window = DEDUP_WINDOWS.get(alert.alert_type, 600)
    since_ts = datetime.now().timestamp() - window
    since_dt = datetime.fromtimestamp(since_ts)

    sig = _alert_signature(alert)

    query = select(DetectionAlert).where(
        DetectionAlert.project_id == alert.project_id,
        DetectionAlert.alert_type == alert.alert_type,
        DetectionAlert.acknowledged == False,
        DetectionAlert.detected_at >= since_dt,
    ).order_by(desc(DetectionAlert.detected_at))

    result = await session.execute(query)
    existing_alerts = result.scalars().all()

    for existing in existing_alerts:
        if _alert_signature(existing) == sig:
            existing.title = alert.title
            existing.description = alert.description
            existing.evidence = alert.evidence
            existing.severity = alert.severity
            existing.detected_at = datetime.now()
            return None

    return alert


async def run_detection(
    project_id: int,
    model: str,
    endpoint: str,
    response_data: dict,
    latency_ms: float,
    request_hash: str,
    request_body: bytes,
) -> None:
    """主检测入口：加载项目配置后依次运行所有启用的检测器。

    每个检测器错误独立捕获，不影响其他检测器。
    """
    async with async_session() as session:
        try:
            cfg = await load_detector_config(session, project_id)
            if not cfg.get("enabled", True):
                return

            alerts = []

            # 三个检测器的异常独立捕获，一个崩溃不影响其他检测器继续运行
            # 1) 模型掺水检测
            if cfg.get("model_watering", {}).get("enabled", True):
                try:
                    a = await detect_model_watering(
                        session, project_id, model, response_data, latency_ms, request_hash,
                    )
                    if a:
                        alerts.append(a)
                except Exception:
                    logger.exception("Model watering detection error")

            # 2) JSON 注入检测
            if cfg.get("json_injection", {}).get("enabled", True):
                try:
                    a = await detect_json_injection(
                        project_id, model, endpoint, response_data, request_body, request_hash,
                    )
                    if a:
                        alerts.append(a)
                except Exception:
                    logger.exception("JSON injection detection error")

            # 3) 诱饵密钥窃取检测
            if cfg.get("bait_key_theft", {}).get("enabled", True):
                try:
                    a = await detect_bait_key_theft(
                        session, project_id, model, endpoint, request_body, response_data, request_hash,
                    )
                    if a:
                        alerts.append(a)
                except Exception:
                    logger.exception("Bait key theft detection error")

            # 去重后批量写入
            for alert in alerts:
                alert = await _dedup_or_update(session, alert)
                if alert:
                    session.add(alert)
            if alerts:
                await session.commit()
                for a in alerts:
                    logger.warning(
                        "Detection [%s] [%s] project=%d: %s",
                        a.alert_type, a.severity, a.project_id, a.title,
                    )

        except Exception:
            logger.exception("Detection engine error for project %d", project_id)
