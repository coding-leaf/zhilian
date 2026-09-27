"""Unit tests for FolderRepository in app/repositories/folder.py.

Verifies folder CRUD, archive/restore, expired listing, name uniqueness checks,
aggregate count queries, and strict multi-tenant isolation.
"""

import uuid
from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.base import Base
from app.models.knowledge import KnowledgePoint
from app.models.material import Material, MaterialStatus
from app.models.practice import Practice
from app.models.question import Question
from app.repositories.folder import FolderRepository


@pytest.fixture
def session() -> Generator[Session, None, None]:
    """Provides an isolated in-memory SQLite database session."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as sess:
        yield sess
    engine.dispose()


class TestFolderRepositoryCRUD:
    """Test suite for FolderRepository CRUD and lifecycle."""

    def test_create_get_list(self, session: Session) -> None:
        """Verify creating, fetching, and listing folders."""
        repo = FolderRepository(session)
        user_id = uuid.uuid4()

        folder = repo.create(user_id=user_id, name="计算机网络")
        session.commit()
        assert folder.id is not None
        assert folder.archived_at is None

        fetched = repo.get_by_id(folder.id, user_id)
        assert fetched is not None
        assert fetched.name == "计算机网络"

        items, total = repo.list_by_user(user_id)
        assert total == 1
        assert items[0].id == folder.id

    def test_name_exists_and_exclude(self, session: Session) -> None:
        """Verify name_exists honors exclude_id for rename self-check."""
        repo = FolderRepository(session)
        user_id = uuid.uuid4()

        folder = repo.create(user_id=user_id, name="操作系统")
        session.commit()

        assert repo.name_exists(user_id, "操作系统") is True
        assert repo.name_exists(user_id, "操作系统", exclude_id=folder.id) is False
        assert repo.name_exists(user_id, "不存在") is False

    def test_update_name(self, session: Session) -> None:
        """Verify renaming a folder."""
        repo = FolderRepository(session)
        user_id = uuid.uuid4()

        folder = repo.create(user_id=user_id, name="旧名")
        session.commit()

        updated = repo.update_name(folder.id, user_id, "新名")
        session.commit()
        assert updated is not None
        assert updated.name == "新名"

    def test_archive_restore_and_listing_visibility(self, session: Session) -> None:
        """Verify archived folders hidden by default and restored afterwards."""
        repo = FolderRepository(session)
        user_id = uuid.uuid4()

        folder = repo.create(user_id=user_id, name="归档课程")
        session.commit()

        repo.archive(folder.id, user_id, datetime.now(UTC))
        session.commit()

        assert repo.get_by_id(folder.id, user_id) is None
        assert repo.get_by_id(folder.id, user_id, include_archived=True) is not None

        items, total = repo.list_by_user(user_id)
        assert total == 0
        assert items == []
        all_items, all_total = repo.list_by_user(user_id, include_archived=True)
        assert all_total == 1
        assert all_items[0].id == folder.id

        repo.restore(folder.id, user_id)
        session.commit()
        assert repo.get_by_id(folder.id, user_id) is not None

    def test_list_expired(self, session: Session) -> None:
        """Verify list_expired returns only folders archived before the threshold."""
        repo = FolderRepository(session)
        user_id = uuid.uuid4()

        old = repo.create(user_id=user_id, name="逾期课程")
        fresh = repo.create(user_id=user_id, name="新归档课程")
        active = repo.create(user_id=user_id, name="活跃课程")
        session.commit()

        repo.archive(old.id, user_id, datetime.now(UTC) - timedelta(days=8))
        repo.archive(fresh.id, user_id, datetime.now(UTC) - timedelta(days=1))
        session.commit()

        expired = repo.list_expired(user_id, before=datetime.now(UTC) - timedelta(days=7))
        assert [f.id for f in expired] == [old.id]
        assert active.id not in [f.id for f in expired]

    def test_hard_delete(self, session: Session) -> None:
        """Verify physical deletion of a folder row."""
        repo = FolderRepository(session)
        user_id = uuid.uuid4()

        folder = repo.create(user_id=user_id, name="待清理")
        session.commit()

        assert repo.hard_delete(folder.id, user_id) is True
        session.commit()
        assert repo.get_by_id(folder.id, user_id, include_archived=True) is None

    def test_cross_tenant_isolation(self, session: Session) -> None:
        """Verify User B cannot see or mutate User A's folders."""
        repo = FolderRepository(session)
        user_a = uuid.uuid4()
        user_b = uuid.uuid4()

        folder = repo.create(user_id=user_a, name="A私有课程")
        session.commit()

        assert repo.get_by_id(folder.id, user_b) is None
        assert repo.update_name(folder.id, user_b, "篡改") is None
        assert repo.archive(folder.id, user_b, datetime.now(UTC)) is None
        assert repo.restore(folder.id, user_b) is None
        assert repo.hard_delete(folder.id, user_b) is False
        assert repo.name_exists(user_b, "A私有课程") is False
        items, total = repo.list_by_user(user_b)
        assert total == 0
        assert items == []


class TestFolderRepositoryCounts:
    """Test suite for per-folder aggregate count queries."""

    def _seed(self, session: Session, user_id: uuid.UUID, folder_id: uuid.UUID) -> None:
        material_ready = Material(
            user_id=user_id,
            title="ready.pdf",
            file_format="pdf",
            file_size=10,
            status=MaterialStatus.READY.value,
            folder_id=folder_id,
        )
        material_pending = Material(
            user_id=user_id,
            title="pending.pdf",
            file_format="pdf",
            file_size=10,
            status=MaterialStatus.PENDING.value,
            folder_id=folder_id,
        )
        session.add_all([material_ready, material_pending])
        session.commit()

        version_id = uuid.uuid4()
        knowledge = KnowledgePoint(
            user_id=user_id,
            material_id=material_ready.id,
            version_id=version_id,
            name="极限定义",
            batch_id="batch-1",
        )
        session.add(knowledge)
        session.commit()

        question = Question(
            user_id=user_id,
            material_id=material_ready.id,
            version_id=version_id,
            knowledge_point_id=knowledge.id,
            question_type="single_choice",
            stem="题干",
            answer="A",
        )
        practice = Practice(
            user_id=user_id,
            material_id=material_ready.id,
            title="练习一",
        )
        session.add_all([question, practice])
        session.commit()

    def test_count_queries(self, session: Session) -> None:
        """Verify material/ready/knowledge/question/last_practice aggregates."""
        repo = FolderRepository(session)
        user_id = uuid.uuid4()

        folder = repo.create(user_id=user_id, name="统计课程")
        other = repo.create(user_id=user_id, name="空课程")
        session.commit()

        self._seed(session, user_id, folder.id)

        assert repo.count_materials_by_folder_ids([folder.id, other.id], user_id) == {folder.id: 2}
        assert repo.count_ready_materials_by_folder_ids([folder.id], user_id) == {folder.id: 1}
        assert repo.count_knowledge_points_by_folder_ids([folder.id], user_id) == {folder.id: 1}
        assert repo.count_questions_by_folder_ids([folder.id], user_id) == {folder.id: 1}
        last = repo.last_practice_at_by_folder_ids([folder.id], user_id)
        assert folder.id in last
        assert last[folder.id] is not None

    def test_count_queries_empty_ids(self, session: Session) -> None:
        """Verify empty folder id collections short-circuit to empty mappings."""
        repo = FolderRepository(session)
        user_id = uuid.uuid4()
        assert repo.count_materials_by_folder_ids([], user_id) == {}
        assert repo.count_ready_materials_by_folder_ids([], user_id) == {}
        assert repo.count_knowledge_points_by_folder_ids([], user_id) == {}
        assert repo.count_questions_by_folder_ids([], user_id) == {}
        assert repo.last_practice_at_by_folder_ids([], user_id) == {}

    def test_list_material_ids_by_folder(self, session: Session) -> None:
        """Verify listing material ids belonging to a folder."""
        repo = FolderRepository(session)
        user_id = uuid.uuid4()
        folder = repo.create(user_id=user_id, name="归属课程")
        session.commit()

        material = Material(
            user_id=user_id,
            title="归属资料.pdf",
            file_format="pdf",
            file_size=10,
            folder_id=folder.id,
        )
        session.add(material)
        session.commit()

        assert repo.list_material_ids_by_folder(folder.id, user_id) == [material.id]
        assert repo.list_material_ids_by_folder(folder.id, uuid.uuid4()) == []
