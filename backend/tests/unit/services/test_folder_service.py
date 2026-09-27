"""Unit tests for FolderService in app/services/folder.py.

Verifies name-conflict 409, cross-tenant 404, archive/restore visibility,
7-day lazy physical purge cascade, aggregate counts, and material attribution moves.
"""

import uuid
from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import (
    FolderNameConflictError,
    FolderNotFoundError,
    MaterialNotFoundError,
)
from app.integrations.embedding.fake import FakeEmbeddingAdapter
from app.integrations.ocr.fake import FakeOCRAdapter
from app.integrations.queue.memory import MemoryQueueAdapter
from app.integrations.storage.memory import MemoryStorageAdapter
from app.models.base import Base
from app.models.knowledge import KnowledgePoint
from app.models.material import Material, MaterialStatus
from app.repositories.folder import FolderRepository
from app.services.folder import FolderService
from app.services.material import MaterialService


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
def folder_service(session: Session) -> FolderService:
    """Provides a FolderService wired to a real MaterialService with fake adapters."""
    storage = MemoryStorageAdapter()
    storage.ensure_bucket_exists("zhilian-materials")
    material_service = MaterialService(
        session=session,
        storage_adapter=storage,
        ocr_adapter=FakeOCRAdapter(),
        embedding_adapter=FakeEmbeddingAdapter(),
        queue_adapter=MemoryQueueAdapter(),
    )
    return FolderService(session=session, material_service=material_service)


def _create_material(
    session: Session,
    user_id: uuid.UUID,
    *,
    folder_id: uuid.UUID | None = None,
    status: str = MaterialStatus.READY.value,
) -> Material:
    """Helper: persist a material owned by user in the given folder."""
    material = Material(
        user_id=user_id,
        title="资料.pdf",
        file_format="pdf",
        file_size=10,
        status=status,
        folder_id=folder_id,
    )
    session.add(material)
    session.commit()
    return material


class TestFolderServiceCRUD:
    """Test suite for folder create/rename/get semantics."""

    def test_create_folder_success(self, folder_service: FolderService) -> None:
        """Verify creating a folder returns zeroed aggregates."""
        user_id = uuid.uuid4()
        aggregate = folder_service.create_folder(user_id, "计算机网络")
        assert aggregate.folder.name == "计算机网络"
        assert aggregate.material_count == 0
        assert aggregate.ready_material_count == 0
        assert aggregate.purge_after is None

    def test_create_folder_name_conflict(self, folder_service: FolderService) -> None:
        """Verify duplicate folder names raise FolderNameConflictError (409)."""
        user_id = uuid.uuid4()
        folder_service.create_folder(user_id, "高等数学")
        with pytest.raises(FolderNameConflictError) as exc_info:
            folder_service.create_folder(user_id, "高等数学")
        assert exc_info.value.status_code == 409
        assert exc_info.value.error_code == 40021

    def test_same_name_across_users_allowed(self, folder_service: FolderService) -> None:
        """Verify the unique constraint is scoped per tenant."""
        folder_service.create_folder(uuid.uuid4(), "英语")
        aggregate = folder_service.create_folder(uuid.uuid4(), "英语")
        assert aggregate.folder.name == "英语"

    def test_get_folder_cross_tenant_404(self, folder_service: FolderService) -> None:
        """Verify accessing another user's folder raises FolderNotFoundError (404)."""
        owner = uuid.uuid4()
        aggregate = folder_service.create_folder(owner, "私有课程")
        with pytest.raises(FolderNotFoundError) as exc_info:
            folder_service.get_folder(uuid.uuid4(), aggregate.folder.id)
        assert exc_info.value.status_code == 404
        assert exc_info.value.error_code == 40020

    def test_rename_folder_conflict(self, folder_service: FolderService) -> None:
        """Verify renaming to an occupied name raises 409."""
        user_id = uuid.uuid4()
        first = folder_service.create_folder(user_id, "课程甲")
        folder_service.create_folder(user_id, "课程乙")
        with pytest.raises(FolderNameConflictError):
            folder_service.rename_folder(user_id, first.folder.id, "课程乙")

    def test_rename_folder_same_name_self_ok(self, folder_service: FolderService) -> None:
        """Verify renaming a folder to its own name is allowed."""
        user_id = uuid.uuid4()
        aggregate = folder_service.create_folder(user_id, "课程甲")
        renamed = folder_service.rename_folder(user_id, aggregate.folder.id, "课程甲")
        assert renamed.folder.name == "课程甲"

    def test_create_folder_reuses_archived_name(self, folder_service: FolderService) -> None:
        """Verify an archived folder's name is reusable by an active course (B1/B6)."""
        user_id = uuid.uuid4()
        first = folder_service.create_folder(user_id, "可复用课程")
        folder_service.archive_folder(user_id, first.folder.id)

        reused = folder_service.create_folder(user_id, "可复用课程")
        assert reused.folder.name == "可复用课程"
        assert reused.folder.id != first.folder.id
        assert reused.folder.archived_at is None


class TestFolderServiceArchive:
    """Test suite for archive/restore and lazy purge."""

    def test_archive_hides_and_sets_purge_after(self, folder_service: FolderService) -> None:
        """Verify archived folders vanish from list and expose purge_after."""
        user_id = uuid.uuid4()
        aggregate = folder_service.create_folder(user_id, "可归档课程")

        archived = folder_service.archive_folder(user_id, aggregate.folder.id)
        assert archived.folder.archived_at is not None
        assert archived.purge_after == archived.folder.archived_at + timedelta(days=7)

        items, total = folder_service.list_folders(user_id)
        assert total == 0
        assert items == []

        all_items, all_total = folder_service.list_folders(user_id, include_archived=True)
        assert all_total == 1
        assert all_items[0].folder.id == aggregate.folder.id

    def test_restore_visible_again(self, folder_service: FolderService) -> None:
        """Verify restoring clears archived_at and re-exposes the folder."""
        user_id = uuid.uuid4()
        aggregate = folder_service.create_folder(user_id, "恢复课程")
        folder_service.archive_folder(user_id, aggregate.folder.id)

        restored = folder_service.restore_folder(user_id, aggregate.folder.id)
        assert restored.folder.archived_at is None
        items, total = folder_service.list_folders(user_id)
        assert total == 1
        assert items[0].folder.id == aggregate.folder.id

    def test_restore_conflicts_with_active_same_name(self, folder_service: FolderService) -> None:
        """Verify restoring an archived folder whose name is now active raises 409."""
        user_id = uuid.uuid4()
        first = folder_service.create_folder(user_id, "同名课程")
        folder_service.archive_folder(user_id, first.folder.id)
        folder_service.create_folder(user_id, "同名课程")

        with pytest.raises(FolderNameConflictError) as exc_info:
            folder_service.restore_folder(user_id, first.folder.id)
        assert exc_info.value.error_code == 40021

    def test_lazy_purge_physically_deletes_folder_and_materials(
        self, session: Session, folder_service: FolderService
    ) -> None:
        """Verify listing triggers physical cascade when archived_at older than 7 days."""
        user_id = uuid.uuid4()
        aggregate = folder_service.create_folder(user_id, "逾期课程")
        folder_id = aggregate.folder.id
        material = _create_material(session, user_id, folder_id=folder_id)

        repo = FolderRepository(session)
        repo.archive(folder_id, user_id, datetime.now(UTC) - timedelta(days=8))
        session.commit()

        # Any list query triggers lazy purge
        items, total = folder_service.list_folders(user_id)
        assert total == 0
        assert items == []

        assert repo.get_by_id(folder_id, user_id, include_archived=True) is None
        assert session.scalar(select(Material).where(Material.id == material.id)) is None

    def test_purge_folder_immediate(self, session: Session, folder_service: FolderService) -> None:
        """Verify explicit purge removes folder and its materials immediately."""
        user_id = uuid.uuid4()
        aggregate = folder_service.create_folder(user_id, "立即清理")
        material = _create_material(session, user_id, folder_id=aggregate.folder.id)

        folder_service.purge_folder(user_id, aggregate.folder.id)

        assert (
            FolderRepository(session).get_by_id(aggregate.folder.id, user_id, include_archived=True)
            is None
        )
        assert session.scalar(select(Material).where(Material.id == material.id)) is None

    def test_purge_other_user_folder_404(self, folder_service: FolderService) -> None:
        """Verify purging another user's folder raises 404."""
        owner = uuid.uuid4()
        aggregate = folder_service.create_folder(owner, "他人课程")
        with pytest.raises(FolderNotFoundError):
            folder_service.purge_folder(uuid.uuid4(), aggregate.folder.id)


class TestFolderServiceAggregates:
    """Test suite for per-folder aggregate assembly."""

    def test_aggregate_counts(self, session: Session, folder_service: FolderService) -> None:
        """Verify material/ready/knowledge/question aggregates surface in detail."""
        user_id = uuid.uuid4()
        aggregate = folder_service.create_folder(user_id, "统计课程")
        folder_id = aggregate.folder.id

        ready_material = _create_material(session, user_id, folder_id=folder_id)
        _create_material(session, user_id, folder_id=folder_id, status=MaterialStatus.PENDING.value)

        knowledge = KnowledgePoint(
            user_id=user_id,
            material_id=ready_material.id,
            version_id=uuid.uuid4(),
            name="导数",
            batch_id="batch-agg",
        )
        session.add(knowledge)
        session.commit()

        detail = folder_service.get_folder(user_id, folder_id)
        assert detail.material_count == 2
        assert detail.ready_material_count == 1
        assert detail.knowledge_point_count == 1
        assert detail.question_count == 0

    def test_list_aggregates_do_not_leak_across_folders(
        self, session: Session, folder_service: FolderService
    ) -> None:
        """Verify each folder reports only its own counts."""
        user_id = uuid.uuid4()
        first = folder_service.create_folder(user_id, "课程一")
        second = folder_service.create_folder(user_id, "课程二")
        _create_material(session, user_id, folder_id=first.folder.id)

        items, _ = folder_service.list_folders(user_id)
        by_id = {item.folder.id: item for item in items}
        assert by_id[first.folder.id].material_count == 1
        assert by_id[second.folder.id].material_count == 0


class TestFolderServiceMoveMaterial:
    """Test suite for material attribution moves."""

    def test_move_unclassified_to_folder_and_back(
        self, session: Session, folder_service: FolderService
    ) -> None:
        """Verify moving between unclassified and a folder."""
        user_id = uuid.uuid4()
        aggregate = folder_service.create_folder(user_id, "目标课程")
        material = _create_material(session, user_id, folder_id=None)

        moved = folder_service.move_material(user_id, material.id, aggregate.folder.id)
        assert moved.folder_id == aggregate.folder.id

        back = folder_service.move_material(user_id, material.id, None)
        assert back.folder_id is None

    def test_move_to_missing_folder_404(
        self, session: Session, folder_service: FolderService
    ) -> None:
        """Verify moving to a non-existent folder raises 404."""
        user_id = uuid.uuid4()
        material = _create_material(session, user_id)
        with pytest.raises(FolderNotFoundError):
            folder_service.move_material(user_id, material.id, uuid.uuid4())

    def test_move_to_archived_folder_404(
        self, session: Session, folder_service: FolderService
    ) -> None:
        """Verify moving to an archived folder raises 404."""
        user_id = uuid.uuid4()
        aggregate = folder_service.create_folder(user_id, "归档课程")
        folder_service.archive_folder(user_id, aggregate.folder.id)
        material = _create_material(session, user_id)

        with pytest.raises(FolderNotFoundError):
            folder_service.move_material(user_id, material.id, aggregate.folder.id)

    def test_move_to_other_user_folder_404(
        self, session: Session, folder_service: FolderService
    ) -> None:
        """Verify moving to another user's folder raises 404."""
        owner = uuid.uuid4()
        aggregate = folder_service.create_folder(owner, "他人课程")
        material = _create_material(session, uuid.uuid4())

        with pytest.raises(FolderNotFoundError):
            folder_service.move_material(material.user_id, material.id, aggregate.folder.id)

    def test_move_missing_material_404(self, folder_service: FolderService) -> None:
        """Verify moving a non-existent material raises MaterialNotFoundError."""
        with pytest.raises(MaterialNotFoundError):
            folder_service.move_material(uuid.uuid4(), uuid.uuid4(), None)

    def test_material_service_upload_with_folder_attribution(self, session: Session) -> None:
        """Verify create_material persists folder_id and validates ownership."""
        user_id = uuid.uuid4()
        folder_repo = FolderRepository(session)
        folder = folder_repo.create(user_id=user_id, name="上传归属课程")
        session.commit()

        storage = MemoryStorageAdapter()
        storage.ensure_bucket_exists("zhilian-materials")
        material_service = MaterialService(
            session=session,
            storage_adapter=storage,
            ocr_adapter=FakeOCRAdapter(),
            embedding_adapter=FakeEmbeddingAdapter(),
            queue_adapter=MemoryQueueAdapter(),
        )
        material, _ = material_service.import_material_file(
            user_id=user_id,
            file_content=b"%PDF-1.4 upload folder attribution",
            filename="归属.pdf",
            folder_id=folder.id,
        )
        assert material.folder_id == folder.id

        with pytest.raises(FolderNotFoundError):
            material_service.import_material_file(
                user_id=user_id,
                file_content=b"%PDF-1.4 another upload",
                filename="越权.pdf",
                folder_id=uuid.uuid4(),
            )
