"""Unit tests for PracticeService in app/services/practice.py.

Verifies:
1. 3 assembly modes: SEQUENTIAL, RANDOM, WEAK_POINTS (prioritizing unmastered
   wrong questions and weak knowledge points)
2. Question filtering by type, difficulty, and PracticeEmptyQuestionsError (40012) on shortage
3. Anti-redundancy reuse: active NOT_STARTED practice with matching source_report_id (FR-58)
4. Pure scattering and question snapshot decoupling (6 elements)
5. State machine transitions:
   NOT_STARTED -> IN_PROGRESS -> PAUSED -> IN_PROGRESS, TIMEOUT, COMPLETED
6. Autosave/save_answer with duration accumulation and is_answered updates
7. Submission scheduling:
   - Unanswered confirmation check (confirm_unanswered)
   - Distributed idempotency lock and duplicate submission replay (24h cache)
   - Queue job dispatch to 'grading_jobs'
   - Status completion and PracticeStatusError when already completed
8. Tenant cross-access isolation (Anti-horizontal privilege escalation)
"""

import uuid
from collections.abc import Generator
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import (
    IdempotencyConflictError,
    PracticeEmptyQuestionsError,
    PracticeNotFoundError,
    PracticeStatusError,
)
from app.integrations.idempotency.memory import MemoryIdempotencyAdapter
from app.integrations.queue.memory import MemoryQueueAdapter
from app.models.base import Base
from app.models.knowledge import KnowledgePoint
from app.models.material import Material, MaterialVersion
from app.models.practice import (
    AttemptItem,
    MasteryLevel,
    MasteryRecord,
    Practice,
    PracticeStatus,
    WrongRecord,
)
from app.models.question import Question, QuestionStatus, QuestionType
from app.services.practice import (
    CreatePracticeOptions,
    PracticeAssemblyMode,
    PracticeService,
    SaveAnswerDTO,
    SubmitPracticeDTO,
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
def test_setup(session: Session) -> dict[str, Any]:
    """Pre-populates material, version, knowledge points, and available questions."""
    user_id = uuid.uuid4()
    material_id = uuid.uuid4()
    version_id = uuid.uuid4()
    kp1_id = uuid.uuid4()
    kp2_id = uuid.uuid4()

    material = Material(
        id=material_id,
        user_id=user_id,
        title="操作系统导论.pdf",
        file_format="pdf",
        file_size=2048,
    )
    version = MaterialVersion(
        id=version_id,
        material_id=material_id,
        user_id=user_id,
        version_number=1,
        storage_key="raw/os.pdf",
        content_hash="hash_os",
    )
    kp1 = KnowledgePoint(
        id=kp1_id,
        material_id=material_id,
        version_id=version_id,
        user_id=user_id,
        name="进程同步与互斥",
        batch_id="batch_001",
    )
    kp2 = KnowledgePoint(
        id=kp2_id,
        material_id=material_id,
        version_id=version_id,
        user_id=user_id,
        name="虚拟内存分页机制",
        batch_id="batch_001",
    )

    questions: list[Question] = []
    # Create 4 questions for kp1
    for i in range(4):
        q = Question(
            id=uuid.uuid4(),
            material_id=material_id,
            version_id=version_id,
            knowledge_point_id=kp1_id,
            user_id=user_id,
            question_type=QuestionType.SINGLE_CHOICE.value,
            stem=f"进程同步题目_{i}：信号量初值为1代表什么？",
            options=[{"key": "A", "content": "互斥信号量"}, {"key": "B", "content": "资源信号量"}],
            answer="A",
            difficulty=3,
            status=QuestionStatus.AVAILABLE.value,
        )
        questions.append(q)

    # Create 4 questions for kp2
    for i in range(4):
        q = Question(
            id=uuid.uuid4(),
            material_id=material_id,
            version_id=version_id,
            knowledge_point_id=kp2_id,
            user_id=user_id,
            question_type=QuestionType.SINGLE_CHOICE.value,
            stem=f"分页题目_{i}：TLB的作用是什么？",
            options=[{"key": "A", "content": "快表缓存"}, {"key": "B", "content": "外存置换"}],
            answer="A",
            difficulty=3,
            status=QuestionStatus.AVAILABLE.value,
        )
        questions.append(q)

    session.add_all([material, version, kp1, kp2, *questions])
    session.commit()

    return {
        "user_id": user_id,
        "material_id": material_id,
        "version_id": version_id,
        "kp1_id": kp1_id,
        "kp2_id": kp2_id,
        "questions": questions,
    }


class TestPracticeServiceCreationAndAssembly:
    """Test suite for practice creation, question assembly modes, and scattering."""

    def test_sequential_assembly_and_scattering(
        self, session: Session, test_setup: dict[str, Any]
    ) -> None:
        """Verify sequential mode assembles questions and scatters adjacent knowledge points."""
        idempotency = MemoryIdempotencyAdapter()
        queue = MemoryQueueAdapter()
        service = PracticeService(session, idempotency=idempotency, queue=queue)

        user_id = test_setup["user_id"]
        material_id = test_setup["material_id"]
        kp1_id = test_setup["kp1_id"]
        kp2_id = test_setup["kp2_id"]

        options = CreatePracticeOptions(
            title="操作系统模拟练",
            material_id=material_id,
            knowledge_point_ids=[kp1_id, kp2_id],
            question_count=6,
            mode=PracticeAssemblyMode.SEQUENTIAL,
        )

        practice = service.create_practice(user_id, options)

        assert practice.id is not None
        assert practice.status == PracticeStatus.NOT_STARTED.value
        assert practice.question_count == 6
        assert len(practice.items) == 6

        # Check that adjacent items have different knowledge points (scattered)
        for i in range(len(practice.items) - 1):
            curr_q_id = practice.items[i].question_id
            next_q_id = practice.items[i + 1].question_id
            curr_q = session.get(Question, curr_q_id)
            next_q = session.get(Question, next_q_id)
            assert curr_q is not None and next_q is not None
            assert curr_q.knowledge_point_id != next_q.knowledge_point_id

        # Verify snapshot 6 elements are preserved in items
        snapshot = practice.items[0].question_snapshot
        assert "stem" in snapshot
        assert "question_type" in snapshot
        assert "options" in snapshot
        assert "answer" in snapshot
        assert "analysis" in snapshot
        assert "difficulty" in snapshot

    def test_random_assembly_mode(self, session: Session, test_setup: dict[str, Any]) -> None:
        """Verify random mode creates practice with requested count."""
        service = PracticeService(session)
        user_id = test_setup["user_id"]
        material_id = test_setup["material_id"]
        kp1_id = test_setup["kp1_id"]

        options = CreatePracticeOptions(
            title="随机抽样练习",
            material_id=material_id,
            knowledge_point_ids=[kp1_id],
            question_count=3,
            mode=PracticeAssemblyMode.RANDOM,
        )

        practice = service.create_practice(user_id, options)
        assert practice.question_count == 3
        assert len(practice.items) == 3

    def test_create_practice_resolves_material_from_questions(
        self, session: Session, test_setup: dict[str, Any]
    ) -> None:
        """Verify material_id=None resolves from selected question (wrong_record source)."""
        service = PracticeService(session)
        user_id = test_setup["user_id"]
        material_id = test_setup["material_id"]
        kp1_id = test_setup["kp1_id"]

        options = CreatePracticeOptions(
            title="错题巩固练习",
            material_id=None,
            knowledge_point_ids=[kp1_id],
            question_count=2,
            source_type="wrong_record",
        )
        practice = service.create_practice(user_id, options)

        assert practice.material_id == material_id
        assert practice.source_type == "wrong_record"
        assert practice.question_count == 2

    def test_weak_points_assembly_mode(self, session: Session, test_setup: dict[str, Any]) -> None:
        """Verify WEAK_POINTS mode prioritizes unmastered wrong questions
        and weak knowledge points.
        """
        service = PracticeService(session)
        user_id = test_setup["user_id"]
        material_id = test_setup["material_id"]
        kp1_id = test_setup["kp1_id"]
        kp2_id = test_setup["kp2_id"]

        target_wrong_q = test_setup["questions"][2]

        # Setup an unmastered WrongRecord for target_wrong_q
        dummy_practice = Practice(material_id=material_id, title="历史练习", user_id=user_id)
        session.add(dummy_practice)
        session.flush()
        dummy_item = AttemptItem(
            practice_id=dummy_practice.id,
            question_id=target_wrong_q.id,
            user_id=user_id,
            question_snapshot={
                "stem": target_wrong_q.stem,
                "question_type": "single_choice",
                "answer": "A",
            },
        )
        session.add(dummy_item)
        session.flush()

        wrong_rec = WrongRecord(
            user_id=user_id,
            question_id=target_wrong_q.id,
            knowledge_point_id=kp1_id,
            practice_id=dummy_practice.id,
            attempt_item_id=dummy_item.id,
            error_type="conceptual",
            is_mastered=False,
            question_snapshot={},
        )
        # Setup MasteryRecord with weak score for kp2
        mastery_rec = MasteryRecord(
            user_id=user_id,
            knowledge_point_id=kp2_id,
            mastery_score=0.25,
            level=MasteryLevel.WEAK.value,
        )
        session.add_all([wrong_rec, mastery_rec])
        session.commit()

        options = CreatePracticeOptions(
            title="薄弱点攻克练习",
            material_id=material_id,
            knowledge_point_ids=[kp1_id, kp2_id],
            question_count=4,
            mode=PracticeAssemblyMode.WEAK_POINTS,
        )

        practice = service.create_practice(user_id, options)
        assert practice.question_count == 4

        # The target wrong question must be included in the selected questions
        included_q_ids = {item.question_id for item in practice.items}
        assert target_wrong_q.id in included_q_ids

    def test_insufficient_questions_raises_error(
        self, session: Session, test_setup: dict[str, Any]
    ) -> None:
        """Verify PracticeEmptyQuestionsError (40012) is raised
        when available questions are insufficient.
        """
        service = PracticeService(session)
        user_id = test_setup["user_id"]
        material_id = test_setup["material_id"]
        kp1_id = test_setup["kp1_id"]

        options = CreatePracticeOptions(
            title="超额出题测试",
            material_id=material_id,
            knowledge_point_ids=[kp1_id],
            question_count=20,  # only 4 available
        )

        with pytest.raises(PracticeEmptyQuestionsError) as exc_info:
            service.create_practice(user_id, options)

        assert exc_info.value.error_code == 40012
        assert exc_info.value.status_code == 400
        assert exc_info.value.details["required"] == 20

    def test_reuse_existing_not_started_practice(
        self, session: Session, test_setup: dict[str, Any]
    ) -> None:
        """Verify FR-58: Reuses existing NOT_STARTED practice if same source_report_id is passed."""
        service = PracticeService(session)
        user_id = test_setup["user_id"]
        material_id = test_setup["material_id"]
        kp1_id = test_setup["kp1_id"]
        report_id = uuid.uuid4()

        options = CreatePracticeOptions(
            title="诊断后一键再练",
            material_id=material_id,
            knowledge_point_ids=[kp1_id],
            question_count=2,
            source_report_id=report_id,
        )

        p1 = service.create_practice(user_id, options)
        p2 = service.create_practice(user_id, options)

        # Must return the identical instance without creating a duplicate
        assert p1.id == p2.id


class TestPracticeServiceStateMachine:
    """Test suite for practice state machine transitions and answer saving."""

    def test_save_answer_auto_transitions_status(
        self, session: Session, test_setup: dict[str, Any]
    ) -> None:
        """Verify saving first answer transitions status from NOT_STARTED to IN_PROGRESS."""
        service = PracticeService(session)
        user_id = test_setup["user_id"]
        material_id = test_setup["material_id"]
        kp1_id = test_setup["kp1_id"]

        practice = service.create_practice(
            user_id,
            CreatePracticeOptions(
                title="作答状态跃迁测试",
                material_id=material_id,
                knowledge_point_ids=[kp1_id],
                question_count=2,
            ),
        )
        assert practice.status == PracticeStatus.NOT_STARTED.value

        q_id = practice.items[0].question_id
        assert q_id is not None
        dto = SaveAnswerDTO(
            practice_id=practice.id,
            question_id=q_id,
            user_answer="A",
            duration_seconds=12,
        )

        updated_item = service.save_answer(user_id, dto)
        assert updated_item.user_answer == "A"
        assert updated_item.is_answered is True
        assert updated_item.duration_seconds == 12

        refreshed_practice = service.get_practice(user_id, practice.id)
        assert refreshed_practice.status == PracticeStatus.IN_PROGRESS.value

    def test_pause_resume_timeout_transitions(
        self, session: Session, test_setup: dict[str, Any]
    ) -> None:
        """Verify IN_PROGRESS <-> PAUSED and TIMEOUT state machine transitions."""
        service = PracticeService(session)
        user_id = test_setup["user_id"]
        material_id = test_setup["material_id"]
        kp1_id = test_setup["kp1_id"]

        practice = service.create_practice(
            user_id,
            CreatePracticeOptions(
                title="暂停与恢复测试",
                material_id=material_id,
                knowledge_point_ids=[kp1_id],
                question_count=2,
            ),
        )

        # Cannot pause NOT_STARTED
        with pytest.raises(PracticeStatusError):
            service.pause_practice(user_id, practice.id)

        # Answer to transition to IN_PROGRESS
        q_item_id = practice.items[0].question_id
        assert q_item_id is not None
        service.save_answer(
            user_id,
            SaveAnswerDTO(practice_id=practice.id, question_id=q_item_id, user_answer="A"),
        )

        # Pause IN_PROGRESS -> paused
        paused_p = service.pause_practice(user_id, practice.id)
        assert paused_p.status == "paused"

        # Resume paused -> IN_PROGRESS
        resumed_p = service.resume_practice(user_id, practice.id)
        assert resumed_p.status == PracticeStatus.IN_PROGRESS.value

        # Timeout practice
        timeout_p = service.timeout_practice(user_id, practice.id)
        assert timeout_p.status == "timeout"

        # Resume when not paused raises PracticeStatusError
        with pytest.raises(PracticeStatusError):
            service.resume_practice(user_id, practice.id)

        # Non-existent practice errors
        fake_id = uuid.uuid4()
        with pytest.raises(PracticeNotFoundError):
            service.pause_practice(user_id, fake_id)
        with pytest.raises(PracticeNotFoundError):
            service.resume_practice(user_id, fake_id)
        with pytest.raises(PracticeNotFoundError):
            service.timeout_practice(user_id, fake_id)

    def test_save_answer_completed_and_listing(
        self, session: Session, test_setup: dict[str, Any]
    ) -> None:
        """Verify save_answer on completed practice and list_practices."""
        service = PracticeService(session)
        user_id = test_setup["user_id"]
        material_id = test_setup["material_id"]
        kp1_id = test_setup["kp1_id"]

        practice = service.create_practice(
            user_id,
            CreatePracticeOptions(
                title="已完成作答拦截测试",
                material_id=material_id,
                knowledge_point_ids=[kp1_id],
                question_count=1,
            ),
        )

        # List practices
        p_list = service.list_practices(user_id, material_id=material_id)
        assert len(p_list) >= 1

        # Submit to complete
        q0 = practice.items[0].question_id
        assert q0 is not None
        service.save_answer(
            user_id,
            SaveAnswerDTO(practice_id=practice.id, question_id=q0, user_answer="A"),
        )
        service.submit_practice(
            user_id,
            SubmitPracticeDTO(practice_id=practice.id, idempotency_key=str(uuid.uuid4())),
        )

        # Saving answer to completed practice raises PracticeStatusError
        with pytest.raises(PracticeStatusError):
            service.save_answer(
                user_id,
                SaveAnswerDTO(practice_id=practice.id, question_id=q0, user_answer="B"),
            )

        # Timeout completed practice raises PracticeStatusError
        with pytest.raises(PracticeStatusError):
            service.timeout_practice(user_id, practice.id)


class TestPracticeServiceSubmissionAndIdempotency:
    """Test suite for practice submission, idempotency lock, deduplication, and queue dispatch."""

    def test_submission_unanswered_check(
        self, session: Session, test_setup: dict[str, Any]
    ) -> None:
        """Verify submitting with unanswered questions requires confirm_unanswered=True."""
        idempotency = MemoryIdempotencyAdapter()
        queue = MemoryQueueAdapter()
        service = PracticeService(session, idempotency=idempotency, queue=queue)

        user_id = test_setup["user_id"]
        material_id = test_setup["material_id"]
        kp1_id = test_setup["kp1_id"]

        practice = service.create_practice(
            user_id,
            CreatePracticeOptions(
                title="交卷未答测试",
                material_id=material_id,
                knowledge_point_ids=[kp1_id],
                question_count=2,
            ),
        )

        # Answer only 1 question
        q1_id = practice.items[0].question_id
        assert q1_id is not None
        service.save_answer(
            user_id,
            SaveAnswerDTO(practice_id=practice.id, question_id=q1_id, user_answer="A"),
        )

        # Submit without confirmation -> PracticeStatusError
        with pytest.raises(PracticeStatusError) as exc_info:
            service.submit_practice(
                user_id,
                SubmitPracticeDTO(
                    practice_id=practice.id,
                    idempotency_key=str(uuid.uuid4()),
                    confirm_unanswered=False,
                ),
            )
        assert exc_info.value.error_code == 40011
        assert exc_info.value.details["unanswered_count"] == 1

        # Submit with confirm_unanswered=True -> succeeds
        submit_key = str(uuid.uuid4())
        result = service.submit_practice(
            user_id,
            SubmitPracticeDTO(
                practice_id=practice.id,
                idempotency_key=submit_key,
                confirm_unanswered=True,
            ),
        )
        assert result.practice_id == practice.id
        assert result.status == PracticeStatus.COMPLETED.value
        assert result.total_questions == 2
        assert result.unanswered_count == 1
        assert result.answered_questions == 1
        assert result.task_id != ""

        # Verify task is enqueued to "grading_jobs"
        assert len(queue._queue) == 1
        assert queue._queue[0].task_name == "grading_jobs"
        assert queue._queue[0].payload["practice_id"] == str(practice.id)

    def test_submission_idempotency_and_replay(
        self, session: Session, test_setup: dict[str, Any]
    ) -> None:
        """Verify idempotent submission replay from cached result within 24h."""
        idempotency = MemoryIdempotencyAdapter()
        queue = MemoryQueueAdapter()
        service = PracticeService(session, idempotency=idempotency, queue=queue)

        user_id = test_setup["user_id"]
        material_id = test_setup["material_id"]
        kp1_id = test_setup["kp1_id"]

        practice = service.create_practice(
            user_id,
            CreatePracticeOptions(
                title="幂等交卷测试",
                material_id=material_id,
                knowledge_point_ids=[kp1_id],
                question_count=2,
            ),
        )
        for item in practice.items:
            assert item.question_id is not None
            service.save_answer(
                user_id,
                SaveAnswerDTO(
                    practice_id=practice.id, question_id=item.question_id, user_answer="A"
                ),
            )

        submit_key = str(uuid.uuid4())
        dto = SubmitPracticeDTO(practice_id=practice.id, idempotency_key=submit_key)

        res1 = service.submit_practice(user_id, dto)
        res2 = service.submit_practice(user_id, dto)

        # Second submission must replay the exact same result
        assert res1.task_id == res2.task_id
        assert res1.submitted_at == res2.submitted_at
        # Queue should only contain 1 dispatched job
        assert len(queue._queue) == 1

        # Trying to submit with a different key when practice is already COMPLETED
        # raises PracticeStatusError
        new_key = str(uuid.uuid4())
        with pytest.raises(PracticeStatusError) as exc_info:
            service.submit_practice(
                user_id,
                SubmitPracticeDTO(practice_id=practice.id, idempotency_key=new_key),
            )
        assert exc_info.value.error_code == 40011

    def test_submission_concurrent_conflict(
        self, session: Session, test_setup: dict[str, Any]
    ) -> None:
        """Verify concurrent submission with same idempotency key
        raises IdempotencyConflictError.
        """
        idempotency = MemoryIdempotencyAdapter()
        service = PracticeService(session, idempotency=idempotency)

        user_id = test_setup["user_id"]
        material_id = test_setup["material_id"]
        kp1_id = test_setup["kp1_id"]

        practice = service.create_practice(
            user_id,
            CreatePracticeOptions(
                title="并发冲突测试",
                material_id=material_id,
                knowledge_point_ids=[kp1_id],
                question_count=1,
            ),
        )

        submit_key = str(uuid.uuid4())
        # Simulate lock already held by another thread
        idempotency.acquire_lock(submit_key, str(user_id), ttl_seconds=60)

        with pytest.raises(IdempotencyConflictError):
            service.submit_practice(
                user_id,
                SubmitPracticeDTO(practice_id=practice.id, idempotency_key=submit_key),
            )


class TestPracticeServiceTenantIsolation:
    """Test suite for tenant cross-access isolation in PracticeService."""

    def test_user_b_cannot_access_user_a_practice(
        self, session: Session, test_setup: dict[str, Any]
    ) -> None:
        """Verify User B cannot view, save answer to, or submit User A's practice."""
        service = PracticeService(session)
        user_a = test_setup["user_id"]
        user_b = uuid.uuid4()
        material_id = test_setup["material_id"]
        kp1_id = test_setup["kp1_id"]

        practice = service.create_practice(
            user_a,
            CreatePracticeOptions(
                title="User A 专属练习",
                material_id=material_id,
                knowledge_point_ids=[kp1_id],
                question_count=2,
            ),
        )

        # User B gets PracticeNotFoundError
        with pytest.raises(PracticeNotFoundError):
            service.get_practice(user_b, practice.id)

        # User B save answer -> PracticeNotFoundError
        item_q_id = practice.items[0].question_id
        assert item_q_id is not None
        with pytest.raises(PracticeNotFoundError):
            service.save_answer(
                user_b,
                SaveAnswerDTO(
                    practice_id=practice.id,
                    question_id=item_q_id,
                    user_answer="偷答",
                ),
            )

        # User B submit -> PracticeNotFoundError
        with pytest.raises(PracticeNotFoundError):
            service.submit_practice(
                user_b,
                SubmitPracticeDTO(
                    practice_id=practice.id,
                    idempotency_key=str(uuid.uuid4()),
                ),
            )
