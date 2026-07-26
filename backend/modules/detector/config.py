"""检测配置管理，支持项目级 JSON 覆盖配置通过 deep_merge 与默认值合并。"""

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession as AsyncSessionType

from backend.modules.models.project import Project

logger = logging.getLogger(__name__)

# 检测器默认配置：所有检测器默认开启
DEFAULT_CONFIG = {
    "enabled": True,
    "model_watering": {
        "enabled": True,
        "purity_threshold_warn": 90,
        "purity_threshold_alert": 70,
    },
    "json_injection": {
        "enabled": True,
    },
    "bait_key_theft": {
        "enabled": True,
    },
}


def deep_merge(base: dict, override: dict) -> dict:
    """递归合并两个字典，嵌套字段按粒度覆盖而非整块替换 — 例如只覆盖 model_watering.purity_threshold_warn 而保留其他阈值。"""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


async def load_detector_config(session: AsyncSessionType, project_id: int) -> dict:
    """加载指定项目的检测器配置（DEFAULT_CONFIG + 项目覆盖）。"""
    project = await session.get(Project, project_id)
    if project and project.detection_config:
        try:
            overrides = json.loads(project.detection_config)
            return deep_merge(DEFAULT_CONFIG, overrides)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Invalid detection_config JSON for project %d", project_id)
    return dict(DEFAULT_CONFIG)
