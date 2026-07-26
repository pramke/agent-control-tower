"""SDK 追踪数据录入接口 + Prompt 版本管理端点。"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from backend.core.database import async_session
from backend.core.security import get_current_user
from backend.modules.observability.models import AgentNodeTrace
from backend.modules.observability.prompts import Prompt
from backend.modules.observability.trace_writer import create_run, add_node, finish_run

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["traces", "prompts"])


# ── SDK Trace Ingestion ──

class SpanItem(BaseModel):
    span_id: str = ""
    parent_span_id: str | None = None
    name: str = "unknown"
    input: dict | None = None
    output: dict | None = None
    duration_ms: float = 0.0
    token_usage: dict | None = None
    model: str | None = None
    error: str | None = None


class TracePayload(BaseModel):
    trace_id: str = ""
    name: str = "trace"
    input: dict | None = None
    output: dict | None = None
    duration_ms: float = 0.0
    project_id: int | None = None
    spans: list[SpanItem] = []


class IngestPayload(BaseModel):
    traces: list[TracePayload] = []


@router.post("/traces/ingest")
async def ingest_traces(payload: IngestPayload, _user=Depends(get_current_user)):
    """Receive batched trace data from act-sdk.

    Each trace becomes an AgentRun; spans become AgentNodeTraces
    with parent_node_id linking for hierarchy.
    """
    results: list[dict] = []
    ingested = 0
    failed = 0

    # 每个 trace 在独立 DB 事务中处理，单条失败不影响其余
    for trace in payload.traces:
        if not trace.spans:
            continue
        trace_spans = 0
        try:
            async with async_session() as db:
                run = await create_run(
                    db,
                    trace_id=trace.trace_id,
                    project_id=trace.project_id,
                    agent_name=trace.name,
                    input_data=trace.input,
                )

                # span_id → node_id 映射用于建立父子节点关系
                span_id_to_node_id: dict[str, int] = {}

                for seq, span in enumerate(trace.spans):
                    parent_node_id = None
                    if span.parent_span_id and span.parent_span_id in span_id_to_node_id:
                        parent_node_id = span_id_to_node_id[span.parent_span_id]

                    # 根据是否有 token_usage 推断节点类型：有即 LLM 调用，否则为普通 span
                    node = await add_node(
                        db,
                        trace_id=run.trace_id,
                        node_name=span.name,
                        node_type="llm_call" if span.token_usage else "span",
                        sequence=seq,
                        input_data=span.input,
                        output_data=span.output,
                        duration_ms=int(span.duration_ms),
                        token_usage=span.token_usage,
                        status="failed" if span.error else "success",
                        parent_node_id=parent_node_id,
                        error=span.error,
                    )
                    span_id_to_node_id[span.span_id] = node.id

                model = next((s.model for s in trace.spans if s.model), None)
                await finish_run(db, trace.trace_id, output_data=trace.output, model=model)

                await db.commit()
                trace_spans = len(trace.spans)
                ingested += trace_spans
                results.append({"trace_id": trace.trace_id, "status": "ok", "spans": trace_spans})
                logger.info("Ingested trace %s with %d spans", trace.trace_id, trace_spans)
        except Exception as exc:
            failed += len(trace.spans)
            results.append({"trace_id": trace.trace_id, "status": "failed", "error": str(exc)})
            logger.warning("Failed to ingest trace %s: %s", trace.trace_id, exc)

    return {"ingested": ingested, "failed": failed, "results": results}


# ── Prompt Management ──

class PromptCreate(BaseModel):
    name: str
    content: str
    project_id: int


@router.get("/prompts")
async def list_prompts(project_id: int | None = None, _user=Depends(get_current_user)):
    async with async_session() as session:
        query = select(Prompt).order_by(Prompt.updated_at.desc())
        if project_id:
            query = query.where(Prompt.project_id == project_id)
        result = await session.execute(query)
        prompts = result.scalars().all()
        return [
            {"id": p.id, "name": p.name, "content": p.content, "version": p.version, "created_at": p.created_at.isoformat()}
            for p in prompts
        ]


@router.post("/prompts")
async def create_prompt(req: PromptCreate, _user=Depends(get_current_user)):
    async with async_session() as session:
        existing = (await session.execute(
            select(Prompt).where(Prompt.project_id == req.project_id, Prompt.name == req.name).order_by(Prompt.version.desc())
        )).scalars().first()
        # 自动版本递增：同名 Prompt 每次创建生成新版本号
        version = (existing.version + 1) if existing else 1

        prompt = Prompt(project_id=req.project_id, name=req.name, content=req.content, version=version)
        session.add(prompt)
        await session.commit()
        return {"id": prompt.id, "name": prompt.name, "version": prompt.version}


@router.get("/prompts/{name}")
async def get_prompt(name: str, project_id: int, version: int | None = None, _user=Depends(get_current_user)):
    async with async_session() as session:
        query = select(Prompt).where(Prompt.project_id == project_id, Prompt.name == name)
        if version:
            query = query.where(Prompt.version == version)
        else:
            query = query.order_by(Prompt.version.desc())
        prompt = (await session.execute(query)).scalars().first()
        if not prompt:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": f"Prompt '{name}' not found"})
        return {"id": prompt.id, "name": prompt.name, "content": prompt.content, "version": prompt.version}
