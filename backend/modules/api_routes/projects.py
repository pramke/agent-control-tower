"""
模块: 后端 - 项目管理路由
功能: 创建/删除项目，管理项目级别的 Agent 设置和环境变量
"""
import json
import os
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_serializer
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.core.database import get_db
from backend.core.security import get_current_user
from backend.modules.models.project import Project
from backend.shared.errors import conflict, not_found
from backend.modules.models.api_call import ApiCall
from backend.modules.detector.models import DetectionAlert, BaitCredential

router = APIRouter(prefix="/api/projects", tags=["projects"])


class CreateProjectRequest(BaseModel):
    """创建项目请求体"""
    name: str
    base_url: str
    api_key_upstream: str
    project_type: str = "monitor"  # monitor / agent / production
    target_model: str | None = None  # 代理目标模型，留空则使用默认映射规则
    provider_type: str = "anthropic"  # 上游 API 格式：anthropic | openai


class ProjectResponse(BaseModel):
    """项目响应体 — 创建成功后返回完整项目信息"""
    id: int
    name: str
    api_key: str
    base_url: str
    project_type: str
    created_at: datetime

    @field_serializer("created_at")
    def serialize_created_at(self, v: datetime) -> str:
        return v.isoformat()

    model_config = {"from_attributes": True}


async def _get_project(project_id: int, db: AsyncSession) -> Project:
    """获取项目，不存在则返回 404"""
    project = await db.get(Project, project_id)
    if not project:
        not_found("Project", project_id)
    return project


@router.get("")
async def list_projects(db: AsyncSession = Depends(get_db), _user = Depends(get_current_user)):
    """列出所有项目（所有登录用户可见）"""
    stmt = select(Project).order_by(Project.created_at.desc())
    result = await db.execute(stmt)
    projects = result.scalars().all()
    return [p.safe_dict() for p in projects]


@router.post("", response_model=ProjectResponse)
async def create_project(
    req: CreateProjectRequest,
    db: AsyncSession = Depends(get_db),
    _user = Depends(get_current_user),
):
    """创建项目 — 仅管理员和经理可操作"""
    existing = await db.execute(select(Project).where(Project.name == req.name))
    if existing.scalar_one_or_none():
        conflict("Project name already exists")

    api_key_plain, api_key_hash = Project.generate_api_key()
    project = Project(
        name=req.name,
        api_key=api_key_plain,
        api_key_hash=api_key_hash,
        base_url=req.base_url,
        api_key_upstream=req.api_key_upstream,
        project_type=req.project_type,
        target_model=req.target_model,
        provider_type=req.provider_type,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


@router.delete("/{project_id}")
async def delete_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _user = Depends(get_current_user),
):
    """删除项目及所有关联数据 — 仅管理员和经理可操作"""
    project = await _get_project(project_id, db)
    await db.execute(delete(ApiCall).where(ApiCall.project_id == project_id))
    await db.execute(delete(DetectionAlert).where(DetectionAlert.project_id == project_id))
    await db.execute(delete(BaitCredential).where(BaitCredential.project_id == project_id))
    await db.delete(project)
    await db.commit()
    return {"ok": True}


@router.get("/{project_id}/full")
async def get_project_full(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _user = Depends(get_current_user),
):
    """获取项目完整信息（所有登录用户可见）"""
    project = await _get_project(project_id, db)
    return {
        "id": project.id,
        "name": project.name,
        "api_key": project.api_key or "N/A",
        "base_url": project.base_url,
        "proxy_url": settings.proxy_url,
        "api_key_upstream": project.api_key_upstream,
        "project_type": project.project_type,
        "target_model": project.target_model or "",
        "provider_type": project.provider_type or "anthropic",
        "created_at": project.created_at.isoformat(),
    }


@router.post("/{project_id}/setup-env")
async def setup_env(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _user = Depends(get_current_user),
):
    """配置 Claude Desktop 环境变量 — 将项目代理地址和 API Key 写入 ~/.claude/settings.json"""
    project = await _get_project(project_id, db)

    settings_path = Path.home() / ".claude" / "settings.json"
    if settings_path.exists():
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                claude_settings = json.load(f)
        except (json.JSONDecodeError, IOError):
            claude_settings = {}
    else:
        claude_settings = {}

    if "env" not in claude_settings:
        claude_settings["env"] = {}

    # 写入 Claude Desktop 配置，让 Claude CLI 通过本代理服务转发请求
    claude_settings["env"]["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:8001/proxy"
    # 移除旧版 AUTH_TOKEN 键名（兼容早期版本），统一使用 ANTHROPIC_API_KEY
    claude_settings["env"].pop("ANTHROPIC_AUTH_TOKEN", None)
    claude_settings["env"]["ANTHROPIC_API_KEY"] = project.api_key

    os.makedirs(settings_path.parent, exist_ok=True)
    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(claude_settings, f, indent=2, ensure_ascii=False)

    return {"ok": True, "command": f'$env:ANTHROPIC_BASE_URL="http://127.0.0.1:8001/proxy"; $env:ANTHROPIC_API_KEY="{project.api_key}"; claude'}


class AgentSettingsUpdate(BaseModel):
    """Agent 设置更新请求体"""
    agent_model: str | None = None
    agent_api_key: str | None = None
    agent_base_url: str | None = None


@router.get("/{project_id}/agent-settings")
async def get_agent_settings(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _user = Depends(get_current_user),
):
    """获取项目级 Agent 设置（所有登录用户可见）"""
    project = await _get_project(project_id, db)

    using_global = not (project.agent_model or project.agent_api_key or project.agent_base_url)

    return {
        "agent_model": project.agent_model or settings.agent_model,
        "agent_api_key_set": bool(project.agent_api_key),
        "agent_base_url": project.agent_base_url or settings.agent_base_url,
        "using_global": using_global,
    }


@router.put("/{project_id}/agent-settings")
async def update_agent_settings(
    project_id: int,
    req: AgentSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    _user = Depends(get_current_user),
):
    """更新项目级 Agent 设置 — 仅管理员和经理可操作"""
    project = await _get_project(project_id, db)

    if req.agent_model is not None:
        project.agent_model = req.agent_model
    if req.agent_api_key is not None:
        project.agent_api_key = req.agent_api_key
    if req.agent_base_url is not None:
        project.agent_base_url = req.agent_base_url

    await db.commit()
    return {"ok": True}


class ProjectSettingsUpdate(BaseModel):
    """项目设置更新请求体"""
    target_model: str | None = None
    provider_type: str | None = None


@router.put("/{project_id}/settings")
async def update_project_settings(
    project_id: int,
    req: ProjectSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    _user = Depends(get_current_user),
):
    """更新项目设置（目标模型等）— 仅管理员和经理可操作"""
    project = await _get_project(project_id, db)

    if req.target_model is not None:
        project.target_model = req.target_model
    if req.provider_type is not None:
        project.provider_type = req.provider_type

    await db.commit()
    return {"ok": True}
