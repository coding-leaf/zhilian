"""Unit tests for multi-knowledge-point question generation orchestration.

Verifies:
1. Pure helper `distribute_count`: even split, remainder front-loading, floor-one.
2. Service orchestration `generate_questions_for_knowledge_points`:
   - per-knowledge-point call count and count distribution,
   - aggregation of qualified/pending/quality_checks and counters,
   - legacy knowledge_point_id equals the first target,
   - fail-fast propagation when any knowledge point fails.
"""

import uuid
from unittest.mock import MagicMock

import pytest

from app.core.errors import KnowledgeNotFoundError
from app.models.question import Question
from app.services.question import (
    GenerateQuestionsOptions,
    MultiKnowledgePointGenerationResult,
    QuestionGenerationResult,
    QuestionService,
    distribute_count,
)


def _make_question(
    user_id: uuid.UUID,
    material_id: uuid.UUID,
    version_id: uuid.UUID,
    knowledge_point_id: uuid.UUID,
    stem: str,
) -> Question:
    """Builds a lightweight in-memory Question entity for orchestration assertions."""
    return Question(
        user_id=user_id,
        material_id=material_id,
        version_id=version_id,
        knowledge_point_id=knowledge_point_id,
        question_type="single_choice",
        stem=stem,
        options=[{"key": "A", "content": "选项A"}, {"key": "B", "content": "选项B"}],
        answer="A",
        difficulty=3,
    )


def _build_service(
    monkeypatch: pytest.MonkeyPatch,
    captured: list[tuple[uuid.UUID, int]],
    fail_on: uuid.UUID | None = None,
) -> QuestionService:
    """Builds a QuestionService with generate_questions stubbed for orchestration tests."""
    service = QuestionService(
        session=MagicMock(),
        llm=MagicMock(),
        embedding=MagicMock(),
    )

    def fake_generate_questions(
        *,
        user_id: uuid.UUID,
        material_id: uuid.UUID,
        version_id: uuid.UUID | None = None,
        knowledge_point_id: uuid.UUID,
        options: GenerateQuestionsOptions | None = None,
    ) -> QuestionGenerationResult:
        effective_options = options if options is not None else GenerateQuestionsOptions()
        captured.append((knowledge_point_id, effective_options.count))
        if fail_on is not None and knowledge_point_id == fail_on:
            raise KnowledgeNotFoundError("请求的知识点不存在或无权访问")

        aligned_version_id = version_id or uuid.uuid4()
        questions = [
            _make_question(
                user_id=user_id,
                material_id=material_id,
                version_id=aligned_version_id,
                knowledge_point_id=knowledge_point_id,
                stem=f"考点{str(knowledge_point_id)[:6]}题目{idx}描述内容",
            )
            for idx in range(effective_options.count)
        ]
        return QuestionGenerationResult(
            batch_id=f"batch_{knowledge_point_id.hex[:8]}",
            material_id=material_id,
            version_id=aligned_version_id,
            knowledge_point_id=knowledge_point_id,
            total_generated=len(questions),
            qualified_questions=questions,
            pending_questions=[],
            quality_checks=[],
            retry_count=0,
        )

    monkeypatch.setattr(service, "generate_questions", fake_generate_questions)
    return service


class TestDistributeCount:
    """Test suite for the pure `distribute_count` helper."""

    def test_even_split(self) -> None:
        assert distribute_count(6, 3) == [2, 2, 2]

    def test_remainder_front_loaded(self) -> None:
        assert distribute_count(7, 3) == [3, 2, 2]

    def test_total_less_than_n_floors_each_at_one(self) -> None:
        assert distribute_count(2, 3) == [1, 1, 1]

    def test_single_target(self) -> None:
        assert distribute_count(1, 1) == [1]
        assert distribute_count(5, 1) == [5]

    def test_invalid_inputs_raise(self) -> None:
        with pytest.raises(ValueError, match="total 必须为正整数"):
            distribute_count(0, 2)
        with pytest.raises(ValueError, match="n 必须为正整数"):
            distribute_count(5, 0)


class TestMultiKnowledgePointOrchestration:
    """Test suite for `QuestionService.generate_questions_for_knowledge_points`."""

    def test_aggregates_three_knowledge_points_evenly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """3 knowledge points / 6 questions -> 2 each, aggregated in call order."""
        captured: list[tuple[uuid.UUID, int]] = []
        service = _build_service(monkeypatch, captured)

        user_id = uuid.uuid4()
        material_id = uuid.uuid4()
        version_id = uuid.uuid4()
        kp_ids = [uuid.uuid4() for _ in range(3)]

        result = service.generate_questions_for_knowledge_points(
            user_id=user_id,
            material_id=material_id,
            version_id=version_id,
            knowledge_point_ids=kp_ids,
            options=GenerateQuestionsOptions(count=6),
        )

        assert captured == [(kp_ids[0], 2), (kp_ids[1], 2), (kp_ids[2], 2)]
        assert isinstance(result, MultiKnowledgePointGenerationResult)
        assert result.knowledge_point_id == kp_ids[0]
        assert list(result.knowledge_point_ids) == kp_ids
        assert result.requested_count == 6
        assert result.total_generated == 6
        assert result.version_id == version_id
        assert result.retry_count == 0
        assert len(result.qualified_questions) == 6
        assert {q.knowledge_point_id for q in result.qualified_questions} == set(kp_ids)

    def test_total_less_than_knowledge_points_floors_each_to_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """2 knowledge points / 1 requested question -> 1 each (actual total 2)."""
        captured: list[tuple[uuid.UUID, int]] = []
        service = _build_service(monkeypatch, captured)

        kp_ids = [uuid.uuid4(), uuid.uuid4()]
        result = service.generate_questions_for_knowledge_points(
            user_id=uuid.uuid4(),
            material_id=uuid.uuid4(),
            version_id=uuid.uuid4(),
            knowledge_point_ids=kp_ids,
            options=GenerateQuestionsOptions(count=1),
        )

        assert captured == [(kp_ids[0], 1), (kp_ids[1], 1)]
        assert result.requested_count == 1
        assert result.total_generated == 2
        assert {q.knowledge_point_id for q in result.qualified_questions} == set(kp_ids)

    def test_fail_fast_propagates_knowledge_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Any failed knowledge point aborts the whole orchestration (no silent skip)."""
        captured: list[tuple[uuid.UUID, int]] = []
        kp_ids = [uuid.uuid4() for _ in range(3)]
        service = _build_service(monkeypatch, captured, fail_on=kp_ids[1])

        with pytest.raises(KnowledgeNotFoundError):
            service.generate_questions_for_knowledge_points(
                user_id=uuid.uuid4(),
                material_id=uuid.uuid4(),
                version_id=uuid.uuid4(),
                knowledge_point_ids=kp_ids,
                options=GenerateQuestionsOptions(count=6),
            )

        # First target succeeded, second failed, third never reached.
        assert captured == [(kp_ids[0], 2), (kp_ids[1], 2)]

    def test_deduplicates_knowledge_point_ids_preserving_order(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Duplicate targets collapse to unique ones while keeping first-seen order."""
        captured: list[tuple[uuid.UUID, int]] = []
        service = _build_service(monkeypatch, captured)

        kp_a = uuid.uuid4()
        kp_b = uuid.uuid4()
        result = service.generate_questions_for_knowledge_points(
            user_id=uuid.uuid4(),
            material_id=uuid.uuid4(),
            version_id=uuid.uuid4(),
            knowledge_point_ids=[kp_a, kp_b, kp_a],
            options=GenerateQuestionsOptions(count=4),
        )

        assert captured == [(kp_a, 2), (kp_b, 2)]
        assert list(result.knowledge_point_ids) == [kp_a, kp_b]

    def test_empty_knowledge_point_ids_raises(self) -> None:
        """Orchestration rejects an empty target list."""
        service = QuestionService(session=MagicMock(), llm=MagicMock(), embedding=MagicMock())
        with pytest.raises(ValueError, match="knowledge_point_ids 不能为空"):
            service.generate_questions_for_knowledge_points(
                user_id=uuid.uuid4(),
                material_id=uuid.uuid4(),
                knowledge_point_ids=[],
            )
