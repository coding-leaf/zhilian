"""Unit tests for M2 Track A: QuestionCollection, grouped summary, and course filtering.

Covers:
1. CollectionService CRUD, duplicate name 409, folder validation, zero N+1 listing,
   soft-deleted question exclusion, delete preserving original questions.
2. Idempotent add_items, tenant/soft-delete rejection, remove_item, and
   sync_question_collections atomic add/remove.
3. PracticeService.create_practice with collection_id (caps at MAX_PRACTICE_QUESTIONS=50).
4. PracticeService.list_practices / count_practices / build_practice_summaries with
   folder_id & __none__ (including single-material practices where Practice.folder_id IS NULL).
5. QuestionService.get_grouped_summary, list_question_batches, list_questions with
   folder_id & __none__.
6. DiagnosisService.list_wrong_records & list_wrong_record_groups filtered by folder_id & __none__.
7. FastAPI router tests for /collections, /questions/{id}/collections, /questions/grouped-summary,
   and 422 validation on malformed folder_id across all review endpoints.
"""

import uuid
from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps.auth import get_current_user
from app.api.deps.collection import get_collection_service
from app.api.deps.diagnosis import get_diagnosis_service
from app.api.deps.practice import get_practice_service
from app.api.deps.question import get_question_service
from app.api.v1 import api_v1_router
from app.core.errors import (
    AppError,
    FolderNotFoundError,
    PracticeEmptyQuestionsError,
    QuestionNotFoundError,
)
from app.integrations.embedding import FakeEmbeddingAdapter
from app.integrations.llm.fake import FakeLLMAdapter
from app.models.base import Base
from app.models.knowledge import KnowledgePoint
from app.models.material import Material, MaterialFolder, MaterialVersion
from app.models.practice import ErrorType, Practice, PracticeStatus, WrongRecord
from app.models.question import Question, QuestionStatus, QuestionType
from app.models.user import User
from app.services.collection import (
    CollectionNameConflictError,
    CollectionNotFoundError,
    CollectionService,
)
from app.services.diagnosis import DiagnosisService
from app.services.practice import MAX_PRACTICE_QUESTIONS, CreatePracticeOptions, PracticeService
from app.services.question import QuestionService


@pytest.fixture
def session() -> Generator[Session, None, None]:
    """Isolated in-memory SQLite session."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as sess:
        yield sess
    engine.dispose()


def _seed_user(session: Session, nickname: str = "learner") -> User:
    user = User(id=uuid.uuid4(), openid=f"wx_{uuid.uuid4().hex[:12]}", nickname=nickname)
    session.add(user)
    session.flush()
    return user


def _seed_material_and_kp(
    session: Session,
    user_id: uuid.UUID,
    *,
    title: str,
    folder_id: uuid.UUID | None = None,
    kp_name: str = "核心考点",
) -> tuple[Material, KnowledgePoint]:
    material = Material(
        id=uuid.uuid4(),
        user_id=user_id,
        title=title,
        file_format="pdf",
        file_size=512,
        folder_id=folder_id,
    )
    version = MaterialVersion(
        id=uuid.uuid4(),
        user_id=user_id,
        material_id=material.id,
        version_number=1,
        storage_key=f"materials/{material.id}.pdf",
        content_hash=uuid.uuid4().hex,
    )
    kp = KnowledgePoint(
        id=uuid.uuid4(),
        user_id=user_id,
        material_id=material.id,
        version_id=version.id,
        name=kp_name,
        description="考点描述",
        level=1,
        batch_id="kp-batch-1",
    )
    session.add_all([material, version, kp])
    session.flush()
    return material, kp


def _seed_question(
    session: Session,
    user_id: uuid.UUID,
    material: Material,
    kp: KnowledgePoint,
    *,
    stem: str = "什么是超平面？",
    batch_id: str | None = "batch_1",
    is_deleted: bool = False,
    created_at: datetime | None = None,
) -> Question:
    version_id = session.execute(
        select(MaterialVersion.id).where(MaterialVersion.material_id == material.id)
    ).scalar_one()
    question = Question(
        id=uuid.uuid4(),
        user_id=user_id,
        material_id=material.id,
        version_id=version_id,
        knowledge_point_id=kp.id,
        question_type=QuestionType.SINGLE_CHOICE.value,
        status=QuestionStatus.AVAILABLE.value,
        is_deleted=is_deleted,
        batch_id=batch_id,
        stem=stem,
        options=[{"key": "A", "content": "选项A"}, {"key": "B", "content": "选项B"}],
        answer="A",
        analysis="解析说明",
        difficulty=3,
        grading_rubric={},
        source_snippet_ids=[],
        created_at=created_at or datetime.now(UTC),
    )
    session.add(question)
    session.flush()
    return question


class TestCollectionService:
    """Custom QuestionCollection CRUD, item management, and zero N+1 checks."""

    def test_crud_conflict_and_delete_preserves_questions(self, session: Session) -> None:
        user = _seed_user(session)
        folder = MaterialFolder(id=uuid.uuid4(), user_id=user.id, name="机器学习", sort_order=0)
        session.add(folder)
        mat, kp = _seed_material_and_kp(session, user.id, title="SVM.pdf", folder_id=folder.id)
        q_active = _seed_question(session, user.id, mat, kp, stem="活跃题")
        q_deleted = _seed_question(session, user.id, mat, kp, stem="已删题", is_deleted=True)
        session.commit()

        service = CollectionService(session)
        created = service.create_collection(
            user.id,
            name="  期中必刷  ",
            description="重点题目",
            folder_id=folder.id,
            color_token="accent",  # noqa: S106
            is_pinned=True,
        )
        assert created.name == "期中必刷"
        assert created.folder_name == "机器学习"
        assert created.question_count == 0
        assert created.is_pinned is True

        with pytest.raises(CollectionNameConflictError):
            service.create_collection(user.id, name="期中必刷")

        with pytest.raises(FolderNotFoundError):
            service.create_collection(user.id, name="越权课程", folder_id=uuid.uuid4())

        add_res = service.add_items(user.id, created.id, [q_active.id, q_active.id], note="口诀1")
        assert add_res.added_count == 1
        assert add_res.skipped_count == 0
        assert add_res.total_count == 1

        # Second add is idempotent
        add_again = service.add_items(user.id, created.id, [q_active.id])
        assert add_again.added_count == 0
        assert add_again.skipped_count == 1
        assert add_again.total_count == 1

        # Soft-deleted or foreign question rejected
        with pytest.raises(QuestionNotFoundError):
            service.add_items(user.id, created.id, [q_deleted.id])

        # List questions returns wire-mapped fields
        q_page = service.list_collection_questions(user.id, created.id, page=1, page_size=20)
        assert q_page.total == 1
        item = q_page.items[0]
        assert item.question_id == q_active.id
        assert item.content == "活跃题"
        assert item.explanation == "解析说明"
        assert item.kp_name == "核心考点"
        assert item.material_title == "SVM.pdf"
        assert item.note == "口诀1"

        # Update rename + clear_folder
        updated = service.update_collection(
            user.id,
            created.id,
            name="期末必刷",
            clear_folder=True,
            is_pinned=False,
        )
        assert updated.name == "期末必刷"
        assert updated.folder_id is None
        assert updated.folder_name is None
        assert updated.is_pinned is False

        # Delete collection never deletes underlying question
        service.delete_collection(user.id, created.id)
        with pytest.raises(CollectionNotFoundError):
            service.list_collection_questions(user.id, created.id)
        still_there = session.execute(
            select(Question).where(Question.id == q_active.id)
        ).scalar_one_or_none()
        assert still_there is not None
        assert still_there.is_deleted is False

    def test_list_collections_zero_n_plus_one_and_folder_filter(self, session: Session) -> None:
        user = _seed_user(session)
        f1 = MaterialFolder(id=uuid.uuid4(), user_id=user.id, name="课程A", sort_order=0)
        f2 = MaterialFolder(id=uuid.uuid4(), user_id=user.id, name="课程B", sort_order=1)
        session.add_all([f1, f2])
        mat, kp = _seed_material_and_kp(session, user.id, title="讲义.pdf", folder_id=f1.id)
        q1 = _seed_question(session, user.id, mat, kp, stem="Q1")
        q2 = _seed_question(session, user.id, mat, kp, stem="Q2")
        session.commit()

        service = CollectionService(session)
        c1 = service.create_collection(user.id, name="单1", folder_id=f1.id)
        c2 = service.create_collection(user.id, name="单2", folder_id=f2.id)
        c_unclassified = service.create_collection(user.id, name="通用单", folder_id=None)
        for idx in range(5):
            col = service.create_collection(user.id, name=f"批量单{idx}", folder_id=f1.id)
            service.add_items(user.id, col.id, [q1.id, q2.id])
        service.add_items(user.id, c1.id, [q1.id])
        service.add_items(user.id, c_unclassified.id, [q2.id])

        # Soft-delete q2: count must drop immediately
        q2.is_deleted = True
        session.commit()

        selects: list[str] = []

        def _count_selects(_conn: object, _cursor: object, stmt: str, *_args: object) -> None:
            if stmt.lstrip().upper().startswith("SELECT"):
                selects.append(stmt)

        bind = session.get_bind()
        user_id = user.id
        event.listen(bind, "before_cursor_execute", _count_selects)
        try:
            all_res = service.list_collections(user_id)
        finally:
            event.remove(bind, "before_cursor_execute", _count_selects)

        assert all_res.total == 8
        # Constant 3 SELECTs (collections, counts GROUP BY, folder names) regardless of count
        assert len(selects) == 3

        counts_by_name = {item.name: item.question_count for item in all_res.items}
        assert counts_by_name["单1"] == 1
        assert counts_by_name["通用单"] == 0
        assert counts_by_name["批量单0"] == 1

        f1_res = service.list_collections(user.id, folder_id=f1.id)
        assert {item.id for item in f1_res.items} == {c1.id} | {
            item.id for item in all_res.items if item.name.startswith("批量单")
        }

        none_res = service.list_collections(user.id, unclassified=True)
        assert [item.id for item in none_res.items] == [c_unclassified.id]
        assert c2.id not in {item.id for item in f1_res.items}

    def test_sync_question_collections_and_remove_item(self, session: Session) -> None:
        user = _seed_user(session)
        other_user = _seed_user(session, nickname="other")
        mat, kp = _seed_material_and_kp(session, user.id, title="高数.pdf")
        q1 = _seed_question(session, user.id, mat, kp, stem="高数题")
        session.commit()

        service = CollectionService(session)
        c1 = service.create_collection(user.id, name="题单1")
        c2 = service.create_collection(user.id, name="题单2")
        c3 = service.create_collection(user.id, name="题单3")
        other_col = service.create_collection(other_user.id, name="他人题单")

        sync1 = service.sync_question_collections(user.id, q1.id, [c1.id, c2.id])
        assert set(sync1.collection_ids) == {c1.id, c2.id}
        assert sync1.added_count == 2
        assert sync1.removed_count == 0

        sync2 = service.sync_question_collections(user.id, q1.id, [c2.id, c3.id])
        assert set(sync2.collection_ids) == {c2.id, c3.id}
        assert sync2.added_count == 1
        assert sync2.removed_count == 1

        got = service.get_question_collections(user.id, q1.id)
        assert set(got.collection_ids) == {c2.id, c3.id}

        with pytest.raises(CollectionNotFoundError):
            service.sync_question_collections(user.id, q1.id, [other_col.id])

        service.remove_item(user.id, c2.id, q1.id)
        assert service.get_question_collections(user.id, q1.id).collection_ids == [c3.id]


class TestReviewFiltersAndPracticeFromCollection:
    """Cross-domain filter parity and collection-to-practice integration."""

    def test_create_practice_from_collection_respects_limit_and_soft_delete(
        self, session: Session
    ) -> None:
        user = _seed_user(session)
        folder = MaterialFolder(id=uuid.uuid4(), user_id=user.id, name="概率论", sort_order=0)
        session.add(folder)
        mat, kp = _seed_material_and_kp(session, user.id, title="概率.pdf", folder_id=folder.id)
        questions = [
            _seed_question(
                session,
                user.id,
                mat,
                kp,
                stem=f"第{i}题",
                created_at=datetime.now(UTC) + timedelta(seconds=i),
            )
            for i in range(55)
        ]
        session.commit()

        col_service = CollectionService(session)
        col = col_service.create_collection(user.id, name="超大题单", folder_id=folder.id)
        col_service.add_items(user.id, col.id, [q.id for q in questions])
        empty_col = col_service.create_collection(user.id, name="空题单")

        # Soft delete one question inside collection
        questions[0].is_deleted = True
        session.commit()

        practice_service = PracticeService(session)
        practice = practice_service.create_practice(
            user.id,
            CreatePracticeOptions(
                title="题单整单开练",
                material_id=None,
                knowledge_point_ids=[],
                question_count=50,
                collection_id=col.id,
            ),
        )
        assert practice.question_count == MAX_PRACTICE_QUESTIONS
        assert practice.folder_id == folder.id
        assert all(item.question_id != questions[0].id for item in practice.items)

        with pytest.raises(PracticeEmptyQuestionsError):
            practice_service.create_practice(
                user.id,
                CreatePracticeOptions(
                    title="空题单开练",
                    material_id=None,
                    knowledge_point_ids=[],
                    question_count=50,
                    collection_id=empty_col.id,
                ),
            )

        with pytest.raises(CollectionNotFoundError):
            practice_service.create_practice(
                user.id,
                CreatePracticeOptions(
                    title="不存在题单",
                    material_id=None,
                    knowledge_point_ids=[],
                    question_count=50,
                    collection_id=uuid.uuid4(),
                ),
            )

    def test_practices_folder_filter_real_total_and_display_meta(self, session: Session) -> None:
        user = _seed_user(session)
        f_a = MaterialFolder(id=uuid.uuid4(), user_id=user.id, name="软件工程", sort_order=0)
        f_b = MaterialFolder(id=uuid.uuid4(), user_id=user.id, name="啊", sort_order=1)
        session.add_all([f_a, f_b])
        mat_a, _ = _seed_material_and_kp(session, user.id, title="需求工程.pdf", folder_id=f_a.id)
        mat_none, _ = _seed_material_and_kp(session, user.id, title="未分类.pdf", folder_id=None)

        # Single-material practice (folder_id=None, material_id=mat_a.id)
        p_single = Practice(
            user_id=user.id,
            material_id=mat_a.id,
            folder_id=None,
            title="单资料练习",
            status=PracticeStatus.COMPLETED.value,
        )
        # Course-level practice (folder_id=f_a.id, material_id=None)
        p_folder = Practice(
            user_id=user.id,
            material_id=None,
            folder_id=f_a.id,
            title="课程综合练习",
            status=PracticeStatus.IN_PROGRESS.value,
        )
        # Unclassified practice
        p_unclassified = Practice(
            user_id=user.id,
            material_id=mat_none.id,
            folder_id=None,
            title="未分类练习",
            status=PracticeStatus.NOT_STARTED.value,
        )
        session.add_all([p_single, p_folder, p_unclassified])
        session.commit()

        service = PracticeService(session)
        fa_items = service.list_practices(user.id, folder_id=f_a.id, limit=1, offset=0)
        fa_total = service.count_practices(user.id, folder_id=f_a.id)
        assert len(fa_items) == 1
        assert fa_total == 2

        fb_total = service.count_practices(user.id, folder_id=f_b.id)
        assert fb_total == 0

        unclass_items = service.list_practices(user.id, unclassified=True)
        assert [p.id for p in unclass_items] == [p_unclassified.id]

        summaries = service.build_practice_summaries([p_single, p_folder], user_id=user.id)
        by_id = {s.id: s for s in summaries}
        assert by_id[p_single.id].material_title == "需求工程.pdf"
        assert by_id[p_single.id].folder_name == "软件工程"
        assert by_id[p_folder.id].folder_name == "软件工程"
        assert by_id[p_folder.id].material_title is None

    def test_questions_grouped_summary_batches_and_wrong_groups(self, session: Session) -> None:
        user = _seed_user(session)
        f_a = MaterialFolder(id=uuid.uuid4(), user_id=user.id, name="课程A", sort_order=0)
        f_b = MaterialFolder(id=uuid.uuid4(), user_id=user.id, name="课程B", sort_order=1)
        session.add_all([f_a, f_b])

        mat_a, kp_a = _seed_material_and_kp(
            session, user.id, title="SVM.pdf", folder_id=f_a.id, kp_name="核技巧"
        )
        mat_none, kp_none = _seed_material_and_kp(
            session, user.id, title="散落讲义.pdf", folder_id=None, kp_name="散落考点"
        )
        q_a = _seed_question(session, user.id, mat_a, kp_a, batch_id="batch_a")
        q_none = _seed_question(session, user.id, mat_none, kp_none, batch_id="batch_none")

        session.add(
            WrongRecord(
                user_id=user.id,
                question_id=q_a.id,
                knowledge_point_id=kp_a.id,
                question_snapshot={
                    "question_type": "single_choice",
                    "stem": "q_a",
                    "options": [{"key": "A", "content": "a"}],
                    "answer": "A",
                    "analysis": "x",
                    "difficulty": 3,
                },
                error_type=ErrorType.CONCEPTUAL.value,
                is_mastered=False,
            )
        )
        session.add(
            WrongRecord(
                user_id=user.id,
                question_id=q_none.id,
                knowledge_point_id=kp_none.id,
                question_snapshot={
                    "question_type": "single_choice",
                    "stem": "q_none",
                    "options": [{"key": "A", "content": "a"}],
                    "answer": "A",
                    "analysis": "x",
                    "difficulty": 3,
                },
                error_type=ErrorType.CONCEPTUAL.value,
                is_mastered=False,
            )
        )
        session.commit()

        q_service = QuestionService(
            session=session,
            llm=FakeLLMAdapter(),
            embedding=FakeEmbeddingAdapter(),
        )
        summary_a = q_service.get_grouped_summary(user.id, folder_id=f_a.id)
        assert summary_a.total_questions == 1
        assert len(summary_a.materials) == 1
        assert summary_a.materials[0].material_title == "SVM.pdf"
        assert summary_a.materials[0].folder_name == "课程A"
        assert summary_a.materials[0].knowledge_points[0].kp_name == "核技巧"

        summary_none = q_service.get_grouped_summary(user.id, unclassified=True)
        assert summary_none.total_questions == 1
        assert summary_none.materials[0].material_id == mat_none.id

        batches_a, total_a = q_service.list_question_batches(user.id, folder_id=f_a.id)
        assert total_a == 1
        assert [b.batch_id for b in batches_a] == ["batch_a"]

        batches_none, total_none = q_service.list_question_batches(user.id, unclassified=True)
        assert total_none == 1
        assert [b.batch_id for b in batches_none] == ["batch_none"]

        qs_none, q_total_none = q_service.list_questions(user.id, unclassified=True)
        assert q_total_none == 1
        assert qs_none[0].id == q_none.id

        diag_service = DiagnosisService(session)
        groups_a = diag_service.list_wrong_record_groups(user.id, folder_id=f_a.id)
        assert len(groups_a) == 1
        assert groups_a[0]["folder_id"] == f_a.id

        groups_b = diag_service.list_wrong_record_groups(user.id, folder_id=f_b.id)
        assert groups_b == []

        groups_none = diag_service.list_wrong_record_groups(user.id, unclassified=True)
        assert len(groups_none) == 1
        assert groups_none[0]["material_id"] == mat_none.id


def _create_router_test_app(session: Session, user: User) -> FastAPI:
    app = FastAPI(title="Track A Integration Router Test")

    @app.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.error_code, "message": exc.message, "details": exc.details},
        )

    app.include_router(api_v1_router)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_collection_service] = lambda: CollectionService(session)
    app.dependency_overrides[get_diagnosis_service] = lambda: DiagnosisService(session)
    app.dependency_overrides[get_practice_service] = lambda: PracticeService(session)
    app.dependency_overrides[get_question_service] = lambda: QuestionService(
        session=session,
        llm=FakeLLMAdapter(),
        embedding=FakeEmbeddingAdapter(),
    )
    return app


@pytest.mark.asyncio
async def test_collections_and_filters_http_contract(session: Session) -> None:
    """Verify HTTP routes, status codes, 422 folder validation, and zero PATCH methods."""
    user = _seed_user(session)
    folder = MaterialFolder(id=uuid.uuid4(), user_id=user.id, name="计算机网络", sort_order=0)
    session.add(folder)
    mat, kp = _seed_material_and_kp(session, user.id, title="TCP.pdf", folder_id=folder.id)
    q1 = _seed_question(session, user.id, mat, kp, stem="三次握手")
    session.commit()

    app = _create_router_test_app(session, user)
    # Verify zero PATCH routes on collections
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set())
        if "/collections" in path:
            assert "PATCH" not in methods

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 422 on invalid folder_id across all unified endpoints
        for endpoint in (
            "/api/v1/wrong-records",
            "/api/v1/practices",
            "/api/v1/questions/batches",
            "/api/v1/questions",
            "/api/v1/questions/grouped-summary",
            "/api/v1/collections",
        ):
            bad_res = await client.get(endpoint, params={"folder_id": "invalid-uuid"})
            assert bad_res.status_code == 422, f"{endpoint} returned {bad_res.status_code}"

        # grouped-summary is not shadowed by /questions/{id}
        gs_res = await client.get(
            "/api/v1/questions/grouped-summary", params={"folder_id": str(folder.id)}
        )
        assert gs_res.status_code == 200
        assert gs_res.json()["total_questions"] == 1

        # Create collection (201) + duplicate (409)
        create_res = await client.post(
            "/api/v1/collections",
            json={"name": "网络必刷", "folder_id": str(folder.id)},
        )
        assert create_res.status_code == 201
        col_id = create_res.json()["id"]

        dup_res = await client.post("/api/v1/collections", json={"name": "网络必刷"})
        assert dup_res.status_code == 409

        # Add item, query collection questions, sync question collections, start practice
        add_res = await client.post(
            f"/api/v1/collections/{col_id}/items",
            json={"question_ids": [str(q1.id)], "note": "必考"},
        )
        assert add_res.status_code == 200
        assert add_res.json()["added_count"] == 1

        list_q_res = await client.get(f"/api/v1/collections/{col_id}/questions")
        assert list_q_res.status_code == 200
        assert list_q_res.json()["items"][0]["content"] == "三次握手"

        prac_res = await client.post(
            "/api/v1/practices",
            json={"title": "按题单开练", "collection_id": col_id},
        )
        assert prac_res.status_code == 201
        assert prac_res.json()["question_count"] == 1

        sync_res = await client.post(
            f"/api/v1/questions/{q1.id}/collections",
            json={"collection_ids": []},
        )
        assert sync_res.status_code == 200
        assert sync_res.json()["removed_count"] == 1

        del_res = await client.delete(f"/api/v1/collections/{col_id}")
        assert del_res.status_code == 204
