"""
模块: 后端 - 安全检测路由
功能: 安全告警查询、诱饵密钥管理、模型纯度检测
"""
import json
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.security import get_current_user
from backend.modules.models.project import Project
from backend.shared.errors import not_found
from backend.modules.models.api_call import ApiCall
from backend.modules.detector.models import DetectionAlert, BaitCredential
from backend.modules.detector.config import DEFAULT_CONFIG, deep_merge
from backend.modules.detector.fingerprints import get_fingerprint

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/detection", tags=["detection"])


# ─── 安全告警 ─────────────────────────────────────────────


@router.get("/{project_id}/alerts")
async def list_alerts(
    project_id: int,
    alert_type: str | None = Query(None),
    severity: str | None = Query(None),
    acknowledged: bool | None = Query(None),
    days: int = Query(default=7, ge=1, le=90),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _user = Depends(get_current_user),
):
    """
    分页查询安全告警 — 支持按类型、严重等级、确认状态过滤
    按检测时间倒序排列
    """
    since = datetime.now() - timedelta(days=days)

    query = select(DetectionAlert).where(
        DetectionAlert.project_id == project_id,
        DetectionAlert.detected_at >= since,
    )
    if alert_type:
        query = query.where(DetectionAlert.alert_type == alert_type)
    if severity:
        query = query.where(DetectionAlert.severity == severity)
    if acknowledged is not None:
        query = query.where(DetectionAlert.acknowledged == acknowledged)

    # 统计符合过滤条件的告警总数
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    result = await db.execute(
        query.order_by(desc(DetectionAlert.detected_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    alerts = result.scalars().all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_alert_to_dict(a) for a in alerts],
    }


@router.get("/{project_id}/alerts/{alert_id}")
async def get_alert(project_id: int, alert_id: int, db: AsyncSession = Depends(get_db), _user = Depends(get_current_user)):
    """获取单条告警的详细信息"""
    alert = await db.get(DetectionAlert, alert_id)
    if not alert or alert.project_id != project_id:
        not_found("Alert", alert_id)
    return _alert_to_dict(alert)


@router.post("/{project_id}/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(project_id: int, alert_id: int, db: AsyncSession = Depends(get_db), _user = Depends(get_current_user)):
    """确认（标记已处理）一条安全告警"""
    alert = await db.get(DetectionAlert, alert_id)
    if not alert or alert.project_id != project_id:
        not_found("Alert", alert_id)
    alert.acknowledged = True
    await db.commit()
    return {"ok": True}


@router.delete("/{project_id}/alerts/{alert_id}")
async def delete_alert(project_id: int, alert_id: int, db: AsyncSession = Depends(get_db), _user = Depends(get_current_user)):
    """删除一条安全告警"""
    alert = await db.get(DetectionAlert, alert_id)
    if not alert or alert.project_id != project_id:
        not_found("Alert", alert_id)
    await db.delete(alert)
    await db.commit()
    return {"ok": True}


# ─── 诱饵密钥管理 ─────────────────────────────────────────


class BaitCredentialCreate(BaseModel):
    """诱饵密钥创建请求体"""
    key_type: str
    key_value: str
    label: str = ""


@router.get("/{project_id}/bait-keys")
async def list_bait_keys(project_id: int, db: AsyncSession = Depends(get_db), _user = Depends(get_current_user)):
    """列出项目的全部诱饵密钥（用于检测第三方泄露）"""
    result = await db.execute(
        select(BaitCredential).where(BaitCredential.project_id == project_id)
        .order_by(desc(BaitCredential.created_at))
    )
    return [_bait_to_dict(k) for k in result.scalars().all()]


@router.post("/{project_id}/bait-keys")
async def create_bait_key(
    project_id: int, req: BaitCredentialCreate, db: AsyncSession = Depends(get_db),
    _user = Depends(get_current_user),
):
    """创建新的诱饵密钥 — 值会被掩码处理后返回"""
    project = await db.get(Project, project_id)
    if not project:
        not_found("Project", project_id)
    bait = BaitCredential(
        project_id=project_id, key_type=req.key_type,
        key_value=req.key_value, label=req.label,
    )
    db.add(bait)
    await db.commit()
    await db.refresh(bait)
    return _bait_to_dict(bait)


@router.delete("/{project_id}/bait-keys/{key_id}")
async def delete_bait_key(project_id: int, key_id: int, db: AsyncSession = Depends(get_db), _user = Depends(get_current_user)):
    """删除一个诱饵密钥"""
    bait = await db.get(BaitCredential, key_id)
    if not bait or bait.project_id != project_id:
        not_found("BaitKey", key_id)
    await db.delete(bait)
    await db.commit()
    return {"ok": True}


# ─── 模型纯度检测 ─────────────────────────────────────────


@router.get("/{project_id}/purity")
async def get_purity(
    project_id: int,
    days: int = Query(default=7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    _user = Depends(get_current_user),
):
    """
    模型纯度检测 — 通过 Token/秒 (TPS) 分布判断实际使用的模型是否与声明一致。
    主要逻辑：
      1. 遍历项目用过的所有模型
      2. 用指纹库获取每个模型预期的 TPS 范围
      3. 取最近 100 条有效调用的 TPS，以中位数 ±50% 为正常窗口
      4. 窗口内的调用数占比即为"纯度"百分比
    """
    since = datetime.now() - timedelta(days=days)

    # 获取该项目在时间范围内使用过的所有模型列表
    models_result = await db.execute(
        select(ApiCall.model)
        .where(ApiCall.project_id == project_id, ApiCall.timestamp >= since)
        .distinct()
    )
    models = [r[0] for r in models_result.all()]

    results = []
    for claimed_model in models:
        fp = get_fingerprint(claimed_model)
        # 指纹库中找不到该模型
        if not fp:
            results.append({
                "model": claimed_model,
                "purity": None,
                "total_calls": 0,
                "matched": 0,
                "tps_min": None,
                "tps_max": None,
                "reason": "unknown_model",
            })
            continue

        tps_range = fp.get("tokens_per_second")
        if not tps_range:
            continue

        # 获取该模型的有效调用数据（output_tokens >= 20 且 latency > 0）
        calls_result = await db.execute(
            select(ApiCall.output_tokens, ApiCall.latency_ms)
            .where(
                ApiCall.project_id == project_id,
                ApiCall.model == claimed_model,
                ApiCall.timestamp >= since,
                ApiCall.output_tokens >= 20,
                ApiCall.latency_ms > 0,
            )
            .order_by(ApiCall.timestamp.desc())
            .limit(100)
        )
        rows = calls_result.all()
        # 数据量不足 3 条时无法做统计学判断
        if len(rows) < 3:
            results.append({
                "model": claimed_model,
                "purity": None,
                "total_calls": len(rows),
                "matched": 0,
                "tps_min": tps_range[0],
                "tps_max": tps_range[1],
                "reason": "insufficient_data",
            })
            continue

        # 计算每条调用的 TPS，以中位数为基准确定正常窗口
        tps_values = [out / (lat / 1000) for out, lat in rows]
        sorted_tps = sorted(tps_values)
        median_tps = sorted_tps[len(sorted_tps) // 2]
        tps_low = median_tps * 0.5   # 下界：中位数的 50%
        tps_high = median_tps * 1.8  # 上界：中位数的 180%

        matched = sum(1 for t in tps_values if tps_low <= t <= tps_high)
        purity = round(matched / len(rows) * 100, 1)

        results.append({
            "model": claimed_model,
            "purity": purity,
            "total_calls": len(rows),
            "matched": matched,
            "tps_min": round(tps_low, 1),
            "tps_max": round(tps_high, 1),
            "tps_values": [round(t, 1) for t in tps_values],
            "reason": "ok",
        })

    return {"project_id": project_id, "models": results}


# ─── 检测配置管理 ─────────────────────────────────────────


@router.get("/{project_id}/config")
async def get_detection_config(project_id: int, db: AsyncSession = Depends(get_db), _user = Depends(get_current_user)):
    """获取项目的安全检测配置 — 若未自定义则返回系统默认配置"""
    project = await db.get(Project, project_id)
    if not project:
        not_found("Project", project_id)
    if project.detection_config:
        cfg = deep_merge(DEFAULT_CONFIG, json.loads(project.detection_config))
    else:
        cfg = dict(DEFAULT_CONFIG)
    return {"project_id": project_id, "config": cfg, "is_default": not bool(project.detection_config)}


class DetectionConfigUpdate(BaseModel):
    """检测配置更新请求体"""
    config: dict


@router.put("/{project_id}/config")
async def update_detection_config(
    project_id: int, req: DetectionConfigUpdate, db: AsyncSession = Depends(get_db),
    _user = Depends(get_current_user),
):
    """更新项目的安全检测配置（JSON 格式，将覆盖式写入 detection_config 字段）"""
    project = await db.get(Project, project_id)
    if not project:
        not_found("Project", project_id)
    project.detection_config = json.dumps(req.config, ensure_ascii=False)
    await db.commit()
    return {"ok": True}


# ─── 辅助函数 ─────────────────────────────────────────────


def _alert_to_dict(a: DetectionAlert) -> dict:
    """将 DetectionAlert ORM 对象转为可序列化的字典"""
    return {
        "id": a.id,
        "alert_type": a.alert_type,
        "severity": a.severity,
        "title": a.title,
        "description": a.description,
        "evidence": json.loads(a.evidence) if a.evidence else {},
        "model": a.model,
        "endpoint": a.endpoint,
        "request_hash": a.request_hash,
        "acknowledged": a.acknowledged,
        "detected_at": a.detected_at.isoformat() if a.detected_at else "",
    }


def _mask_key(key: str) -> str:
    """掩码处理密钥值 — 仅保留首尾若干字符，中间替换为 ****"""
    # <=12 字符的短密钥：前缀缩短至 4 字符，避免掩码后几乎可以反推原文
    if len(key) <= 12:
        return key[:4] + "****"
    return key[:6] + "****" + key[-4:]


def _bait_to_dict(k: BaitCredential) -> dict:
    """将 BaitCredential ORM 对象转为可序列化的字典（密钥值经掩码处理）"""
    return {
        "id": k.id,
        "key_type": k.key_type,
        "key_value": _mask_key(k.key_value),
        "label": k.label,
        "active": k.active,
        "created_at": k.created_at.isoformat() if k.created_at else "",
    }
