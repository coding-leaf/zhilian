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

import json
import uuid
from collections.abc import Generator
from typing import Any

import pytest
from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import (
    IdempotencyConflictError,
    PracticeEmptyQuestionsError,
    PracticeNotFoundError,
    PracticeStatusError,
    QueueError,
)
from app.integrations.idempotency.memory import MemoryIdempotencyAdapter
from app.integrations.queue.memory import MemoryQueueAdapter
from app.models.base import Base
from app.models.knowledge import KnowledgePoint
from app.models.material import Material, MaterialSnippet, MaterialVersion
from app.models.practice import (
    AttemptItem,
    MasteryLevel,
    MasteryRecord,
    Practice,
    PracticeStatus,
    WrongRecord,
)
from app.models.question import Question, QuestionStatus, QuestionType
from app.schemas.material import SourceSnippetDTO
from app.schemas.practice import PracticeDetailResponse
from app.services.grading import GradingService
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

    def test_create_practice_persists_mode_and_detail_completed_count(
        self, session: Session, test_setup: dict[str, Any]
    ) -> None:
        """Verify mode persistence and detail completed_count tracking (BUG-PRAC-011)."""
        service = PracticeService(session)
        user_id = test_setup["user_id"]
        material_id = test_setup["material_id"]
        kp1_id = test_setup["kp1_id"]

        practice = service.create_practice(
            user_id,
            CreatePracticeOptions(
                title="随机模式落库测试",
                material_id=material_id,
                knowledge_point_ids=[kp1_id],
                question_count=2,
                mode=PracticeAssemblyMode.RANDOM,
            ),
        )
        assert practice.mode == "random"

        detail = PracticeDetailResponse.model_validate(practice)
        assert detail.mode == "random"
        assert detail.completed_count == 0

        q0 = practice.items[0].question_id
        assert q0 is not None
        service.save_answer(
            user_id,
            SaveAnswerDTO(practice_id=practice.id, question_id=q0, user_answer="A"),
        )
        refreshed = service.get_practice(user_id, practice.id)
        detail_after = PracticeDetailResponse.model_validate(refreshed)
        assert detail_after.completed_count == 1

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

    def test_create_practice_idempotency_key_replays(
        self, session: Session, test_setup: dict[str, Any]
    ) -> None:
        """BUG-DIAG-018: 相同幂等键重复创建须回放既有练习而非重复建卷。"""
        idempotency = MemoryIdempotencyAdapter()
        service = PracticeService(session, idempotency=idempotency)
        user_id = test_setup["user_id"]
        material_id = test_setup["material_id"]
        kp1_id = test_setup["kp1_id"]

        options = CreatePracticeOptions(
            title="幂等建卷",
            material_id=material_id,
            knowledge_point_ids=[kp1_id],
            question_count=2,
            idempotency_key="create-idem-key-1",
        )

        p1 = service.create_practice(user_id, options)
        p2 = service.create_practice(user_id, options)

        assert p1.id == p2.id
        assert len(p2.items) == 2

    def test_create_practice_idempotency_key_blocks_concurrent_duplicate(
        self, session: Session, test_setup: dict[str, Any]
    ) -> None:
        """BUG-DIAG-018: 同键并发抢占中的请求须抛 IdempotencyConflictError (409)。"""
        idempotency = MemoryIdempotencyAdapter()
        service = PracticeService(session, idempotency=idempotency)
        user_id = test_setup["user_id"]
        material_id = test_setup["material_id"]
        kp1_id = test_setup["kp1_id"]

        options = CreatePracticeOptions(
            title="并发幂等建卷",
            material_id=material_id,
            knowledge_point_ids=[kp1_id],
            question_count=2,
            idempotency_key="create-concurrent-key-1",
        )

        # 模拟首请求正持有处理中锁
        idempotency.acquire_lock("create-concurrent-key-1", str(user_id))

        with pytest.raises(IdempotencyConflictError):
            service.create_practice(user_id, options)

    def test_create_practice_snapshot_write_degrades_without_failure(
        self, session: Session, test_setup: dict[str, Any]
    ) -> None:
        """BUG-DIAG-018: 快照写入失败不得让已提交练习返回 5xx，且须释放处理中锁。"""
        idempotency = MemoryIdempotencyAdapter()
        service = PracticeService(session, idempotency=idempotency)
        user_id = test_setup["user_id"]
        material_id = test_setup["material_id"]
        kp1_id = test_setup["kp1_id"]

        options = CreatePracticeOptions(
            title="快照降级建卷",
            material_id=material_id,
            knowledge_point_ids=[kp1_id],
            question_count=1,
            idempotency_key="create-degraded-key-1",
        )

        idempotency.set_fault_injection("set_result", RuntimeError("redis snapshot write failed"))

        # 快照写入降级，但主流程仍返回成功的练习实体。
        practice = service.create_practice(user_id, options)
        assert practice is not None
        assert practice.id is not None

        # 处理中锁已被释放：同键重试不再撞并发冲突，可重新进入。
        idempotency.set_fault_injection("set_result", None)
        retried = service.create_practice(user_id, options)
        assert retried is not None
        assert retried.id is not None


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

    def test_save_answer_rejects_non_answerable_states(
        self, session: Session, test_setup: dict[str, Any]
    ) -> None:
        """Verify real service blocks saving on PAUSED/TIMEOUT/PARTIALLY_GRADED (BUG-PRAC-007)."""
        service = PracticeService(session)
        user_id = test_setup["user_id"]
        material_id = test_setup["material_id"]
        kp1_id = test_setup["kp1_id"]

        practice = service.create_practice(
            user_id,
            CreatePracticeOptions(
                title="非作答态拦截测试",
                material_id=material_id,
                knowledge_point_ids=[kp1_id],
                question_count=1,
            ),
        )
        q0 = practice.items[0].question_id
        assert q0 is not None
        service.save_answer(
            user_id,
            SaveAnswerDTO(practice_id=practice.id, question_id=q0, user_answer="A"),
        )

        # PAUSED rejects further answers
        service.pause_practice(user_id, practice.id)
        with pytest.raises(PracticeStatusError):
            service.save_answer(
                user_id,
                SaveAnswerDTO(practice_id=practice.id, question_id=q0, user_answer="B"),
            )

        # TIMEOUT rejects further answers
        service.resume_practice(user_id, practice.id)
        service.timeout_practice(user_id, practice.id)
        with pytest.raises(PracticeStatusError):
            service.save_answer(
                user_id,
                SaveAnswerDTO(practice_id=practice.id, question_id=q0, user_answer="C"),
            )

        # PARTIALLY_GRADED rejects further answers
        paused_model = session.get(Practice, practice.id)
        assert paused_model is not None
        paused_model.status = PracticeStatus.PARTIALLY_GRADED.value
        session.commit()
        with pytest.raises(PracticeStatusError):
            service.save_answer(
                user_id,
                SaveAnswerDTO(practice_id=practice.id, question_id=q0, user_answer="D"),
            )

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
        assert result.status == PracticeStatus.SUBMITTED.value
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
        # First submission is not a replay; cached replay is flagged (BUG-PRAC-005)
        assert res1.is_idempotent_replay is False
        assert res2.is_idempotent_replay is True
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

    def test_submission_survives_snapshot_write_failure_and_replays(
        self, session: Session, test_setup: dict[str, Any]
    ) -> None:
        """Verify PRAC-013: set_result failure must not 5xx and same-key retry replays."""
        idempotency = MemoryIdempotencyAdapter()
        queue = MemoryQueueAdapter()
        service = PracticeService(session, idempotency=idempotency, queue=queue)

        user_id = test_setup["user_id"]
        material_id = test_setup["material_id"]
        kp1_id = test_setup["kp1_id"]

        practice = service.create_practice(
            user_id,
            CreatePracticeOptions(
                title="快照写入降级测试",
                material_id=material_id,
                knowledge_point_ids=[kp1_id],
                question_count=1,
            ),
        )
        q0 = practice.items[0].question_id
        assert q0 is not None
        service.save_answer(
            user_id,
            SaveAnswerDTO(practice_id=practice.id, question_id=q0, user_answer="A"),
        )

        submit_key = str(uuid.uuid4())
        # Inject a Redis/snapshot write outage for the first submission.
        idempotency.set_fault_injection("set_result", RuntimeError("redis snapshot write failed"))

        result = service.submit_practice(
            user_id,
            SubmitPracticeDTO(practice_id=practice.id, idempotency_key=submit_key),
        )
        # Snapshot write degraded, but the primary flow still returns the acceptance state.
        assert result.status == PracticeStatus.SUBMITTED.value
        assert result.is_idempotent_replay is False
        assert result.practice_id == practice.id
        assert len(queue._queue) == 1

        # The transaction already persisted the idempotency key on the practice row.
        persisted = session.get(Practice, practice.id)
        assert persisted is not None
        assert persisted.status == PracticeStatus.SUBMITTED.value
        assert persisted.submit_idempotency_key == submit_key

        # Same-key retry must replay (not raise 40011), because the snapshot was lost.
        replay = service.submit_practice(
            user_id,
            SubmitPracticeDTO(practice_id=practice.id, idempotency_key=submit_key),
        )
        assert replay.practice_id == practice.id
        assert replay.status == PracticeStatus.SUBMITTED.value
        assert replay.is_idempotent_replay is True
        assert replay.total_questions == 1
        assert len(queue._queue) == 1

        # A different key is still rejected (40011), preserving the guard.
        with pytest.raises(PracticeStatusError) as exc_info:
            service.submit_practice(
                user_id,
                SubmitPracticeDTO(practice_id=practice.id, idempotency_key=str(uuid.uuid4())),
            )
        assert exc_info.value.error_code == 40011

    def test_save_answer_serializes_multiselect_as_json(
        self, session: Session, test_setup: dict[str, Any]
    ) -> None:
        """Verify PRAC-016: list answers are persisted as canonical JSON, not Python repr."""
        service = PracticeService(session)
        user_id = test_setup["user_id"]
        material_id = test_setup["material_id"]
        kp1_id = test_setup["kp1_id"]

        practice = service.create_practice(
            user_id,
            CreatePracticeOptions(
                title="多选序列化测试",
                material_id=material_id,
                knowledge_point_ids=[kp1_id],
                question_count=1,
            ),
        )
        q0 = practice.items[0].question_id
        assert q0 is not None

        item = service.save_answer(
            user_id,
            practice_id=practice.id,
            question_id=q0,
            user_answer=["B", "A", "C"],
            time_spent_seconds=5,
        )

        assert isinstance(item.user_answer, str)
        # Canonical JSON: json.loads parses it; Python repr would raise.
        assert json.loads(item.user_answer) == ["A", "B", "C"]
        assert item.user_answer == '["A", "B", "C"]'

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

    def test_get_practice_attaches_source_snippet(
        self, session: Session, test_setup: dict[str, Any]
    ) -> None:
        """验证练习详情按 source_snippet_id 关联装配原文切片对象 (BUG-GRADE-004)."""
        user_id = test_setup["user_id"]
        material_id = test_setup["material_id"]
        version_id = test_setup["version_id"]
        kp1_id = test_setup["kp1_id"]

        snippet_id = uuid.uuid4()
        session.add(
            MaterialSnippet(
                id=snippet_id,
                material_id=material_id,
                version_id=version_id,
                user_id=user_id,
                snippet_index=0,
                content="二叉树中序遍历先左子树后根节点再右子树。",
                char_length=20,
                start_offset=0,
                end_offset=20,
                chapter_title="第 3 章 树与二叉树",
                source_info={"page_number": 42},
            )
        )
        session.flush()

        service = PracticeService(session)
        practice = service.create_practice(
            user_id,
            CreatePracticeOptions(
                title="原文溯源装配测试",
                material_id=material_id,
                knowledge_point_ids=[kp1_id],
                question_count=1,
            ),
        )

        orm_item = practice.items[0]
        snapshot = dict(orm_item.question_snapshot)
        snapshot["source_snippet_id"] = str(snippet_id)
        orm_item.question_snapshot = snapshot
        session.flush()

        detail = service.get_practice(user_id, practice.id)
        assert len(detail.items) == 1
        item = detail.items[0]
        assert item.source_snippet is not None
        snippet = item.source_snippet
        assert isinstance(snippet, SourceSnippetDTO)
        assert snippet.snippet_content == "二叉树中序遍历先左子树后根节点再右子树。"
        assert snippet.chapter_title == "第 3 章 树与二叉树"
        assert snippet.page_index == 42

    def test_get_practice_without_snippet_keeps_none(
        self, session: Session, test_setup: dict[str, Any]
    ) -> None:
        """验证无 source_snippet_id 时来源切片保持 None (向后兼容)."""
        user_id = test_setup["user_id"]
        material_id = test_setup["material_id"]
        kp1_id = test_setup["kp1_id"]

        service = PracticeService(session)
        practice = service.create_practice(
            user_id,
            CreatePracticeOptions(
                title="无切片装配测试",
                material_id=material_id,
                knowledge_point_ids=[kp1_id],
                question_count=1,
            ),
        )

        detail = service.get_practice(user_id, practice.id)
        assert detail.items[0].source_snippet is None

    def test_create_practice_with_question_ids(
        self, session: Session, test_setup: dict[str, Any]
    ) -> None:
        """验证使用指定 question_ids 直接组卷能力 (错题本针对性重练)."""
        user_id = test_setup["user_id"]
        material_id = test_setup["material_id"]
        questions = test_setup["questions"]

        service = PracticeService(session)
        target_ids = [questions[0].id, questions[2].id]

        practice = service.create_practice(
            user_id,
            CreatePracticeOptions(
                title="错题定向重练组卷",
                material_id=material_id,
                knowledge_point_ids=[],
                question_count=2,
                question_ids=target_ids,
            ),
        )

        assert practice.question_count == 2
        assert len(practice.items) == 2
        item_qids = {item.question_id for item in practice.items}
        assert item_qids == set(target_ids)

        # 验证指定不存在题目时抛出 PracticeEmptyQuestionsError
        with pytest.raises(PracticeEmptyQuestionsError):
            service.create_practice(
                user_id,
                CreatePracticeOptions(
                    title="非法题目组卷",
                    material_id=material_id,
                    knowledge_point_ids=[],
                    question_count=1,
                    question_ids=[uuid.uuid4()],
                ),
            )

    def test_create_practice_response_items_carry_source_snippet(
        self, session: Session, test_setup: dict[str, Any]
    ) -> None:
        """验证创建练习的响应与详情响应一致地包含原文溯源对象 (R5 原文依据)."""
        user_id = test_setup["user_id"]
        material_id = test_setup["material_id"]
        version_id = test_setup["version_id"]
        kp1_id = test_setup["kp1_id"]

        snippet_id = uuid.uuid4()
        session.add(
            MaterialSnippet(
                id=snippet_id,
                material_id=material_id,
                version_id=version_id,
                user_id=user_id,
                snippet_index=0,
                content="慢启动阶段拥塞窗口指数增长，直到达到慢启动阈值。",
                char_length=24,
                start_offset=0,
                end_offset=24,
                chapter_title="第 3 章 拥塞控制",
                source_info={"page_number": 88},
            )
        )
        sourced_question = Question(
            id=uuid.uuid4(),
            material_id=material_id,
            version_id=version_id,
            knowledge_point_id=kp1_id,
            user_id=user_id,
            question_type=QuestionType.SINGLE_CHOICE.value,
            stem="慢启动阶段拥塞窗口如何变化？",
            options=[{"key": "A", "content": "指数增长"}, {"key": "B", "content": "线性增长"}],
            answer="A",
            difficulty=3,
            status=QuestionStatus.AVAILABLE.value,
            source_snippet_id=snippet_id,
        )
        session.add(sourced_question)
        session.commit()

        service = PracticeService(session)
        practice = service.create_practice(
            user_id,
            CreatePracticeOptions(
                title="创建响应原文溯源测试",
                material_id=material_id,
                knowledge_point_ids=[kp1_id],
                question_count=1,
                question_ids=[sourced_question.id],
            ),
        )

        # 路由层对创建返回值直接 model_validate，因此创建响应必须已挂载追溯对象
        detail = PracticeDetailResponse.model_validate(practice)
        assert len(detail.items) == 1
        item = detail.items[0]
        assert item.source_snippet is not None
        assert isinstance(item.source_snippet, SourceSnippetDTO)
        assert (
            item.source_snippet.snippet_content
            == "慢启动阶段拥塞窗口指数增长，直到达到慢启动阈值。"
        )
        assert item.source_snippet.chapter_title == "第 3 章 拥塞控制"
        assert item.source_snippet.page_index == 88
        # 快照副本同样带上溯源对象，供前端原文回顾抽屉读取
        snapshot = item.question_snapshot
        snapshot_snippet = (
            snapshot.get("source_snippet")
            if isinstance(snapshot, dict)
            else snapshot.source_snippet
        )
        assert isinstance(snapshot_snippet, SourceSnippetDTO)
        assert snapshot_snippet.snippet_content == item.source_snippet.snippet_content


class TestPracticeServiceGradingRecovery:
    """判题任务终态失败回写与主动重试 (AC-9 / design.md 第 19 条)."""

    @staticmethod
    def _create_and_submit(service: PracticeService, setup: dict[str, Any]) -> Practice:
        """创建一个全部作答并已交卷的练习，返回 ORM 实体。"""
        practice = service.create_practice(
            setup["user_id"],
            CreatePracticeOptions(
                title="判题恢复测试",
                material_id=setup["material_id"],
                knowledge_point_ids=[setup["kp1_id"]],
                question_count=2,
            ),
        )
        for item in practice.items:
            assert item.question_id is not None
            service.save_answer(
                setup["user_id"],
                SaveAnswerDTO(
                    practice_id=practice.id,
                    question_id=item.question_id,
                    user_answer="A",
                ),
            )
        service.submit_practice(
            setup["user_id"],
            SubmitPracticeDTO(practice_id=practice.id, idempotency_key=str(uuid.uuid4())),
        )
        return practice

    def test_mark_grading_failed_writes_recoverable_partially_graded_state(
        self, session: Session, test_setup: dict[str, Any]
    ) -> None:
        """worker 抛错重试耗尽后，练习必须回写为可恢复的 partially_graded 且不放行报告."""
        queue = MemoryQueueAdapter()
        service = PracticeService(session, idempotency=MemoryIdempotencyAdapter(), queue=queue)
        practice = self._create_and_submit(service, test_setup)
        assert practice.status == PracticeStatus.SUBMITTED.value

        recovered = service.mark_grading_failed(
            test_setup["user_id"], practice.id, reason="rq_job_failed"
        )

        assert recovered is not None
        assert recovered.status == PracticeStatus.PARTIALLY_GRADED.value
        # completed_at 必须保持为空：DiagnosisService 以 (completed, completed_at) 双条件
        # 门禁阻断早产报告，因此回写不会绕过诊断门禁。
        assert recovered.completed_at is None

    def test_mark_grading_failed_is_idempotent_and_never_downgrades_terminal(
        self, session: Session, test_setup: dict[str, Any]
    ) -> None:
        """重复回调不得重复计分或回退，且绝不覆盖已完成的终态."""
        service = PracticeService(session, idempotency=MemoryIdempotencyAdapter())
        practice = self._create_and_submit(service, test_setup)
        user_id = test_setup["user_id"]

        first = service.mark_grading_failed(user_id, practice.id)
        second = service.mark_grading_failed(user_id, practice.id)
        assert first is not None and second is not None
        assert first.status == PracticeStatus.PARTIALLY_GRADED.value
        assert second.status == PracticeStatus.PARTIALLY_GRADED.value

        # 已完成的练习不得被失败回调降级
        practice.status = PracticeStatus.COMPLETED.value
        session.commit()
        kept = service.mark_grading_failed(user_id, practice.id)
        assert kept is not None
        assert kept.status == PracticeStatus.COMPLETED.value

    def test_mark_grading_failed_skips_unsubmitted_and_missing_practice(
        self, session: Session, test_setup: dict[str, Any]
    ) -> None:
        """未交卷练习不受影响；练习不存在时返回 None 且不抛异常."""
        service = PracticeService(session, idempotency=MemoryIdempotencyAdapter())
        user_id = test_setup["user_id"]
        practice = service.create_practice(
            user_id,
            CreatePracticeOptions(
                title="未交卷练习",
                material_id=test_setup["material_id"],
                knowledge_point_ids=[test_setup["kp1_id"]],
                question_count=1,
            ),
        )

        untouched = service.mark_grading_failed(user_id, practice.id)
        assert untouched is not None
        assert untouched.status == PracticeStatus.NOT_STARTED.value
        assert service.mark_grading_failed(user_id, uuid.uuid4()) is None

    def test_retry_grading_redispatches_and_second_trigger_is_rejected(
        self, session: Session, test_setup: dict[str, Any]
    ) -> None:
        """重试成功派发一次判题任务；重复触发被状态锁拒绝，不会重复派发."""
        queue = MemoryQueueAdapter()
        service = PracticeService(session, idempotency=MemoryIdempotencyAdapter(), queue=queue)
        practice = self._create_and_submit(service, test_setup)
        user_id = test_setup["user_id"]
        service.mark_grading_failed(user_id, practice.id)
        assert len(queue._queue) == 1  # 仅交卷派发的那一次

        task_id, retried = service.retry_grading(user_id, practice.id)

        assert task_id != ""
        assert retried.status == PracticeStatus.SUBMITTED.value
        assert len(queue._queue) == 2
        # 重试任务以高优先级入队，按优先级排序后位于队首
        assert queue._queue[0].task_name == "grading_jobs"
        assert queue._queue[0].payload["practice_id"] == str(practice.id)

        # 状态已回到 submitted，第二次触发必须被拒绝（并发锁语义）
        with pytest.raises(PracticeStatusError) as exc_info:
            service.retry_grading(user_id, practice.id)
        assert exc_info.value.error_code == 40011
        assert len(queue._queue) == 2

    def test_retry_grading_rejects_completed_and_unauthorized(
        self, session: Session, test_setup: dict[str, Any]
    ) -> None:
        """已全判完或非 partially_graded 状态不得重试；跨租户一律 404."""
        queue = MemoryQueueAdapter()
        service = PracticeService(session, idempotency=MemoryIdempotencyAdapter(), queue=queue)
        practice = self._create_and_submit(service, test_setup)
        user_id = test_setup["user_id"]

        with pytest.raises(PracticeStatusError):
            service.retry_grading(user_id, practice.id)

        practice.status = PracticeStatus.COMPLETED.value
        session.commit()
        with pytest.raises(PracticeStatusError):
            service.retry_grading(user_id, practice.id)

        practice.status = PracticeStatus.PARTIALLY_GRADED.value
        session.commit()
        with pytest.raises(PracticeNotFoundError):
            service.retry_grading(uuid.uuid4(), practice.id)

    def test_retry_grading_rolls_back_status_when_dispatch_fails(
        self, session: Session, test_setup: dict[str, Any]
    ) -> None:
        """入队失败必须回滚为可恢复状态，避免练习永久停在「判题中」.

        BUG-FIX: retry_grading 的异常捕获从 `except Exception` 收紧到
        `except (QueueError, SQLAlchemyError)`，测试同步改为注入 QueueError
        以模拟真实队列异常路径。
        """

        queue = MemoryQueueAdapter()
        service = PracticeService(session, idempotency=MemoryIdempotencyAdapter(), queue=queue)
        practice = self._create_and_submit(service, test_setup)
        user_id = test_setup["user_id"]
        service.mark_grading_failed(user_id, practice.id)

        # 注入生产中真实抛出的异常类型（QueueError），而非任意 RuntimeError
        queue.set_fault_injection("enqueue", QueueError("redis down"))
        with pytest.raises(PracticeStatusError) as exc_info:
            service.retry_grading(user_id, practice.id)
        # BUG-FIX: 入队失败必须抛包装后的 PracticeStatusError 带 reason
        assert exc_info.value.error_code == 40011
        assert "redis down" in exc_info.value.details.get("reason", "")

        queue.set_fault_injection("enqueue", None)
        restored = service.practice_repo.get_practice_by_id(practice.id, user_id)
        assert restored is not None
        assert restored.status == PracticeStatus.PARTIALLY_GRADED.value
        # 仍可再次主动重试，恢复入口没有被堵死
        _, retried = service.retry_grading(user_id, practice.id)
        assert retried.status == PracticeStatus.SUBMITTED.value

    def test_regrading_after_failure_completes_and_only_then_stamps_completed_at(
        self, session: Session, test_setup: dict[str, Any]
    ) -> None:
        """重试后真正跑完判题才写 completed_at；失败回写期间始终保持未完成."""
        queue = MemoryQueueAdapter()
        service = PracticeService(session, idempotency=MemoryIdempotencyAdapter(), queue=queue)
        practice = self._create_and_submit(service, test_setup)
        user_id = test_setup["user_id"]

        service.mark_grading_failed(user_id, practice.id)
        failed_state = service.practice_repo.get_practice_by_id(practice.id, user_id)
        assert failed_state is not None
        assert failed_state.completed_at is None
        assert failed_state.total_score is None

        service.retry_grading(user_id, practice.id)

        grading_service = GradingService(session)
        summary = grading_service.grade_practice(user_id=user_id, practice_id=practice.id)

        assert summary.status == PracticeStatus.COMPLETED.value
        completed = service.practice_repo.get_practice_by_id(practice.id, user_id)
        assert completed is not None
        assert completed.status == PracticeStatus.COMPLETED.value
        assert completed.completed_at is not None
        assert summary.graded_items == summary.total_items

    def test_regrading_is_idempotent_and_does_not_double_count(
        self, session: Session, test_setup: dict[str, Any]
    ) -> None:
        """判题任务被重复投递时不得重复计分或产生重复生效记录 (AC-9 幂等)."""
        queue = MemoryQueueAdapter()
        service = PracticeService(session, idempotency=MemoryIdempotencyAdapter(), queue=queue)
        practice = self._create_and_submit(service, test_setup)
        user_id = test_setup["user_id"]

        grading_service = GradingService(session)
        first = grading_service.grade_practice(user_id=user_id, practice_id=practice.id)
        second = grading_service.grade_practice(user_id=user_id, practice_id=practice.id)

        assert first.total_score == second.total_score
        assert second.graded_items == second.total_items
        completed = service.practice_repo.get_practice_by_id(practice.id, user_id)
        assert completed is not None
        assert completed.status == PracticeStatus.COMPLETED.value
        assert completed.completed_at is not None
        # 每个作答项只有一条生效判题记录，重复投递不产生重复计分
        records = grading_service.grading_repo.list_final_records_by_practice(practice.id, user_id)
        assert len(records) == len(practice.items)

    def test_retry_grading_rejects_stale_read_when_row_already_transitioned(
        self, session: Session, test_setup: dict[str, Any]
    ) -> None:
        """并发请求不得凭陈旧读重复派发判题任务 (状态跃迁由数据库条件更新判定).

        模拟真实竞态：本会话先加载出 ``partially_graded`` 的实体，另一请求随后把该行
        推进到 ``submitted``。若状态跃迁是「先读后写」，本请求会凭陈旧状态再次入队，
        同一批待判项就会被判两遍并产生重复生效记录；条件更新 (compare-and-swap) 则
        因未能改到该行而拒绝本次请求。
        """
        queue = MemoryQueueAdapter()
        service = PracticeService(session, idempotency=MemoryIdempotencyAdapter(), queue=queue)
        practice = self._create_and_submit(service, test_setup)
        user_id = test_setup["user_id"]

        service.mark_grading_failed(user_id, practice.id)
        # 先加载实体，让本会话持有 partially_graded 的快照（此后 SELECT 不会覆盖它）
        stale = service.practice_repo.get_practice_by_id(practice.id, user_id)
        assert stale is not None
        assert stale.status == PracticeStatus.PARTIALLY_GRADED.value
        queued_before = len(queue._queue)

        # 另一请求已把该行推进到 submitted（synchronize_session=False 使本会话的
        # 身份映射保持陈旧，从而忠实模拟并发写入后的陈旧读）
        session.execute(
            update(Practice)
            .where(Practice.id == practice.id)
            .values(status=PracticeStatus.SUBMITTED.value)
            .execution_options(synchronize_session=False)
        )

        with pytest.raises(PracticeStatusError) as exc_info:
            service.retry_grading(user_id, practice.id)
        assert exc_info.value.error_code == 40011
        # 未重复派发：队列长度与竞态发生前一致
        assert len(queue._queue) == queued_before
