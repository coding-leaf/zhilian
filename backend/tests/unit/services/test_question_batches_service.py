"""Unit tests for QuestionService.list_question_batches in app/services/question.py.

Verifies:
1. Batch summaries carry server-side counts (available / pending_review split).
2. Sources are assembled for every material of a cross-material batch.
3. ``batch_id IS NULL`` stays a visible group with an empty source list.
4. Source lookup is one batched query for the whole page — no per-batch N+1.
5. ``total`` is the real batch count, independent of the page size.
"""

import uuid
from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.integrations.embedding import FakeEmbeddingAdapter
from app.integrations.llm.fake import FakeLLMAdapter
from app.models.base import Base
from app.models.knowledge import KnowledgePoint
from app.models.material import Material, MaterialFolder, MaterialVersion
from app.models.question import Question, QuestionStatus, QuestionType
from app.services.question import QuestionService


@pytest.fixture
def session() -> Generator[Session, None, None]:
    """Provides an isolated in-memory SQLite session that counts SELECT statements."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as sess:
        yield sess
    engine.dispose()


@pytest.fixture
def statement_counter() -> Generator[list[str], None, None]:
    """Collects every statement emitted against the SQLite engine under test."""
    statements: list[str] = []
    yield statements


def _build_service(session: Session) -> QuestionService:
    """Builds a QuestionService with offline fake adapters (no LLM calls involved)."""
    return QuestionService(
        session=session,
        llm=FakeLLMAdapter(),
        embedding=FakeEmbeddingAdapter(),
    )


def _seed_material(
    session: Session,
    user_id: uuid.UUID,
    *,
    title: str,
    folder_id: uuid.UUID | None = None,
) -> dict[str, uuid.UUID]:
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


def _add_question(
    session: Session,
    user_id: uuid.UUID,
    graph: dict[str, uuid.UUID],
    *,
    batch_id: str | None,
    status: str = QuestionStatus.AVAILABLE.value,
    created_at: datetime | None = None,
) -> None:
    question = Question(
        id=uuid.uuid4(),
        user_id=user_id,
        material_id=graph["material_id"],
        version_id=graph["version_id"],
        knowledge_point_id=graph["point_id"],
        question_type=QuestionType.SINGLE_CHOICE.value,
        status=status,
        is_deleted=False,
        batch_id=batch_id,
        stem="题干内容",
        options=[{"key": "A", "content": "选项"}],
        answer="A",
    )
    if created_at is not None:
        question.created_at = created_at
    session.add(question)


class TestListQuestionBatchesService:
    """Assembly of batch summaries and their sources."""

    def test_cross_material_batch_reports_every_source(self, session: Session) -> None:
        user_id = uuid.uuid4()
        folder_id = uuid.uuid4()
        session.add(MaterialFolder(id=folder_id, user_id=user_id, name="软件工程", sort_order=0))
        first = _seed_material(session, user_id, title="讲义一.pdf", folder_id=folder_id)
        second = _seed_material(session, user_id, title="讲义二.pdf", folder_id=folder_id)
        base = datetime(2026, 3, 1, 8, 0, tzinfo=UTC)
        _add_question(session, user_id, first, batch_id="batch_course", created_at=base)
        _add_question(
            session,
            user_id,
            first,
            batch_id="batch_course",
            status=QuestionStatus.PENDING_REVIEW.value,
            created_at=base + timedelta(minutes=1),
        )
        _add_question(
            session,
            user_id,
            second,
            batch_id="batch_course",
            created_at=base + timedelta(minutes=2),
        )
        session.commit()

        items, total = _build_service(session).list_question_batches(user_id, page=1, page_size=20)

        assert total == 1
        assert len(items) == 1
        summary = items[0]
        assert summary.batch_id == "batch_course"
        assert summary.question_count == 3
        assert summary.available_count == 2
        assert summary.pending_review_count == 1
        assert {source.material_title for source in summary.sources} == {
            "讲义一.pdf",
            "讲义二.pdf",
        }
        assert {source.folder_name for source in summary.sources} == {"软件工程"}
        assert summary.created_at.replace(tzinfo=UTC) == base

    def test_unbatched_group_is_listed_without_sources(self, session: Session) -> None:
        user_id = uuid.uuid4()
        graph = _seed_material(session, user_id, title="讲义.pdf")
        _add_question(session, user_id, graph, batch_id=None)
        _add_question(
            session,
            user_id,
            graph,
            batch_id=None,
            status=QuestionStatus.PENDING_REVIEW.value,
        )
        session.commit()

        items, total = _build_service(session).list_question_batches(user_id, page=1, page_size=20)

        assert total == 1
        assert items[0].batch_id is None
        assert items[0].question_count == 2
        assert items[0].available_count == 1
        assert items[0].sources == [], "未分批组不借它的资料拼一个假来源"

    def test_sources_are_fetched_once_for_the_whole_page(self, session: Session) -> None:
        """批次来源必须一次批量查询装配，请求数不随批次数量增长。"""
        user_id = uuid.uuid4()
        graph = _seed_material(session, user_id, title="讲义.pdf")
        for index in range(5):
            _add_question(session, user_id, graph, batch_id=f"batch_{index}")
        session.commit()

        statements: list[str] = []
        engine = session.get_bind()

        def _record(
            _conn: object,
            _cursor: object,
            statement: str,
            _parameters: object,
            _context: object,
            _executemany: object,
        ) -> None:
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", _record)
        try:
            items, total = _build_service(session).list_question_batches(
                user_id, page=1, page_size=20
            )
        finally:
            event.remove(engine, "before_cursor_execute", _record)

        assert total == 5
        assert len(items) == 5
        source_queries = [
            statement
            for statement in statements
            if "materials" in statement and "questions" in statement
        ]
        assert len(source_queries) == 1, "来源查询必须只有一次 (禁止逐批次查询)"

    def test_total_counts_every_batch_not_just_the_page(self, session: Session) -> None:
        user_id = uuid.uuid4()
        graph = _seed_material(session, user_id, title="讲义.pdf")
        base = datetime(2026, 3, 1, 8, 0, tzinfo=UTC)
        for index in range(4):
            _add_question(
                session,
                user_id,
                graph,
                batch_id=f"batch_{index}",
                created_at=base + timedelta(days=index),
            )
        session.commit()

        items, total = _build_service(session).list_question_batches(user_id, page=2, page_size=2)

        assert total == 4
        assert [item.batch_id for item in items] == ["batch_1", "batch_0"]
