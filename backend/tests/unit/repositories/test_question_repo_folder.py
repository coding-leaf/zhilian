"""Unit tests for course-folder scoped queries on QuestionRepository.

Verifies:
1. ``list_questions(folder_id=...)`` filters by ``materials.folder_id`` and excludes
   archived courses, including combined material_id + folder_id filters.
2. ``list_knowledge_points_for_folder`` returns only knowledge points of ready,
   non-deleted, non-archived course materials.
3. ``list_material_ids_for_folder`` honors the ``ready_only`` switch.
4. Strict multi-tenant isolation.
"""

import uuid
from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.base import Base
from app.models.knowledge import KnowledgePoint
from app.models.material import Material, MaterialStatus
from app.models.question import Question, QuestionStatus
from app.repositories.folder import FolderRepository
from app.repositories.question import QuestionRepository


@pytest.fixture
def session() -> Generator[Session, None, None]:
    """Provides an isolated in-memory SQLite database session."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as sess:
        yield sess
    engine.dispose()


def _seed_material(
    session: Session,
    user_id: uuid.UUID,
    *,
    folder_id: uuid.UUID | None,
    status: str = MaterialStatus.READY.value,
    title: str = "资料.pdf",
) -> tuple[Material, uuid.UUID, KnowledgePoint]:
    """Persists a material, version id, knowledge point, and one question."""
    material = Material(
        user_id=user_id,
        title=title,
        file_format="pdf",
        file_size=10,
        status=status,
        folder_id=folder_id,
    )
    session.add(material)
    session.flush()

    version_id = uuid.uuid4()
    point = KnowledgePoint(
        user_id=user_id,
        material_id=material.id,
        version_id=version_id,
        name="知识点",
        batch_id="batch-seed",
    )
    session.add(point)
    session.flush()

    question = Question(
        user_id=user_id,
        material_id=material.id,
        version_id=version_id,
        knowledge_point_id=point.id,
        question_type="single_choice",
        status=QuestionStatus.AVAILABLE.value,
        stem="题干内容？",
        answer="A",
    )
    session.add(question)
    session.commit()
    return material, version_id, point


class TestQuestionRepositoryFolderFilter:
    """Test suite for folder-scoped question listing."""

    def test_list_questions_by_folder_only(self, session: Session) -> None:
        """Verify folder filter returns only questions belonging to that course."""
        user_id = uuid.uuid4()
        folder = FolderRepository(session).create(user_id=user_id, name="计算机网络")
        session.commit()

        in_folder, _, _ = _seed_material(session, user_id, folder_id=folder.id)
        outside, _, _ = _seed_material(session, user_id, folder_id=None)

        repo = QuestionRepository(session)
        items, total = repo.list_questions(user_id, folder_id=folder.id)
        assert total == 1
        assert [q.material_id for q in items] == [in_folder.id]

        all_items, all_total = repo.list_questions(user_id)
        assert all_total == 2
        assert {q.material_id for q in all_items} == {in_folder.id, outside.id}

    def test_list_questions_combined_material_and_folder(self, session: Session) -> None:
        """Verify combined material_id + folder_id filters intersect correctly."""
        user_id = uuid.uuid4()
        folder = FolderRepository(session).create(user_id=user_id, name="操作系统")
        session.commit()

        first, _, _ = _seed_material(session, user_id, folder_id=folder.id, title="a.pdf")
        _seed_material(session, user_id, folder_id=folder.id, title="b.pdf")

        repo = QuestionRepository(session)
        items, total = repo.list_questions(user_id, material_id=first.id, folder_id=folder.id)
        assert total == 1
        assert items[0].material_id == first.id

    def test_archived_folder_questions_excluded(self, session: Session) -> None:
        """Verify archived-course questions never surface via folder filter."""
        user_id = uuid.uuid4()
        repo_folders = FolderRepository(session)
        folder = repo_folders.create(user_id=user_id, name="已归档课程")
        session.commit()
        _seed_material(session, user_id, folder_id=folder.id)
        repo_folders.archive(folder.id, user_id, datetime.now(UTC))
        session.commit()

        repo = QuestionRepository(session)
        items, total = repo.list_questions(user_id, folder_id=folder.id)
        assert total == 0
        assert items == []
        assert repo.list_knowledge_points_for_folder(user_id, folder.id) == []

    def test_cross_tenant_folder_isolation(self, session: Session) -> None:
        """Verify User B cannot list User A's folder questions."""
        user_a = uuid.uuid4()
        user_b = uuid.uuid4()
        folder = FolderRepository(session).create(user_id=user_a, name="A课程")
        session.commit()
        _seed_material(session, user_a, folder_id=folder.id)

        repo = QuestionRepository(session)
        _, total = repo.list_questions(user_b, folder_id=folder.id)
        assert total == 0


class TestListKnowledgePointsForFolder:
    """Test suite for default-scope knowledge point resolution."""

    def test_returns_only_ready_material_points(self, session: Session) -> None:
        """Verify pending (non-ready) materials are excluded from the default scope."""
        user_id = uuid.uuid4()
        folder = FolderRepository(session).create(user_id=user_id, name="线性代数")
        session.commit()

        ready_material, _, ready_point = _seed_material(
            session, user_id, folder_id=folder.id, status=MaterialStatus.READY.value
        )
        _seed_material(session, user_id, folder_id=folder.id, status=MaterialStatus.PENDING.value)

        repo = QuestionRepository(session)
        points = repo.list_knowledge_points_for_folder(user_id, folder.id)
        assert [p.id for p in points] == [ready_point.id]
        assert points[0].material_id == ready_material.id

    def test_excludes_archived_folder_points(self, session: Session) -> None:
        """Verify archived folder materials do not contribute knowledge points."""
        user_id = uuid.uuid4()
        repo_folders = FolderRepository(session)
        folder = repo_folders.create(user_id=user_id, name="归档课程")
        session.commit()
        _seed_material(session, user_id, folder_id=folder.id)

        repo_folders.archive(folder.id, user_id, datetime.now(UTC))
        session.commit()

        repo = QuestionRepository(session)
        assert repo.list_knowledge_points_for_folder(user_id, folder.id) == []

    def test_material_ids_ready_only_switch(self, session: Session) -> None:
        """Verify list_material_ids_for_folder honors ready_only."""
        user_id = uuid.uuid4()
        folder = FolderRepository(session).create(user_id=user_id, name="概率论")
        session.commit()

        ready_material, _, _ = _seed_material(
            session, user_id, folder_id=folder.id, status=MaterialStatus.READY.value
        )
        pending_material, _, _ = _seed_material(
            session, user_id, folder_id=folder.id, status=MaterialStatus.PENDING.value
        )

        repo = QuestionRepository(session)
        all_ids = set(repo.list_material_ids_for_folder(user_id, folder.id))
        ready_ids = set(repo.list_material_ids_for_folder(user_id, folder.id, ready_only=True))
        assert all_ids == {ready_material.id, pending_material.id}
        assert ready_ids == {ready_material.id}

    def test_deleted_folder_row_returns_empty(self, session: Session) -> None:
        """Verify a hard-deleted folder yields no knowledge points."""
        user_id = uuid.uuid4()
        repo_folders = FolderRepository(session)
        folder = repo_folders.create(user_id=user_id, name="已删除课程")
        session.commit()
        repo_folders.hard_delete(folder.id, user_id)
        session.commit()

        repo = QuestionRepository(session)
        assert repo.list_knowledge_points_for_folder(user_id, folder.id) == []
