"""Unit tests for option prefix strip, display meta enrichment, folder mastery, and sync."""

import uuid
from collections.abc import Generator
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps.auth import get_current_user
from app.api.deps.diagnosis import get_diagnosis_service
from app.api.v1 import api_v1_router
from app.core.errors import AppError
from app.models.base import Base
from app.models.knowledge import KnowledgePoint
from app.models.material import Material, MaterialFolder, MaterialVersion
from app.models.practice import (
    AttemptItem,
    DiagnosisReport,
    ErrorType,
    MasteryLevel,
    MasteryRecord,
    PracticeStatus,
    WrongRecord,
)
from app.models.question import Question, QuestionStatus, QuestionType
from app.models.user import User
from app.schemas.practice import QuestionSnapshotDTO
from app.services._question_llm_schemas import _normalize_llm_options
from app.services.diagnosis import DiagnosisService
from app.services.grading import GradingService, RegradeAttemptDTO, SelfEvaluateDTO
from app.services.practice import (
    CreatePracticeOptions,
    PracticeService,
    SaveAnswerDTO,
    SubmitPracticeDTO,
)


@pytest.fixture
def session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as sess:
        yield sess
    engine.dispose()


def _seed_folder_and_uncategorized_env(session: Session) -> dict[str, Any]:
    user_id = uuid.uuid4()
    folder = MaterialFolder(
        id=uuid.uuid4(),
        user_id=user_id,
        name="计算机网络",
    )
    mat_in_folder = Material(
        id=uuid.uuid4(),
        user_id=user_id,
        folder_id=folder.id,
        title="TCP协议详解.pdf",
        file_format="pdf",
        file_size=1024,
    )
    ver_in_folder = MaterialVersion(
        id=uuid.uuid4(),
        material_id=mat_in_folder.id,
        user_id=user_id,
        version_number=1,
        storage_key="raw/tcp.pdf",
        content_hash="tcp_hash",
    )
    kp_in_folder = KnowledgePoint(
        id=uuid.uuid4(),
        user_id=user_id,
        material_id=mat_in_folder.id,
        version_id=ver_in_folder.id,
        name="TCP三次握手",
        description="建立连接过程",
        batch_id="b1",
    )
    mat_uncat = Material(
        id=uuid.uuid4(),
        user_id=user_id,
        folder_id=None,
        title="未分类资料.md",
        file_format="md",
        file_size=512,
    )
    ver_uncat = MaterialVersion(
        id=uuid.uuid4(),
        material_id=mat_uncat.id,
        user_id=user_id,
        version_number=1,
        storage_key="raw/uncat.md",
        content_hash="uncat_hash",
    )
    kp_uncat = KnowledgePoint(
        id=uuid.uuid4(),
        user_id=user_id,
        material_id=mat_uncat.id,
        version_id=ver_uncat.id,
        name="独立知识点",
        description="未分类描述",
        batch_id="b1",
    )
    q_obj = Question(
        id=uuid.uuid4(),
        user_id=user_id,
        material_id=mat_in_folder.id,
        version_id=ver_in_folder.id,
        knowledge_point_id=kp_in_folder.id,
        question_type=QuestionType.SINGLE_CHOICE.value,
        stem="TCP 建立连接需要几次握手？",
        options=[{"key": "A", "content": "三次"}, {"key": "B", "content": "两次"}],
        answer="A",
        difficulty=2,
        status=QuestionStatus.AVAILABLE.value,
    )
    q_sub = Question(
        id=uuid.uuid4(),
        user_id=user_id,
        material_id=mat_in_folder.id,
        version_id=ver_in_folder.id,
        knowledge_point_id=kp_in_folder.id,
        question_type=QuestionType.SHORT_ANSWER.value,
        stem="说明第三次握手的必要性。",
        options=[],
        answer="防止已失效的连接请求报文段突然又传送到服务端",
        difficulty=3,
        status=QuestionStatus.AVAILABLE.value,
    )
    session.add_all(
        [
            folder,
            mat_in_folder,
            ver_in_folder,
            kp_in_folder,
            mat_uncat,
            ver_uncat,
            kp_uncat,
            q_obj,
            q_sub,
        ]
    )
    session.commit()
    return {
        "user_id": user_id,
        "folder": folder,
        "mat_in_folder": mat_in_folder,
        "kp_in_folder": kp_in_folder,
        "mat_uncat": mat_uncat,
        "kp_uncat": kp_uncat,
        "q_obj": q_obj,
        "q_sub": q_sub,
    }


def test_normalize_llm_options_strips_duplicate_prefixes_on_dict_items() -> None:
    """dict option items like {'key': 'A', 'content': 'A. 选项内容'} strip redundant prefix."""
    normalized = _normalize_llm_options(
        [
            {"key": "A.", "content": "A. 进程互斥"},
            {"key": "B、", "content": "B、进程同步"},
            {"key": "(C)", "content": "(C) 死锁预防"},
            {"key": "D:", "content": "D: 页面置换"},
        ]
    )
    assert normalized == [
        {"key": "A", "content": "进程互斥"},
        {"key": "B", "content": "进程同步"},
        {"key": "C", "content": "死锁预防"},
        {"key": "D", "content": "页面置换"},
    ]


def test_practice_snapshot_populates_and_hydrates_knowledge_point_name(session: Session) -> None:
    """Created snapshots capture knowledge_point_name and get_practice hydrates legacy nulls."""
    env = _seed_folder_and_uncategorized_env(session)
    user_id = env["user_id"]
    kp = env["kp_in_folder"]
    q_obj = env["q_obj"]

    service = PracticeService(session)
    practice = service.create_practice(
        user_id,
        CreatePracticeOptions(
            title="知识点名称快照测试",
            material_id=env["mat_in_folder"].id,
            knowledge_point_ids=[kp.id],
            question_ids=[q_obj.id],
            question_count=1,
        ),
    )
    assert practice.items[0].question_snapshot["knowledge_point_name"] == kp.name

    # Simulate a legacy snapshot without knowledge_point_name in DB
    item_orm = session.query(AttemptItem).filter_by(practice_id=practice.id).one()
    legacy_snapshot = dict(item_orm.question_snapshot)
    legacy_snapshot.pop("knowledge_point_name", None)
    item_orm.question_snapshot = legacy_snapshot
    session.commit()

    detail = service.get_practice(user_id=user_id, practice_id=practice.id)
    snapshot = detail.items[0].question_snapshot
    validated_snapshot = (
        snapshot
        if isinstance(snapshot, QuestionSnapshotDTO)
        else QuestionSnapshotDTO.model_validate(snapshot)
    )
    assert validated_snapshot.knowledge_point_name == kp.name


def test_grading_auto_sync_is_idempotent_across_submit_grade_and_self_evaluate(
    session: Session,
) -> None:
    """Mixed submit + grade + self_evaluate syncs state without inflating error_count."""
    env = _seed_folder_and_uncategorized_env(session)
    user_id = env["user_id"]
    kp = env["kp_in_folder"]
    q_obj = env["q_obj"]
    q_sub = env["q_sub"]

    practice_service = PracticeService(session)
    practice = practice_service.create_practice(
        user_id,
        CreatePracticeOptions(
            title="闭环自动同步测试",
            material_id=env["mat_in_folder"].id,
            knowledge_point_ids=[kp.id],
            question_ids=[q_obj.id, q_sub.id],
            question_count=2,
        ),
    )
    practice_service.save_answer(
        user_id, SaveAnswerDTO(practice_id=practice.id, question_id=q_obj.id, user_answer="B")
    )
    practice_service.save_answer(
        user_id,
        SaveAnswerDTO(
            practice_id=practice.id,
            question_id=q_sub.id,
            user_answer="防止已失效的连接请求报文段突然又传送到服务端",
        ),
    )

    submit_res = practice_service.submit_practice(
        user_id,
        SubmitPracticeDTO(practice_id=practice.id, idempotency_key=str(uuid.uuid4())),
    )
    assert submit_res.status == PracticeStatus.SUBMITTED.value

    # WrongRecord for q_obj created immediately on submit with error_count == 1
    wrong_obj = session.query(WrongRecord).filter_by(user_id=user_id, question_id=q_obj.id).one()
    assert wrong_obj.error_count == 1

    # Complete grading -> triggers auto diagnosis sync & generates report idempotently
    grading_service = GradingService(session)
    summary = grading_service.grade_practice(user_id=user_id, practice_id=practice.id)
    assert summary.status == PracticeStatus.COMPLETED.value

    session.refresh(wrong_obj)
    assert wrong_obj.error_count == 1
    assert (
        session.query(MasteryRecord).filter_by(user_id=user_id, knowledge_point_id=kp.id).count()
        == 1
    )
    assert session.query(DiagnosisReport).filter_by(practice_id=practice.id).count() == 1

    # Self-evaluate subjective item to zero -> adds subjective wrong record & updates mastery
    sub_item = (
        session.query(AttemptItem).filter_by(practice_id=practice.id, question_id=q_sub.id).one()
    )
    grading_service.self_evaluate_attempt(
        user_id=user_id,
        dto=SelfEvaluateDTO(attempt_item_id=sub_item.id, score=0.0, is_correct=False),
    )
    wrong_sub = session.query(WrongRecord).filter_by(user_id=user_id, question_id=q_sub.id).one()
    assert wrong_sub.error_count == 1

    # Re-evaluate subjective item again on SAME attempt_item -> idempotent error_count stays 1
    grading_service.self_evaluate_attempt(
        user_id=user_id,
        dto=SelfEvaluateDTO(attempt_item_id=sub_item.id, score=0.5, is_correct=False),
    )
    session.refresh(wrong_sub)
    assert wrong_sub.error_count == 1

    # Verify regrade_attempt hook too with stub LLM
    from app.integrations.llm.protocol import (
        LLMOptions,
        LLMProtocol,
        LLMResponse,
        LLMUsage,
    )

    class _StubRegradeLLM(LLMProtocol):
        def generate(self, messages: Any, options: Any = None) -> LLMResponse:
            return LLMResponse(content="{}", model="stub", usage=LLMUsage())

        def generate_structured(
            self,
            messages: Any,
            response_model: Any,
            options: LLMOptions | None = None,
        ) -> tuple[Any, LLMResponse]:
            parsed = response_model.model_validate(
                {"score": 1.0, "confidence": 0.95, "feedback": "正确", "evaluations": []}
            )
            return parsed, LLMResponse(content="{}", model="stub", usage=LLMUsage())

    regrade_service = GradingService(session=session, llm_adapter=_StubRegradeLLM())
    regrade_service.regrade_attempt(
        user_id=user_id, dto=RegradeAttemptDTO(attempt_item_id=sub_item.id)
    )
    session.refresh(wrong_sub)
    assert wrong_sub.is_mastered is True


@pytest.mark.asyncio
async def test_mastery_folder_filter_and_wrong_record_display_meta_endpoints(
    session: Session,
) -> None:
    """GET /mastery?folder_id= and /wrong-records return scoped mastery and display names."""
    env = _seed_folder_and_uncategorized_env(session)
    user_id = env["user_id"]
    folder = env["folder"]
    kp_folder = env["kp_in_folder"]
    kp_uncat = env["kp_uncat"]

    session.add_all(
        [
            MasteryRecord(
                user_id=user_id,
                knowledge_point_id=kp_folder.id,
                mastery_score=0.35,
                level=MasteryLevel.WEAK.value,
                practice_count=2,
                correct_count=1,
            ),
            MasteryRecord(
                user_id=user_id,
                knowledge_point_id=kp_uncat.id,
                mastery_score=0.85,
                level=MasteryLevel.PROFICIENT.value,
                practice_count=4,
                correct_count=4,
            ),
            WrongRecord(
                user_id=user_id,
                question_id=env["q_obj"].id,
                knowledge_point_id=kp_folder.id,
                error_type=ErrorType.CONCEPTUAL.value,
                error_count=1,
                is_mastered=False,
                question_snapshot={"stem": env["q_obj"].stem, "question_type": "single_choice"},
            ),
        ]
    )
    session.commit()

    app = FastAPI()

    @app.exception_handler(AppError)
    async def _app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"code": exc.error_code})

    app.include_router(api_v1_router)
    user = User(id=user_id, nickname="learner", is_active=True, token_version=1)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_diagnosis_service] = lambda: DiagnosisService(session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        folder_resp = await client.get(f"/api/v1/mastery?folder_id={folder.id}")
        uncat_resp = await client.get("/api/v1/mastery?folder_id=__none__")
        bad_resp = await client.get("/api/v1/mastery?folder_id=not-a-uuid")
        wr_resp = await client.get("/api/v1/wrong-records")

    assert folder_resp.status_code == 200
    assert folder_resp.json()["total_knowledge_points"] == 1
    assert folder_resp.json()["weak_count"] == 1
    assert folder_resp.json()["proficient_count"] == 0

    assert uncat_resp.status_code == 200
    assert uncat_resp.json()["total_knowledge_points"] == 1
    assert uncat_resp.json()["proficient_count"] == 1

    assert bad_resp.status_code == 400

    assert wr_resp.status_code == 200
    wr_item = wr_resp.json()["items"][0]
    assert wr_item["knowledge_point_name"] == "TCP三次握手"
    assert wr_item["material_title"] == "TCP协议详解.pdf"
