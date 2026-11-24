"""Unit tests for async question generation jobs: auto-practice, idempotency, short-tx & retries."""

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import LLMAuthError, LLMTimeoutError, MissingSourceSnippetError
from app.integrations.embedding.fake import FakeEmbeddingAdapter
from app.integrations.llm.protocol import LLMMessage, LLMOptions, LLMResponse, LLMUsage
from app.integrations.queue.memory import MemoryQueueAdapter
from app.models.base import Base
from app.models.knowledge import KnowledgePoint, KnowledgePointSnippet
from app.models.material import Material, MaterialSnippet, MaterialStatus, MaterialVersion
from app.models.practice import Practice, PracticeSourceType
from app.models.question import QuestionGenerationJobStatus
from app.models.user import User
from app.schemas.question import QuestionGenerateRequest, QuestionGenerationJobCreateRequest
from app.services._question_llm_schemas import LLMGeneratedQuestionItem, LLMQuestionBatchOutput
from app.services.question import QuestionService


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    db = factory()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _seed_material_with_kp(session: Session) -> dict[str, uuid.UUID]:
    user = User(id=uuid.uuid4(), openid=f"wx_{uuid.uuid4().hex[:8]}", nickname="tester")
    session.add(user)
    material = Material(
        id=uuid.uuid4(),
        user_id=user.id,
        title="操作系统核心讲义",
        file_format="pdf",
        file_size=1024,
        status=MaterialStatus.READY.value,
    )
    session.add(material)
    version = MaterialVersion(
        id=uuid.uuid4(),
        user_id=user.id,
        material_id=material.id,
        version_number=1,
        storage_key="raw/os.pdf",
        content_hash=uuid.uuid4().hex,
        parse_status="completed",
    )
    session.add(version)
    material.current_version_id = version.id

    snippet_text = (
        "死锁的四个必要条件为互斥条件、请求与保持条件、不可剥夺条件和循环等待条件。"
        "时间片轮转调度算法保证每个就绪进程在有限时间内获得 CPU 执行机会，"
        "优先权调度可能引发饥饿问题并可通过老化技术缓解。"
    )
    embedder = FakeEmbeddingAdapter()
    vec = embedder.embed_documents([snippet_text])[0]

    kp = KnowledgePoint(
        id=uuid.uuid4(),
        user_id=user.id,
        material_id=material.id,
        version_id=version.id,
        name="进程调度与死锁",
        description="死锁的四个必要条件与时间片轮转调度算法",
        level=1,
        batch_id="kp-batch-1",
    )
    session.add(kp)
    snippet = MaterialSnippet(
        id=uuid.uuid4(),
        user_id=user.id,
        material_id=material.id,
        version_id=version.id,
        snippet_index=0,
        chapter_title="第2章 进程管理",
        content=snippet_text,
        char_length=len(snippet_text),
        start_offset=0,
        end_offset=len(snippet_text),
        embedding=vec,
        source_info={"page": 12, "similarity": 0.92},
    )
    session.add(snippet)
    session.add(
        KnowledgePointSnippet(
            user_id=user.id,
            knowledge_point_id=kp.id,
            snippet_id=snippet.id,
        )
    )
    session.commit()
    return {
        "user_id": user.id,
        "material_id": material.id,
        "version_id": version.id,
        "kp_id": kp.id,
    }


class _CountingValidQuestionLLM:
    """Stub LLM producing N distinct valid single-choice questions and asserting tx state."""

    def __init__(
        self,
        *,
        session: Session | None = None,
        count_per_call: int = 12,
        produce_invalid: bool = False,
        raise_exc: Exception | None = None,
    ) -> None:
        self.session = session
        self.count_per_call = count_per_call
        self.produce_invalid = produce_invalid
        self.raise_exc = raise_exc
        self.observed_in_tx: list[bool] = []
        self._seq = 0

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
        if self.session is not None:
            self.observed_in_tx.append(self.session.in_transaction())
        if self.raise_exc is not None:
            raise self.raise_exc

        items: list[LLMGeneratedQuestionItem] = []
        for idx in range(self.count_per_call):
            self._seq += 1
            if self.produce_invalid:
                items.append(
                    LLMGeneratedQuestionItem(
                        question_type="single_choice",
                        stem=f"死锁条件题目 #{self._seq}",
                        options=["重复选项", "重复选项"],
                        answer="Z",
                        explanation="",
                        source_snippet_index=0,
                    )
                )
            else:
                items.append(
                    LLMGeneratedQuestionItem(
                        question_type="single_choice",
                        stem=(
                            f"关于死锁四个必要条件与时间片轮转调度的独立考点判断 #{self._seq}"
                            f"（场景 {idx}，互斥/请求保持/不可剥夺/循环等待），以下哪项准确？"
                        ),
                        options=[
                            f"死锁需满足互斥、请求保持、不可剥夺和循环等待（场景{self._seq}）",
                            f"时间片轮转会导致死锁必然发生（场景{self._seq}）",
                            f"老化技术会加重进程饥饿问题（场景{self._seq}）",
                            f"循环等待不是死锁必要条件（场景{self._seq}）",
                        ],
                        answer="A",
                        explanation="依据第2章讲义，死锁四个必要条件为互斥、请求与保持、不可剥夺和循环等待。",
                        source_snippet_index=0,
                    )
                )
        batch = LLMQuestionBatchOutput(questions=items)
        parsed = response_model.model_validate(batch.model_dump())
        return parsed, LLMResponse(
            content="{}",
            model="stub-llm",
            usage=LLMUsage(),
        )


def test_create_generation_job_deduplicates_by_idempotency_key_and_active_scope(
    session: Session,
) -> None:
    """Both explicit Idempotency-Key and active-scope double-clicks reuse existing job."""
    env = _seed_material_with_kp(session)
    queue = MemoryQueueAdapter()
    service = QuestionService(
        session=session,
        llm=_CountingValidQuestionLLM(),
        embedding=FakeEmbeddingAdapter(),
        queue=queue,
    )
    source_practice_id = uuid.uuid4()
    payload = QuestionGenerationJobCreateRequest(
        material_id=env["material_id"],
        version_id=env["version_id"],
        knowledge_point_ids=[env["kp_id"]],
        question_types=["single_choice"],
        count=12,
        difficulty=3,
        auto_create_practice=True,
        practice_title="错题巩固练习",
        source_type="wrong_record",
        source_practice_id=source_practice_id,
    )

    job1 = service.create_generation_job(
        user_id=env["user_id"],
        payload=payload,
        idempotency_key="wrong-regen-key-001",
    )
    assert job1.source_type == "wrong_record"
    assert job1.source_practice_id == source_practice_id
    assert job1.idempotency_key == "wrong-regen-key-001"
    assert job1.practice_title == "错题巩固练习"
    assert len(queue._queue) == 1

    # Same Idempotency-Key returns same job without enqueueing again
    job2 = service.create_generation_job(
        user_id=env["user_id"],
        payload=payload,
        idempotency_key="wrong-regen-key-001",
    )
    assert job2.id == job1.id
    assert len(queue._queue) == 1

    # Double-click without Idempotency-Key for same active scope reuses active job
    job3 = service.create_generation_job(
        user_id=env["user_id"],
        payload=payload,
    )
    assert job3.id == job1.id
    assert len(queue._queue) == 1


def test_run_generation_job_auto_creates_practice_with_all_available_and_short_tx(
    session: Session,
) -> None:
    """auto_create_practice=True creates Practice with >10 items and releases DB tx before LLM."""
    env = _seed_material_with_kp(session)
    llm = _CountingValidQuestionLLM(session=session, count_per_call=12)
    service = QuestionService(
        session=session,
        llm=llm,
        embedding=FakeEmbeddingAdapter(),
        queue=MemoryQueueAdapter(),
    )
    payload = QuestionGenerationJobCreateRequest(
        material_id=env["material_id"],
        version_id=env["version_id"],
        knowledge_point_ids=[env["kp_id"]],
        question_types=["single_choice"],
        count=12,
        difficulty=3,
        max_retries=0,
        auto_create_practice=True,
        practice_title="死锁错题强化卷",
        source_type="wrong_record",
        source_practice_id=uuid.uuid4(),
    )
    job = service.create_generation_job(user_id=env["user_id"], payload=payload)
    completed = service.run_generation_job(job_id=job.id, user_id=env["user_id"])

    # Short-tx contract: DB session was NOT inside an open transaction during LLM call
    assert llm.observed_in_tx
    assert all(in_tx is False for in_tx in llm.observed_in_tx)

    assert completed.status == QuestionGenerationJobStatus.COMPLETED.value
    assert completed.result_practice_id is not None
    assert completed.error_message is None

    practice = session.get(Practice, completed.result_practice_id)
    assert practice is not None
    assert practice.title == "死锁错题强化卷"
    assert practice.source_type == PracticeSourceType.WRONG_RECORD.value
    # Pin api-payload-contracts.md: must NOT silently truncate 12 available questions to 10!
    assert practice.question_count == 12
    assert len(practice.items) == 12


def test_run_generation_job_zero_available_leaves_result_practice_none(session: Session) -> None:
    """When all generated questions fail quality gate, result_practice_id stays None with notice."""
    env = _seed_material_with_kp(session)
    llm = _CountingValidQuestionLLM(count_per_call=2, produce_invalid=True)
    service = QuestionService(
        session=session,
        llm=llm,
        embedding=FakeEmbeddingAdapter(),
        queue=MemoryQueueAdapter(),
    )
    payload = QuestionGenerationJobCreateRequest(
        material_id=env["material_id"],
        version_id=env["version_id"],
        knowledge_point_ids=[env["kp_id"]],
        question_types=["single_choice"],
        count=2,
        difficulty=3,
        max_retries=0,
        auto_create_practice=True,
        source_type="initial_compose",
    )
    job = service.create_generation_job(user_id=env["user_id"], payload=payload)
    completed = service.run_generation_job(job_id=job.id, user_id=env["user_id"])

    assert completed.status == QuestionGenerationJobStatus.COMPLETED.value
    assert completed.result_practice_id is None
    assert completed.error_message is not None
    assert "暂无可用题目" in completed.error_message


def test_run_generation_job_retryable_vs_non_retryable_errors(session: Session) -> None:
    """Retryable infra errors do NOT prematurely write FAILED; business/auth errors mark FAILED."""
    env = _seed_material_with_kp(session)

    # 1. Retryable LLMTimeoutError -> status remains running (not FAILED) for RQ retry
    retryable_service = QuestionService(
        session=session,
        llm=_CountingValidQuestionLLM(raise_exc=LLMTimeoutError("upstream timeout")),
        embedding=FakeEmbeddingAdapter(),
        queue=MemoryQueueAdapter(),
    )
    payload = QuestionGenerateRequest(
        material_id=env["material_id"],
        version_id=env["version_id"],
        knowledge_point_ids=[env["kp_id"]],
        question_types=["single_choice"],
        count=2,
        difficulty=3,
        max_retries=0,
    )
    job_retry = retryable_service.create_generation_job(user_id=env["user_id"], payload=payload)
    with pytest.raises(LLMTimeoutError):
        retryable_service.run_generation_job(job_id=job_retry.id, user_id=env["user_id"])
    refreshed_retry = retryable_service.get_generation_job(
        user_id=env["user_id"], job_id=job_retry.id
    )
    assert refreshed_retry.status == QuestionGenerationJobStatus.RUNNING.value

    # 2. Non-retryable LLMAuthError -> immediately marked FAILED
    non_retryable_service = QuestionService(
        session=session,
        llm=_CountingValidQuestionLLM(raise_exc=LLMAuthError("invalid key")),
        embedding=FakeEmbeddingAdapter(),
        queue=MemoryQueueAdapter(),
    )
    job_fail = non_retryable_service.create_generation_job(
        user_id=env["user_id"],
        payload=payload,
        idempotency_key="auth-fail-job",
    )
    with pytest.raises(LLMAuthError):
        non_retryable_service.run_generation_job(job_id=job_fail.id, user_id=env["user_id"])
    refreshed_fail = non_retryable_service.get_generation_job(
        user_id=env["user_id"], job_id=job_fail.id
    )
    assert refreshed_fail.status == QuestionGenerationJobStatus.FAILED.value
    assert refreshed_fail.completed_at is not None

    # 3. Non-retryable MissingSourceSnippetError -> immediately marked FAILED
    kp_no_snippet = KnowledgePoint(
        id=uuid.uuid4(),
        user_id=env["user_id"],
        material_id=env["material_id"],
        version_id=env["version_id"],
        name="无切片考点",
        description="完全无关的主题",
        level=1,
        batch_id="kp-batch-2",
    )
    session.add(kp_no_snippet)
    session.commit()
    service_biz = QuestionService(
        session=session,
        llm=_CountingValidQuestionLLM(raise_exc=MissingSourceSnippetError("missing snippet")),
        embedding=FakeEmbeddingAdapter(),
        queue=MemoryQueueAdapter(),
    )
    job_biz = service_biz.create_generation_job(
        user_id=env["user_id"],
        payload=QuestionGenerateRequest(
            material_id=env["material_id"],
            version_id=env["version_id"],
            knowledge_point_ids=[kp_no_snippet.id],
            question_types=["single_choice"],
            count=2,
            difficulty=3,
        ),
    )
    with pytest.raises(MissingSourceSnippetError):
        service_biz.run_generation_job(job_id=job_biz.id, user_id=env["user_id"])
    refreshed_biz = service_biz.get_generation_job(user_id=env["user_id"], job_id=job_biz.id)
    assert refreshed_biz.status == QuestionGenerationJobStatus.FAILED.value
