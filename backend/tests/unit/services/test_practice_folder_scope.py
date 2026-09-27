"""Unit tests for course-folder scoped practice assembly.

Verifies:
1. Folder-scope assembly persists ``folder_id`` with an empty ``material_id`` and
   resolves default knowledge points from the folder's ready materials.
2. Explicit folder knowledge points are accepted and validated.
3. Insufficient questions still raises ``PracticeEmptyQuestionsError``.
4. Archived, cross-tenant, and out-of-folder knowledge points are rejected.
"""

import uuid
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import (
    FolderNotFoundError,
    KnowledgeNotFoundError,
    PracticeEmptyQuestionsError,
)
from app.models.base import Base
from app.models.knowledge import KnowledgePoint
from app.models.material import Material, MaterialStatus
from app.models.question import Question, QuestionStatus
from app.repositories.folder import FolderRepository
from app.services.practice import CreatePracticeOptions, PracticeService


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
    point_name: str,
    question_count: int,
    status: str = MaterialStatus.READY.value,
) -> tuple[Material, KnowledgePoint]:
    """Persists a material with one knowledge point and N available questions."""
    material = Material(
        user_id=user_id,
        title=f"{point_name}.pdf",
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
        name=point_name,
        batch_id="batch-seed",
    )
    session.add(point)
    session.flush()

    for idx in range(question_count):
        session.add(
            Question(
                user_id=user_id,
                material_id=material.id,
                version_id=version_id,
                knowledge_point_id=point.id,
                question_type="single_choice",
                status=QuestionStatus.AVAILABLE.value,
                stem=f"{point_name}题目{idx}？",
                options=[{"key": "A", "content": "选项A"}, {"key": "B", "content": "选项B"}],
                answer="A",
                difficulty=3,
            )
        )
    session.commit()
    return material, point


class TestFolderScopePracticeAssembly:
    """Test suite for folder-scoped practice creation."""

    def test_default_points_resolve_from_folder(self, session: Session) -> None:
        """Folder scope with empty knowledge_point_ids uses all ready folder points."""
        user_id = uuid.uuid4()
        folder = FolderRepository(session).create(user_id=user_id, name="操作系统")
        session.commit()
        _seed_material(
            session, user_id, folder_id=folder.id, point_name="进程管理", question_count=2
        )
        _seed_material(
            session, user_id, folder_id=folder.id, point_name="内存管理", question_count=2
        )

        service = PracticeService(session)
        practice = service.create_practice(
            user_id,
            CreatePracticeOptions(
                title="操作系统课程练习",
                material_id=None,
                knowledge_point_ids=[],
                question_count=4,
                folder_id=folder.id,
            ),
        )

        assert practice.folder_id == folder.id
        assert practice.material_id is None
        assert len(practice.knowledge_point_ids) == 2
        assert len(practice.items) == 4

    def test_explicit_points_within_folder(self, session: Session) -> None:
        """Explicit knowledge points belonging to the folder are accepted."""
        user_id = uuid.uuid4()
        folder = FolderRepository(session).create(user_id=user_id, name="编译原理")
        session.commit()
        _, point = _seed_material(
            session, user_id, folder_id=folder.id, point_name="词法分析", question_count=3
        )

        service = PracticeService(session)
        practice = service.create_practice(
            user_id,
            CreatePracticeOptions(
                title="编译原理专项",
                material_id=None,
                knowledge_point_ids=[point.id],
                question_count=2,
                folder_id=folder.id,
            ),
        )

        assert practice.folder_id == folder.id
        assert practice.material_id is None
        assert practice.knowledge_point_ids == [str(point.id)]
        assert len(practice.items) == 2

    def test_insufficient_questions_raises(self, session: Session) -> None:
        """Folder scope still enforces the question-count gate (40012)."""
        user_id = uuid.uuid4()
        folder = FolderRepository(session).create(user_id=user_id, name="题量不足课程")
        session.commit()
        _seed_material(session, user_id, folder_id=folder.id, point_name="考点", question_count=1)

        service = PracticeService(session)
        with pytest.raises(PracticeEmptyQuestionsError) as exc_info:
            service.create_practice(
                user_id,
                CreatePracticeOptions(
                    title="超额组卷",
                    material_id=None,
                    knowledge_point_ids=[],
                    question_count=5,
                    folder_id=folder.id,
                ),
            )
        assert exc_info.value.error_code == 40012

    def test_folder_without_points_raises(self, session: Session) -> None:
        """A folder with no ready materials raises PracticeEmptyQuestionsError."""
        user_id = uuid.uuid4()
        folder = FolderRepository(session).create(user_id=user_id, name="未就绪课程")
        session.commit()
        _seed_material(
            session,
            user_id,
            folder_id=folder.id,
            point_name="待解析",
            question_count=0,
            status=MaterialStatus.PENDING.value,
        )

        service = PracticeService(session)
        with pytest.raises(PracticeEmptyQuestionsError):
            service.create_practice(
                user_id,
                CreatePracticeOptions(
                    title="空课程组卷",
                    material_id=None,
                    knowledge_point_ids=[],
                    question_count=1,
                    folder_id=folder.id,
                ),
            )


class TestFolderScopePracticeGuards:
    """Test suite for folder ownership and archive guards."""

    def test_archived_folder_raises(self, session: Session) -> None:
        """Archived courses are excluded from folder-scope assembly."""
        from datetime import UTC, datetime

        user_id = uuid.uuid4()
        repo_folders = FolderRepository(session)
        folder = repo_folders.create(user_id=user_id, name="归档课程")
        session.commit()
        _seed_material(
            session, user_id, folder_id=folder.id, point_name="归档考点", question_count=2
        )
        repo_folders.archive(folder.id, user_id, datetime.now(UTC))
        session.commit()

        service = PracticeService(session)
        with pytest.raises(FolderNotFoundError):
            service.create_practice(
                user_id,
                CreatePracticeOptions(
                    title="归档组卷",
                    material_id=None,
                    knowledge_point_ids=[],
                    question_count=1,
                    folder_id=folder.id,
                ),
            )

    def test_cross_tenant_folder_raises(self, session: Session) -> None:
        """Another user's folder raises FolderNotFoundError."""
        owner = uuid.uuid4()
        folder = FolderRepository(session).create(user_id=owner, name="他人课程")
        session.commit()

        service = PracticeService(session)
        with pytest.raises(FolderNotFoundError):
            service.create_practice(
                uuid.uuid4(),
                CreatePracticeOptions(
                    title="越权组卷",
                    material_id=None,
                    knowledge_point_ids=[],
                    question_count=1,
                    folder_id=folder.id,
                ),
            )

    def test_explicit_point_outside_folder_raises(self, session: Session) -> None:
        """Explicit knowledge points must belong to the target folder."""
        user_id = uuid.uuid4()
        folder = FolderRepository(session).create(user_id=user_id, name="目标课程")
        session.commit()
        _, outside_point = _seed_material(
            session, user_id, folder_id=None, point_name="外部考点", question_count=3
        )

        service = PracticeService(session)
        with pytest.raises(KnowledgeNotFoundError):
            service.create_practice(
                user_id,
                CreatePracticeOptions(
                    title="越界组卷",
                    material_id=None,
                    knowledge_point_ids=[outside_point.id],
                    question_count=1,
                    folder_id=folder.id,
                ),
            )

    def test_single_material_path_unchanged(self, session: Session) -> None:
        """Zero regression: no folder_id keeps the existing material binding."""
        user_id = uuid.uuid4()
        material, point = _seed_material(
            session, user_id, folder_id=None, point_name="单资料考点", question_count=2
        )

        service = PracticeService(session)
        practice = service.create_practice(
            user_id,
            CreatePracticeOptions(
                title="单资料练习",
                material_id=material.id,
                knowledge_point_ids=[point.id],
                question_count=2,
            ),
        )

        assert practice.folder_id is None
        assert practice.material_id == material.id
