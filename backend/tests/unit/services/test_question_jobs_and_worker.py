"""Unit tests for QuestionService async job pipeline, multi-KP concurrency, and worker."""

import json
import uuid
from collections.abc import Generator, Sequence
from types import SimpleNamespace
from typing import Any, TypeVar
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app import worker
from app.core.errors import QuestionGenerationJobNotFoundError
from app.integrations.embedding import FakeEmbeddingAdapter
from app.integrations.llm.protocol import (
    LLMMessage,
    LLMOptions,
    LLMProtocol,
    LLMResponse,
    LLMUsage,
)
from app.integrations.queue.memory import MemoryQueueAdapter
from app.models.base import Base
from app.models.knowledge import KnowledgePoint, KnowledgePointSnippet
from app.models.material import Material, MaterialSnippet, MaterialVersion
from app.models.question import Question, QuestionGenerationJobStatus
from app.schemas.question import QuestionGenerateRequest
from app.services._question_llm_schemas import LLMGeneratedQuestionItem, LLMQuestionBatchOutput
from app.services.question import QuestionService

T = TypeVar("T", bound=BaseModel)


class _StructuredQuestionStubLLM(LLMProtocol):
    """Stub LLM generating distinct valid questions per snippet prompt."""

    def generate(
        self,
        messages: Sequence[LLMMessage],
        options: LLMOptions | None = None,
    ) -> LLMResponse:
        return LLMResponse(content="{}", model="stub", usage=LLMUsage())

    def generate_structured(
        self,
        messages: Sequence[LLMMessage],
        response_model: type[T],
        options: LLMOptions | None = None,
    ) -> tuple[T, LLMResponse]:
        prompt = messages[-1].content
        token = "kp2" if "KP_TWO" in prompt else "kp1"
        output = LLMQuestionBatchOutput(
            questions=[
                LLMGeneratedQuestionItem(
                    question_type="single_choice",
                    stem=f"关于{token}的核心概念，下列哪项描述准确？({uuid.uuid4().hex[:6]})",
                    options=["概念定义准确", "干扰项二", "干扰项三", "干扰项四"],
                    answer="A",
                    explanation="严格依据切片原文得出正确解析。",
                    source_snippet_index=0,
                )
            ]
        )
        return response_model.model_validate(output.model_dump()), LLMResponse(
            content=json.dumps(output.model_dump(), ensure_ascii=False),
            model="stub",
            usage=LLMUsage(),
        )


@pytest.fixture
def session() -> Generator[Session, None, None]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as sess:
        yield sess
    engine.dispose()


def _seed_two_kp_material(session: Session) -> dict[str, Any]:
    user_id = uuid.uuid4()
    material_id = uuid.uuid4()
    version_id = uuid.uuid4()
    kp1_id = uuid.uuid4()
    kp2_id = uuid.uuid4()

    embedder = FakeEmbeddingAdapter()
    text_1 = "KP_ONE 进程同步使用信号量与 PV 原语防止竞态条件并保证临界区互斥访问。"
    text_2 = "KP_TWO 虚拟内存通过页表与 TLB 快表实现逻辑地址到物理页框的快速映射。"
    vecs = embedder.embed_documents([text_1, text_2])

    material = Material(
        id=material_id,
        user_id=user_id,
        title="操作系统原理",
        file_format="pdf",
        file_size=1024,
    )
    version = MaterialVersion(
        id=version_id,
        material_id=material_id,
        user_id=user_id,
        version_number=1,
        storage_key="raw/os.pdf",
        content_hash="os_hash",
    )
    s1 = MaterialSnippet(
        id=uuid.uuid4(),
        user_id=user_id,
        material_id=material_id,
        version_id=version_id,
        snippet_index=0,
        content=text_1,
        char_length=len(text_1),
        start_offset=0,
        end_offset=len(text_1),
        embedding=vecs[0],
        source_info={"page_number": 1},
    )
    s2 = MaterialSnippet(
        id=uuid.uuid4(),
        user_id=user_id,
        material_id=material_id,
        version_id=version_id,
        snippet_index=1,
        content=text_2,
        char_length=len(text_2),
        start_offset=len(text_1),
        end_offset=len(text_1) + len(text_2),
        embedding=vecs[1],
        source_info={"page_number": 2},
    )
    kp1 = KnowledgePoint(
        id=kp1_id,
        user_id=user_id,
        material_id=material_id,
        version_id=version_id,
        name="进程同步",
        description=text_1,
        batch_id="b1",
    )
    kp2 = KnowledgePoint(
        id=kp2_id,
        user_id=user_id,
        material_id=material_id,
        version_id=version_id,
        name="虚拟内存",
        description=text_2,
        batch_id="b1",
    )
    rel1 = KnowledgePointSnippet(
        user_id=user_id,
        knowledge_point_id=kp1_id,
        snippet_id=s1.id,
    )
    rel2 = KnowledgePointSnippet(
        user_id=user_id,
        knowledge_point_id=kp2_id,
        snippet_id=s2.id,
    )
    session.add_all([material, version, s1, s2, kp1, kp2, rel1, rel2])
    session.commit()
    return {
        "user_id": user_id,
        "material_id": material_id,
        "version_id": version_id,
        "kp1_id": kp1_id,
        "kp2_id": kp2_id,
    }


def test_question_generation_job_lifecycle_and_concurrent_multi_kp(
    session: Session,
) -> None:
    """Creating and executing a generation job completes all KPs and updates progress."""
    env = _seed_two_kp_material(session)
    queue = MemoryQueueAdapter()
    service = QuestionService(
        session=session,
        llm=_StructuredQuestionStubLLM(),
        embedding=FakeEmbeddingAdapter(),
        queue=queue,
    )
    payload = QuestionGenerateRequest(
        material_id=env["material_id"],
        version_id=env["version_id"],
        knowledge_point_ids=[env["kp1_id"], env["kp2_id"]],
        question_types=["single_choice"],
        count=2,
        difficulty=3,
    )

    job = service.create_generation_job(user_id=env["user_id"], payload=payload)
    assert job.status == QuestionGenerationJobStatus.QUEUED.value
    assert job.total_kps == 2
    assert job.completed_kps == 0
    assert len(queue._queue) == 1
    assert queue._queue[0].task_name == "generate_questions_job"
    assert queue._queue[0].payload["job_id"] == str(job.id)

    active_jobs, active_total = service.list_generation_jobs(
        user_id=env["user_id"], active_only=True, material_id=env["material_id"]
    )
    assert active_total == 1
    assert active_jobs[0].id == job.id

    completed = service.run_generation_job(job_id=job.id, user_id=env["user_id"])
    assert completed.status == QuestionGenerationJobStatus.COMPLETED.value
    assert completed.total_kps == 2
    assert completed.completed_kps == 2
    assert completed.generated_count >= 2
    assert completed.batch_id is not None
    assert len(completed.question_ids) == completed.generated_count
    assert completed.completed_at is not None

    # Tenant isolation and active_only filter after completion
    after_active, after_total = service.list_generation_jobs(
        user_id=env["user_id"], active_only=True
    )
    assert after_total == 0
    assert after_active == []
    with pytest.raises(QuestionGenerationJobNotFoundError):
        service.get_generation_job(user_id=uuid.uuid4(), job_id=job.id)

    persisted_questions = session.query(Question).filter_by(user_id=env["user_id"]).all()
    assert len(persisted_questions) == completed.generated_count


def test_mark_generation_job_failed_sets_failed_status_and_error(session: Session) -> None:
    """mark_generation_job_failed records failed terminal state without dropping user scope."""
    env = _seed_two_kp_material(session)
    service = QuestionService(
        session=session,
        llm=_StructuredQuestionStubLLM(),
        embedding=FakeEmbeddingAdapter(),
        queue=MemoryQueueAdapter(),
    )
    job = service.create_generation_job(
        user_id=env["user_id"],
        payload=QuestionGenerateRequest(
            material_id=env["material_id"],
            knowledge_point_ids=[env["kp1_id"]],
            question_types=["single_choice"],
            count=1,
            difficulty=3,
        ),
    )

    failed = service.mark_generation_job_failed(
        user_id=env["user_id"],
        job_id=job.id,
        error_message="模拟超时失败",
    )
    assert failed is not None
    assert failed.status == QuestionGenerationJobStatus.FAILED.value
    assert failed.error_message == "模拟超时失败"
    assert failed.completed_at is not None


def test_worker_dispatches_generate_questions_and_handles_terminal_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """worker.py routes generate_questions_job, force parse, and terminal failure callbacks."""
    fake_session = MagicMock()
    fake_question_svc = MagicMock()
    fake_material_svc = MagicMock()
    fake_container = MagicMock()
    fake_container.get_session.return_value.__enter__.return_value = fake_session
    fake_container.get_session.return_value.__exit__.return_value = False
    fake_container.create_question_service.return_value = fake_question_svc
    fake_container.create_material_service.return_value = fake_material_svc

    async def _noop_shutdown() -> None:
        return None

    fake_container.shutdown.side_effect = _noop_shutdown
    monkeypatch.setattr(worker.AppContainer, "create", classmethod(lambda cls: fake_container))

    user_id = uuid.uuid4()
    job_id = uuid.uuid4()
    worker.execute_registered_task(
        "generate_questions_job",
        {"job_id": str(job_id), "user_id": str(user_id)},
        str(user_id),
    )
    fake_question_svc.run_generation_job.assert_called_once_with(job_id=job_id, user_id=user_id)

    material_id = uuid.uuid4()
    version_id = uuid.uuid4()
    worker.execute_registered_task(
        "parse_material_pipeline",
        {
            "material_id": str(material_id),
            "version_id": str(version_id),
            "user_id": str(user_id),
            "force": "true",
        },
        str(user_id),
    )
    fake_material_svc.parse_material_pipeline.assert_called_once_with(
        material_id=material_id,
        version_id=version_id,
        user_id=user_id,
        force=True,
    )

    # Retryable failure must skip terminal callback
    retryable_job = SimpleNamespace(
        id="rq-1",
        args=("generate_questions_job", {"job_id": str(job_id)}, str(user_id)),
        meta={},
        should_retry=True,
    )
    worker.handle_job_terminal_failure(retryable_job, MagicMock(), TimeoutError, None, None)  # type: ignore[arg-type]
    fake_question_svc.mark_generation_job_failed.assert_not_called()

    # Terminal failure marks job failed
    terminal_job = SimpleNamespace(
        id="rq-2",
        args=("generate_questions_job", {"job_id": str(job_id)}, str(user_id)),
        meta={},
        should_retry=False,
    )
    worker.handle_job_terminal_failure(terminal_job, MagicMock(), TimeoutError, None, None)  # type: ignore[arg-type]
    fake_question_svc.mark_generation_job_failed.assert_called_once()
