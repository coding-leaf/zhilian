"""Unit tests verifying soft-deleted material visibility across Review Tab repositories.

Verifies:
1. Soft-deleting a material (`Material.is_deleted == True`) hides its mastery records,
   knowledge points, wrong records (list, count, groups, unmastered ids, weak kp ids),
   question bank entries (list_questions, batches, grouped counts, batch sources),
   and collection items/counts under All / Folder / Unclassified / Material scopes.
2. Historical `Practice` sessions, `AttemptItem`s, `DiagnosisReport`s, and
   `QuestionRepository.get_question_by_id` / `list_questions_by_ids` remain 100% readable.
"""

import uuid
from collections.abc import Generator
from dataclasses import dataclass

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.base import Base
from app.models.knowledge import KnowledgePoint
from app.models.material import Material, MaterialFolder, MaterialVersion
from app.models.practice import (
    AttemptItem,
    DiagnosisReport,
    ErrorType,
    MasteryLevel,
    Practice,
    PracticeStatus,
)
from app.models.question import Question, QuestionStatus, QuestionType
from app.models.user import User
from app.repositories.collection import CollectionRepository
from app.repositories.diagnosis import DiagnosisRepository
from app.repositories.knowledge import KnowledgeRepository
from app.repositories.practice import PracticeRepository
from app.repositories.question import QuestionRepository
from app.services.diagnosis import DiagnosisService


@dataclass(frozen=True)
class _MaterialGraph:
    material: Material
    kp_id: uuid.UUID
    question: Question


@dataclass(frozen=True)
class _VisibilityFixture:
    user_id: uuid.UUID
    folder_id: uuid.UUID
    active_in_folder: _MaterialGraph
    deleted_in_folder: _MaterialGraph
    active_unclassified: _MaterialGraph
    deleted_unclassified: _MaterialGraph
    collection_id: uuid.UUID
    deleted_practice_id: uuid.UUID


@pytest.fixture
def session() -> Generator[Session, None, None]:
    """Provide an isolated in-memory SQLite database session."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as sess:
        yield sess
    engine.dispose()


def _seed_material_graph(
    session: Session,
    *,
    user_id: uuid.UUID,
    title: str,
    folder_id: uuid.UUID | None,
    kp_name: str,
    batch_id: str,
    is_deleted: bool,
) -> _MaterialGraph:
    """Create a material, version, knowledge point, and question."""
    material = Material(
        id=uuid.uuid4(),
        user_id=user_id,
        title=title,
        file_format="pdf",
        file_size=1024,
        folder_id=folder_id,
        is_deleted=is_deleted,
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
        level=1,
        batch_id=f"kp_{batch_id}",
    )
    question = Question(
        id=uuid.uuid4(),
        user_id=user_id,
        material_id=material.id,
        version_id=version.id,
        knowledge_point_id=kp.id,
        question_type=QuestionType.SINGLE_CHOICE.value,
        status=QuestionStatus.AVAILABLE.value,
        is_deleted=False,
        batch_id=batch_id,
        stem=f"{kp_name}练习题",
        options=[{"key": "A", "content": "选项A"}, {"key": "B", "content": "选项B"}],
        answer="A",
        analysis="解析内容",
        difficulty=2,
    )
    session.add_all([material, version, kp, question])
    session.flush()
    return _MaterialGraph(material=material, kp_id=kp.id, question=question)


def _seed_mastery_and_wrong(
    diag_repo: DiagnosisRepository,
    *,
    user_id: uuid.UUID,
    graph: _MaterialGraph,
    score: float,
    level: str,
    practice_id: uuid.UUID,
) -> None:
    """Seed a mastery record and an unmastered wrong record for a material graph."""
    diag_repo.upsert_mastery_record(
        user_id=user_id,
        knowledge_point_id=graph.kp_id,
        mastery_score=score,
        level=level,
        practice_count=3,
        correct_count=1 if score < 0.5 else 3,
        last_practiced_at=None,
        decayed_at=None,
        recent_records_snapshot=[],
    )
    diag_repo.upsert_wrong_record(
        user_id=user_id,
        question_id=graph.question.id,
        knowledge_point_id=graph.kp_id,
        practice_id=practice_id,
        attempt_item_id=None,
        error_type=ErrorType.CONCEPTUAL.value,
        question_snapshot={
            "question_type": QuestionType.SINGLE_CHOICE.value,
            "stem": graph.question.stem,
            "options": graph.question.options,
            "answer": graph.question.answer,
            "analysis": graph.question.analysis,
            "difficulty": 2,
        },
        last_wrong_answer="B",
    )


@pytest.fixture
def visibility_fixture(session: Session) -> _VisibilityFixture:
    """Seed active and soft-deleted materials in both classified and unclassified scopes."""
    user = User(id=uuid.uuid4(), openid=f"openid_{uuid.uuid4().hex}")
    folder = MaterialFolder(id=uuid.uuid4(), user_id=user.id, name="机器学习", sort_order=0)
    session.add_all([user, folder])
    session.flush()

    active_in_folder = _seed_material_graph(
        session,
        user_id=user.id,
        title="活跃课程讲义.pdf",
        folder_id=folder.id,
        kp_name="活跃课程考点",
        batch_id="batch_active_folder",
        is_deleted=False,
    )
    deleted_in_folder = _seed_material_graph(
        session,
        user_id=user.id,
        title="已删课程讲义.pdf",
        folder_id=folder.id,
        kp_name="已删课程考点",
        batch_id="batch_deleted_folder",
        is_deleted=True,
    )
    active_unclassified = _seed_material_graph(
        session,
        user_id=user.id,
        title="活跃未分类讲义.pdf",
        folder_id=None,
        kp_name="活跃未分类考点",
        batch_id="batch_active_unclassified",
        is_deleted=False,
    )
    deleted_unclassified = _seed_material_graph(
        session,
        user_id=user.id,
        title="已删未分类讲义.pdf",
        folder_id=None,
        kp_name="已删未分类考点",
        batch_id="batch_deleted_unclassified",
        is_deleted=True,
    )

    # Cross-material batch: spans active_in_folder and deleted_in_folder
    cross_deleted_q = Question(
        id=uuid.uuid4(),
        user_id=user.id,
        material_id=deleted_in_folder.material.id,
        version_id=deleted_in_folder.question.version_id,
        knowledge_point_id=deleted_in_folder.kp_id,
        question_type=QuestionType.SINGLE_CHOICE.value,
        status=QuestionStatus.AVAILABLE.value,
        is_deleted=False,
        batch_id="batch_active_folder",
        stem="跨资料批次中属于已删资料的题",
        options=[{"key": "A", "content": "选项A"}],
        answer="A",
    )
    session.add(cross_deleted_q)

    # Historical completed practice & report on the soft-deleted material
    practice = Practice(
        id=uuid.uuid4(),
        user_id=user.id,
        material_id=deleted_in_folder.material.id,
        title="历史机器学习练习",
        status=PracticeStatus.COMPLETED.value,
        question_count=1,
    )
    attempt_item = AttemptItem(
        id=uuid.uuid4(),
        practice_id=practice.id,
        user_id=user.id,
        question_id=deleted_in_folder.question.id,
        order_index=1,
        question_snapshot={"stem": deleted_in_folder.question.stem, "answer": "A"},
        user_answer="B",
        is_answered=True,
    )
    report = DiagnosisReport(
        id=uuid.uuid4(),
        practice_id=practice.id,
        user_id=user.id,
        weak_knowledge_points=[{"id": str(deleted_in_folder.kp_id), "name": "已删课程考点"}],
        regressed_knowledge_points=[],
        analysis_causes=[{"cause": "概念混淆"}],
        actionable_suggestions=[{"suggestion": "复盘"}],
        unanswered_count=0,
        wrong_count=1,
        pending_regrade_count=0,
        total_questions=1,
        score_rate=0.0,
        is_structure_degraded=False,
    )
    session.add_all([practice, attempt_item, report])
    session.flush()

    diag_repo = DiagnosisRepository(session)
    _seed_mastery_and_wrong(
        diag_repo,
        user_id=user.id,
        graph=active_in_folder,
        score=0.25,
        level=MasteryLevel.WEAK.value,
        practice_id=practice.id,
    )
    _seed_mastery_and_wrong(
        diag_repo,
        user_id=user.id,
        graph=deleted_in_folder,
        score=0.10,
        level=MasteryLevel.WEAK.value,
        practice_id=practice.id,
    )
    _seed_mastery_and_wrong(
        diag_repo,
        user_id=user.id,
        graph=active_unclassified,
        score=0.80,
        level=MasteryLevel.PROFICIENT.value,
        practice_id=practice.id,
    )
    _seed_mastery_and_wrong(
        diag_repo,
        user_id=user.id,
        graph=deleted_unclassified,
        score=0.15,
        level=MasteryLevel.WEAK.value,
        practice_id=practice.id,
    )

    col_repo = CollectionRepository(session)
    collection = col_repo.create_collection(user_id=user.id, name="考前冲刺题单")
    col_repo.add_items(
        user_id=user.id,
        collection_id=collection.id,
        question_ids=[
            active_in_folder.question.id,
            deleted_in_folder.question.id,
            active_unclassified.question.id,
            deleted_unclassified.question.id,
        ],
    )
    session.commit()

    return _VisibilityFixture(
        user_id=user.id,
        folder_id=folder.id,
        active_in_folder=active_in_folder,
        deleted_in_folder=deleted_in_folder,
        active_unclassified=active_unclassified,
        deleted_unclassified=deleted_unclassified,
        collection_id=collection.id,
        deleted_practice_id=practice.id,
    )


class TestDeletedMaterialVisibility:
    """End-to-end repository and service visibility checks after material soft-delete."""

    def test_mastery_and_weak_kps_exclude_deleted_materials(
        self, session: Session, visibility_fixture: _VisibilityFixture
    ) -> None:
        fx = visibility_fixture
        diag_repo = DiagnosisRepository(session)
        kp_repo = KnowledgeRepository(session)
        diag_service = DiagnosisService(session)

        active_kp_ids = {fx.active_in_folder.kp_id, fx.active_unclassified.kp_id}
        deleted_kp_ids = {fx.deleted_in_folder.kp_id, fx.deleted_unclassified.kp_id}

        # DiagnosisRepository mastery queries
        user_records = diag_repo.list_mastery_records_by_user(fx.user_id)
        assert {r.knowledge_point_id for r in user_records} == active_kp_ids
        assert (
            diag_repo.list_mastery_records_by_material(fx.deleted_in_folder.material.id, fx.user_id)
            == []
        )
        assert (
            len(
                diag_repo.list_mastery_records_by_material(
                    fx.active_in_folder.material.id, fx.user_id
                )
            )
            == 1
        )
        assert diag_repo.list_weak_knowledge_point_ids(fx.user_id, threshold=0.40) == {
            fx.active_in_folder.kp_id
        }

        # KnowledgeRepository queries
        assert {kp.id for kp in kp_repo.list_all_by_user_id(fx.user_id)} == active_kp_ids
        assert kp_repo.list_by_material_id(fx.deleted_in_folder.material.id, fx.user_id) == []
        assert {
            kp.id for kp in kp_repo.list_by_folder_scope(fx.user_id, folder_id=fx.folder_id)
        } == {fx.active_in_folder.kp_id}
        assert {kp.id for kp in kp_repo.list_by_folder_scope(fx.user_id, unclassified=True)} == {
            fx.active_unclassified.kp_id
        }

        # DiagnosisService mastery overview across All / Folder / Unclassified / Material
        overview_all = diag_service.get_user_mastery_overview(fx.user_id, None)
        assert overview_all.total_knowledge_points == 2
        assert overview_all.weak_count == 1
        assert overview_all.proficient_count == 1
        assert {w.knowledge_point_id for w in overview_all.weak_knowledge_points} == {
            fx.active_in_folder.kp_id
        }
        assert all(
            w.knowledge_point_id not in deleted_kp_ids for w in overview_all.weak_knowledge_points
        )

        overview_folder = diag_service.get_user_mastery_overview(
            fx.user_id, None, folder_id=fx.folder_id
        )
        assert overview_folder.total_knowledge_points == 1
        assert overview_folder.weak_count == 1

        overview_unclassified = diag_service.get_user_mastery_overview(
            fx.user_id, None, unclassified=True
        )
        assert overview_unclassified.total_knowledge_points == 1
        assert overview_unclassified.proficient_count == 1

        overview_deleted_mat = diag_service.get_user_mastery_overview(
            fx.user_id, fx.deleted_in_folder.material.id
        )
        assert overview_deleted_mat.total_knowledge_points == 0

    def test_wrong_book_queries_exclude_deleted_materials_in_all_scopes(
        self, session: Session, visibility_fixture: _VisibilityFixture
    ) -> None:
        fx = visibility_fixture
        diag_repo = DiagnosisRepository(session)

        # All scope
        all_records = diag_repo.list_wrong_records(fx.user_id)
        assert {r.knowledge_point_id for r in all_records} == {
            fx.active_in_folder.kp_id,
            fx.active_unclassified.kp_id,
        }
        assert diag_repo.count_wrong_records(fx.user_id) == 2

        # Folder scope
        folder_records = diag_repo.list_wrong_records(fx.user_id, folder_id=fx.folder_id)
        assert [r.knowledge_point_id for r in folder_records] == [fx.active_in_folder.kp_id]
        assert diag_repo.count_wrong_records(fx.user_id, folder_id=fx.folder_id) == 1

        # Unclassified scope
        unclassified_records = diag_repo.list_wrong_records(fx.user_id, unclassified=True)
        assert [r.knowledge_point_id for r in unclassified_records] == [
            fx.active_unclassified.kp_id
        ]
        assert diag_repo.count_wrong_records(fx.user_id, unclassified=True) == 1

        # Explicit deleted material_id
        assert (
            diag_repo.list_wrong_records(fx.user_id, material_id=fx.deleted_in_folder.material.id)
            == []
        )
        assert (
            diag_repo.count_wrong_records(fx.user_id, material_id=fx.deleted_in_folder.material.id)
            == 0
        )

        # Groups across All / Folder / Unclassified
        groups_all = diag_repo.list_wrong_record_groups(fx.user_id)
        assert {g[2] for g in groups_all} == {
            fx.active_in_folder.material.id,
            fx.active_unclassified.material.id,
        }
        groups_folder = diag_repo.list_wrong_record_groups(fx.user_id, folder_id=fx.folder_id)
        assert [g[2] for g in groups_folder] == [fx.active_in_folder.material.id]
        groups_unclassified = diag_repo.list_wrong_record_groups(fx.user_id, unclassified=True)
        assert [g[2] for g in groups_unclassified] == [fx.active_unclassified.material.id]

        # Unmastered wrong question ids for smart practice prioritization
        assert diag_repo.list_unmastered_wrong_question_ids(fx.user_id) == {
            fx.active_in_folder.question.id,
            fx.active_unclassified.question.id,
        }

    def test_question_bank_queries_exclude_deleted_materials_in_all_scopes(
        self, session: Session, visibility_fixture: _VisibilityFixture
    ) -> None:
        fx = visibility_fixture
        q_repo = QuestionRepository(session)

        # list_questions + total under All / Folder / Unclassified
        qs_all, total_all = q_repo.list_questions(fx.user_id)
        assert total_all == 2
        assert {q.id for q in qs_all} == {
            fx.active_in_folder.question.id,
            fx.active_unclassified.question.id,
        }

        qs_folder, total_folder = q_repo.list_questions(fx.user_id, folder_id=fx.folder_id)
        assert total_folder == 1
        assert [q.id for q in qs_folder] == [fx.active_in_folder.question.id]

        qs_unclassified, total_unclassified = q_repo.list_questions(fx.user_id, unclassified=True)
        assert total_unclassified == 1
        assert [q.id for q in qs_unclassified] == [fx.active_unclassified.question.id]

        # Batches & counts under All / Folder / Unclassified
        batches_all = q_repo.list_question_batches(fx.user_id)
        assert {b[0]: b[1] for b in batches_all} == {
            "batch_active_folder": 1,
            "batch_active_unclassified": 1,
        }
        assert q_repo.count_question_batches(fx.user_id) == 2

        batches_folder = q_repo.list_question_batches(fx.user_id, folder_id=fx.folder_id)
        assert [(b[0], b[1]) for b in batches_folder] == [("batch_active_folder", 1)]
        assert q_repo.count_question_batches(fx.user_id, folder_id=fx.folder_id) == 1

        batches_unclassified = q_repo.list_question_batches(fx.user_id, unclassified=True)
        assert [(b[0], b[1]) for b in batches_unclassified] == [("batch_active_unclassified", 1)]
        assert q_repo.count_question_batches(fx.user_id, unclassified=True) == 1

        # Cross-material batch sources must NOT leak the deleted material
        sources = q_repo.list_batch_sources(
            fx.user_id, ["batch_active_folder", "batch_deleted_folder"]
        )
        assert [(s[0], s[1]) for s in sources] == [
            ("batch_active_folder", fx.active_in_folder.material.id)
        ]

        # Grouped question counts under All / Folder / Unclassified
        grouped_all = q_repo.list_grouped_question_counts(fx.user_id)
        assert {(m_id, kp_id, cnt) for m_id, kp_id, cnt in grouped_all} == {
            (fx.active_in_folder.material.id, fx.active_in_folder.kp_id, 1),
            (fx.active_unclassified.material.id, fx.active_unclassified.kp_id, 1),
        }
        grouped_folder = q_repo.list_grouped_question_counts(fx.user_id, folder_id=fx.folder_id)
        assert grouped_folder == [(fx.active_in_folder.material.id, fx.active_in_folder.kp_id, 1)]
        grouped_unclassified = q_repo.list_grouped_question_counts(fx.user_id, unclassified=True)
        assert grouped_unclassified == [
            (fx.active_unclassified.material.id, fx.active_unclassified.kp_id, 1)
        ]

    def test_collection_queries_exclude_deleted_materials(
        self, session: Session, visibility_fixture: _VisibilityFixture
    ) -> None:
        fx = visibility_fixture
        col_repo = CollectionRepository(session)

        counts = col_repo.count_active_questions_by_collection_ids(fx.user_id, [fx.collection_id])
        assert counts == {fx.collection_id: 2}

        rows, total = col_repo.list_collection_questions(fx.user_id, fx.collection_id)
        assert total == 2
        assert {row[1].id for row in rows} == {
            fx.active_in_folder.question.id,
            fx.active_unclassified.question.id,
        }

        active_ids = col_repo.list_active_question_ids(fx.collection_id, fx.user_id)
        assert set(active_ids) == {
            fx.active_in_folder.question.id,
            fx.active_unclassified.question.id,
        }

        valid_ids = col_repo.list_valid_user_question_ids(
            fx.user_id,
            [
                fx.active_in_folder.question.id,
                fx.deleted_in_folder.question.id,
                fx.active_unclassified.question.id,
                fx.deleted_unclassified.question.id,
            ],
        )
        assert valid_ids == {
            fx.active_in_folder.question.id,
            fx.active_unclassified.question.id,
        }

    def test_historical_practice_and_reports_remain_readable(
        self, session: Session, visibility_fixture: _VisibilityFixture
    ) -> None:
        fx = visibility_fixture
        practice_repo = PracticeRepository(session)
        diag_repo = DiagnosisRepository(session)
        q_repo = QuestionRepository(session)

        # Practice records & attempt items stay readable
        practices = practice_repo.list_practices(fx.user_id)
        assert [p.id for p in practices] == [fx.deleted_practice_id]
        practice = practice_repo.get_practice_by_id(fx.deleted_practice_id, fx.user_id)
        assert practice is not None
        attempt_items = practice_repo.list_attempt_items(fx.deleted_practice_id, fx.user_id)
        assert len(attempt_items) == 1
        assert attempt_items[0].question_id == fx.deleted_in_folder.question.id

        # Historical diagnosis report stays readable
        report = diag_repo.get_diagnosis_report_by_practice_id(fx.deleted_practice_id, fx.user_id)
        assert report is not None
        assert len(diag_repo.list_diagnosis_reports_by_user(fx.user_id)) == 1

        # Question lookup by id(s) stays readable for historical practice report rendering
        q_single = q_repo.get_question_by_id(fx.deleted_in_folder.question.id, fx.user_id)
        assert q_single is not None
        assert q_single.id == fx.deleted_in_folder.question.id
        q_batch = q_repo.list_questions_by_ids(
            [fx.deleted_in_folder.question.id, fx.deleted_unclassified.question.id],
            fx.user_id,
        )
        assert {q.id for q in q_batch} == {
            fx.deleted_in_folder.question.id,
            fx.deleted_unclassified.question.id,
        }
