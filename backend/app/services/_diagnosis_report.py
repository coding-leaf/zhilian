"""Internal synthesis and persistence helpers for DiagnosisService report generation."""

import contextlib
import uuid
from datetime import datetime
from typing import Any

from app.core.algorithms.diagnosis import (
    DiagnosisReportResult,
    KnowledgeEvaluationInput,
    MistakeEvidence,
)
from app.core.errors import PracticeNotGradedError
from app.models.practice import (
    AttemptItem,
    DiagnosisReport,
    ErrorType,
    GradingRecord,
    GradingStatus,
    MasteryRecord,
)
from app.repositories.diagnosis import DiagnosisRepository
from app.repositories.knowledge import KnowledgeRepository

_SUBJECTIVE_TYPES: frozenset[str] = frozenset(("short_answer", "essay", "subjective"))


def _resolve_item_score(
    item: AttemptItem,
    grading: GradingRecord | None,
) -> tuple[float, float]:
    """解析单题得分与满分基准（优先采用最终生效判题记录）。"""
    if grading is not None and grading.score is not None:
        return float(grading.score), (float(grading.max_score) if grading.max_score > 0.0 else 1.0)
    if item.score is not None:
        return float(item.score), (float(item.max_score) if item.max_score > 0.0 else 1.0)
    return 0.0, 1.0


def evaluate_practice_items(
    *,
    practice_id: uuid.UUID,
    items: list[AttemptItem],
    grading_records: list[GradingRecord],
) -> tuple[list[dict[str, Any]], int, int, float, float]:
    """校验全部作答项已完成判题并聚合作答统计与单项评估明细。"""
    grading_map = {record.attempt_item_id: record for record in grading_records}
    if not items or any(
        item.id not in grading_map
        or grading_map[item.id].status != GradingStatus.SUCCESS.value
        or grading_map[item.id].score is None
        for item in items
    ):
        raise PracticeNotGradedError(
            "练习仍有未判完题目，无法生成学情诊断报告",
            details={"practice_id": str(practice_id)},
        )

    unanswered_count = 0
    wrong_count = 0
    total_scored = 0.0
    total_maximum = 0.0
    item_evaluations: list[dict[str, Any]] = []

    for item in items:
        grading = grading_map.get(item.id)
        item_score, item_max_score = _resolve_item_score(item, grading)
        total_scored += item_score
        total_maximum += item_max_score

        is_answered = bool(item.is_answered)
        if not is_answered:
            unanswered_count += 1

        is_correct = is_answered and (item_score >= item_max_score)
        if not is_correct:
            wrong_count += 1

        point_id: uuid.UUID | None = None
        if item.question_snapshot and "knowledge_point_id" in item.question_snapshot:
            with contextlib.suppress(ValueError, TypeError):
                point_id = uuid.UUID(str(item.question_snapshot["knowledge_point_id"]))

        item_evaluations.append(
            {
                "item": item,
                "grading": grading,
                "score": item_score,
                "max_score": item_max_score,
                "is_answered": is_answered,
                "is_correct": is_correct,
                "point_id": point_id,
            }
        )

    return item_evaluations, unanswered_count, wrong_count, total_scored, total_maximum


def collect_involved_point_ids(
    practice_kp_ids: list[str] | None,
    item_evaluations: list[dict[str, Any]],
) -> list[uuid.UUID]:
    """合并练习元数据与作答快照涉及的全部去重有序知识点主键。"""
    involved: set[uuid.UUID] = set()
    for point_string in practice_kp_ids or []:
        with contextlib.suppress(ValueError, TypeError):
            involved.add(uuid.UUID(point_string))
    for eval_info in item_evaluations:
        if eval_info["point_id"] is not None:
            involved.add(eval_info["point_id"])
    return sorted(involved)


def build_evaluation_inputs_and_mistakes(
    *,
    knowledge_repo: KnowledgeRepository,
    user_id: uuid.UUID,
    sorted_point_ids: list[uuid.UUID],
    previous_record_map: dict[uuid.UUID, MasteryRecord],
    current_record_map: dict[uuid.UUID, MasteryRecord],
    item_evaluations: list[dict[str, Any]],
    evaluation_time: datetime,
) -> tuple[list[KnowledgeEvaluationInput], list[MistakeEvidence], bool, uuid.UUID | None]:
    """装配纯函数诊断输入、错题证据与结构低可信度降级标志。"""
    evaluation_inputs: list[KnowledgeEvaluationInput] = []
    mistake_evidences: list[MistakeEvidence] = []
    is_structure_degraded = False
    fallback_point_id = sorted_point_ids[0] if sorted_point_ids else None

    for point_id in sorted_point_ids:
        knowledge_point = knowledge_repo.get_by_id(point_id, user_id)
        if knowledge_point and getattr(knowledge_point, "is_low_confidence", False):
            is_structure_degraded = True

        prev_record = previous_record_map.get(point_id)
        curr_record = current_record_map.get(point_id)
        days_since: float | None = None
        if prev_record and prev_record.last_practiced_at:
            delta_seconds = (evaluation_time - prev_record.last_practiced_at).total_seconds()
            days_since = max(0.0, delta_seconds / 86400.0)

        point_items = [
            e
            for e in item_evaluations
            if e["point_id"] == point_id
            or (e["point_id"] is None and point_id == fallback_point_id)
        ]
        has_subjective = any(
            not e["is_correct"]
            and e["item"].question_snapshot.get("question_type") in _SUBJECTIVE_TYPES
            for e in point_items
        )
        has_objective = any(
            not e["is_correct"]
            and e["item"].question_snapshot.get("question_type") not in _SUBJECTIVE_TYPES
            for e in point_items
        )

        evaluation_inputs.append(
            KnowledgeEvaluationInput(
                knowledge_id=str(point_id),
                knowledge_title=(
                    knowledge_point.name if knowledge_point else f"知识点-{str(point_id)[:8]}"
                ),
                current_score=curr_record.mastery_score if curr_record else 0.0,
                previous_score=prev_record.mastery_score if prev_record else None,
                days_since_last_practice=days_since,
                has_subjective_mistake=has_subjective,
                has_objective_mistake=has_objective,
            )
        )

    for eval_info in item_evaluations:
        if eval_info["is_correct"]:
            continue
        item_entity = eval_info["item"]
        snapshot = item_entity.question_snapshot or {}
        point_id_target = eval_info["point_id"] or fallback_point_id
        mistake_evidences.append(
            MistakeEvidence(
                question_id=str(item_entity.question_id or item_entity.id),
                question_brief=str(snapshot.get("stem") or "")[:50],
                user_answer=str(item_entity.user_answer or "")[:50],
                correct_answer=str(snapshot.get("answer") or "")[:50],
                knowledge_id=str(point_id_target) if point_id_target else "unknown",
                is_negation_inversion=bool(snapshot.get("is_negation_inversion", False)),
            )
        )

    return evaluation_inputs, mistake_evidences, is_structure_degraded, fallback_point_id


def sync_wrong_records_from_evaluations(
    *,
    diagnosis_repo: DiagnosisRepository,
    user_id: uuid.UUID,
    practice_id: uuid.UUID,
    item_evaluations: list[dict[str, Any]],
    fallback_point_id: uuid.UUID | None,
) -> None:
    """根据作答评估结果联动新增错题或将答对历史错题标记为已攻克。"""
    for eval_info in item_evaluations:
        item_entity = eval_info["item"]
        point_id_target = eval_info["point_id"] or fallback_point_id
        if point_id_target is None:
            continue

        if not eval_info["is_correct"]:
            error_type_val = (
                ErrorType.UNANSWERED.value
                if not eval_info["is_answered"]
                else ErrorType.CONCEPTUAL.value
            )
            diagnosis_repo.upsert_wrong_record(
                user_id=user_id,
                question_id=item_entity.question_id,
                knowledge_point_id=point_id_target,
                practice_id=practice_id,
                attempt_item_id=item_entity.id,
                error_type=error_type_val,
                question_snapshot=item_entity.question_snapshot or {},
                last_wrong_answer=item_entity.user_answer,
            )
        elif item_entity.question_id is not None:
            diagnosis_repo.mark_wrong_record_mastered(
                question_id=item_entity.question_id,
                user_id=user_id,
            )


def build_diagnosis_report_entity(
    *,
    report_id: uuid.UUID,
    practice_id: uuid.UUID,
    user_id: uuid.UUID,
    synthesis_result: DiagnosisReportResult,
    total_questions: int,
    unanswered_count: int,
    wrong_count: int,
    score_rate: float,
    is_structure_degraded: bool,
) -> DiagnosisReport:
    """将纯函数诊断合成结果转换为可持久化的 DiagnosisReport ORM 实体。"""
    weak_knowledge_data = [
        {
            "knowledge_id": item.knowledge_id,
            "knowledge_title": item.knowledge_title,
            "current_score": item.current_score,
            "previous_score": item.previous_score,
            "score_delta": item.score_delta,
            "cause_type": item.cause_type.value,
            "cause_explanation": item.cause_explanation,
            "actionable_advice": item.actionable_advice,
            "associated_mistakes": [
                {
                    "question_id": mistake.question_id,
                    "is_negation_inversion": mistake.is_negation_inversion,
                }
                for mistake in item.associated_mistakes
            ],
        }
        for item in synthesis_result.weak_points
    ]
    regressed_knowledge_data = [
        {
            "knowledge_id": item.knowledge_id,
            "knowledge_title": item.knowledge_title,
            "current_score": item.current_score,
            "previous_score": item.previous_score,
            "score_delta": item.score_delta,
            "cause_type": item.cause_type.value,
            "cause_explanation": item.cause_explanation,
            "actionable_advice": item.actionable_advice,
        }
        for item in synthesis_result.regressed_points
    ]
    analysis_causes_data = [
        {
            "knowledge_id": item.knowledge_id,
            "cause_type": item.cause_type.value,
            "explanation": item.cause_explanation,
        }
        for item in synthesis_result.weak_points
    ]
    actionable_suggestions_data = [
        {"action": action} for action in synthesis_result.suggested_review_actions
    ]
    return DiagnosisReport(
        id=report_id,
        practice_id=practice_id,
        user_id=user_id,
        weak_knowledge_points=weak_knowledge_data,
        regressed_knowledge_points=regressed_knowledge_data,
        analysis_causes=analysis_causes_data,
        actionable_suggestions=actionable_suggestions_data,
        unanswered_count=unanswered_count,
        wrong_count=wrong_count,
        pending_regrade_count=0,
        total_questions=total_questions,
        score_rate=score_rate,
        is_structure_degraded=is_structure_degraded,
    )


__all__ = [
    "build_diagnosis_report_entity",
    "build_evaluation_inputs_and_mistakes",
    "collect_involved_point_ids",
    "evaluate_practice_items",
    "sync_wrong_records_from_evaluations",
]
