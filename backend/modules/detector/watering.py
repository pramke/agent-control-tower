"""通过分析 TPS 分布判断模型是否被替换（掺水），并推测实际使用的模型。"""

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.modules.models.api_call import ApiCall
from backend.modules.detector.models import DetectionAlert
from backend.modules.detector.fingerprints import MODEL_FINGERPRINTS

logger = logging.getLogger(__name__)

ANALYSIS_WINDOW = 50       # 取最近 50 次调用做分析
MIN_OUTPUT_TOKENS = 20     # 输出太短的调用不参与计算
TPS_TOLERANCE_LOW = 0.5    # TPS 下限 = 中位数 × 0.5
TPS_TOLERANCE_HIGH = 1.8   # TPS 上限 = 中位数 × 1.8


async def detect_model_watering(
    session: AsyncSession,
    project_id: int,
    claimed_model: str,
    response_data: dict,
    latency_ms: float,
    request_hash: str,
) -> DetectionAlert | None:
    """判断当前调用 + 历史调用的 TPS 分布是否与声称模型一致。"""
    actual_model = response_data.get("model") or claimed_model

    usage = response_data.get("usage", {})
    output_tokens = usage.get("output_tokens", 0) or 0
    if output_tokens < MIN_OUTPUT_TOKENS or latency_ms <= 0:
        return None

    # 取历史调用数据
    result = await session.execute(
        select(ApiCall.output_tokens, ApiCall.latency_ms)
        .where(
            ApiCall.project_id == project_id,
            ApiCall.model == actual_model,
            ApiCall.output_tokens >= MIN_OUTPUT_TOKENS,
        )
        .order_by(ApiCall.timestamp.desc())
        .limit(ANALYSIS_WINDOW)
    )
    rows = result.all()

    # 将当前调用纳入样本集，保证检测能反映最新状态
    samples = [(output_tokens, latency_ms)]
    for r in rows:
        if r.latency_ms > 0 and r.output_tokens >= MIN_OUTPUT_TOKENS:
            samples.append((r.output_tokens, r.latency_ms))

    # 样本不足不触发检测，避免小样本导致的误判
    if len(samples) < 3:
        return None

    # 计算每个样本的 TPS = tokens / seconds
    tps_values = [out / (lat / 1000) for out, lat in samples]

    sorted_tps = sorted(tps_values)
    median_tps = sorted_tps[len(sorted_tps) // 2]

    tps_low = median_tps * TPS_TOLERANCE_LOW
    tps_high = median_tps * TPS_TOLERANCE_HIGH

    matched = sum(1 for t in tps_values if tps_low <= t <= tps_high)
    purity = round(matched / len(samples) * 100, 1)

    # 90% 为容忍阈值：允许少量波动（如网络抖动），不误报
    if purity >= 90:
        return None

    # 异常值聚类，推测实际模型
    outliers = [t for t in tps_values if t < tps_low or t > tps_high]
    clusters = _cluster_tps(outliers)

    cluster_desc_parts = []
    for center, count in sorted(clusters, key=lambda x: -x[1]):
        guessed = _guess_model_by_tps(center, claimed_model)
        pct = round(count / len(samples) * 100, 1)
        cluster_desc_parts.append(f"{pct}% 调用速度约 {center:.0f} token/s ({guessed})")

    cluster_text = ""
    if cluster_desc_parts:
        cluster_text = "疑似混用: " + "; ".join(cluster_desc_parts)

    severity = "critical" if purity < 50 else "high" if purity < 70 else "medium"

    return DetectionAlert(
        project_id=project_id,
        alert_type="model_watering",
        severity=severity,
        title=f"模型纯净度 {purity}% — {actual_model} 疑似被掺水替换",
        description=(
            f"实际模型 '{actual_model}' 的 {len(samples)} 次调用中 "
            f"仅 {pct_str(matched, len(samples))} 符合该模型的速度特征。"
            + (f" {cluster_text}" if cluster_text else "")
        ),
        evidence=json.dumps({
            "claimed_model": claimed_model,
            "actual_model": actual_model,
            "purity": purity,
            "total_samples": len(samples),
            "matched": matched,
            "median_tps": round(median_tps, 1),
            "tps_range": [round(tps_low, 1), round(tps_high, 1)],
            "tps_values": [round(t, 1) for t in tps_values],
            "clusters": [
                {"tps_center": round(c, 1), "count": cnt}
                for c, cnt in clusters
            ],
        }),
        model=actual_model,
        request_hash=request_hash,
    )


def _cluster_tps(values: list[float], bucket_size: float = 50.0) -> list[tuple[float, int]]:
    """将 TPS 值按 50 区间分桶聚类，返回 [(中心值, 数量)]。

    50 token/s 的桶宽旨在区分不同模型族（如 Haiku ~80 vs Sonnet ~40）。
    """
    if not values:
        return []
    buckets: dict[int, list[float]] = {}
    for v in values:
        key = int(v // bucket_size)
        buckets.setdefault(key, []).append(v)
    result = []
    for key, vals in buckets.items():
        center = sum(vals) / len(vals)
        result.append((center, len(vals)))
    result.sort(key=lambda x: -x[1])
    return result


def _guess_model_by_tps(tps: float, exclude: str) -> str:
    """根据 TPS 值与 MODEL_FINGERPRINTS 匹配，推测实际使用的模型。"""
    best = None
    best_diff = float("inf")
    for name, fp in MODEL_FINGERPRINTS.items():
        if name == exclude:
            continue
        mid = (fp["tokens_per_second"][0] + fp["tokens_per_second"][1]) / 2
        diff = abs(tps - mid)
        if diff < best_diff:
            best = name
            best_diff = diff
    return best or "未知模型"


def pct_str(n: int, total: int) -> str:
    """格式化百分比字符串：如 '3/5 (60.0%)'"""
    return f"{n}/{total} ({round(n / total * 100, 1)}%)"
