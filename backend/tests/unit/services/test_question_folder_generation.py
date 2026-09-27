"""Unit tests for course-folder scoped question generation orchestration.

Verifies:
1. Cross-material grouping and count distribution (group split then within-group split).
2. Single-transaction atomicity: any group failure leaves zero persisted rows.
3. Default scope resolution (all ready folder materials) and archived/cross-tenant guards.
4. Explicit cross-material knowledge point ownership validation.
5. Backward compatibility of ``defer_commit`` default on the multi-KP orchestration.
"""

import uuid
from collections.abc import Generator
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import (
    FolderNotFoundError,
    KnowledgeNotFoundError,
    MissingSourceSnippetError,
)
from app.models.base import Base
from app.models.knowledge import KnowledgePoint
from app.models.material import Material, MaterialStatus
from app.models.question import Question
from app.repositories.folder import FolderRepository
from app.services.question import (
    GenerateQuestionsOptions,
    QuestionGenerationResult,
    QuestionService,
)


@pytest.fixture
def session() -> Generator[Session, None, None]:
    """Provides an isolated in-memory SQLite database session."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as sess:
        yield sess
    engine.dispose()


def _seed_material_with_points(
    session: Session,
    user_id: uuid.UUID,
    *,
    folder_id: uuid.UUID | None,
    point_names: list[str],
    status: str = MaterialStatus.READY.value,
) -> tuple[Material, uuid.UUID, list[KnowledgePoint]]:
    """Persists a material together with its version and knowledge points."""
    material = Material(
        user_id=user_id,
        title=f"{point_names[0]}.pdf",
        file_format="pdf",
        file_size=10,
        status=status,
        folder_id=folder_id,
    )
    session.add(material)
    session.flush()

    version_id = uuid.uuid4()
    points: list[KnowledgePoint] = []
    for name in point_names:
        point = KnowledgePoint(
            user_id=user_id,
            material_id=material.id,
            version_id=version_id,
            name=name,
            batch_id="batch-seed",
        )
        session.add(point)
        points.append(point)
    session.commit()
    return material, version_id, points


def _install_persisting_generate(
    service: QuestionService,
    monkeypatch: pytest.MonkeyPatch,
    captured: list[tuple[uuid.UUID, uuid.UUID, int, bool]],
    *,
    fail_on: uuid.UUID | None = None,
) -> None:
    """Patches the leaf ``generate_questions`` with a persisting fake (no inner commit)."""

    def fake_generate_questions(
        *,
        user_id: uuid.UUID,
        material_id: uuid.UUID,
        version_id: uuid.UUID | None = None,
        knowledge_point_id: uuid.UUID,
        options: GenerateQuestionsOptions | None = None,
        defer_commit: bool = False,
    ) -> QuestionGenerationResult:
        effective = options if options is not None else GenerateQuestionsOptions()
        captured.append((material_id, knowledge_point_id, effective.count, defer_commit))
        if fail_on is not None and knowledge_point_id == fail_on:
            raise MissingSourceSnippetError("检索不到与知识点匹配的有效资料片段，拒绝出题")

        aligned_version_id = version_id or uuid.uuid4()
        questions = [
            Question(
                user_id=user_id,
                material_id=material_id,
                version_id=aligned_version_id,
                knowledge_point_id=knowledge_point_id,
                question_type="single_choice",
                stem=f"考点{str(knowledge_point_id)[:6]}题目{idx}？",
                options=[{"key": "A", "content": "选项A"}],
                answer="A",
                difficulty=3,
            )
            for idx in range(effective.count)
        ]
        saved = service.question_repo.batch_create_questions(questions, user_id)
        return QuestionGenerationResult(
            batch_id=f"batch_{knowledge_point_id.hex[:8]}",
            material_id=material_id,
            version_id=aligned_version_id,
            knowledge_point_id=knowledge_point_id,
            total_generated=len(saved),
            qualified_questions=saved,
            pending_questions=[],
            quality_checks=[],
            retry_count=0,
        )

    monkeypatch.setattr(service, "generate_questions", fake_generate_questions)


class TestFolderGenerationGrouping:
    """Test suite for cross-material grouping and count distribution."""

    def test_groups_by_material_and_distributes_counts(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """6 questions over two materials (1 + 2 KPs) -> per-group and per-KP split."""
        user_id = uuid.uuid4()
        folder = FolderRepository(session).create(user_id=user_id, name="操作系统")
        session.commit()

        mat_a, ver_a, points_a = _seed_material_with_points(
            session, user_id, folder_id=folder.id, point_names=["进程管理"]
        )
        mat_b, _ver_b, points_b = _seed_material_with_points(
            session, user_id, folder_id=folder.id, point_names=["内存管理", "文件系统"]
        )
        kp_a, kp_b1, kp_b2 = points_a[0], points_b[0], points_b[1]

        service = QuestionService(session=session, llm=MagicMock(), embedding=MagicMock())
        captured: list[tuple[uuid.UUID, uuid.UUID, int, bool]] = []
        _install_persisting_generate(service, monkeypatch, captured)

        result = service.generate_questions_for_folder(
            user_id=user_id,
            folder_id=folder.id,
            knowledge_point_ids=[kp_a.id, kp_b1.id, kp_b2.id],
            options=GenerateQuestionsOptions(count=6),
        )

        assert captured == [
            (mat_a.id, kp_a.id, 3, True),
            (mat_b.id, kp_b1.id, 2, True),
            (mat_b.id, kp_b2.id, 1, True),
        ]
        assert result.material_id == mat_a.id
        assert result.version_id == ver_a
        assert result.knowledge_point_ids == (kp_a.id, kp_b1.id, kp_b2.id)
        assert result.requested_count == 6
        assert result.total_generated == 6
        per_material: dict[uuid.UUID, int] = {}
        for q in result.qualified_questions:
            per_material[q.material_id] = per_material.get(q.material_id, 0) + 1
        assert per_material == {mat_a.id: 3, mat_b.id: 3}

        _, total = service.question_repo.list_questions(user_id, folder_id=folder.id)
        assert total == 6

    def test_default_scope_uses_all_ready_folder_points(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Omitting knowledge_point_ids targets every ready folder knowledge point."""
        user_id = uuid.uuid4()
        folder = FolderRepository(session).create(user_id=user_id, name="数据结构")
        session.commit()
        _seed_material_with_points(session, user_id, folder_id=folder.id, point_names=["树", "图"])
        _seed_material_with_points(session, user_id, folder_id=folder.id, point_names=["排序"])

        service = QuestionService(session=session, llm=MagicMock(), embedding=MagicMock())
        captured: list[tuple[uuid.UUID, uuid.UUID, int, bool]] = []
        _install_persisting_generate(service, monkeypatch, captured)

        result = service.generate_questions_for_folder(
            user_id=user_id,
            folder_id=folder.id,
            knowledge_point_ids=None,
            options=GenerateQuestionsOptions(count=3),
        )

        assert {entry[1] for entry in captured} == set(result.knowledge_point_ids)
        assert len(captured) == 3
        assert result.total_generated == 3
        assert len(result.knowledge_point_ids) == 3


class TestFolderGenerationAtomicity:
    """Regression suite: cross-material generation must be a single transaction."""

    def test_failure_rolls_back_entire_folder_batch(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A failure on the second material leaves zero rows for the whole folder batch."""
        user_id = uuid.uuid4()
        folder = FolderRepository(session).create(user_id=user_id, name="编译原理")
        session.commit()
        _, _, points_a = _seed_material_with_points(
            session, user_id, folder_id=folder.id, point_names=["词法分析"]
        )
        _, _, points_b = _seed_material_with_points(
            session, user_id, folder_id=folder.id, point_names=["语法分析"]
        )

        service = QuestionService(session=session, llm=MagicMock(), embedding=MagicMock())
        captured: list[tuple[uuid.UUID, uuid.UUID, int, bool]] = []
        rollback_spy = MagicMock(wraps=session.rollback)
        monkeypatch.setattr(session, "rollback", rollback_spy)
        _install_persisting_generate(service, monkeypatch, captured, fail_on=points_b[0].id)

        with pytest.raises(MissingSourceSnippetError):
            service.generate_questions_for_folder(
                user_id=user_id,
                folder_id=folder.id,
                knowledge_point_ids=[points_a[0].id, points_b[0].id],
                options=GenerateQuestionsOptions(count=2),
            )

        assert captured == [
            (points_a[0].material_id, points_a[0].id, 1, True),
            (points_b[0].material_id, points_b[0].id, 1, True),
        ]
        rollback_spy.assert_called_once()
        _, total = service.question_repo.list_questions(user_id, folder_id=folder.id)
        assert total == 0

    def test_success_commits_once(self, session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
        """Full success persists every group question through a single outer commit."""
        user_id = uuid.uuid4()
        folder = FolderRepository(session).create(user_id=user_id, name="离散数学")
        session.commit()
        _seed_material_with_points(session, user_id, folder_id=folder.id, point_names=["集合"])
        _seed_material_with_points(session, user_id, folder_id=folder.id, point_names=["图论"])

        service = QuestionService(session=session, llm=MagicMock(), embedding=MagicMock())
        captured: list[tuple[uuid.UUID, uuid.UUID, int, bool]] = []
        commit_spy = MagicMock(wraps=session.commit)
        monkeypatch.setattr(session, "commit", commit_spy)
        _install_persisting_generate(service, monkeypatch, captured)

        result = service.generate_questions_for_folder(
            user_id=user_id,
            folder_id=folder.id,
            knowledge_point_ids=None,
            options=GenerateQuestionsOptions(count=2),
        )

        assert result.total_generated == 2
        assert commit_spy.call_count == 1
        _, total = service.question_repo.list_questions(user_id, folder_id=folder.id)
        assert total == 2


class TestFolderGenerationGuards:
    """Test suite for folder ownership, archive, and explicit ownership guards."""

    def _service(self, session: Session) -> QuestionService:
        return QuestionService(session=session, llm=MagicMock(), embedding=MagicMock())

    def test_missing_folder_raises(self, session: Session) -> None:
        """Unknown folder id raises FolderNotFoundError (404)."""
        service = self._service(session)
        with pytest.raises(FolderNotFoundError):
            service.generate_questions_for_folder(
                user_id=uuid.uuid4(),
                folder_id=uuid.uuid4(),
                options=GenerateQuestionsOptions(count=2),
            )

    def test_cross_tenant_folder_raises(self, session: Session) -> None:
        """Another user's folder is invisible and raises FolderNotFoundError."""
        owner = uuid.uuid4()
        folder = FolderRepository(session).create(user_id=owner, name="他人课程")
        session.commit()

        service = self._service(session)
        with pytest.raises(FolderNotFoundError):
            service.generate_questions_for_folder(
                user_id=uuid.uuid4(),
                folder_id=folder.id,
                options=GenerateQuestionsOptions(count=2),
            )

    def test_archived_folder_raises(self, session: Session) -> None:
        """Archived courses are excluded from folder-scope generation."""
        from datetime import UTC, datetime

        user_id = uuid.uuid4()
        repo_folders = FolderRepository(session)
        folder = repo_folders.create(user_id=user_id, name="归档课程")
        session.commit()
        _seed_material_with_points(session, user_id, folder_id=folder.id, point_names=["考点"])
        repo_folders.archive(folder.id, user_id, datetime.now(UTC))
        session.commit()

        service = self._service(session)
        with pytest.raises(FolderNotFoundError):
            service.generate_questions_for_folder(
                user_id=user_id,
                folder_id=folder.id,
                options=GenerateQuestionsOptions(count=2),
            )

    def test_folder_without_ready_points_raises(self, session: Session) -> None:
        """A folder with no ready materials has no default scope and raises clearly."""
        user_id = uuid.uuid4()
        folder = FolderRepository(session).create(user_id=user_id, name="未就绪课程")
        session.commit()
        _seed_material_with_points(
            session,
            user_id,
            folder_id=folder.id,
            point_names=["待解析考点"],
            status=MaterialStatus.PENDING.value,
        )

        service = self._service(session)
        with pytest.raises(KnowledgeNotFoundError):
            service.generate_questions_for_folder(
                user_id=user_id,
                folder_id=folder.id,
                options=GenerateQuestionsOptions(count=2),
            )

    def test_explicit_point_outside_folder_raises(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Explicit knowledge points must belong to a material in the target folder."""
        user_id = uuid.uuid4()
        folder = FolderRepository(session).create(user_id=user_id, name="目标课程")
        session.commit()
        _, _, inside_points = _seed_material_with_points(
            session, user_id, folder_id=folder.id, point_names=["内部考点"]
        )
        _, _, outside_points = _seed_material_with_points(
            session, user_id, folder_id=None, point_names=["外部考点"]
        )

        service = self._service(session)
        captured: list[tuple[uuid.UUID, uuid.UUID, int, bool]] = []
        _install_persisting_generate(service, monkeypatch, captured)

        with pytest.raises(KnowledgeNotFoundError):
            service.generate_questions_for_folder(
                user_id=user_id,
                folder_id=folder.id,
                knowledge_point_ids=[inside_points[0].id, outside_points[0].id],
                options=GenerateQuestionsOptions(count=2),
            )
        assert captured == []

    def test_explicit_unknown_point_raises(self, session: Session) -> None:
        """A non-existent knowledge point id raises KnowledgeNotFoundError."""
        user_id = uuid.uuid4()
        folder = FolderRepository(session).create(user_id=user_id, name="课程")
        session.commit()

        service = self._service(session)
        with pytest.raises(KnowledgeNotFoundError):
            service.generate_questions_for_folder(
                user_id=user_id,
                folder_id=folder.id,
                knowledge_point_ids=[uuid.uuid4()],
                options=GenerateQuestionsOptions(count=2),
            )


class TestMultiKnowledgePointDeferCommitRegression:
    """Zero-regression suite for the new ``defer_commit`` flag."""

    def test_default_defer_commit_false_still_commits(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Default defer_commit=False keeps the existing single-commit behavior."""
        service = QuestionService(session=session, llm=MagicMock(), embedding=MagicMock())
        captured: list[tuple[uuid.UUID, uuid.UUID, int, bool]] = []
        commit_spy = MagicMock(wraps=session.commit)
        monkeypatch.setattr(session, "commit", commit_spy)
        _install_persisting_generate(service, monkeypatch, captured)

        user_id = uuid.uuid4()
        material_id = uuid.uuid4()
        result = service.generate_questions_for_knowledge_points(
            user_id=user_id,
            material_id=material_id,
            version_id=uuid.uuid4(),
            knowledge_point_ids=[uuid.uuid4(), uuid.uuid4()],
            options=GenerateQuestionsOptions(count=2),
        )

        assert result.total_generated == 2
        assert commit_spy.call_count == 1
