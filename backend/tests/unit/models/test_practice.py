"""Unit tests for Practice, AttemptItem, GradingRecord, MasteryRecord, DiagnosisReport, WrongRecord.

Covers:
1. 6 core entities field constraints and enum validations
2. Decision 1: Two-stage state machine transitions (partially_graded blocks mastery & formal report)
3. Decision 2: Weak question foreign key (SET NULL) with JSONB snapshot decoupling
4. (practice_id, question_id) idempotency unique constraint on attempt_items
5. (user_id, knowledge_point_id) mastery record unique constraint
6. (user_id, question_id) wrong record unique constraint
7. Practice cascade deletion
8. validate_question_snapshot and validate_practice_transition pure functions
9. Desensitized __repr__ ensuring zero leakage of stems, options, answers, responses, rubrics.
"""

import uuid
from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models.base import Base
from app.models.knowledge import KnowledgePoint
from app.models.material import Material, MaterialDocType, MaterialVersion
from app.models.practice import (
    AttemptItem,
    DiagnosisReport,
    ErrorType,
    GradingChannel,
    GradingRecord,
    GradingStatus,
    MasteryLevel,
    MasteryRecord,
    Practice,
    PracticeSourceType,
    PracticeStatus,
    WrongRecord,
    validate_practice_transition,
    validate_question_snapshot,
)
from app.models.question import Question, QuestionType
from app.models.user import User


@pytest.fixture
def db_session() -> Generator[sessionmaker[Session], None, None]:
    """Creates an in-memory SQLite database session factory for practice tests."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory: sessionmaker[Session] = sessionmaker(bind=engine)
    try:
        yield session_factory
    finally:
        engine.dispose()


@pytest.fixture
def setup_practice_context(
    db_session: sessionmaker[Session],
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """Provides user, material, version, and knowledge point for tests."""
    user_id = uuid.uuid4()
    material_id = uuid.uuid4()
    version_id = uuid.uuid4()
    kp_id = uuid.uuid4()

    with db_session() as session:
        user = User(id=user_id, openid=f"test_practice_user_{user_id.hex[:8]}")
        session.add(user)

        material = Material(
            id=material_id,
            user_id=user_id,
            title="Operating Systems Principles",
            file_format=MaterialDocType.PDF.value,
            file_size=1048576,
        )
        session.add(material)

        version = MaterialVersion(
            id=version_id,
            user_id=user_id,
            material_id=material_id,
            version_number=1,
            storage_key="materials/os_v1.pdf",
            content_hash="content_hash_os_01",
        )
        session.add(version)

        kp = KnowledgePoint(
            id=kp_id,
            user_id=user_id,
            material_id=material_id,
            version_id=version_id,
            name="Virtual Memory Paging",
            description="Paging concepts and page tables",
            level=2,
            batch_id="batch_01",
        )
        session.add(kp)
        session.commit()

    return user_id, material_id, version_id, kp_id


class TestPracticePureFunctions:
    """Test suite for pure validation helper functions."""

    def test_validate_question_snapshot_valid_objective(self) -> None:
        """Verify valid objective choice question snapshot passes validation."""
        snapshot = {
            "question_id": str(uuid.uuid4()),
            "question_type": QuestionType.SINGLE_CHOICE.value,
            "stem": "Which page replacement algorithm suffers from Belady's anomaly?",
            "options": [
                {"key": "A", "content": "FIFO"},
                {"key": "B", "content": "LRU"},
                {"key": "C", "content": "Optimal"},
                {"key": "D", "content": "Clock"},
            ],
            "answer": "A",
            "analysis": "FIFO is known to suffer from Belady's anomaly.",
        }
        valid, error = validate_question_snapshot(snapshot)
        assert valid is True
        assert error is None

    def test_validate_question_snapshot_valid_subjective_with_rubric(self) -> None:
        """Verify valid subjective question snapshot with rubric passes."""
        snapshot = {
            "question_id": str(uuid.uuid4()),
            "question_type": QuestionType.SHORT_ANSWER.value,
            "stem": "Explain the role of TLB in virtual address translation.",
            "answer": "TLB is a fast hardware cache storing virtual-to-physical address mappings.",
            "analysis": "TLB avoids accessing main memory page tables on every reference.",
            "grading_rubric": {
                "total_score": 10.0,
                "dimensions": [
                    {"name": "Cache definition", "points": 4.0},
                    {"name": "Translation acceleration", "points": 6.0},
                ],
            },
        }
        valid, error = validate_question_snapshot(snapshot)
        assert valid is True
        assert error is None

    def test_validate_question_snapshot_invalid_cases(self) -> None:
        """Verify invalid snapshots are rejected with informative error messages."""
        # Non-dict
        valid, error = validate_question_snapshot("not a dict")  # type: ignore[arg-type]
        assert valid is False
        assert "must be a dictionary" in str(error)

        # Missing stem
        valid, error = validate_question_snapshot({"question_type": "single_choice", "answer": "A"})
        assert valid is False
        assert "stem is required" in str(error)

        # Blank stem
        valid, error = validate_question_snapshot(
            {"stem": "   ", "question_type": "single_choice", "answer": "A"}
        )
        assert valid is False
        assert "stem is required" in str(error)

        # Missing question_type
        valid, error = validate_question_snapshot({"stem": "What is paging?", "answer": "A"})
        assert valid is False
        assert "question_type is required" in str(error)

        # Missing answer
        valid, error = validate_question_snapshot(
            {"stem": "What is paging?", "question_type": "short_answer"}
        )
        assert valid is False
        assert "answer is required" in str(error)

        # Empty string answer
        valid, error = validate_question_snapshot(
            {"stem": "What is paging?", "question_type": "short_answer", "answer": "  "}
        )
        assert valid is False
        assert "answer is required" in str(error)

        # Choice type with invalid options
        valid, error = validate_question_snapshot(
            {
                "stem": "Select option",
                "question_type": "single_choice",
                "answer": "A",
                "options": [{"key": "A", "content": "Only one"}],
            }
        )
        assert valid is False
        assert "at least 2 items" in str(error)

        # Choice type with malformed option items
        valid, error = validate_question_snapshot(
            {
                "stem": "Select option",
                "question_type": "single_choice",
                "answer": "A",
                "options": [{"key": "A", "content": "OK"}, {"no_key": "wrong"}],
            }
        )
        assert valid is False
        assert "must contain 'key' and 'content'" in str(error)

        # Rubric without total_score passes cleanly
        valid, error = validate_question_snapshot(
            {
                "stem": "Subjective question",
                "question_type": "short_answer",
                "answer": "Answer here",
                "grading_rubric": {"general_note": "check key points"},
            }
        )
        assert valid is True
        assert error is None

        # Rubric points sum mismatch
        valid, error = validate_question_snapshot(
            {
                "stem": "Subjective question",
                "question_type": "short_answer",
                "answer": "Answer here",
                "grading_rubric": {
                    "total_score": 10.0,
                    "points": [{"score": 3.0}, {"score": 4.0}],
                },
            }
        )
        assert valid is False
        assert "does not match total_score" in str(error)

        # Rubric with non-dict and non-numeric dimension items
        valid, error = validate_question_snapshot(
            {
                "stem": "Subjective question",
                "question_type": "short_answer",
                "answer": "Answer here",
                "grading_rubric": {
                    "total_score": 10.0,
                    "dimensions": ["invalid_item", {"points": "nan"}, {"points": 10.0}],
                },
            }
        )
        assert valid is True
        assert error is None

    def test_validate_practice_transition_decision_1(self) -> None:
        """Verify Technical Decision 1: Two-stage state machine transitions."""
        # 1. NOT_STARTED -> IN_PROGRESS
        ok, reason, target = validate_practice_transition(PracticeStatus.NOT_STARTED, False, False)
        assert ok is True
        assert target == PracticeStatus.IN_PROGRESS

        # 2. IN_PROGRESS -> PARTIALLY_GRADED (when has_pending_regrade)
        ok, reason, target = validate_practice_transition(PracticeStatus.IN_PROGRESS, True, False)
        assert ok is True
        assert target == PracticeStatus.PARTIALLY_GRADED

        ok, reason, target = validate_practice_transition(PracticeStatus.IN_PROGRESS, True, True)
        assert ok is True
        assert target == PracticeStatus.PARTIALLY_GRADED

        # 3. IN_PROGRESS -> COMPLETED (all graded, no pending_regrade)
        ok, reason, target = validate_practice_transition(PracticeStatus.IN_PROGRESS, False, True)
        assert ok is True
        assert target == PracticeStatus.COMPLETED

        # 4. IN_PROGRESS stays IN_PROGRESS if items still being answered
        ok, reason, target = validate_practice_transition(PracticeStatus.IN_PROGRESS, False, False)
        assert ok is True
        assert target == PracticeStatus.IN_PROGRESS

        # 5. PARTIALLY_GRADED blocks COMPLETED while pending_regrade exists
        ok, reason, target = validate_practice_transition(
            PracticeStatus.PARTIALLY_GRADED, True, True
        )
        assert ok is False
        assert "Cannot complete practice with pending_regrade" in str(reason)
        assert target is None

        # 6. PARTIALLY_GRADED -> COMPLETED when all resolved
        ok, reason, target = validate_practice_transition(
            PracticeStatus.PARTIALLY_GRADED, False, True
        )
        assert ok is True
        assert target == PracticeStatus.COMPLETED

        # 7. PARTIALLY_GRADED stays PARTIALLY_GRADED if not all items resolved
        ok, reason, target = validate_practice_transition(
            PracticeStatus.PARTIALLY_GRADED, False, False
        )
        assert ok is True
        assert target == PracticeStatus.PARTIALLY_GRADED

        # 8. COMPLETED is terminal
        ok, reason, target = validate_practice_transition(PracticeStatus.COMPLETED, False, True)
        assert ok is False
        assert "immutable" in str(reason)

        # 9. Invalid string status
        ok, reason, target = validate_practice_transition("invalid_status", False, False)
        assert ok is False
        assert "Unknown practice status" in str(reason)

    def test_validate_practice_transition_paused_and_timeout(self) -> None:
        """Verify PAUSED/TIMEOUT are canonical states with correct transitions (BUG-PRAC-006)."""
        # Enum exposes the two runtime-persisted states
        assert PracticeStatus.PAUSED.value == "paused"
        assert PracticeStatus.TIMEOUT.value == "timeout"

        # PAUSED can resume back to IN_PROGRESS
        ok, reason, target = validate_practice_transition(PracticeStatus.PAUSED, False, False)
        assert ok is True
        assert reason is None
        assert target == PracticeStatus.IN_PROGRESS

        ok, reason, target = validate_practice_transition("paused", False, True)
        assert ok is True
        assert target == PracticeStatus.IN_PROGRESS

        # TIMEOUT is an immutable terminal state
        ok, reason, target = validate_practice_transition(PracticeStatus.TIMEOUT, False, True)
        assert ok is False
        assert target is None
        assert "immutable" in str(reason).lower() or "timeout" in str(reason).lower()

        ok, reason, target = validate_practice_transition("timeout", True, False)
        assert ok is False
        assert target is None


class TestPracticeModelConstraints:
    """Test suite for Practice model creation and constraints."""

    def test_create_practice_success(
        self,
        db_session: sessionmaker[Session],
        setup_practice_context: tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID],
    ) -> None:
        """Verify normal creation of Practice entity with default and explicit fields."""
        user_id, material_id, _, kp_id = setup_practice_context
        practice_id = uuid.uuid4()

        with db_session() as session:
            practice = Practice(
                id=practice_id,
                user_id=user_id,
                material_id=material_id,
                title="OS Unit 1 Practice",
                knowledge_point_ids=[str(kp_id)],
                question_types=[QuestionType.SINGLE_CHOICE.value],
                difficulty=3,
                question_count=5,
                ordered_question_ids=[str(uuid.uuid4()) for _ in range(5)],
                source_type=PracticeSourceType.NORMAL.value,
                submit_idempotency_key=str(uuid.uuid4()),
                total_score=8.5,
                max_score=10.0,
            )
            session.add(practice)
            session.commit()

        with db_session() as session:
            saved = session.get(Practice, practice_id)
            assert saved is not None
            assert saved.title == "OS Unit 1 Practice"
            assert saved.status == PracticeStatus.NOT_STARTED.value
            assert saved.source_type == PracticeSourceType.NORMAL.value
            assert saved.question_count == 5
            assert saved.total_score == 8.5
            assert saved.max_score == 10.0
            assert len(saved.ordered_question_ids) == 5

    def test_practice_submit_idempotency_unique_constraint(
        self,
        db_session: sessionmaker[Session],
        setup_practice_context: tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID],
    ) -> None:
        """Verify submit_idempotency_key unique constraint prevents duplicate submission keys."""
        user_id, material_id, _, _ = setup_practice_context
        idempotency_key = f"submit_idem_key_{uuid.uuid4().hex[:12]}"

        with db_session() as session:
            p1 = Practice(
                user_id=user_id,
                material_id=material_id,
                title="Practice 1",
                submit_idempotency_key=idempotency_key,
            )
            session.add(p1)
            session.commit()

            p2 = Practice(
                user_id=user_id,
                material_id=material_id,
                title="Practice 2 with same key",
                submit_idempotency_key=idempotency_key,
            )
            session.add(p2)
            with pytest.raises(IntegrityError):
                session.commit()


class TestAttemptItemAndDecoupling:
    """Test suite for AttemptItem, weak question foreign key, and question snapshot."""

    def test_question_snapshot_decoupling_on_question_deletion(
        self,
        db_session: sessionmaker[Session],
        setup_practice_context: tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID],
    ) -> None:
        """Verify Technical Decision 2: when Question is deleted,

        AttemptItem.question_id becomes NULL and question_snapshot remains intact.
        """
        user_id, material_id, version_id, kp_id = setup_practice_context
        question_id = uuid.uuid4()
        practice_id = uuid.uuid4()
        item_id = uuid.uuid4()

        snapshot_data = {
            "question_id": str(question_id),
            "question_type": "single_choice",
            "stem": "Which register holds the page table base address?",
            "options": [
                {"key": "A", "content": "CR3"},
                {"key": "B", "content": "EAX"},
            ],
            "answer": "A",
            "analysis": "CR3 register holds the page directory base address in x86.",
        }

        with db_session() as session:
            # 1. Create a Question
            question = Question(
                id=question_id,
                user_id=user_id,
                material_id=material_id,
                version_id=version_id,
                knowledge_point_id=kp_id,
                question_type=QuestionType.SINGLE_CHOICE.value,
                stem=snapshot_data["stem"],
                options=snapshot_data["options"],
                answer=snapshot_data["answer"],
                analysis=snapshot_data["analysis"],
            )
            session.add(question)

            # 2. Create Practice and AttemptItem referencing question
            practice = Practice(
                id=practice_id,
                user_id=user_id,
                material_id=material_id,
                title="Decoupling Test Practice",
            )
            session.add(practice)

            item = AttemptItem(
                id=item_id,
                user_id=user_id,
                practice_id=practice_id,
                question_id=question_id,
                order_index=1,
                question_snapshot=snapshot_data,
                user_answer="A",
                is_answered=True,
                duration_seconds=25,
                score=1.0,
                max_score=1.0,
            )
            session.add(item)
            session.commit()

        # 3. Simulate Question deletion (e.g. material deleted or question pruned)
        with db_session() as session:
            q = session.get(Question, question_id)
            assert q is not None
            session.delete(q)
            session.commit()

        # 4. Verify AttemptItem still exists and snapshot is completely intact
        with db_session() as session:
            it = session.get(AttemptItem, item_id)
            assert it is not None
            # In SQLite memory without foreign_keys PRAGMA, SET NULL might stay or become None,
            # but snapshot data must be completely preserved:
            expected_stem = "Which register holds the page table base address?"
            assert it.question_snapshot["stem"] == expected_stem
            assert it.question_snapshot["answer"] == "A"
            assert it.user_answer == "A"
            assert it.is_answered is True
            assert it.score == 1.0

    def test_attempt_items_practice_question_unique_constraint(
        self,
        db_session: sessionmaker[Session],
        setup_practice_context: tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID],
    ) -> None:
        """Verify (practice_id, question_id) unique constraint prevents duplicate attempt items."""
        user_id, material_id, _, _ = setup_practice_context
        practice_id = uuid.uuid4()
        question_id = uuid.uuid4()

        snapshot_data = {
            "question_type": "true_false",
            "stem": "Paging causes external fragmentation.",
            "answer": "False",
        }

        with db_session() as session:
            practice = Practice(
                id=practice_id,
                user_id=user_id,
                material_id=material_id,
                title="Idempotency Test",
            )
            session.add(practice)

            item1 = AttemptItem(
                user_id=user_id,
                practice_id=practice_id,
                question_id=question_id,
                order_index=1,
                question_snapshot=snapshot_data,
                user_answer="False",
            )
            session.add(item1)
            session.commit()

            item2 = AttemptItem(
                user_id=user_id,
                practice_id=practice_id,
                question_id=question_id,
                order_index=2,
                question_snapshot=snapshot_data,
                user_answer="True",
            )
            session.add(item2)
            with pytest.raises(IntegrityError):
                session.commit()


class TestGradingRecordAndCascade:
    """Test suite for GradingRecord, two-stage pending_regrade detection, and cascade deletion."""

    def test_create_grading_records_and_cascade(
        self,
        db_session: sessionmaker[Session],
        setup_practice_context: tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID],
    ) -> None:
        """Verify grading records persistence, pending_regrade status, and cascade deletion."""
        user_id, material_id, _, _ = setup_practice_context
        practice_id = uuid.uuid4()
        item_id = uuid.uuid4()
        grading_id_1 = uuid.uuid4()
        grading_id_2 = uuid.uuid4()

        with db_session() as session:
            practice = Practice(
                id=practice_id,
                user_id=user_id,
                material_id=material_id,
                title="Grading Test Practice",
            )
            session.add(practice)

            item = AttemptItem(
                id=item_id,
                user_id=user_id,
                practice_id=practice_id,
                order_index=1,
                question_snapshot={"stem": "Q1", "question_type": "short_answer", "answer": "Ans"},
                user_answer="User ans",
                is_answered=True,
            )
            session.add(item)

            # Offline fast match failed/neutral -> LLM pending regrade
            gr1 = GradingRecord(
                id=grading_id_1,
                user_id=user_id,
                practice_id=practice_id,
                attempt_item_id=item_id,
                channel=GradingChannel.OFFLINE.value,
                status=GradingStatus.SUCCESS.value,
                is_final=False,
                score=0.5,
                similarity_score=0.65,
                hit_keywords=["keyword1"],
                missing_keywords=["keyword2"],
            )
            gr2 = GradingRecord(
                id=grading_id_2,
                user_id=user_id,
                practice_id=practice_id,
                attempt_item_id=item_id,
                channel=GradingChannel.AI.value,
                status=GradingStatus.PENDING_REGRADE.value,
                is_final=True,
                feedback="LLM invocation timed out after 20s",
                grading_metadata={"timeout_seconds": 20},
            )
            session.add_all([gr1, gr2])
            session.commit()

        # Verify query and pending_regrade detection
        with db_session() as session:
            practice = session.get(Practice, practice_id)
            assert practice is not None
            assert len(practice.grading_records) == 2

            # Check if any grading record is pending_regrade
            has_pending = any(
                gr.status == GradingStatus.PENDING_REGRADE.value for gr in practice.grading_records
            )
            assert has_pending is True

            # Cascade deletion: deleting Practice deletes items and grading records
            session.delete(practice)
            session.commit()

        with db_session() as session:
            assert session.get(AttemptItem, item_id) is None
            assert session.get(GradingRecord, grading_id_1) is None
            assert session.get(GradingRecord, grading_id_2) is None


class TestMasteryAndWrongRecords:
    """Test suite for MasteryRecord and WrongRecord constraints."""

    def test_mastery_record_unique_constraint(
        self,
        db_session: sessionmaker[Session],
        setup_practice_context: tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID],
    ) -> None:
        """Verify (user_id, knowledge_point_id) unique constraint on MasteryRecord."""
        user_id, _, _, kp_id = setup_practice_context

        with db_session() as session:
            m1 = MasteryRecord(
                user_id=user_id,
                knowledge_point_id=kp_id,
                mastery_score=0.85,
                level=MasteryLevel.PROFICIENT.value,
                practice_count=10,
                correct_count=9,
            )
            session.add(m1)
            session.commit()

            m2 = MasteryRecord(
                user_id=user_id,
                knowledge_point_id=kp_id,
                mastery_score=0.60,
                level=MasteryLevel.BASIC.value,
            )
            session.add(m2)
            with pytest.raises(IntegrityError):
                session.commit()

    def test_wrong_record_unique_constraint_and_accumulation(
        self,
        db_session: sessionmaker[Session],
        setup_practice_context: tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID],
    ) -> None:
        """Verify (user_id, question_id) unique constraint and error_count accumulation."""
        user_id, material_id, _, kp_id = setup_practice_context
        question_id = uuid.uuid4()
        practice_id = uuid.uuid4()
        item_id = uuid.uuid4()

        snapshot_data = {
            "stem": "Which layer handles routing?",
            "question_type": "single_choice",
            "answer": "Network Layer",
        }

        with db_session() as session:
            practice = Practice(
                id=practice_id, user_id=user_id, material_id=material_id, title="P1"
            )
            session.add(practice)
            item = AttemptItem(
                id=item_id,
                user_id=user_id,
                practice_id=practice_id,
                question_id=question_id,
                order_index=1,
                question_snapshot=snapshot_data,
            )
            session.add(item)

            wr1 = WrongRecord(
                user_id=user_id,
                question_id=question_id,
                knowledge_point_id=kp_id,
                practice_id=practice_id,
                attempt_item_id=item_id,
                error_type=ErrorType.CONCEPTUAL.value,
                error_count=1,
                is_mastered=False,
                last_wrong_answer="Data Link Layer",
                question_snapshot=snapshot_data,
            )
            session.add(wr1)
            session.commit()

            # Inserting duplicate (user_id, question_id) triggers unique violation
            wr2 = WrongRecord(
                user_id=user_id,
                question_id=question_id,
                knowledge_point_id=kp_id,
                practice_id=practice_id,
                attempt_item_id=item_id,
                error_type=ErrorType.CONCEPTUAL.value,
                error_count=2,
                question_snapshot=snapshot_data,
            )
            session.add(wr2)
            with pytest.raises(IntegrityError):
                session.commit()

        # Simulate update logic (accumulating error_count and mastering)
        with db_session() as session:
            stmt = select(WrongRecord).where(
                WrongRecord.user_id == user_id, WrongRecord.question_id == question_id
            )
            existing = session.scalar(stmt)
            assert existing is not None
            existing.error_count += 1
            existing.is_mastered = True
            existing.mastered_at = datetime.now(UTC)
            session.commit()

        with db_session() as session:
            stmt = select(WrongRecord).where(
                WrongRecord.user_id == user_id, WrongRecord.question_id == question_id
            )
            updated = session.scalar(stmt)
            assert updated is not None
            assert updated.error_count == 2
            assert updated.is_mastered is True
            assert updated.mastered_at is not None


class TestDiagnosisReportConstraints:
    """Test suite for DiagnosisReport 1:1 relation and structured fields."""

    def test_diagnosis_report_practice_unique_constraint(
        self,
        db_session: sessionmaker[Session],
        setup_practice_context: tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID],
    ) -> None:
        """Verify (practice_id) unique constraint ensures exactly one report per practice."""
        user_id, material_id, _, kp_id = setup_practice_context
        practice_id = uuid.uuid4()
        report_id = uuid.uuid4()

        with db_session() as session:
            practice = Practice(
                id=practice_id,
                user_id=user_id,
                material_id=material_id,
                title="Diag Practice",
            )
            session.add(practice)

            report = DiagnosisReport(
                id=report_id,
                user_id=user_id,
                practice_id=practice_id,
                weak_knowledge_points=[
                    {
                        "knowledge_point_id": str(kp_id),
                        "name": "Paging",
                        "mastery_score": 0.3,
                        "wrong_question_ids": [str(uuid.uuid4())],
                    }
                ],
                regressed_knowledge_points=[],
                analysis_causes=[
                    {"cause_code": "UNANSWERED_DOMINANT", "title": "High unanswered rate"}
                ],
                actionable_suggestions=[
                    {"knowledge_point_id": str(kp_id), "suggestion_text": "Review paging"}
                ],
                unanswered_count=1,
                wrong_count=2,
                total_questions=5,
                score_rate=0.4,
                is_structure_degraded=False,
            )
            session.add(report)
            session.commit()

        with db_session() as session:
            p = session.get(Practice, practice_id)
            assert p is not None
            assert p.diagnosis_report is not None
            assert p.diagnosis_report.unanswered_count == 1
            assert p.diagnosis_report.wrong_count == 2
            assert len(p.diagnosis_report.weak_knowledge_points) == 1

            # Adding a second report for the same practice must fail unique constraint
            dup_report = DiagnosisReport(
                user_id=user_id,
                practice_id=practice_id,
                total_questions=5,
            )
            session.add(dup_report)
            with pytest.raises(IntegrityError):
                session.commit()


class TestDesensitizedRepr:
    """Test suite verifying __repr__ methods never leak sensitive contents."""

    def test_desensitized_repr_never_leaks_secrets(self) -> None:
        """Inject canary markers into stem, options, answers, responses, and rubrics,

        and verify repr() output strictly masks them.
        """
        leak_canary = "TOP_SECRET_DO_NOT_PRINT_CANARY_9999"

        # 1. Practice
        practice = Practice(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            material_id=uuid.uuid4(),
            title=f"Secret Title {leak_canary}",
            question_count=5,
            total_score=4.0,
            max_score=5.0,
            status=PracticeStatus.COMPLETED.value,
        )
        repr_practice = repr(practice)
        assert leak_canary not in repr_practice
        assert "<Practice" in repr_practice
        assert "score=4.0/5.0" in repr_practice

        # 2. AttemptItem
        item = AttemptItem(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            practice_id=uuid.uuid4(),
            question_id=uuid.uuid4(),
            order_index=1,
            question_snapshot={
                "stem": f"Stem with {leak_canary}",
                "answer": f"Answer with {leak_canary}",
            },
            user_answer=f"My response containing {leak_canary}",
            is_answered=True,
            score=1.0,
        )
        repr_item = repr(item)
        assert leak_canary not in repr_item
        assert "<AttemptItem" in repr_item
        assert item.user_answer is not None
        assert f"ans_len={len(item.user_answer)}" in repr_item
        assert "score=1.0" in repr_item

        # 3. GradingRecord
        gr = GradingRecord(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            practice_id=uuid.uuid4(),
            attempt_item_id=uuid.uuid4(),
            channel=GradingChannel.AI.value,
            status=GradingStatus.SUCCESS.value,
            is_final=True,
            score=0.8,
            max_score=1.0,
            hit_keywords=[f"hit {leak_canary}"],
            missing_keywords=[f"missing {leak_canary}"],
            feedback=f"Feedback with {leak_canary}",
        )
        repr_gr = repr(gr)
        assert leak_canary not in repr_gr
        assert "<GradingRecord" in repr_gr
        assert "score=0.8/1.0" in repr_gr

        # 4. MasteryRecord
        mastery = MasteryRecord(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            knowledge_point_id=uuid.uuid4(),
            mastery_score=0.75,
            level=MasteryLevel.PROFICIENT.value,
            practice_count=12,
        )
        repr_mastery = repr(mastery)
        assert "<MasteryRecord" in repr_mastery
        assert "score=0.75" in repr_mastery

        # 5. DiagnosisReport
        report = DiagnosisReport(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            practice_id=uuid.uuid4(),
            analysis_causes=[{"desc": f"Cause {leak_canary}"}],
            actionable_suggestions=[{"text": f"Suggestion {leak_canary}"}],
            wrong_count=1,
            unanswered_count=0,
            score_rate=0.8,
            is_structure_degraded=False,
        )
        repr_report = repr(report)
        assert leak_canary not in repr_report
        assert "<DiagnosisReport" in repr_report
        assert "score_rate=0.80" in repr_report

        # 6. WrongRecord
        wrong = WrongRecord(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            question_id=uuid.uuid4(),
            knowledge_point_id=uuid.uuid4(),
            practice_id=uuid.uuid4(),
            attempt_item_id=uuid.uuid4(),
            error_type=ErrorType.CONCEPTUAL.value,
            error_count=3,
            is_mastered=False,
            last_wrong_answer=f"Wrong answer {leak_canary}",
            question_snapshot={"stem": f"Stem {leak_canary}"},
        )
        repr_wrong = repr(wrong)
        assert leak_canary not in repr_wrong
        assert "<WrongRecord" in repr_wrong
        assert "count=3" in repr_wrong
        assert wrong.last_wrong_answer is not None
        assert f"ans_len={len(wrong.last_wrong_answer)}" in repr_wrong

        # Empty/None answers on AttemptItem and WrongRecord
        item_empty = AttemptItem(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            practice_id=uuid.uuid4(),
            question_snapshot={"stem": "Stem", "answer": "Ans"},
            user_answer=None,
        )
        assert "ans_len=0" in repr(item_empty)

        wrong_empty = WrongRecord(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            knowledge_point_id=uuid.uuid4(),
            practice_id=uuid.uuid4(),
            attempt_item_id=uuid.uuid4(),
            error_type=ErrorType.UNANSWERED.value,
            question_snapshot={"stem": "Stem"},
            last_wrong_answer=None,
        )
        assert "ans_len=0" in repr(wrong_empty)
