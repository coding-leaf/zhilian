"""Internal assembly helpers and typed wrappers for PracticeService."""

import random
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from app.core.errors import AppError, PracticeEmptyQuestionsError
from app.models.practice import (
    AttemptItem,
    Practice,
    build_question_snapshot,
    validate_question_snapshot,
)
from app.models.question import Question, QuestionStatus
from app.repositories.diagnosis import DiagnosisRepository
from app.repositories.question import QuestionRepository
from app.schemas.material import SourceSnippetDTO


@dataclass
class PracticeItemView:
    """作答项与原文溯源投影的强类型视图，替代 ORM 实例 setattr 挂载。"""

    _item: AttemptItem
    source_snippet: SourceSnippetDTO | None = None

    @property
    def id(self) -> uuid.UUID:
        return self._item.id

    @property
    def practice_id(self) -> uuid.UUID:
        return self._item.practice_id

    @property
    def question_id(self) -> uuid.UUID | None:
        return self._item.question_id

    @property
    def order_index(self) -> int:
        return self._item.order_index

    @property
    def user_answer(self) -> str | None:
        return self._item.user_answer

    @property
    def duration_seconds(self) -> int:
        return self._item.duration_seconds

    @property
    def is_answered(self) -> bool:
        return self._item.is_answered

    @property
    def score(self) -> float | None:
        return self._item.score

    @property
    def max_score(self) -> float:
        return self._item.max_score

    @property
    def question_snapshot(self) -> dict[str, Any]:
        return self._item.question_snapshot

    @question_snapshot.setter
    def question_snapshot(self, value: dict[str, Any]) -> None:
        self._item.question_snapshot = value

    def __getattr__(self, name: str) -> Any:
        return getattr(self._item, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in {"_item", "source_snippet"}:
            object.__setattr__(self, name, value)
            return
        setattr(self._item, name, value)


@dataclass
class PracticeView:
    """练习会话与已包装作答项的强类型视图，支持测试与调用方兼容读取与状态变更。"""

    _practice: Practice
    items: list[PracticeItemView]

    @property
    def id(self) -> uuid.UUID:
        return self._practice.id

    @property
    def user_id(self) -> uuid.UUID:
        return self._practice.user_id

    @property
    def material_id(self) -> uuid.UUID | None:
        return self._practice.material_id

    @property
    def folder_id(self) -> uuid.UUID | None:
        return self._practice.folder_id

    @property
    def title(self) -> str:
        return self._practice.title

    @property
    def question_count(self) -> int:
        return self._practice.question_count

    @property
    def status(self) -> str:
        return self._practice.status

    @status.setter
    def status(self, value: str) -> None:
        self._practice.status = value

    @property
    def mode(self) -> str:
        return self._practice.mode

    @property
    def source_type(self) -> str:
        return self._practice.source_type

    @property
    def source_report_id(self) -> uuid.UUID | None:
        return self._practice.source_report_id

    @property
    def total_score(self) -> float | None:
        return self._practice.total_score

    @property
    def max_score(self) -> float | None:
        return self._practice.max_score

    @property
    def created_at(self) -> Any:
        return self._practice.created_at

    @property
    def submitted_at(self) -> Any:
        return self._practice.submitted_at

    @property
    def completed_at(self) -> Any:
        return self._practice.completed_at

    @property
    def ordered_question_ids(self) -> list[str]:
        return list(self._practice.ordered_question_ids or [])

    @property
    def knowledge_point_ids(self) -> list[str]:
        return list(self._practice.knowledge_point_ids or [])

    @property
    def question_types(self) -> list[str]:
        return list(self._practice.question_types or [])

    @property
    def difficulty(self) -> int | None:
        return self._practice.difficulty

    def __getattr__(self, name: str) -> Any:
        return getattr(self._practice, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in {"_practice", "items"}:
            object.__setattr__(self, name, value)
            return
        setattr(self._practice, name, value)


def wrap_practice_with_source_snippets(
    practice: Practice,
    snippet_map: dict[uuid.UUID, SourceSnippetDTO],
    snapshot_snippet_id_fn: Callable[[AttemptItem], uuid.UUID | None],
) -> PracticeView:
    """将 Practice 及其 AttemptItem 列表包装为携带原文溯源投影的强类型视图。"""
    wrapped_items = [
        PracticeItemView(
            _item=item,
            source_snippet=(
                snippet_map.get(snippet_id)
                if (snippet_id := snapshot_snippet_id_fn(item)) is not None
                else None
            ),
        )
        for item in (practice.items or [])
    ]
    return PracticeView(_practice=practice, items=wrapped_items)


def select_explicit_questions(
    question_repo: QuestionRepository,
    *,
    user_id: uuid.UUID,
    question_ids: Sequence[uuid.UUID],
    question_count: int,
    is_random: bool,
    on_empty_metric: Callable[[int, int], None],
) -> tuple[list[Question], list[uuid.UUID]]:
    """按显式指定题目主键集合筛选可用题目并对齐目标数量。"""
    explicit_questions = question_repo.list_questions_by_ids(
        question_ids,
        user_id,
        include_deleted=False,
    )
    available_questions = [
        q for q in explicit_questions if q.status == QuestionStatus.AVAILABLE.value
    ]
    if not available_questions:
        on_empty_metric(len(question_ids), 0)
        raise PracticeEmptyQuestionsError(
            "指定的题目不存在、越权或不可用",
            details={"requested_ids": [str(qid) for qid in question_ids]},
        )

    q_map = {q.id: q for q in available_questions}
    ordered_explicit = [q_map[qid] for qid in question_ids if qid in q_map]
    effective_kp_ids = list(
        dict.fromkeys(
            q.knowledge_point_id for q in ordered_explicit if q.knowledge_point_id is not None
        )
    )

    pool = list(ordered_explicit)
    if is_random:
        random.shuffle(pool)
    return pool[:question_count], effective_kp_ids


def collect_interleaved_candidates(
    question_repo: QuestionRepository,
    *,
    user_id: uuid.UUID,
    effective_kp_ids: Sequence[uuid.UUID],
    question_types: Sequence[str] | None,
    difficulty: int | None,
    required_count: int,
    on_insufficient_metric: Callable[[int, int], None],
) -> list[Question]:
    """按知识点轮转收集并去重候选题目，不足目标题量时触发门禁异常。"""
    kp_questions_map: dict[uuid.UUID, list[Question]] = {}
    type_set = set(question_types) if question_types else None
    total_available = 0

    for kp_id in effective_kp_ids:
        kp_questions = question_repo.list_questions_by_knowledge_point(
            knowledge_point_id=kp_id,
            user_id=user_id,
            status=QuestionStatus.AVAILABLE.value,
            include_deleted=False,
        )
        if type_set is not None:
            kp_questions = [q for q in kp_questions if q.question_type in type_set]
        if difficulty is not None:
            kp_questions = [q for q in kp_questions if q.difficulty == difficulty]
        kp_questions_map[kp_id] = kp_questions
        total_available += len(kp_questions)

    if total_available < required_count:
        on_insufficient_metric(required_count, total_available)
        raise PracticeEmptyQuestionsError(
            "题库可用题目不足，无法满足当前出题配置要求",
            details={"required": required_count, "available": total_available},
        )

    interleaved: list[Question] = []
    max_kp_len = max((len(qs) for qs in kp_questions_map.values()), default=0)
    for idx in range(max_kp_len):
        for kp_id in effective_kp_ids:
            qs = kp_questions_map[kp_id]
            if idx < len(qs):
                interleaved.append(qs[idx])

    seen_ids: set[uuid.UUID] = set()
    unique_candidates: list[Question] = []
    for question in interleaved:
        if question.id not in seen_ids:
            seen_ids.add(question.id)
            unique_candidates.append(question)
    return unique_candidates


def rank_candidates_by_mode(
    candidates: list[Question],
    *,
    mode_value: str,
    question_count: int,
    diagnosis_repo: DiagnosisRepository,
    user_id: uuid.UUID,
) -> list[Question]:
    """根据组卷模式（薄弱优先/随机/顺序）筛选并截取目标题目数量。"""
    if mode_value == "weak_points":
        unmastered_wrong_ids = diagnosis_repo.list_unmastered_wrong_question_ids(user_id)
        weak_kp_ids = diagnosis_repo.list_weak_knowledge_point_ids(user_id, threshold=0.40)

        def _weakness_priority(q: Question) -> tuple[int, int]:
            return (
                1 if q.id in unmastered_wrong_ids else 0,
                1 if q.knowledge_point_id in weak_kp_ids else 0,
            )

        candidates.sort(key=_weakness_priority, reverse=True)
        return candidates[:question_count]

    if mode_value == "random":
        shuffled = list(candidates)
        random.shuffle(shuffled)
        return shuffled[:question_count]

    return candidates[:question_count]


def build_validated_snapshots(questions: Sequence[Question]) -> list[dict[str, Any]]:
    """为选中题目构造并校验 6 要素不可变快照列表。"""
    snapshots: list[dict[str, Any]] = []
    for question in questions:
        snapshot = build_question_snapshot(question)
        is_valid, err_msg = validate_question_snapshot(snapshot)
        if not is_valid:
            raise AppError(
                error_code=40008,
                message=f"题目快照质检未通过: {err_msg}",
                details={"question_id": str(question.id), "reason": err_msg},
            )
        snapshots.append(snapshot)
    return snapshots


__all__ = [
    "PracticeItemView",
    "PracticeView",
    "build_validated_snapshots",
    "collect_interleaved_candidates",
    "rank_candidates_by_mode",
    "select_explicit_questions",
    "wrap_practice_with_source_snippets",
]
