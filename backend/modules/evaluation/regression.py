"""Regression detection: compare two eval runs and flag if scores dropped >5%.

If the new run's average score is more than 5% worse than the baseline,
a regression alert is raised via the observability alerts module.
"""

import logging

from sqlalchemy import select

from backend.core.database import async_session
from backend.modules.evaluation.eval_model import EvalRun
from backend.modules.observability.alerts import create_alert

logger = logging.getLogger(__name__)

REGRESSION_THRESHOLD = 0.05  # 分数相对基线下降超过 5% 触发回归告警


async def detect_regression(
    baseline_run_id: int,
    new_run_id: int,
    threshold: float = REGRESSION_THRESHOLD,
) -> bool:
    """Compare two eval runs. Returns True if regression is detected.

    A regression alert is also created in the alerts table.
    """
    async with async_session() as session:
        baseline = await session.get(EvalRun, baseline_run_id)
        new_run = await session.get(EvalRun, new_run_id)

        if baseline is None or new_run is None:
            logger.warning("Cannot detect regression: run not found (baseline=%s, new=%s)",
                           baseline_run_id, new_run_id)
            return False

        # 基线分数必须 > 0 才可计算下降百分比，0 分基线无比较意义
        if baseline.average_score <= 0:
            return False

        drop = baseline.average_score - new_run.average_score
        drop_pct = drop / baseline.average_score

        if drop_pct > threshold:
            logger.warning(
                "Regression detected! Baseline %s (score %.4f) -> Run %s (score %.4f), drop: %.1f%%",
                baseline_run_id, baseline.average_score,
                new_run_id, new_run.average_score,
                drop_pct * 100,
            )
            # 向 alerts 系统写入回归告警
            await create_alert(
                category="eval_regression",
                level="warning",
                message=(
                    f"评估回归检测：Run #{new_run_id} 的平均分 ({new_run.average_score:.4f}) "
                    f"相较基线 Run #{baseline_run_id} ({baseline.average_score:.4f}) 下降了 "
                    f"{drop_pct:.1%}（阈值 {threshold:.0%}）"
                ),
                project_id=new_run.project_id,
                suggestion="检查模型配置变更和 Prompt 差异，考虑回滚到基线配置",
            )
            return True

        return False

