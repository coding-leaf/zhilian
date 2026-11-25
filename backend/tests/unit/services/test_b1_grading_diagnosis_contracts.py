"""B1 contract tests: Commit-First grading, regressed KPs, diagnosis refresh & short-tx."""

import logging
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import PracticeStatusError, QueueError
from app.core.security import generate_user_ref
from app.integrations.idempotency.memory import MemoryIdempotencyAdapter
from app.integrations.llm.protocol import LLMMessage, LLMOptions, LLMResponse, LLMUsage
from app.integrations.queue.memory import MemoryQueueAdapter
from app.models.base import Base
from app.models.knowledge import KnowledgePoint
from app.models.material import Material, MaterialStatus, MaterialVersion
from app.models.practice import (
    AttemptItem,
    DiagnosisReport,
    Practice,
    PracticeStatus,
)
from app.models.question import Question, QuestionStatus, QuestionType
from app.models.user import User
from app.repositories.diagnosis import DiagnosisRepository
from app.services._diagnosis_report import build_evaluation_inputs_and_mistakes
from app.services.diagnosis import DiagnosisService
from app.services.grading import GradingService, RegradeAttemptDTO, SelfEvaluateDTO
from app.services.practice import (
    CreatePracticeOptions,
    PracticeService,
    SaveAnswerDTO,
    SubmitPracticeDTO,
)


@pytest.fixture
def engine_and_factory() -> Iterator[tuple[Any, sessionmaker[Session]]]:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    try:
        yield engine, factory
    finally:
        engine.dispose()


def _seed_user_kp_questions(
    session: Session,
) -> dict[str, Any]:
    user = User(id=uuid.uuid4(), openid=f"wx_{uuid.uuid4().hex[:8]}", nickname="student")
    session.add(user)
    material = Material(
        id=uuid.uuid4(),
        user_id=user.id,
        title="计算机网络",
        file_format="pdf",
        file_size=512,
        status=MaterialStatus.READY.value,
    )
    session.add(material)
    version = MaterialVersion(
        id=uuid.uuid4(),
        user_id=user.id,
        material_id=material.id,
        version_number=1,
        storage_key="raw/net.pdf",
        content_hash=uuid.uuid4().hex,
        parse_status="completed",
    )
    session.add(version)
    kp = KnowledgePoint(
        id=uuid.uuid4(),
        user_id=user.id,
        material_id=material.id,
        version_id=version.id,
        name="TCP 三次握手",
        description="SYN/SYN-ACK/ACK 建连过程",
        level=1,
        batch_id="kp-batch-net",
    )
    session.add(kp)
    q_obj = Question(
        id=uuid.uuid4(),
        user_id=user.id,
        material_id=material.id,
        version_id=version.id,
        knowledge_point_id=kp.id,
        question_type=QuestionType.SINGLE_CHOICE.value,
        status=QuestionStatus.AVAILABLE.value,
        stem="TCP 建立连接需要几次握手？",
        options=[{"key": "A", "content": "三次"}, {"key": "B", "content": "两次"}],
        answer="A",
        analysis="TCP 建连需要三次握手。",
        difficulty=2,
    )
    q_sub = Question(
        id=uuid.uuid4(),
        user_id=user.id,
        material_id=material.id,
        version_id=version.id,
        knowledge_point_id=kp.id,
        question_type=QuestionType.SHORT_ANSWER.value,
        status=QuestionStatus.AVAILABLE.value,
        stem="简述 TCP 三次握手的关键报文交互过程。",
        options=[],
        answer="客户端发 SYN，服务端回 SYN-ACK，客户端确认 ACK。",
        analysis="包含 SYN、SYN-ACK、ACK 三个阶段。",
        difficulty=3,
        grading_rubric={},
    )
    session.add_all([q_obj, q_sub])
    session.commit()
    return {
        "user_id": user.id,
        "material_id": material.id,
        "kp_id": kp.id,
        "q_obj_id": q_obj.id,
        "q_sub_id": q_sub.id,
    }


class _TxInspectingQueue(MemoryQueueAdapter):
    """Queue spy verifying DB state is committed before enqueue() is invoked."""

    def __init__(self, session_factory: sessionmaker[Session], *, fail: bool = False) -> None:
        super().__init__()
        self._session_factory = session_factory
        self._fail = fail
        self.observed_statuses: list[str | None] = []

    def enqueue(
        self,
        task_name: str,
        payload: dict[str, Any],
        user_id: str | None = None,
        priority: int = 0,
        task_id: str | None = None,
    ) -> str:
        practice_id = uuid.UUID(payload["practice_id"])
        with self._session_factory() as reader:
            persisted = reader.get(Practice, practice_id)
            self.observed_statuses.append(persisted.status if persisted is not None else None)
        if self._fail:
            raise QueueError("simulated redis outage")
        return super().enqueue(
            task_name=task_name,
            payload=payload,
            user_id=user_id,
            priority=priority,
            task_id=task_id,
        )


class _InspectingGradingLLM:
    """Stub LLM capturing prompt text and verifying DB session is NOT in transaction during call."""

    def __init__(self, *, session: Session, score: float = 5.0) -> None:
        self.session = session
        self.score = score
        self.captured_prompts: list[str] = []
        self.observed_in_tx: list[bool] = []

    def generate(
        self, messages: list[LLMMessage], options: LLMOptions | None = None
    ) -> LLMResponse:
        raise NotImplementedError

    def generate_structured(
        self,
        messages: list[LLMMessage],
        response_model: type[BaseModel],
        options: LLMOptions | None = None,
    ) -> tuple[Any, LLMResponse]:
        self.observed_in_tx.append(self.session.in_transaction())
        self.captured_prompts.append("\n".join(m.content for m in messages))
        parsed = response_model.model_validate(
            {
                "score": self.score,
                "confidence": 0.95,
                "feedback": "核查后要点完整",
                "hit_keywords": ["SYN", "ACK"],
                "missing_keywords": [],
                "evaluations": [],
            }
        )
        return parsed, LLMResponse(
            content="{}",
            model="stub-grader",
            usage=LLMUsage(),
            duration_ms=12.0,
        )


def test_submit_practice_commit_first_and_enqueue_failure_compensation(
    engine_and_factory: tuple[Any, sessionmaker[Session]],
) -> None:
    """submit_practice commits SUBMITTED before queue.enqueue and compensates on enqueue failure."""
    _, factory = engine_and_factory
    with factory() as session:
        env = _seed_user_kp_questions(session)

        # Case 1: Normal subjective submit -> reader sees SUBMITTED during enqueue()
        queue_ok = _TxInspectingQueue(factory, fail=False)
        svc_ok = PracticeService(session=session, queue=queue_ok)
        p1 = svc_ok.create_practice(
            env["user_id"],
            CreatePracticeOptions(
                title="主观题CommitFirst测试",
                material_id=env["material_id"],
                knowledge_point_ids=[env["kp_id"]],
                question_ids=[env["q_sub_id"]],
                question_count=1,
            ),
        )
        svc_ok.save_answer(
            env["user_id"],
            SaveAnswerDTO(
                practice_id=p1.id, question_id=env["q_sub_id"], user_answer="SYN->SYN-ACK->ACK"
            ),
        )
        res = svc_ok.submit_practice(
            env["user_id"],
            SubmitPracticeDTO(practice_id=p1.id, idempotency_key=f"sub-{uuid.uuid4().hex}"),
        )
        assert res.status == PracticeStatus.SUBMITTED.value
        assert queue_ok.observed_statuses == [PracticeStatus.SUBMITTED.value]

        # Case 2: Enqueue fails -> compensating short tx persists PARTIALLY_GRADED
        queue_fail = _TxInspectingQueue(factory, fail=True)
        svc_fail = PracticeService(session=session, queue=queue_fail)
        p2 = svc_fail.create_practice(
            env["user_id"],
            CreatePracticeOptions(
                title="入队失败补偿测试",
                material_id=env["material_id"],
                knowledge_point_ids=[env["kp_id"]],
                question_ids=[env["q_sub_id"]],
                question_count=1,
            ),
        )
        svc_fail.save_answer(
            env["user_id"],
            SaveAnswerDTO(practice_id=p2.id, question_id=env["q_sub_id"], user_answer="三次握手"),
        )
        with pytest.raises(QueueError):
            svc_fail.submit_practice(
                env["user_id"],
                SubmitPracticeDTO(practice_id=p2.id, idempotency_key=f"fail-{uuid.uuid4().hex}"),
            )
        assert queue_fail.observed_statuses == [PracticeStatus.SUBMITTED.value]
        with factory() as verifier:
            persisted_p2 = verifier.get(Practice, p2.id)
            assert persisted_p2 is not None
            assert persisted_p2.status == PracticeStatus.PARTIALLY_GRADED.value

        # Case 3: retry_grading commits SUBMITTED before enqueue; on failure compensates back
        retry_queue = _TxInspectingQueue(factory, fail=True)
        svc_retry = PracticeService(session=session, queue=retry_queue)
        with pytest.raises(PracticeStatusError):
            svc_retry.retry_grading(env["user_id"], p2.id)
        assert retry_queue.observed_statuses == [PracticeStatus.SUBMITTED.value]
        with factory() as verifier:
            persisted_after = verifier.get(Practice, p2.id)
            assert persisted_after is not None
            assert persisted_after.status == PracticeStatus.PARTIALLY_GRADED.value


def test_submit_practice_logs_redacted_user_ref_and_releases_lock_quietly(
    engine_and_factory: tuple[Any, sessionmaker[Session]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """submit_practice redacts user_id in warning log and shields primary error on lock release."""
    _, factory = engine_and_factory
    with factory() as session:
        env = _seed_user_kp_questions(session)
        idem = MagicMock(spec=MemoryIdempotencyAdapter)
        idem.get_result.return_value = None
        idem.set_result.side_effect = RuntimeError("redis snapshot timeout")
        idem.release_lock.side_effect = RuntimeError("redis unlock failed")

        svc = PracticeService(session=session, idempotency=idem)
        p = svc.create_practice(
            env["user_id"],
            CreatePracticeOptions(
                title="脱敏日志测试",
                material_id=env["material_id"],
                knowledge_point_ids=[env["kp_id"]],
                question_ids=[env["q_obj_id"]],
                question_count=1,
            ),
        )
        svc.save_answer(
            env["user_id"],
            SaveAnswerDTO(practice_id=p.id, question_id=env["q_obj_id"], user_answer="A"),
        )
        with caplog.at_level(logging.WARNING):
            res = svc.submit_practice(
                env["user_id"],
                SubmitPracticeDTO(practice_id=p.id, idempotency_key=f"log-{uuid.uuid4().hex}"),
            )
        assert res.status == PracticeStatus.COMPLETED.value
        expected_ref = generate_user_ref(env["user_id"])
        assert expected_ref in caplog.text
        assert str(env["user_id"]) not in caplog.text

        # Error path: release_lock failure must NOT swallow PracticeStatusError
        with pytest.raises(PracticeStatusError):
            svc.submit_practice(
                env["user_id"],
                SubmitPracticeDTO(practice_id=p.id, idempotency_key=f"dup-{uuid.uuid4().hex}"),
            )


def test_pure_objective_submit_single_pass_detects_regressed_knowledge_points(
    engine_and_factory: tuple[Any, sessionmaker[Session]],
) -> None:
    """Pure objective submit avoids double mastery write so regressed KPs are populated."""
    _, factory = engine_and_factory
    with factory() as session:
        env = _seed_user_kp_questions(session)
        svc = PracticeService(session=session)
        diag_repo = DiagnosisRepository(session)

        # Practice 1: answer correctly -> establishes high baseline mastery (1.0)
        p1 = svc.create_practice(
            env["user_id"],
            CreatePracticeOptions(
                title="基线练习",
                material_id=env["material_id"],
                knowledge_point_ids=[env["kp_id"]],
                question_ids=[env["q_obj_id"]],
                question_count=1,
            ),
        )
        svc.save_answer(
            env["user_id"],
            SaveAnswerDTO(practice_id=p1.id, question_id=env["q_obj_id"], user_answer="A"),
        )
        svc.submit_practice(
            env["user_id"],
            SubmitPracticeDTO(practice_id=p1.id, idempotency_key=f"p1-{uuid.uuid4().hex}"),
        )

        # Practice 2: answer wrongly -> mastery drops from 1.0 to 0.5 -> regression!
        p2 = svc.create_practice(
            env["user_id"],
            CreatePracticeOptions(
                title="退步检测练习",
                material_id=env["material_id"],
                knowledge_point_ids=[env["kp_id"]],
                question_ids=[env["q_obj_id"]],
                question_count=1,
            ),
        )
        svc.save_answer(
            env["user_id"],
            SaveAnswerDTO(practice_id=p2.id, question_id=env["q_obj_id"], user_answer="B"),
        )

        with patch.object(
            DiagnosisService,
            "sync_practice_learning_state",
            wraps=DiagnosisService.sync_practice_learning_state,
        ) as sync_spy:
            res2 = svc.submit_practice(
                env["user_id"],
                SubmitPracticeDTO(practice_id=p2.id, idempotency_key=f"p2-{uuid.uuid4().hex}"),
            )
            assert res2.status == PracticeStatus.COMPLETED.value
            # Single-pass contract: no sync_practice_learning_state on COMPLETED path
            sync_spy.assert_not_called()

        report2 = diag_repo.get_diagnosis_report_by_practice_id(p2.id, env["user_id"])
        assert report2 is not None
        assert len(report2.regressed_knowledge_points) == 1
        regressed = report2.regressed_knowledge_points[0]
        assert regressed["knowledge_id"] == str(env["kp_id"])
        assert regressed["previous_score"] > regressed["current_score"]
        assert regressed["score_delta"] < 0


def test_self_eval_and_regrade_refresh_diagnosis_report_and_pass_reason_short_tx(
    engine_and_factory: tuple[Any, sessionmaker[Session]],
) -> None:
    """Self-eval & regrade refresh DiagnosisReport in place, pass reason, and use short-tx."""
    _, factory = engine_and_factory
    with factory() as session:
        env = _seed_user_kp_questions(session)
        practice_svc = PracticeService(session=session)
        p = practice_svc.create_practice(
            env["user_id"],
            CreatePracticeOptions(
                title="主观题诊断刷新测试",
                material_id=env["material_id"],
                knowledge_point_ids=[env["kp_id"]],
                question_ids=[env["q_sub_id"]],
                question_count=1,
            ),
        )
        practice_svc.save_answer(
            env["user_id"],
            SaveAnswerDTO(
                practice_id=p.id,
                question_id=env["q_sub_id"],
                user_answer="客户端先发 SYN 报文请求建立连接，之后双方继续确认",
            ),
        )
        practice_svc.submit_practice(
            env["user_id"],
            SubmitPracticeDTO(practice_id=p.id, idempotency_key=f"sub-{uuid.uuid4().hex}"),
        )

        # 1. Initial Worker grading gives 0.0/5.0 -> COMPLETED + DiagnosisReport(wrong=1, rate=0)
        low_llm = _InspectingGradingLLM(session=session, score=0.0)
        grading_svc = GradingService(session=session, llm_adapter=low_llm)
        summary = grading_svc.grade_practice(user_id=env["user_id"], practice_id=p.id)
        assert summary.status == PracticeStatus.COMPLETED.value
        assert low_llm.observed_in_tx == [False]

        diag_repo = DiagnosisRepository(session)
        initial_report = diag_repo.get_diagnosis_report_by_practice_id(p.id, env["user_id"])
        assert initial_report is not None
        initial_report_id = initial_report.id
        assert initial_report.wrong_count == 1
        assert initial_report.score_rate == 0.0

        # 2. User self-evaluates to full score 5.0 -> DiagnosisReport updates IN PLACE!
        item = session.query(AttemptItem).filter_by(practice_id=p.id).one()
        item.max_score = 5.0
        session.commit()
        grading_svc.self_evaluate_attempt(
            user_id=env["user_id"],
            dto=SelfEvaluateDTO(
                attempt_item_id=item.id,
                score=5.0,
                is_correct=True,
                feedback="核对答案要点全对",
            ),
        )
        refreshed_after_self = diag_repo.get_diagnosis_report_by_practice_id(p.id, env["user_id"])
        assert refreshed_after_self is not None
        assert refreshed_after_self.id == initial_report_id
        assert refreshed_after_self.wrong_count == 0
        assert refreshed_after_self.score_rate == 1.0

        # 3. AI regrade with appeal reason -> score drops to 2.5 -> DiagnosisReport refreshes!
        regrade_llm = _InspectingGradingLLM(session=session, score=2.5)
        grading_svc.llm_adapter = regrade_llm
        appeal_reason = "我在第二句提到了 SYN-ACK 报文，请重新核分"
        regrade_record = grading_svc.regrade_attempt(
            user_id=env["user_id"],
            dto=RegradeAttemptDTO(attempt_item_id=item.id, reason=appeal_reason),
        )
        # Short-tx verified during regrade LLM call
        assert regrade_llm.observed_in_tx == [False]
        # Prompt-injection fenced reason reached LLM & persisted in metadata
        assert "<user_appeal_reason>" in regrade_llm.captured_prompts[0]
        assert appeal_reason in regrade_llm.captured_prompts[0]
        assert regrade_record.grading_metadata["regrade_reason"] == appeal_reason

        refreshed_after_regrade = diag_repo.get_diagnosis_report_by_practice_id(
            p.id, env["user_id"]
        )
        assert refreshed_after_regrade is not None
        assert refreshed_after_regrade.id == initial_report_id
        assert refreshed_after_regrade.wrong_count == 1
        assert refreshed_after_regrade.score_rate == 0.5
        # Only 1 DiagnosisReport row exists for this practice
        assert session.query(DiagnosisReport).filter_by(practice_id=p.id).count() == 1


def test_diagnosis_report_subjective_types_and_batch_kp_lookup() -> None:
    """fill_in_blank/term_explanation/case_analysis map to subjective and use list_by_ids."""
    user_id = uuid.uuid4()
    kp1 = uuid.uuid4()
    kp2 = uuid.uuid4()
    kp3 = uuid.uuid4()
    kp_entities = [
        KnowledgePoint(
            id=kp_id,
            user_id=user_id,
            material_id=uuid.uuid4(),
            version_id=uuid.uuid4(),
            name=f"KP-{idx}",
        )
        for idx, kp_id in enumerate((kp1, kp2, kp3), start=1)
    ]
    knowledge_repo = MagicMock()
    knowledge_repo.list_by_ids.return_value = kp_entities

    def _eval(kp_id: uuid.UUID, q_type: str) -> dict[str, Any]:
        item = AttemptItem(
            id=uuid.uuid4(),
            practice_id=uuid.uuid4(),
            user_id=user_id,
            order_index=1,
            question_snapshot={
                "question_type": q_type,
                "stem": "测试题干",
                "answer": "参考答案",
                "knowledge_point_id": str(kp_id),
            },
            user_answer="错误回答",
            is_answered=True,
            score=0.0,
            max_score=5.0,
        )
        return {
            "item": item,
            "grading": None,
            "score": 0.0,
            "max_score": 5.0,
            "is_answered": True,
            "is_correct": False,
            "point_id": kp_id,
        }

    evals = [
        _eval(kp1, QuestionType.FILL_IN_BLANK.value),
        _eval(kp2, QuestionType.TERM_EXPLANATION.value),
        _eval(kp3, QuestionType.CASE_ANALYSIS.value),
    ]
    now = datetime.now(UTC) - timedelta(seconds=1)
    inputs, _, _, _ = build_evaluation_inputs_and_mistakes(
        knowledge_repo=knowledge_repo,
        user_id=user_id,
        sorted_point_ids=sorted([kp1, kp2, kp3]),
        previous_record_map={},
        current_record_map={},
        item_evaluations=evals,
        evaluation_time=now,
    )

    knowledge_repo.list_by_ids.assert_called_once()
    knowledge_repo.get_by_id.assert_not_called()
    assert len(inputs) == 3
    for inp in inputs:
        assert inp.has_subjective_mistake is True
        assert inp.has_objective_mistake is False
