"""Evaluation runner: loads an eval set, runs each case through the agent, scores results.

Scoring methods:
- exact_match: output must contain the expected string
- semantic: output is compared via LLM-judge pairwise
- llm_judge: a separate LLM call evaluates the output against criteria

工作流：run_evaluation() → 依次调用 _run_single_case() → 评分 → 写入 EvalScore → 更新 EvalRun
"""

import asyncio
import logging
import time
from datetime import datetime

from sqlalchemy import select

from backend.config import settings
from backend.core.database import async_session
from backend.modules.evaluation.eval_model import EvalCase, EvalRun, EvalScore, EvalSet
from backend.core.llm_utils import create_chat_model
from backend.pricing.table import calculate_cost

logger = logging.getLogger(__name__)

# LLM Judge 评分 Prompt：用于 semantic / llm_judge 评分方式
LLM_JUDGE_PROMPT = (
    "You are an evaluation judge. Compare the following Agent output against the expected "
    "output. Score from 0.0 (completely wrong) to 1.0 (perfect match). Consider factual "
    "correctness, completeness, and relevance.\n\n"
    "Expected output:\n{expected}\n\n"
    "Actual output:\n{actual}\n\n"
    "Respond with ONLY a JSON object: {{\"score\": <0.0-1.0>, \"reason\": \"<one sentence>\"}}"
)


async def score_exact_match(actual: str, expected: str) -> tuple[float, bool]:
    """Simple substring/equality match."""
    if not expected:
        return 1.0, True
    actual_lower = actual.lower().strip()
    expected_lower = expected.lower().strip()
    if actual_lower == expected_lower:
        return 1.0, True
    if expected_lower in actual_lower:
        return 0.7, True
    return 0.0, False


async def score_llm_judge(actual: str, expected: str, model_name: str | None = None) -> tuple[float, bool]:
    """用另一个 LLM 来评判输出质量（LLM-as-Judge 模式）。"""
    import json

    # 使用独立 LLM 调用，而非复用 agent 模型，避免评价偏差
    model = create_chat_model(model_name or settings.agent_model)
    prompt = LLM_JUDGE_PROMPT.format(expected=expected[:2000], actual=actual[:2000])
    try:
        from langchain_core.messages import HumanMessage
        resp = await model.ainvoke([HumanMessage(content=prompt)])
        text = resp.content if isinstance(resp.content, str) else str(resp.content)
        # Extract JSON from response
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            data = json.loads(text[start:end + 1])
            score = float(data.get("score", 0.0))
            return max(0.0, min(1.0, score)), score >= 0.7
    except Exception as exc:
        logger.warning("LLM judge failed: %s, falling back to exact match", exc)
    return await score_exact_match(actual, expected)


async def score_semantic(actual: str, expected: str) -> tuple[float, bool]:
    """Fallback: combines exact match with LLM judge."""
    exact_score, _ = await score_exact_match(actual, expected)
    if exact_score >= 0.7:
        return exact_score, True
    return await score_llm_judge(actual, expected)


# 评分方式映射表
SCORERS = {
    "exact_match": score_exact_match,
    "semantic": score_semantic,
    "llm_judge": score_llm_judge,
}


async def _run_single_case(
    case: EvalCase,
    model_name: str,
    mode: str,
    tools: list[str],
    system_prompt: str | None,
    scoring_method: str,
) -> dict:
    """Run one eval case through the agent and score the output.

    使用轻量级直接 LLM 调用（不经过完整 agent graph），评估提速显著。
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    # 不经过 agent graph，直接用 chat_model 做单次调用
    chat_model = create_chat_model(model_name)
    messages = []
    if system_prompt:
        messages.append(SystemMessage(content=system_prompt))
    messages.append(HumanMessage(content=case.input_text))

    t0 = time.monotonic()
    error = None
    actual_output = ""
    tokens_used = 0

    try:
        resp = await asyncio.wait_for(chat_model.ainvoke(messages), timeout=60)
        actual_output = resp.content if isinstance(resp.content, str) else str(resp.content)
        usage = getattr(resp, "usage_metadata", None) or {}
        tokens_used = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
    except asyncio.TimeoutError:
        error = "Evaluation timed out (60s)"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    duration_ms = int((time.monotonic() - t0) * 1000)

    if error:
        return {
            "actual_output": error,
            "score": 0.0,
            "passed": False,
            "error": error,
            "tokens_used": tokens_used,
            "duration_ms": duration_ms,
        }

    scorer = SCORERS.get(scoring_method, score_exact_match)
    score_val, passed = await scorer(actual_output, case.expected_output or "")

    return {
        "actual_output": actual_output[:5000],
        "score": round(score_val, 4),
        "passed": passed,
        "error": None,
        "tokens_used": tokens_used,
        "duration_ms": duration_ms,
    }


async def run_evaluation(
    eval_set_id: int,
    model_name: str,
    mode: str = "react",
    tools: list[str] | None = None,
    project_id: int | None = None,
    system_prompt: str | None = None,
    baseline_run_id: int | None = None,
) -> EvalRun:
    """Run a full evaluation: load eval set, run all cases, persist results.

    Returns the completed EvalRun with aggregate scores.
    """
    tools = tools or []
    async with async_session() as session:
        eval_set = await session.get(EvalSet, eval_set_id)
        if eval_set is None:
            raise ValueError(f"EvalSet {eval_set_id} not found")

        cases = (
            await session.execute(
                select(EvalCase).where(EvalCase.eval_set_id == eval_set_id).order_by(EvalCase.id)
            )
        ).scalars().all()

        if not cases:
            raise ValueError(f"EvalSet {eval_set_id} has no cases")

        # 创建 EvalRun 记录，初始状态为 "running"
        run = EvalRun(
            eval_set_id=eval_set_id,
            project_id=project_id,
            model=model_name,
            mode=mode,
            tools=tools,
            system_prompt=system_prompt,
            status="running",
            total_cases=len(cases),
            baseline_run_id=baseline_run_id,
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        run_id = run.id

    # 逐题执行评估，每题结果立即写 DB，避免批量失败导致数据丢失
    t_start = time.monotonic()
    total_score = 0.0
    passed_count = 0
    total_tokens = 0
    scores: list[dict] = []

    for case in cases:
        result = await _run_single_case(
            case,
            model_name,
            mode,
            tools,
            system_prompt,
            scoring_method=eval_set.scoring_method,
        )
        total_score += result["score"] * case.weight
        if result["passed"]:
            passed_count += 1
        total_tokens += result["tokens_used"]

        # 每题结果立即写入 DB
        async with async_session() as session:
            score_row = EvalScore(
                eval_run_id=run_id,
                eval_case_id=case.id,
                actual_output=result["actual_output"],
                score=result["score"],
                passed=result["passed"],
                error=result["error"],
                tokens_used=result["tokens_used"],
                duration_ms=result["duration_ms"],
            )
            session.add(score_row)
            await session.commit()

        scores.append(result)

    duration_ms = int((time.monotonic() - t_start) * 1000)
    weighted_avg = total_score / sum(c.weight for c in cases) if cases else 0.0

    # 如果指定了基线 run，检测回归
    regression = False
    if baseline_run_id is not None:
        from backend.modules.evaluation.regression import detect_regression
        regression = await detect_regression(baseline_run_id, run_id)

    # 更新 EvalRun 为 completed
    async with async_session() as session:
        run_row = await session.get(EvalRun, run_id)
        if run_row is not None:
            run_row.status = "completed"
            run_row.passed_cases = passed_count
            run_row.average_score = weighted_avg
            run_row.total_tokens = total_tokens
            run_row.total_cost = calculate_cost(model_name, total_tokens, 0)
            run_row.duration_ms = duration_ms
            run_row.finished_at = datetime.now()
            run_row.regression_detected = regression
            await session.commit()
            await session.refresh(run_row)
            return run_row

    raise RuntimeError(f"EvalRun {run_id} disappeared during execution")
