"""Evaluation framework: eval sets, cases, runs, and regression detection.

Models:
- EvalSet: a named collection of test cases
- EvalCase: a single input/expected_output pair with scoring criteria
- EvalRun: a record of running an eval set against a model/config
- EvalScore: per-case score within a run
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, JSON, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from backend.modules.models.base import Base


class EvalSet(Base):
    """评估集：一组测试用例的集合，包含评分方法和通过阈值。"""
    __tablename__ = "eval_sets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    scoring_method: Mapped[str] = mapped_column(String(20), nullable=False, default="exact_match")  # exact_match, semantic, llm_judge
    pass_threshold: Mapped[float] = mapped_column(Float, default=0.8)  # 判定通过的分数阈值（0.8 = 80% 正确率）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "name": self.name,
            "description": self.description,
            "scoring_method": self.scoring_method,
            "pass_threshold": self.pass_threshold,
            "created_at": self.created_at.isoformat(),
        }


class EvalCase(Base):
    """评估用例：一个输入/期望输出的测试样例。"""
    __tablename__ = "eval_cases"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    eval_set_id: Mapped[int] = mapped_column(ForeignKey("eval_sets.id"), nullable=False, index=True)
    input_text: Mapped[str] = mapped_column(Text, nullable=False)                        # 输入 Prompt
    expected_output: Mapped[str | None] = mapped_column(Text, nullable=True)             # 期望输出
    expected_tools: Mapped[list | None] = mapped_column(JSON, nullable=True)             # 期望使用的工具
    max_tokens: Mapped[int] = mapped_column(Integer, default=2000)                       # 最大 Token 数
    weight: Mapped[float] = mapped_column(Float, default=1.0)                            # 加权分数权重
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)                       # 分类标签
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "eval_set_id": self.eval_set_id,
            "input_text": self.input_text,
            "expected_output": self.expected_output,
            "expected_tools": self.expected_tools,
            "max_tokens": self.max_tokens,
            "weight": self.weight,
            "tags": self.tags,
            "created_at": self.created_at.isoformat(),
        }


class EvalRun(Base):
    """评估运行：记录一次对某个评估集的完整评测执行。"""
    __tablename__ = "eval_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    eval_set_id: Mapped[int] = mapped_column(ForeignKey("eval_sets.id"), nullable=False, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    model: Mapped[str] = mapped_column(String(50), nullable=False)                       # 被评估的模型
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="react")       # agent 模式
    tools: Mapped[list | None] = mapped_column(JSON, nullable=True)                      # 可用工具列表
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")   # running, completed, failed
    total_cases: Mapped[int] = mapped_column(Integer, default=0)
    passed_cases: Mapped[int] = mapped_column(Integer, default=0)
    average_score: Mapped[float] = mapped_column(Float, default=0.0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_cost: Mapped[float] = mapped_column(Float, default=0.0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    baseline_run_id: Mapped[int | None] = mapped_column(ForeignKey("eval_runs.id"), nullable=True)  # 回归对比基线运行
    regression_detected: Mapped[bool] = mapped_column(Boolean, default=False)  # 由 regression.py 在 run 完成后写入
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "eval_set_id": self.eval_set_id,
            "project_id": self.project_id,
            "model": self.model,
            "mode": self.mode,
            "tools": self.tools,
            "system_prompt": self.system_prompt,
            "status": self.status,
            "total_cases": self.total_cases,
            "passed_cases": self.passed_cases,
            "average_score": round(self.average_score, 4),
            "total_tokens": self.total_tokens,
            "total_cost": round(self.total_cost, 6),
            "duration_ms": self.duration_ms,
            "baseline_run_id": self.baseline_run_id,
            "regression_detected": self.regression_detected,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


class EvalScore(Base):
    """评分记录：评估运行中单个用例的打分结果。"""
    __tablename__ = "eval_scores"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    eval_run_id: Mapped[int] = mapped_column(ForeignKey("eval_runs.id"), nullable=False, index=True)
    eval_case_id: Mapped[int] = mapped_column(ForeignKey("eval_cases.id"), nullable=False)
    actual_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)                     # 0.0 ~ 1.0
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "eval_run_id": self.eval_run_id,
            "eval_case_id": self.eval_case_id,
            "actual_output": self.actual_output,
            "score": round(self.score, 4),
            "passed": self.passed,
            "error": self.error,
            "tokens_used": self.tokens_used,
            "duration_ms": self.duration_ms,
        }
