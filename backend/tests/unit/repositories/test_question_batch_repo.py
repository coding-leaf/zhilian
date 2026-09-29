"""Unit tests for QuestionRepository batch aggregation (题库视图).

Verifies:
1. list_question_batches aggregates server-side by batch_id with question/available
   counts and the earliest created_at, ordered by that time descending, paginated.
2. ``batch_id IS NULL`` (unbatched legacy questions) is a visible group — never dropped.
3. count_question_batches yields the real total under the same WHERE clause.
4. list_batch_sources resolves every material of a cross-material batch in one query
   and degrades to a null title when the material row is gone.
5. Strict tenant isolation: another user's batches never appear.
"""

import uuid
from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy import delete as sa_delete
from sqlalchemy.orm import Session, sessionmaker

from app.models.base import Base
from app.models.knowledge import KnowledgePoint
from app.models.material import Material, MaterialFolder, MaterialVersion
from app.models.question import Question, QuestionStatus, QuestionType
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
    title: str,
    folder_id: uuid.UUID | None = None,
) -> dict[str, uuid.UUID]:
    """Seeds one material with its version and knowledge point."""
    material_id = uuid.uuid4()
    version_id = uuid.uuid4()
    point_id = uuid.uuid4()
    session.add(
        Material(
            id=material_id,
            user_id=user_id,
            title=title,
            file_format="pdf",
            file_size=1024,
            folder_id=folder_id,
        )
    )
    session.add(
        MaterialVersion(
            id=version_id,
            user_id=user_id,
            material_id=material_id,
            version_number=1,
            storage_key=f"materials/{version_id}.pdf",
            content_hash=uuid.uuid4().hex,
        )
    )
    session.add(
        KnowledgePoint(
            id=point_id,
            user_id=user_id,
            material_id=material_id,
            version_id=version_id,
            name="考点",
            level=1,
            batch_id="batch_kp_seed",
        )
    )
    return {"material_id": material_id, "version_id": version_id, "point_id": point_id}


def _seed_folder(session: Session, user_id: uuid.UUID, name: str) -> uuid.UUID:
    """Seeds one course folder and returns its id."""
    folder_id = uuid.uuid4()
    session.add(MaterialFolder(id=folder_id, user_id=user_id, name=name, sort_order=0))
    return folder_id


def _add_question(
    session: Session,
    user_id: uuid.UUID,
    graph: dict[str, uuid.UUID],
    *,
    batch_id: str | None,
    status: str = QuestionStatus.AVAILABLE.value,
    is_deleted: bool = False,
    created_at: datetime | None = None,
    stem: str = "题干内容",
) -> Question:
    """Appends one question row to the session and returns it."""
    question = Question(
        id=uuid.uuid4(),
        user_id=user_id,
        material_id=graph["material_id"],
        version_id=graph["version_id"],
        knowledge_point_id=graph["point_id"],
        question_type=QuestionType.SINGLE_CHOICE.value,
        status=status,
        is_deleted=is_deleted,
        batch_id=batch_id,
        stem=stem,
        options=[{"key": "A", "content": "选项"}],
        answer="A",
    )
    if created_at is not None:
        question.created_at = created_at
    session.add(question)
    return question


class TestListQuestionBatches:
    """Aggregation, pagination and tenant isolation of batch summaries."""

    def test_groups_by_batch_with_counts_and_earliest_created_at(self, session: Session) -> None:
        user_id = uuid.uuid4()
        graph = _seed_material(session, user_id, title="软件工程导论.pdf")
        base = datetime(2026, 3, 1, 8, 0, tzinfo=UTC)
        _add_question(
            session,
            user_id,
            graph,
            batch_id="batch_a",
            created_at=base + timedelta(hours=2),
        )
        _add_question(session, user_id, graph, batch_id="batch_a", created_at=base)
        _add_question(
            session,
            user_id,
            graph,
            batch_id="batch_a",
            status=QuestionStatus.PENDING_REVIEW.value,
            created_at=base + timedelta(hours=5),
        )
        _add_question(
            session,
            user_id,
            graph,
            batch_id="batch_b",
            created_at=base + timedelta(days=1),
        )
        session.commit()

        repo = QuestionRepository(session)
        rows = repo.list_question_batches(user_id, limit=20, offset=0)

        assert [(row[0], row[1], row[2]) for row in rows] == [
            ("batch_b", 1, 1),
            ("batch_a", 3, 2),
        ]
        # SQLite 不保留时区，取回的是朴素时间；按 UTC 归一后比较
        assert rows[1][3].replace(tzinfo=UTC) == base

    def test_soft_deleted_questions_are_excluded(self, session: Session) -> None:
        user_id = uuid.uuid4()
        graph = _seed_material(session, user_id, title="讲义.pdf")
        _add_question(session, user_id, graph, batch_id="batch_a")
        _add_question(session, user_id, graph, batch_id="batch_a", is_deleted=True)
        _add_question(session, user_id, graph, batch_id="batch_gone", is_deleted=True)
        session.commit()

        repo = QuestionRepository(session)
        rows = repo.list_question_batches(user_id, limit=20, offset=0)

        assert [(row[0], row[1]) for row in rows] == [("batch_a", 1)]

    def test_unbatched_questions_form_a_visible_group(self, session: Session) -> None:
        user_id = uuid.uuid4()
        graph = _seed_material(session, user_id, title="讲义.pdf")
        _add_question(session, user_id, graph, batch_id=None, stem="历史题一")
        _add_question(
            session,
            user_id,
            graph,
            batch_id=None,
            status=QuestionStatus.PENDING_REVIEW.value,
        )
        _add_question(session, user_id, graph, batch_id="batch_a")
        session.commit()

        repo = QuestionRepository(session)
        rows = repo.list_question_batches(user_id, limit=20, offset=0)
        by_batch = {row[0]: row for row in rows}

        assert None in by_batch, "batch_id IS NULL 的题目必须仍能被看到"
        assert by_batch[None][1] == 2
        assert by_batch[None][2] == 1
        assert repo.count_question_batches(user_id) == 2

    def test_pagination_is_offset_limited_over_the_same_ordering(self, session: Session) -> None:
        user_id = uuid.uuid4()
        graph = _seed_material(session, user_id, title="讲义.pdf")
        base = datetime(2026, 3, 1, 8, 0, tzinfo=UTC)
        for index in range(3):
            _add_question(
                session,
                user_id,
                graph,
                batch_id=f"batch_{index}",
                created_at=base + timedelta(days=index),
            )
        session.commit()

        repo = QuestionRepository(session)

        first_page = repo.list_question_batches(user_id, limit=2, offset=0)
        second_page = repo.list_question_batches(user_id, limit=2, offset=2)

        assert [row[0] for row in first_page] == ["batch_2", "batch_1"]
        assert [row[0] for row in second_page] == ["batch_0"]
        assert repo.count_question_batches(user_id) == 3

    def test_other_users_batches_never_appear(self, session: Session) -> None:
        user_id = uuid.uuid4()
        other_user_id = uuid.uuid4()
        graph = _seed_material(session, user_id, title="我的讲义.pdf")
        other_graph = _seed_material(session, other_user_id, title="别人的讲义.pdf")
        _add_question(session, user_id, graph, batch_id="batch_mine")
        _add_question(session, other_user_id, other_graph, batch_id="batch_other")
        session.commit()

        repo = QuestionRepository(session)

        assert [row[0] for row in repo.list_question_batches(user_id, limit=20, offset=0)] == [
            "batch_mine"
        ]
        assert repo.count_question_batches(user_id) == 1


class TestListBatchSources:
    """Source assembly for a page of batches, including degraded sources."""

    def test_cross_material_batch_returns_every_material_once(self, session: Session) -> None:
        user_id = uuid.uuid4()
        folder_id = _seed_folder(session, user_id, name="软件工程")
        first = _seed_material(session, user_id, title="讲义一.pdf", folder_id=folder_id)
        second = _seed_material(session, user_id, title="讲义二.pdf", folder_id=folder_id)
        _add_question(session, user_id, first, batch_id="batch_course")
        _add_question(session, user_id, first, batch_id="batch_course", is_deleted=True)
        _add_question(session, user_id, second, batch_id="batch_course")
        session.commit()

        repo = QuestionRepository(session)
        rows = repo.list_batch_sources(user_id, ["batch_course"])

        assert len(rows) == 2, "同一批次横跨两份资料时必须给出两条来源"
        assert {row[2] for row in rows} == {"讲义一.pdf", "讲义二.pdf"}
        assert {row[4] for row in rows} == {"软件工程"}
        assert all(row[0] == "batch_course" for row in rows)

    def test_missing_material_row_degrades_instead_of_dropping_the_batch(
        self, session: Session
    ) -> None:
        user_id = uuid.uuid4()
        graph = _seed_material(session, user_id, title="讲义.pdf")
        _add_question(session, user_id, graph, batch_id="batch_orphan")
        session.commit()
        # 绕开 ORM 级联，只把 materials 行拿掉，模拟资料已物理删除
        session.execute(sa_delete(Material).where(Material.id == graph["material_id"]))
        session.commit()

        repo = QuestionRepository(session)
        rows = repo.list_batch_sources(user_id, ["batch_orphan"])

        assert len(rows) == 1
        assert rows[0][1] == graph["material_id"]
        assert rows[0][2] is None, "资料行缺失时标题降级为 null，由装配层给出可读标签"

    def test_no_batch_ids_skips_the_query(self, session: Session) -> None:
        repo = QuestionRepository(session)

        assert repo.list_batch_sources(uuid.uuid4(), []) == []

    def test_other_users_sources_never_appear(self, session: Session) -> None:
        user_id = uuid.uuid4()
        other_user_id = uuid.uuid4()
        graph = _seed_material(session, user_id, title="我的讲义.pdf")
        other_graph = _seed_material(session, other_user_id, title="别人的讲义.pdf")
        _add_question(session, user_id, graph, batch_id="batch_mine")
        _add_question(session, other_user_id, other_graph, batch_id="batch_other")
        session.commit()

        repo = QuestionRepository(session)

        assert repo.list_batch_sources(user_id, ["batch_other"]) == []


class TestListQuestionsUnbatchedFilter:
    """``GET /questions?unbatched=true`` 的仓储过滤（题库「未分批」分组展开用）。"""

    def test_unbatched_filter_returns_only_null_batch_questions(self, session: Session) -> None:
        user_id = uuid.uuid4()
        graph = _seed_material(session, user_id, title="讲义.pdf")
        _add_question(session, user_id, graph, batch_id=None)
        _add_question(session, user_id, graph, batch_id="batch_a")
        session.commit()

        repo = QuestionRepository(session)
        items, total = repo.list_questions(user_id, unbatched=True)

        assert total == 1
        assert [item.batch_id for item in items] == [None]

    def test_unbatched_defaults_to_false_and_keeps_every_batch(self, session: Session) -> None:
        user_id = uuid.uuid4()
        graph = _seed_material(session, user_id, title="讲义.pdf")
        _add_question(session, user_id, graph, batch_id=None)
        _add_question(session, user_id, graph, batch_id="batch_a")
        session.commit()

        repo = QuestionRepository(session)
        _items, total = repo.list_questions(user_id)

        assert total == 2
