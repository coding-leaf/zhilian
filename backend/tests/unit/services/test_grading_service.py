"""Unit tests for GradingService in app/services/grading.py.

Verifies:
1. Offline auto-grading for objective questions (choice, true/false, fill-in-the-blank).
2. Unanswered items handled cleanly with zero score and is_answered=False.
3. Subjective question AI grading success path with structured LLM output.
4. LLM 20s timeout / failure fallback to PENDING_REGRADE without failing entire pipeline.
5. Practice session status transitions (COMPLETED vs PARTIALLY_GRADED).
6. User self-evaluation success, previous records is_final switching, and score recalculation.
7. User self-evaluation rejection on objective questions and score boundary validation.
8. AI regrading flow, is_final switching, and error handling.
9. Strict multi-tenant isolation against horizontal privilege escalation.
"""

import uuid
from collections.abc import Generator
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import (
    AttemptItemNotFoundError,
    GradingExecutionError,
    GradingNotAllowedError,
    LLMTimeoutError,
    PracticeNotFoundError,
)
from app.integrations.llm.fake import FakeLLMAdapter
from app.models.base import Base
from app.models.material import Material
from app.models.practice import (
    AttemptItem,
    GradingChannel,
    GradingStatus,
    Practice,
    PracticeStatus,
)
from app.models.question import QuestionType
from app.services.grading import (
    GradingService,
    LLMGradingOutput,
    LLMGradingRubricEvaluation,
    RegradeAttemptDTO,
    SelfEvaluateDTO,
)


@pytest.fixture
def session() -> Generator[Session, None, None]:
    """Provides an isolated in-memory SQLite database session."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as sess:
        yield sess
    engine.dispose()


@pytest.fixture
def fake_llm() -> FakeLLMAdapter:
    """Provides a fresh FakeLLMAdapter instance."""
    return FakeLLMAdapter()


@pytest.fixture
def setup_practice_env(session: Session) -> dict[str, Any]:
    """Creates a sample completed practice with various types of questions."""
    user_id = uuid.uuid4()
    material_id = uuid.uuid4()
    practice_id = uuid.uuid4()

    material = Material(
        id=material_id,
        user_id=user_id,
        title="网络协议教材.pdf",
        file_format="pdf",
        file_size=2048,
    )

    practice = Practice(
        id=practice_id,
        material_id=material_id,
        user_id=user_id,
        title="网络基础测试",
        status=PracticeStatus.COMPLETED.value,
        question_count=5,
    )

    # 1. Single Choice
    item_sc = AttemptItem(
        id=uuid.uuid4(),
        practice_id=practice_id,
        user_id=user_id,
        order_index=1,
        question_snapshot={
            "stem": "TCP 建立连接需要几次握手？",
            "question_type": QuestionType.SINGLE_CHOICE.value,
            "options": [
                {"key": "A", "content": "1"},
                {"key": "B", "content": "2"},
                {"key": "C", "content": "3"},
                {"key": "D", "content": "4"},
            ],
            "answer": "C",
        },
        user_answer="C",
        is_answered=True,
        max_score=2.0,
    )

    # 2. Multiple Choice
    item_mc = AttemptItem(
        id=uuid.uuid4(),
        practice_id=practice_id,
        user_id=user_id,
        order_index=2,
        question_snapshot={
            "stem": "以下属于传输层协议的是？",
            "question_type": QuestionType.MULTIPLE_CHOICE.value,
            "options": [
                {"key": "A", "content": "TCP"},
                {"key": "B", "content": "IP"},
                {"key": "C", "content": "UDP"},
                {"key": "D", "content": "HTTP"},
            ],
            "answer": "AC",
        },
        user_answer="A, C",
        is_answered=True,
        max_score=3.0,
    )

    # 3. True / False
    item_tf = AttemptItem(
        id=uuid.uuid4(),
        practice_id=practice_id,
        user_id=user_id,
        order_index=3,
        question_snapshot={
            "stem": "HTTP 是无状态协议。",
            "question_type": QuestionType.TRUE_FALSE.value,
            "answer": "True",
        },
        user_answer="对",
        is_answered=True,
        max_score=2.0,
    )

    # 4. Fill in Blank
    item_fib = AttemptItem(
        id=uuid.uuid4(),
        practice_id=practice_id,
        user_id=user_id,
        order_index=4,
        question_snapshot={
            "stem": "域名系统缩写为 ___。",
            "question_type": QuestionType.FILL_IN_BLANK.value,
            "answer": "DNS",
        },
        user_answer="dns",
        is_answered=True,
        max_score=3.0,
    )

    # 5. Subjective Short Answer
    item_sub = AttemptItem(
        id=uuid.uuid4(),
        practice_id=practice_id,
        user_id=user_id,
        order_index=5,
        question_snapshot={
            "stem": "简述三次握手交互过程。",
            "question_type": QuestionType.SHORT_ANSWER.value,
            "answer": "客户端发送SYN，服务端回复SYN+ACK，客户端发送ACK。",
            "grading_rubric": {},
        },
        user_answer="客户端发送SYN，服务端回SYN-ACK，客户端确认ACK",
        is_answered=True,
        max_score=5.0,
    )

    session.add_all([material, practice, item_sc, item_mc, item_tf, item_fib, item_sub])
    session.flush()

    return {
        "user_id": user_id,
        "practice": practice,
        "item_sc": item_sc,
        "item_mc": item_mc,
        "item_tf": item_tf,
        "item_fib": item_fib,
        "item_sub": item_sub,
    }


class TestGradingService:
    """Test suite for GradingService."""

    def test_offline_grading_all_objective_questions(
        self, session: Session, setup_practice_env: dict[str, Any]
    ) -> None:
        """Verify that objective questions are automatically graded offline with high precision."""
        user_id = setup_practice_env["user_id"]
        practice = setup_practice_env["practice"]

        # Only grade objective items by removing the subjective one for this test
        session.delete(setup_practice_env["item_sub"])
        session.flush()

        service = GradingService(session=session)
        summary = service.grade_practice(user_id=user_id, practice_id=practice.id)

        assert summary.practice_id == practice.id
        assert summary.status == PracticeStatus.COMPLETED.value
        assert summary.pending_regrade_count == 0
        assert summary.total_items == 4
        assert summary.graded_items == 4
        # All 4 items are answered correctly: 2 + 3 + 2 + 3 = 10.0
        assert summary.total_score == 10.0
        assert summary.max_score == 10.0

        for record in summary.records:
            assert record.channel == GradingChannel.OFFLINE.value
            assert record.status == GradingStatus.SUCCESS.value
            assert record.is_final is True

    def test_unanswered_items_graded_zero(
        self, session: Session, setup_practice_env: dict[str, Any]
    ) -> None:
        """Verify that unanswered items receive 0 score and offline success record."""
        user_id = setup_practice_env["user_id"]
        practice = setup_practice_env["practice"]
        item_sc = setup_practice_env["item_sc"]

        # Mark as unanswered
        item_sc.is_answered = False
        item_sc.user_answer = ""
        session.flush()

        # Remove subjective item for simplicity
        session.delete(setup_practice_env["item_sub"])
        session.flush()

        service = GradingService(session=session)
        summary = service.grade_practice(user_id=user_id, practice_id=practice.id)

        sc_record = next(r for r in summary.records if r.attempt_item_id == item_sc.id)
        assert sc_record.score == 0.0
        assert sc_record.channel == GradingChannel.OFFLINE.value
        assert sc_record.status == GradingStatus.SUCCESS.value
        assert sc_record.feedback == "未作答"

    def test_subjective_ai_grading_success(
        self,
        session: Session,
        setup_practice_env: dict[str, Any],
        fake_llm: FakeLLMAdapter,
    ) -> None:
        """Verify that subjective questions are graded via LLM with structured output."""
        user_id = setup_practice_env["user_id"]
        practice = setup_practice_env["practice"]
        item_sub = setup_practice_env["item_sub"]

        # Setup canned structured LLM output
        canned_output = LLMGradingOutput(
            score=4.5,
            confidence=0.92,
            feedback="三次握手关键步骤阐述清晰",
            hit_keywords=["SYN", "ACK"],
            missing_keywords=[],
            evaluations=[
                LLMGradingRubricEvaluation(point_id="p1", score=2.5, reason="SYN描述完整"),
                LLMGradingRubricEvaluation(point_id="p2", score=2.0, reason="ACK描述完整"),
            ],
        )
        fake_llm.set_canned_structured_response(LLMGradingOutput, canned_output)

        service = GradingService(session=session, llm_adapter=fake_llm)
        summary = service.grade_practice(user_id=user_id, practice_id=practice.id)

        assert summary.status == PracticeStatus.COMPLETED.value
        assert summary.pending_regrade_count == 0

        sub_record = next(r for r in summary.records if r.attempt_item_id == item_sub.id)
        assert sub_record.channel == GradingChannel.AI.value
        assert sub_record.status == GradingStatus.SUCCESS.value
        assert sub_record.score == 4.5
        assert sub_record.is_final is True
        assert sub_record.confidence == 0.92
        assert "SYN" in sub_record.hit_keywords

    def test_subjective_ai_timeout_fallback_to_pending_regrade(
        self,
        session: Session,
        setup_practice_env: dict[str, Any],
        fake_llm: FakeLLMAdapter,
    ) -> None:
        """Verify LLM timeout degrades to pending_regrade without failing the practice grading."""
        user_id = setup_practice_env["user_id"]
        practice = setup_practice_env["practice"]
        item_sub = setup_practice_env["item_sub"]

        # Inject timeout fault
        fake_llm.set_fault_injection("all", LLMTimeoutError("LLM 20s timeout"))

        service = GradingService(session=session, llm_adapter=fake_llm)
        summary = service.grade_practice(user_id=user_id, practice_id=practice.id)

        # Practice status should be PARTIALLY_GRADED due to pending_regrade
        assert summary.status == PracticeStatus.PARTIALLY_GRADED.value
        assert summary.pending_regrade_count == 1
        assert practice.status == PracticeStatus.PARTIALLY_GRADED.value

        sub_record = next(r for r in summary.records if r.attempt_item_id == item_sub.id)
        assert sub_record.channel == GradingChannel.AI.value
        assert sub_record.status == GradingStatus.PENDING_REGRADE.value
        assert sub_record.score == 0.0
        assert sub_record.is_final is True
        assert "超时" in (sub_record.feedback or "")
        # 待重判的作答项必须为“未定分”(None)，与真实 0 分区分，供前端判定为“待重新判题”
        assert item_sub.score is None

    def test_grade_practice_submission_alias(
        self,
        session: Session,
        setup_practice_env: dict[str, Any],
        fake_llm: FakeLLMAdapter,
    ) -> None:
        """Verify the grade_practice_submission method alias with (practice_id, user_id)."""
        user_id = setup_practice_env["user_id"]
        practice = setup_practice_env["practice"]

        fake_llm.set_canned_structured_response(
            LLMGradingOutput,
            LLMGradingOutput(score=5.0, confidence=1.0, feedback="完美"),
        )

        service = GradingService(session=session, llm_adapter=fake_llm)
        summary = service.grade_practice_submission(practice_id=practice.id, user_id=user_id)
        assert summary.practice_id == practice.id
        assert summary.status == PracticeStatus.COMPLETED.value

    def test_grade_practice_invalid_status(
        self, session: Session, setup_practice_env: dict[str, Any]
    ) -> None:
        """Verify calling grade_practice on not_started practice raises GradingNotAllowedError."""
        user_id = setup_practice_env["user_id"]
        practice = setup_practice_env["practice"]
        practice.status = PracticeStatus.IN_PROGRESS.value
        session.flush()

        service = GradingService(session=session)
        with pytest.raises(GradingNotAllowedError) as exc_info:
            service.grade_practice(user_id=user_id, practice_id=practice.id)
        assert exc_info.value.error_code == 40014

    def test_self_evaluate_attempt_success(
        self, session: Session, setup_practice_env: dict[str, Any]
    ) -> None:
        """Verify user self-evaluation creates a USER_SELF record and updates practice score."""
        user_id = setup_practice_env["user_id"]
        practice = setup_practice_env["practice"]
        item_sub = setup_practice_env["item_sub"]

        service = GradingService(session=session)

        # 1. Initial grade with fake LLM failing -> pending_regrade
        fake_llm = FakeLLMAdapter()
        fake_llm.set_fault_injection("all", LLMTimeoutError("timeout"))
        service.llm_adapter = fake_llm
        service.grade_practice(user_id=user_id, practice_id=practice.id)
        assert practice.status == PracticeStatus.PARTIALLY_GRADED.value

        # 2. User self-evaluates subjective item
        dto = SelfEvaluateDTO(
            attempt_item_id=item_sub.id,
            score=4.0,
            feedback="用户自评要点齐全",
        )
        record = service.self_evaluate_attempt(user_id=user_id, dto=dto)

        assert record.channel == GradingChannel.USER_SELF.value
        assert record.status == GradingStatus.SUCCESS.value
        assert record.is_final is True
        assert record.score == 4.0
        assert record.feedback == "用户自评要点齐全"
        assert item_sub.score == 4.0

        # Pending regrades resolved -> practice transitions to COMPLETED
        assert practice.status == PracticeStatus.COMPLETED.value

        # Verify old records have is_final = False
        all_records = service.grading_repo.list_records_by_attempt_item(
            item_sub.id, user_id=user_id
        )
        assert len(all_records) == 2
        assert all_records[0].is_final is False
        assert all_records[1].is_final is True

    def test_self_evaluate_attempt_positional_alias(
        self, session: Session, setup_practice_env: dict[str, Any]
    ) -> None:
        """Verify self_evaluate_attempt supports positional arguments."""
        user_id = setup_practice_env["user_id"]
        item_sub = setup_practice_env["item_sub"]

        service = GradingService(session=session)
        record = service.self_evaluate_attempt(
            item_sub.id,
            user_id,
            3.5,
            True,
            "还行",
        )
        assert record.score == 3.5
        assert record.channel == GradingChannel.USER_SELF.value

    def test_self_evaluate_attempt_reject_objective(
        self, session: Session, setup_practice_env: dict[str, Any]
    ) -> None:
        """Verify that attempting to self-evaluate objective items raises GradingNotAllowedError."""
        user_id = setup_practice_env["user_id"]
        item_sc = setup_practice_env["item_sc"]

        service = GradingService(session=session)
        dto = SelfEvaluateDTO(attempt_item_id=item_sc.id, score=2.0)

        with pytest.raises(GradingNotAllowedError) as exc_info:
            service.self_evaluate_attempt(user_id=user_id, dto=dto)
        assert exc_info.value.error_code == 40014
        assert "客观" in exc_info.value.message

    def test_self_evaluate_attempt_score_out_of_bounds(
        self, session: Session, setup_practice_env: dict[str, Any]
    ) -> None:
        """Verify that score > max_score or score < 0 raises GradingNotAllowedError."""
        user_id = setup_practice_env["user_id"]
        item_sub = setup_practice_env["item_sub"]

        service = GradingService(session=session)

        # score > max_score (max is 5.0)
        with pytest.raises(GradingNotAllowedError):
            service.self_evaluate_attempt(
                user_id=user_id,
                dto=SelfEvaluateDTO(attempt_item_id=item_sub.id, score=6.0),
            )

        # score < 0
        with pytest.raises(GradingNotAllowedError):
            service.self_evaluate_attempt(
                user_id=user_id,
                dto=SelfEvaluateDTO(attempt_item_id=item_sub.id, score=-1.0),
            )

    def test_self_evaluate_attempt_not_found(
        self, session: Session, setup_practice_env: dict[str, Any]
    ) -> None:
        """Verify that non-existent attempt item raises AttemptItemNotFoundError."""
        user_id = setup_practice_env["user_id"]
        service = GradingService(session=session)

        with pytest.raises(AttemptItemNotFoundError) as exc_info:
            service.self_evaluate_attempt(
                user_id=user_id,
                dto=SelfEvaluateDTO(attempt_item_id=uuid.uuid4(), score=1.0),
            )
        assert exc_info.value.error_code == 40013

    def test_regrade_attempt_success(
        self,
        session: Session,
        setup_practice_env: dict[str, Any],
        fake_llm: FakeLLMAdapter,
    ) -> None:
        """Verify regrading subjective item re-invokes LLM and switches is_final."""
        user_id = setup_practice_env["user_id"]
        practice = setup_practice_env["practice"]
        item_sub = setup_practice_env["item_sub"]

        # Initial grade with failure -> PARTIALLY_GRADED
        fake_llm.set_fault_injection("all", LLMTimeoutError("initial timeout"))
        service = GradingService(session=session, llm_adapter=fake_llm)
        service.grade_practice(user_id=user_id, practice_id=practice.id)
        assert practice.status == PracticeStatus.PARTIALLY_GRADED.value

        # Clear fault and set success canned output
        fake_llm.reset()
        fake_llm.set_canned_structured_response(
            LLMGradingOutput,
            LLMGradingOutput(score=4.8, confidence=0.98, feedback="重判得分更新"),
        )

        dto = RegradeAttemptDTO(attempt_item_id=item_sub.id)
        record = service.regrade_attempt(user_id=user_id, dto=dto)

        assert record.channel == GradingChannel.AI.value
        assert record.status == GradingStatus.SUCCESS.value
        assert record.score == 4.8
        assert record.is_final is True
        assert item_sub.score == 4.8
        assert practice.status == PracticeStatus.COMPLETED.value

        # Check alias
        record_alias = service.regrade_attempt(item_sub.id, user_id)
        assert record_alias.id is not None

    def test_regrade_attempt_reject_objective_or_unanswered(
        self, session: Session, setup_practice_env: dict[str, Any], fake_llm: FakeLLMAdapter
    ) -> None:
        """Verify calling regrade on objective or unanswered item raises GradingNotAllowedError."""
        user_id = setup_practice_env["user_id"]
        item_sc = setup_practice_env["item_sc"]
        item_sub = setup_practice_env["item_sub"]

        service = GradingService(session=session, llm_adapter=fake_llm)

        # Objective item regrade rejected
        with pytest.raises(GradingNotAllowedError) as exc_info:
            service.regrade_attempt(
                user_id=user_id, dto=RegradeAttemptDTO(attempt_item_id=item_sc.id)
            )
        assert exc_info.value.error_code == 40014

        # Unanswered item regrade rejected
        item_sub.is_answered = False
        session.flush()
        with pytest.raises(GradingNotAllowedError):
            service.regrade_attempt(
                user_id=user_id, dto=RegradeAttemptDTO(attempt_item_id=item_sub.id)
            )

    def test_regrade_attempt_llm_failure(
        self,
        session: Session,
        setup_practice_env: dict[str, Any],
        fake_llm: FakeLLMAdapter,
    ) -> None:
        """Verify that LLM failure during regrade raises GradingExecutionError."""
        user_id = setup_practice_env["user_id"]
        item_sub = setup_practice_env["item_sub"]

        fake_llm.set_fault_injection("all", RuntimeError("LLM internal error"))
        service = GradingService(session=session, llm_adapter=fake_llm)

        with pytest.raises(GradingExecutionError) as exc_info:
            service.regrade_attempt(
                user_id=user_id,
                dto=RegradeAttemptDTO(attempt_item_id=item_sub.id),
            )
        assert exc_info.value.error_code == 40015

    def test_tenant_cross_access_isolation(
        self, session: Session, setup_practice_env: dict[str, Any]
    ) -> None:
        """Verify that User B cannot grade, self-evaluate, or regrade User A's attempts."""
        user_b = uuid.uuid4()
        practice = setup_practice_env["practice"]
        item_sub = setup_practice_env["item_sub"]

        service = GradingService(session=session)

        # User B attempts to grade User A's practice
        with pytest.raises(PracticeNotFoundError):
            service.grade_practice(user_id=user_b, practice_id=practice.id)

        # User B attempts to self-evaluate User A's attempt
        with pytest.raises(AttemptItemNotFoundError):
            service.self_evaluate_attempt(
                user_id=user_b,
                dto=SelfEvaluateDTO(attempt_item_id=item_sub.id, score=3.0),
            )

        # User B attempts to regrade User A's attempt
        with pytest.raises(AttemptItemNotFoundError):
            service.regrade_attempt(
                user_id=user_b,
                dto=RegradeAttemptDTO(attempt_item_id=item_sub.id),
            )

    def test_grade_attempt_with_rubric_dimensions_and_no_adapter(
        self, session: Session, setup_practice_env: dict[str, Any]
    ) -> None:
        """Verify rubric parsing with 'dimensions' and fallback when no LLM adapter configured."""
        user_id = setup_practice_env["user_id"]
        practice = setup_practice_env["practice"]
        item_sub = setup_practice_env["item_sub"]

        # Configure rubric with 'dimensions'
        item_sub.question_snapshot["grading_rubric"] = {
            "dimensions": [
                {"point_id": "dim1", "description": "握手步骤", "score": 2.5, "keywords": ["握手"]},
            ]
        }
        item_sub.user_answer = "双方三次握手建立连接"
        session.flush()

        # Grade without llm_adapter -> falls back to pending_regrade
        service = GradingService(session=session, llm_adapter=None)
        summary = service.grade_practice(user_id=user_id, practice_id=practice.id)

        assert summary.status == PracticeStatus.PARTIALLY_GRADED.value
        rec = next(r for r in summary.records if r.attempt_item_id == item_sub.id)
        assert rec.status == GradingStatus.PENDING_REGRADE.value

    def test_self_evaluate_invalid_arguments(
        self, session: Session, setup_practice_env: dict[str, Any]
    ) -> None:
        """Verify defensive argument validation in self_evaluate_attempt."""
        user_id = setup_practice_env["user_id"]
        item_sub = setup_practice_env["item_sub"]
        service = GradingService(session=session)

        # Missing score when calling with user_id
        with pytest.raises(GradingNotAllowedError) as exc:
            service.self_evaluate_attempt(item_sub.id, user_id, score=None)
        assert "score" in str(exc.value)

        # Invalid DTO type (e.g. string)
        with pytest.raises(GradingNotAllowedError):
            service.self_evaluate_attempt(item_sub.id, "invalid_dto")  # type: ignore[arg-type]

    def test_regrade_invalid_arguments_and_missing_adapter(
        self, session: Session, setup_practice_env: dict[str, Any]
    ) -> None:
        """Verify defensive argument validation and missing adapter check in regrade_attempt."""
        user_id = setup_practice_env["user_id"]
        item_sub = setup_practice_env["item_sub"]

        # Missing adapter
        service_no_llm = GradingService(session=session, llm_adapter=None)
        with pytest.raises(GradingExecutionError) as exc:
            service_no_llm.regrade_attempt(item_sub.id, user_id)
        assert "未配置" in str(exc.value)

        # Invalid DTO type
        service = GradingService(session=session)
        with pytest.raises(GradingNotAllowedError):
            service.regrade_attempt(item_sub.id, 12345)  # type: ignore[arg-type]

    def test_get_attempt_grading_detail_success_and_tenant_isolation(
        self, session: Session, setup_practice_env: dict[str, Any]
    ) -> None:
        """Verify get_attempt_grading_detail queries records and enforces tenant isolation."""
        user_id = setup_practice_env["user_id"]
        practice = setup_practice_env["practice"]
        item_sub = setup_practice_env["item_sub"]
        service = GradingService(session=session)

        # 1. Non-existent attempt item
        with pytest.raises(AttemptItemNotFoundError):
            service.get_attempt_grading_detail(user_id=user_id, attempt_item_id=uuid.uuid4())

        # 2. Cross-tenant isolation
        user_b = uuid.uuid4()
        with pytest.raises(AttemptItemNotFoundError):
            service.get_attempt_grading_detail(user_id=user_b, attempt_item_id=item_sub.id)

        # 3. Successful query with self-evaluation record
        service.self_evaluate_attempt(
            user_id=user_id,
            dto=SelfEvaluateDTO(attempt_item_id=item_sub.id, score=4.0, feedback="Nice answer"),
        )
        detail = service.get_attempt_grading_detail(
            user_id=user_id,
            attempt_item_id=item_sub.id,
        )
        assert detail.attempt_item_id == item_sub.id
        assert detail.practice_id == practice.id
        assert detail.latest_grading is not None
        assert detail.latest_grading.score == 4.0
        assert len(detail.records) >= 1
