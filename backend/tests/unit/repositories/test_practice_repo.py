"""Unit tests for PracticeRepository in app/repositories/practice.py.

Verifies:
1. Practice CRUD: create, get_by_id (with and without items), list_practices (filtering),
   find_active_by_source_report, update_practice_status.
2. AttemptItem operations: create_attempt_items, list_attempt_items, get_attempt_item,
   save_answer (duration accumulation, is_answered flag), save_attempt_answer alias.
3. Item counting: count_total_items, count_answered_items, count_unanswered_items.
4. Strict multi-tenant isolation: User B cannot access or mutate User A's data.
"""

import uuid
from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import PracticeNotFoundError
from app.models.base import Base
from app.models.knowledge import KnowledgePoint
from app.models.material import Material, MaterialVersion
from app.models.practice import AttemptItem, Practice, PracticeStatus
from app.models.question import Question, QuestionType
from app.repositories.practice import PracticeRepository


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
def helper_setup(session: Session) -> dict[str, uuid.UUID]:
    """Sets up prerequisite material, version, knowledge point, and question."""
    user_id = uuid.uuid4()
    material_id = uuid.uuid4()
    version_id = uuid.uuid4()
    point_id = uuid.uuid4()
    question_id = uuid.uuid4()

    material = Material(
        id=material_id,
        user_id=user_id,
        title="测试教材.pdf",
        file_format="pdf",
        file_size=1024,
    )
    version = MaterialVersion(
        id=version_id,
        material_id=material_id,
        user_id=user_id,
        version_number=1,
        storage_key="raw/v1.pdf",
        content_hash="hash_v1",
    )
    point = KnowledgePoint(
        id=point_id,
        material_id=material_id,
        version_id=version_id,
        user_id=user_id,
        name="TCP三次握手",
        batch_id="batch_001",
    )
    question = Question(
        id=question_id,
        material_id=material_id,
        version_id=version_id,
        knowledge_point_id=point_id,
        user_id=user_id,
        question_type=QuestionType.SINGLE_CHOICE.value,
        stem="TCP握手需要几次交互？",
        options=[{"key": "A", "content": "1"}, {"key": "B", "content": "3"}],
        answer="B",
    )

    session.add_all([material, version, point, question])
    session.commit()

    return {
        "user_id": user_id,
        "material_id": material_id,
        "version_id": version_id,
        "point_id": point_id,
        "question_id": question_id,
    }


class TestPracticeRepositoryCRUD:
    """Test suite for PracticeRepository basic CRUD operations."""

    def test_create_and_get_practice(
        self, session: Session, helper_setup: dict[str, uuid.UUID]
    ) -> None:
        """Verify creating a practice and retrieving it by id."""
        repo = PracticeRepository(session)
        user_id = helper_setup["user_id"]
        material_id = helper_setup["material_id"]

        practice = Practice(
            material_id=material_id,
            title="网络专项练习",
            question_count=5,
            knowledge_point_ids=[str(helper_setup["point_id"])],
            ordered_question_ids=[str(helper_setup["question_id"])],
        )

        created = repo.create_practice(practice, user_id)
        assert created.id is not None
        assert created.user_id == user_id
        assert created.status == PracticeStatus.NOT_STARTED.value

        retrieved = repo.get_practice_by_id(created.id, user_id)
        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.title == "网络专项练习"

        # Without items
        retrieved_no_items = repo.get_practice_by_id(created.id, user_id, include_items=False)
        assert retrieved_no_items is not None
        assert retrieved_no_items.id == created.id

    def test_find_active_by_source_report(
        self, session: Session, helper_setup: dict[str, uuid.UUID]
    ) -> None:
        """Verify querying active not_started practice by source_report_id."""
        repo = PracticeRepository(session)
        user_id = helper_setup["user_id"]
        material_id = helper_setup["material_id"]
        report_id = uuid.uuid4()

        # None initially
        assert repo.find_active_by_source_report(report_id, user_id) is None

        # Create not_started practice with source_report_id
        practice = Practice(
            material_id=material_id,
            title="诊断复练",
            source_report_id=report_id,
            status=PracticeStatus.NOT_STARTED.value,
        )
        repo.create_practice(practice, user_id)

        active = repo.find_active_by_source_report(report_id, user_id)
        assert active is not None
        assert active.source_report_id == report_id

        # Update status to in_progress -> should no longer be returned
        repo.update_practice_status(active.id, user_id, PracticeStatus.IN_PROGRESS.value)
        assert repo.find_active_by_source_report(report_id, user_id) is None

    def test_list_practices_filtering(
        self, session: Session, helper_setup: dict[str, uuid.UUID]
    ) -> None:
        """Verify list_practices with material and status filters."""
        repo = PracticeRepository(session)
        user_id = helper_setup["user_id"]
        material_id = helper_setup["material_id"]
        other_material_id = uuid.uuid4()

        p1 = Practice(
            material_id=material_id,
            title="练习1",
            status=PracticeStatus.NOT_STARTED.value,
        )
        p2 = Practice(
            material_id=material_id,
            title="练习2",
            status=PracticeStatus.IN_PROGRESS.value,
        )
        p3 = Practice(
            material_id=other_material_id,
            title="练习3",
            status=PracticeStatus.COMPLETED.value,
        )

        repo.create_practice(p1, user_id)
        repo.create_practice(p2, user_id)
        repo.create_practice(p3, user_id)

        all_practices = repo.list_practices(user_id)
        assert len(all_practices) == 3

        # Filter by material
        mat_practices = repo.list_practices(user_id, material_id=material_id)
        assert len(mat_practices) == 2

        # Filter by status
        completed = repo.list_practices(user_id, status=PracticeStatus.COMPLETED.value)
        assert len(completed) == 1
        assert completed[0].title == "练习3"

        # Pagination
        paginated = repo.list_practices(user_id, limit=2, offset=0)
        assert len(paginated) == 2

    def test_update_practice_status(
        self, session: Session, helper_setup: dict[str, uuid.UUID]
    ) -> None:
        """Verify updating practice status and submission metadata."""
        repo = PracticeRepository(session)
        user_id = helper_setup["user_id"]
        material_id = helper_setup["material_id"]

        practice = Practice(material_id=material_id, title="待交卷练习")
        repo.create_practice(practice, user_id)

        now = datetime.now(UTC)
        updated = repo.update_practice_status(
            practice.id,
            user_id,
            PracticeStatus.IN_PROGRESS.value,
            submit_idempotency_key="idemp_key_123",
            submitted_at=now,
        )
        assert updated is not None
        assert updated.status == PracticeStatus.IN_PROGRESS.value
        assert updated.submit_idempotency_key == "idemp_key_123"
        assert updated.submitted_at == now

        # Update non-existent
        assert repo.update_practice_status(uuid.uuid4(), user_id, "completed") is None


class TestAttemptItemOperations:
    """Test suite for AttemptItem operations in PracticeRepository."""

    def test_attempt_items_crud_and_counts(
        self, session: Session, helper_setup: dict[str, uuid.UUID]
    ) -> None:
        """Verify creating items, listing items, saving answers and counting."""
        repo = PracticeRepository(session)
        user_id = helper_setup["user_id"]
        material_id = helper_setup["material_id"]
        question_id = helper_setup["question_id"]
        q2_id = uuid.uuid4()

        practice = Practice(material_id=material_id, title="作答测试")
        repo.create_practice(practice, user_id)

        snapshot_1 = {
            "stem": "TCP握手几次？",
            "question_type": "single_choice",
            "answer": "B",
            "options": [{"key": "A", "content": "1"}, {"key": "B", "content": "3"}],
        }
        snapshot_2 = {
            "stem": "UDP是否可靠？",
            "question_type": "true_false",
            "answer": "False",
        }

        item1 = AttemptItem(
            practice_id=practice.id,
            question_id=question_id,
            order_index=1,
            question_snapshot=snapshot_1,
        )
        item2 = AttemptItem(
            practice_id=practice.id,
            question_id=q2_id,
            order_index=2,
            question_snapshot=snapshot_2,
        )

        repo.create_attempt_items([item1, item2], user_id)

        # List items
        items = repo.list_attempt_items(practice.id, user_id)
        assert len(items) == 2
        assert items[0].order_index == 1
        assert items[1].order_index == 2

        # Single item retrieval
        single_item = repo.get_attempt_item(practice.id, question_id, user_id)
        assert single_item is not None
        assert single_item.question_id == question_id

        # Initial counts
        assert repo.count_total_items(practice.id, user_id) == 2
        assert repo.count_answered_items(practice.id, user_id) == 0
        assert repo.count_unanswered_items(practice.id, user_id) == 2

        # Save answer for item 1
        updated_item = repo.save_answer(
            practice.id,
            question_id,
            user_id,
            user_answer="B",
            duration_seconds=15,
        )
        assert updated_item.user_answer == "B"
        assert updated_item.is_answered is True
        assert updated_item.duration_seconds == 15

        # Save additional duration
        repo.save_attempt_answer(
            practice.id,
            question_id,
            user_id,
            user_answer="B",
            duration_seconds=10,
        )
        refreshed = repo.get_attempt_item(practice.id, question_id, user_id)
        assert refreshed is not None
        assert refreshed.duration_seconds == 25

        # Counts after answer
        assert repo.count_answered_items(practice.id, user_id) == 1
        assert repo.count_unanswered_items(practice.id, user_id) == 1

        # Clear answer (empty/None)
        repo.save_answer(practice.id, question_id, user_id, user_answer="", duration_seconds=0)
        refreshed_empty = repo.get_attempt_item(practice.id, question_id, user_id)
        assert refreshed_empty is not None
        assert refreshed_empty.is_answered is False

        # Non-existent item raises PracticeNotFoundError
        with pytest.raises(PracticeNotFoundError):
            repo.save_answer(practice.id, uuid.uuid4(), user_id, user_answer="A")


class TestTenantIsolation:
    """Verify strict multi-tenant isolation (Anti-horizontal privilege escalation)."""

    def test_cross_tenant_isolation(
        self, session: Session, helper_setup: dict[str, uuid.UUID]
    ) -> None:
        """Verify User B cannot access, count, or modify User A's practice data."""
        repo = PracticeRepository(session)
        user_a = helper_setup["user_id"]
        user_b = uuid.uuid4()
        material_id = helper_setup["material_id"]
        question_id = helper_setup["question_id"]

        practice = Practice(material_id=material_id, title="User A 的练习")
        repo.create_practice(practice, user_a)

        item = AttemptItem(
            practice_id=practice.id,
            question_id=question_id,
            order_index=1,
            question_snapshot={"stem": "Q", "question_type": "short_answer", "answer": "A"},
        )
        repo.create_attempt_items([item], user_a)

        # User B queries practice by id -> None
        assert repo.get_practice_by_id(practice.id, user_b) is None

        # User B lists practices -> empty
        assert repo.list_practices(user_b) == []

        # User B updates status -> None
        assert repo.update_practice_status(practice.id, user_b, "completed") is None

        # User B attempts to save answer -> PracticeNotFoundError
        with pytest.raises(PracticeNotFoundError):
            repo.save_answer(practice.id, question_id, user_b, user_answer="偷看答案")

        # User B counts items -> 0
        assert repo.count_total_items(practice.id, user_b) == 0
        assert repo.count_answered_items(practice.id, user_b) == 0
        assert repo.count_unanswered_items(practice.id, user_b) == 0
