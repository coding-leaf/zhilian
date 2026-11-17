"""Internal helpers for subjective LLM grading invocation and grading argument resolution."""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.algorithms.grading import SCORE_ROUNDING_UNIT, round_half_up
from app.integrations.llm.protocol import LLMMessage, LLMOptions, LLMProtocol
from app.models.practice import AttemptItem, PracticeStatus
from app.repositories.grading import GradingRepository
from app.repositories.practice import PracticeRepository


class LLMGradingRubricEvaluation(BaseModel):
    """LLM 结构化判题采分点响应 Schema。"""

    point_id: str
    score: float
    reason: str


class LLMGradingOutput(BaseModel):
    """LLM 结构化判题响应 Schema。"""

    score: float
    confidence: float = 0.9
    feedback: str = ""
    hit_keywords: list[str] = Field(default_factory=list)
    missing_keywords: list[str] = Field(default_factory=list)
    evaluations: list[LLMGradingRubricEvaluation] = Field(default_factory=list)


@dataclass(frozen=True)
class LLMSubjectiveGradeResult:
    """大模型主观题结构化评分归一化结果。"""

    final_score: float
    is_correct: bool
    confidence: float
    feedback: str
    hit_keywords: list[str]
    missing_keywords: list[str]
    grading_metadata: dict[str, Any]


def invoke_subjective_llm_grading(
    llm_adapter: LLMProtocol,
    *,
    item: AttemptItem,
    snapshot: dict[str, Any],
    user_answer: str,
    system_prompt: str,
    extra_metadata: dict[str, Any] | None = None,
) -> LLMSubjectiveGradeResult:
    """统一构造主观题评分 Prompt、调用大模型结构化输出并归一化得分与元数据。"""
    user_prompt = (
        f"【题型】: {snapshot.get('question_type', '')}\n"
        f"【题干】: {snapshot.get('stem', '')}\n"
        f"【参考答案】: {snapshot.get('answer', '')}\n"
        f"【评分细则】: {json.dumps(snapshot.get('grading_rubric', {}), ensure_ascii=False)}\n"
        f"【考生作答】: {user_answer}\n"
        f"【本题满分】: {item.max_score}"
    )
    messages = [
        LLMMessage(role="system", content=system_prompt),
        LLMMessage(role="user", content=user_prompt),
    ]
    options = LLMOptions(timeout=20.0, temperature=0.2)

    output, resp = llm_adapter.generate_structured(
        messages=messages,
        response_model=LLMGradingOutput,
        options=options,
    )

    clamped_score = min(item.max_score, max(0.0, float(output.score)))
    final_score = round_half_up(clamped_score, SCORE_ROUNDING_UNIT)
    is_correct = bool(final_score >= item.max_score * 0.6)
    metadata: dict[str, Any] = dict(extra_metadata) if extra_metadata else {}
    metadata.update(
        {
            "is_correct": is_correct,
            "evaluations": [e.model_dump() for e in output.evaluations],
            "duration_ms": resp.duration_ms,
            "model": resp.model,
        }
    )
    return LLMSubjectiveGradeResult(
        final_score=final_score,
        is_correct=is_correct,
        confidence=min(1.0, max(0.0, float(output.confidence))),
        feedback=output.feedback,
        hit_keywords=list(output.hit_keywords),
        missing_keywords=list(output.missing_keywords),
        grading_metadata=metadata,
    )


def resolve_self_evaluate_args(
    args: tuple[Any, ...],
    *,
    user_id: uuid.UUID | None,
    dto: Any,
    attempt_item_id: uuid.UUID | None,
    score: float | None,
    is_correct: bool | None,
    user_feedback: str | None,
    dto_type: type[Any],
) -> tuple[uuid.UUID | None, uuid.UUID | None, float | None, bool | None, str | None]:
    """解析 self_evaluate_attempt 的多种兼容位置/关键字参数组合。"""
    resolved_user_id = user_id
    resolved_item_id = attempt_item_id
    resolved_score = score
    resolved_feedback = user_feedback
    resolved_is_correct = is_correct

    if len(args) == 2:
        if isinstance(args[1], dto_type):
            resolved_user_id, dto = args[0], args[1]
        elif isinstance(args[0], dto_type):
            dto, resolved_user_id = args[0], args[1]
    elif len(args) >= 3:
        resolved_item_id, resolved_user_id = args[0], args[1]
        resolved_score = float(args[2])
        if len(args) >= 4:
            resolved_is_correct = bool(args[3])
        if len(args) >= 5:
            resolved_feedback = args[4]
    elif len(args) == 1:
        if isinstance(args[0], dto_type):
            dto = args[0]
        elif isinstance(args[0], uuid.UUID):
            resolved_user_id = args[0]

    if dto is not None:
        resolved_item_id = dto.attempt_item_id
        resolved_score = float(dto.score)
        resolved_feedback = dto.feedback
        if resolved_is_correct is None:
            resolved_is_correct = dto.is_correct

    return (
        resolved_user_id,
        resolved_item_id,
        resolved_score,
        resolved_is_correct,
        resolved_feedback,
    )


def resolve_regrade_args(
    args: tuple[Any, ...],
    *,
    user_id: uuid.UUID | None,
    dto: Any,
    attempt_item_id: uuid.UUID | None,
    dto_type: type[Any],
) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """解析 regrade_attempt 的多种兼容位置/关键字参数组合。"""
    resolved_user_id = user_id
    resolved_item_id = attempt_item_id

    if len(args) == 2:
        if isinstance(args[1], dto_type):
            resolved_user_id, dto = args[0], args[1]
        elif isinstance(args[0], dto_type):
            dto, resolved_user_id = args[0], args[1]
        elif isinstance(args[0], uuid.UUID) and isinstance(args[1], uuid.UUID):
            resolved_item_id, resolved_user_id = args[0], args[1]
    elif len(args) == 1:
        if isinstance(args[0], dto_type):
            dto = args[0]
        elif isinstance(args[0], uuid.UUID):
            resolved_user_id = args[0]

    if dto is not None:
        resolved_item_id = dto.attempt_item_id

    return resolved_user_id, resolved_item_id


def refresh_practice_grading_state(
    practice_repo: PracticeRepository,
    grading_repo: GradingRepository,
    *,
    practice_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    """重新汇总整卷总分与判题流转状态（COMPLETED vs PARTIALLY_GRADED）。"""
    practice = practice_repo.get_practice_by_id(practice_id, user_id, include_items=True)
    if practice is None:
        return
    practice.total_score = round(sum(it.score or 0.0 for it in practice.items), 2)
    pending_count = grading_repo.count_pending_regrade(practice.id, user_id=user_id)
    if pending_count == 0:
        practice.status = PracticeStatus.COMPLETED.value
        if not practice.completed_at:
            practice.completed_at = datetime.now(UTC)
    else:
        practice.status = PracticeStatus.PARTIALLY_GRADED.value
