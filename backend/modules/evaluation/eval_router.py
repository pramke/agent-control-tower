"""Evaluation API: CRUD for eval sets, cases, runs, and triggering evaluations.

端点按功能分组：
- /api/eval/sets/*     — 评估集 CRUD
- /api/eval/cases/*    — 评估用例 CRUD
- /api/eval/runs/*     — 评估运行 CRUD + 启动
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.security import get_current_user
from backend.modules.evaluation.eval_model import EvalCase, EvalRun, EvalScore, EvalSet
from backend.modules.evaluation.eval_runner import run_evaluation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/eval", tags=["evaluation"])


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class EvalSetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    scoring_method: str = "exact_match"
    pass_threshold: float = Field(default=0.8, ge=0, le=1)
    project_id: int | None = None


class EvalCaseCreate(BaseModel):
    eval_set_id: int
    input_text: str = Field(min_length=1)
    expected_output: str | None = None
    expected_tools: list[str] | None = None
    max_tokens: int = 2000
    weight: float = Field(default=1.0, ge=0.1, le=10.0)
    tags: list[str] | None = None


class EvalCaseBatch(BaseModel):
    cases: list[EvalCaseCreate]


class RunEvalRequest(BaseModel):
    eval_set_id: int
    model: str
    mode: str = "react"
    tools: list[str] = []
    project_id: int | None = None
    system_prompt: str | None = None
    baseline_run_id: int | None = None


# ---------------------------------------------------------------------------
# Eval Sets
# ---------------------------------------------------------------------------

@router.get("/sets")
async def list_eval_sets(
    project_id: int | None = None,
    limit: int = Query(default=50, le=200),
    db: AsyncSession = Depends(get_db),
    _user = Depends(get_current_user),
) -> list[dict]:
    """列出评估集（按创建时间倒序），可选按项目过滤。"""
    query = select(EvalSet).order_by(EvalSet.created_at.desc()).limit(limit)
    if project_id is not None:
        query = query.where(EvalSet.project_id == project_id)
    rows = (await db.execute(query)).scalars().all()
    return [r.to_dict() for r in rows]


@router.post("/sets")
async def create_eval_set(req: EvalSetCreate, db: AsyncSession = Depends(get_db), _user = Depends(get_current_user)) -> dict:
    """创建评估集（需要 admin/manager 角色）。"""
    es = EvalSet(
        project_id=req.project_id,
        name=req.name,
        description=req.description,
        scoring_method=req.scoring_method,
        pass_threshold=req.pass_threshold,
    )
    db.add(es)
    await db.commit()
    await db.refresh(es)
    return es.to_dict()


@router.get("/sets/{set_id}")
async def get_eval_set(set_id: int, db: AsyncSession = Depends(get_db), _user = Depends(get_current_user)) -> dict:
    """获取单个评估集详情。"""
    es = await db.get(EvalSet, set_id)
    if es is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": f"EvalSet {set_id} not found", "details": {}})
    return es.to_dict()


@router.delete("/sets/{set_id}")
async def delete_eval_set(set_id: int, db: AsyncSession = Depends(get_db), _user = Depends(get_current_user)) -> dict:
    """删除评估集（仅 admin）。"""
    es = await db.get(EvalSet, set_id)
    if es is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": f"EvalSet {set_id} not found", "details": {}})
    await db.delete(es)
    await db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Eval Cases
# ---------------------------------------------------------------------------

@router.get("/sets/{set_id}/cases")
async def list_cases(set_id: int, db: AsyncSession = Depends(get_db), _user = Depends(get_current_user)) -> list[dict]:
    """列出评估集下的所有用例。"""
    rows = (
        await db.execute(
            select(EvalCase).where(EvalCase.eval_set_id == set_id).order_by(EvalCase.id)
        )
    ).scalars().all()
    return [r.to_dict() for r in rows]


@router.post("/cases")
async def create_case(req: EvalCaseCreate, db: AsyncSession = Depends(get_db), _user = Depends(get_current_user)) -> dict:
    """创建评估用例（需要 admin/manager 角色）。"""
    ec = EvalCase(
        eval_set_id=req.eval_set_id,
        input_text=req.input_text,
        expected_output=req.expected_output,
        expected_tools=req.expected_tools,
        max_tokens=req.max_tokens,
        weight=req.weight,
        tags=req.tags,
    )
    db.add(ec)
    await db.commit()
    await db.refresh(ec)
    return ec.to_dict()


@router.post("/sets/{set_id}/cases/batch")
async def batch_create_cases(set_id: int, req: EvalCaseBatch, db: AsyncSession = Depends(get_db), _user = Depends(get_current_user)) -> dict:
    """批量创建评估用例。"""
    es = await db.get(EvalSet, set_id)
    if es is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": f"EvalSet {set_id} not found", "details": {}})
    count = 0
    for c in req.cases:
        db.add(EvalCase(
            eval_set_id=set_id,
            input_text=c.input_text,
            expected_output=c.expected_output,
            expected_tools=c.expected_tools,
            max_tokens=c.max_tokens,
            weight=c.weight,
            tags=c.tags,
        ))
        count += 1
    await db.commit()
    return {"ok": True, "created": count}


@router.delete("/cases/{case_id}")
async def delete_case(case_id: int, db: AsyncSession = Depends(get_db), _user = Depends(get_current_user)) -> dict:
    """删除评估用例（仅 admin）。"""
    ec = await db.get(EvalCase, case_id)
    if ec is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": f"EvalCase {case_id} not found", "details": {}})
    await db.delete(ec)
    await db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Eval Runs
# ---------------------------------------------------------------------------

@router.get("/runs")
async def list_runs(
    eval_set_id: int | None = None,
    project_id: int | None = None,
    limit: int = Query(default=50, le=200),
    db: AsyncSession = Depends(get_db),
    _user = Depends(get_current_user),
) -> list[dict]:
    """列出评估运行记录，支持按评估集和项目过滤。"""
    query = select(EvalRun).order_by(EvalRun.started_at.desc()).limit(limit)
    if eval_set_id is not None:
        query = query.where(EvalRun.eval_set_id == eval_set_id)
    if project_id is not None:
        query = query.where(EvalRun.project_id == project_id)
    rows = (await db.execute(query)).scalars().all()
    return [r.to_dict() for r in rows]


@router.get("/runs/{run_id}")
async def get_run(run_id: int, db: AsyncSession = Depends(get_db), _user = Depends(get_current_user)) -> dict:
    """获取单个评估运行的详情（含每道题的评分）。"""
    run = await db.get(EvalRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": f"EvalRun {run_id} not found", "details": {}})
    result = run.to_dict()
    scores = (
        await db.execute(
            select(EvalScore).where(EvalScore.eval_run_id == run_id).order_by(EvalScore.id)
        )
    ).scalars().all()
    result["scores"] = [s.to_dict() for s in scores]
    return result


@router.post("/runs")
async def start_eval_run(req: RunEvalRequest, db: AsyncSession = Depends(get_db), _user = Depends(get_current_user)) -> dict:
    """启动一次新的评估运行（触发 eval_runner.run_evaluation）。

    返回完整的 EvalRun 对象，前端可轮询 /runs/{id} 等待完成。"""
    es = await db.get(EvalSet, req.eval_set_id)
    if es is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": f"EvalSet {req.eval_set_id} not found", "details": {}})
    run = await run_evaluation(
        eval_set_id=req.eval_set_id,
        model_name=req.model,
        mode=req.mode,
        tools=req.tools,
        project_id=req.project_id,
        system_prompt=req.system_prompt,
        baseline_run_id=req.baseline_run_id,
    )
    return run.to_dict()


@router.delete("/runs/{run_id}")
async def delete_run(run_id: int, db: AsyncSession = Depends(get_db), _user = Depends(get_current_user)) -> dict:
    """删除评估运行及关联评分（仅 admin）。"""
    run = await db.get(EvalRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": f"EvalRun {run_id} not found", "details": {}})
    scores = (
        await db.execute(select(EvalScore).where(EvalScore.eval_run_id == run_id))
    ).scalars().all()
    for s in scores:
        await db.delete(s)
    await db.delete(run)
    await db.commit()
    return {"ok": True}

