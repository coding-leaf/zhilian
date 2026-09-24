"""Unit tests for GradingRepository in app/repositories/grading.py.

Verifies:
1. GradingRecord CRUD: create_record, batch_create_records, get_record_by_id.
2. History and final records: list_records_by_attempt_item, get_final_record_for_attempt,
   list_final_records_by_practice.
3. Atomic is_final flag switching: update_final_flag, set_records_non_final_by_attempt_id.
4. Pending regrade counting: count_pending_regrade.
5. Method aliases compatibility (create_grading_record, batch_create_grading_records, etc.).
6. Strict multi-tenant isolation: User B cannot access or mutate User A's grading records.
"""

import uuid
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.base import Base
from app.models.material import Material
from app.models.practice import (
    AttemptItem,
    GradingChannel,
    GradingRecord,
    GradingStatus,
    Practice,
    PracticeStatus,
)
from app.repositories.grading import GradingRepository


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
    """Sets up prerequisite material, practice, and attempt items."""
    user_id = uuid.uuid4()
    material_id = uuid.uuid4()
    practice_id = uuid.uuid4()
    item_id_1 = uuid.uuid4()
    item_id_2 = uuid.uuid4()

    material = Material(
        id=material_id,
        user_id=user_id,
        title="测试教材.pdf",
        file_format="pdf",
        file_size=1024,
    )
    practice = Practice(
        id=practice_id,
        material_id=material_id,
        user_id=user_id,
        title="专项练习",
        status=PracticeStatus.COMPLETED.value,
        question_count=2,
    )
    item_1 = AttemptItem(
        id=item_id_1,
        practice_id=practice_id,
        user_id=user_id,
        order_index=1,
        question_snapshot={"stem": "题干1", "question_type": "single_choice", "answer": "A"},
        user_answer="A",
        is_answered=True,
        max_score=2.0,
    )
    item_2 = AttemptItem(
        id=item_id_2,
        practice_id=practice_id,
        user_id=user_id,
        order_index=2,
        question_snapshot={"stem": "题干2", "question_type": "short_answer", "answer": "标准答案"},
        user_answer="用户作答",
        is_answered=True,
        max_score=5.0,
    )

    session.add_all([material, practice, item_1, item_2])
    session.flush()

    return {
        "user_id": user_id,
        "material_id": material_id,
        "practice_id": practice_id,
        "item_id_1": item_id_1,
        "item_id_2": item_id_2,
    }


class TestGradingRepository:
    """Test suite for GradingRepository."""

    def test_create_and_get_record(
        self, session: Session, helper_setup: dict[str, uuid.UUID]
    ) -> None:
        """Verify creating and retrieving a single grading record."""
        repo = GradingRepository(session)
        user_id = helper_setup["user_id"]
        practice_id = helper_setup["practice_id"]
        item_id = helper_setup["item_id_1"]

        record = GradingRecord(
            id=uuid.uuid4(),
            practice_id=practice_id,
            attempt_item_id=item_id,
            channel=GradingChannel.OFFLINE.value,
            status=GradingStatus.SUCCESS.value,
            is_final=True,
            score=2.0,
            max_score=2.0,
            confidence=1.0,
            feedback="作答正确",
        )

        saved = repo.create_record(record, user_id=user_id)
        assert saved.user_id == user_id
        assert saved.score == 2.0

        fetched = repo.get_record_by_id(saved.id, user_id=user_id)
        assert fetched is not None
        assert fetched.id == saved.id
        assert fetched.score == 2.0

        # Method alias check
        fetched_alias = repo.get_grading_record_by_id(saved.id, user_id=user_id)
        assert fetched_alias is not None
        assert fetched_alias.id == saved.id

    def test_batch_create_records(
        self, session: Session, helper_setup: dict[str, uuid.UUID]
    ) -> None:
        """Verify batch creation of grading records."""
        repo = GradingRepository(session)
        user_id = helper_setup["user_id"]
        practice_id = helper_setup["practice_id"]

        r1 = GradingRecord(
            id=uuid.uuid4(),
            practice_id=practice_id,
            attempt_item_id=helper_setup["item_id_1"],
            channel=GradingChannel.OFFLINE.value,
            status=GradingStatus.SUCCESS.value,
            is_final=True,
            score=2.0,
            max_score=2.0,
        )
        r2 = GradingRecord(
            id=uuid.uuid4(),
            practice_id=practice_id,
            attempt_item_id=helper_setup["item_id_2"],
            channel=GradingChannel.AI.value,
            status=GradingStatus.PENDING_REGRADE.value,
            is_final=True,
            score=0.0,
            max_score=5.0,
        )

        saved_list = repo.batch_create_records([r1, r2], user_id=user_id)
        assert len(saved_list) == 2
        assert all(item.user_id == user_id for item in saved_list)

        # Method alias check
        r3 = GradingRecord(
            id=uuid.uuid4(),
            practice_id=practice_id,
            attempt_item_id=helper_setup["item_id_1"],
            channel=GradingChannel.USER_SELF.value,
            status=GradingStatus.SUCCESS.value,
            is_final=False,
            score=1.5,
            max_score=2.0,
        )
        saved_alias = repo.batch_create_grading_records([r3], user_id=user_id)
        assert len(saved_alias) == 1

    def test_list_records_by_attempt_item(
        self, session: Session, helper_setup: dict[str, uuid.UUID]
    ) -> None:
        """Verify listing all historical records for an attempt item in chronological order."""
        repo = GradingRepository(session)
        user_id = helper_setup["user_id"]
        practice_id = helper_setup["practice_id"]
        item_id = helper_setup["item_id_2"]

        r1 = GradingRecord(
            id=uuid.uuid4(),
            practice_id=practice_id,
            attempt_item_id=item_id,
            channel=GradingChannel.AI.value,
            status=GradingStatus.SUCCESS.value,
            is_final=False,
            score=3.0,
            max_score=5.0,
        )
        r2 = GradingRecord(
            id=uuid.uuid4(),
            practice_id=practice_id,
            attempt_item_id=item_id,
            channel=GradingChannel.USER_SELF.value,
            status=GradingStatus.SUCCESS.value,
            is_final=True,
            score=4.0,
            max_score=5.0,
        )

        repo.batch_create_records([r1, r2], user_id=user_id)

        records = repo.list_records_by_attempt_item(item_id, user_id=user_id)
        assert len(records) == 2
        assert records[0].id == r1.id
        assert records[1].id == r2.id

        # Alias check
        records_alias = repo.list_records_by_attempt_id(item_id, user_id=user_id)
        assert len(records_alias) == 2

    def test_get_final_record_for_attempt(
        self, session: Session, helper_setup: dict[str, uuid.UUID]
    ) -> None:
        """Verify fetching the single effective final record for an attempt item."""
        repo = GradingRepository(session)
        user_id = helper_setup["user_id"]
        practice_id = helper_setup["practice_id"]
        item_id = helper_setup["item_id_2"]

        r1 = GradingRecord(
            id=uuid.uuid4(),
            practice_id=practice_id,
            attempt_item_id=item_id,
            channel=GradingChannel.AI.value,
            status=GradingStatus.SUCCESS.value,
            is_final=False,
            score=3.0,
            max_score=5.0,
        )
        r2 = GradingRecord(
            id=uuid.uuid4(),
            practice_id=practice_id,
            attempt_item_id=item_id,
            channel=GradingChannel.USER_SELF.value,
            status=GradingStatus.SUCCESS.value,
            is_final=True,
            score=4.5,
            max_score=5.0,
        )

        repo.batch_create_records([r1, r2], user_id=user_id)

        final_rec = repo.get_final_record_for_attempt(item_id, user_id=user_id)
        assert final_rec is not None
        assert final_rec.id == r2.id
        assert final_rec.score == 4.5

        # Alias check
        final_alias = repo.get_final_record_by_attempt_id(item_id, user_id=user_id)
        assert final_alias is not None
        assert final_alias.id == r2.id

    def test_list_final_records_by_practice(
        self, session: Session, helper_setup: dict[str, uuid.UUID]
    ) -> None:
        """Verify listing all active final records across all items of a practice."""
        repo = GradingRepository(session)
        user_id = helper_setup["user_id"]
        practice_id = helper_setup["practice_id"]

        r1 = GradingRecord(
            id=uuid.uuid4(),
            practice_id=practice_id,
            attempt_item_id=helper_setup["item_id_1"],
            channel=GradingChannel.OFFLINE.value,
            status=GradingStatus.SUCCESS.value,
            is_final=True,
            score=2.0,
            max_score=2.0,
        )
        r2_old = GradingRecord(
            id=uuid.uuid4(),
            practice_id=practice_id,
            attempt_item_id=helper_setup["item_id_2"],
            channel=GradingChannel.AI.value,
            status=GradingStatus.SUCCESS.value,
            is_final=False,
            score=2.0,
            max_score=5.0,
        )
        r2_new = GradingRecord(
            id=uuid.uuid4(),
            practice_id=practice_id,
            attempt_item_id=helper_setup["item_id_2"],
            channel=GradingChannel.USER_SELF.value,
            status=GradingStatus.SUCCESS.value,
            is_final=True,
            score=4.0,
            max_score=5.0,
        )

        repo.batch_create_records([r1, r2_old, r2_new], user_id=user_id)

        final_records = repo.list_final_records_by_practice(practice_id, user_id=user_id)
        assert len(final_records) == 2
        final_ids = {r.id for r in final_records}
        assert r1.id in final_ids
        assert r2_new.id in final_ids
        assert r2_old.id not in final_ids

        # Alias check
        final_alias = repo.list_final_records_by_practice_id(practice_id, user_id=user_id)
        assert len(final_alias) == 2

    def test_update_final_flag_and_set_records_non_final(
        self, session: Session, helper_setup: dict[str, uuid.UUID]
    ) -> None:
        """Verify atomic switching of is_final pointer."""
        repo = GradingRepository(session)
        user_id = helper_setup["user_id"]
        practice_id = helper_setup["practice_id"]
        item_id = helper_setup["item_id_2"]

        r1 = GradingRecord(
            id=uuid.uuid4(),
            practice_id=practice_id,
            attempt_item_id=item_id,
            channel=GradingChannel.AI.value,
            status=GradingStatus.SUCCESS.value,
            is_final=True,
            score=3.0,
            max_score=5.0,
        )
        repo.create_record(r1, user_id=user_id)

        # Call set_records_non_final_by_attempt_id
        affected = repo.set_records_non_final_by_attempt_id(item_id, user_id=user_id)
        assert affected == 1

        final_after = repo.get_final_record_for_attempt(item_id, user_id=user_id)
        assert final_after is None

        # Call update_final_flag to restore to True
        affected_restore = repo.update_final_flag(item_id, user_id=user_id, is_final=True)
        assert affected_restore == 1

        restored = repo.get_final_record_for_attempt(item_id, user_id=user_id)
        assert restored is not None
        assert restored.id == r1.id

    def test_count_pending_regrade(
        self, session: Session, helper_setup: dict[str, uuid.UUID]
    ) -> None:
        """Verify counting pending_regrade items."""
        repo = GradingRepository(session)
        user_id = helper_setup["user_id"]
        practice_id = helper_setup["practice_id"]

        # Initial count is 0
        assert repo.count_pending_regrade(practice_id, user_id=user_id) == 0

        r1 = GradingRecord(
            id=uuid.uuid4(),
            practice_id=practice_id,
            attempt_item_id=helper_setup["item_id_1"],
            channel=GradingChannel.OFFLINE.value,
            status=GradingStatus.SUCCESS.value,
            is_final=True,
            score=2.0,
            max_score=2.0,
        )
        r2 = GradingRecord(
            id=uuid.uuid4(),
            practice_id=practice_id,
            attempt_item_id=helper_setup["item_id_2"],
            channel=GradingChannel.AI.value,
            status=GradingStatus.PENDING_REGRADE.value,
            is_final=True,
            score=0.0,
            max_score=5.0,
        )
        repo.batch_create_records([r1, r2], user_id=user_id)

        count = repo.count_pending_regrade(practice_id, user_id=user_id)
        assert count == 1
        assert repo.count_pending_regrade_by_practice_id(practice_id, user_id=user_id) == 1

        # If r2 is marked non-final, pending count becomes 0
        repo.set_records_non_final_by_attempt_id(helper_setup["item_id_2"], user_id=user_id)
        assert repo.count_pending_regrade(practice_id, user_id=user_id) == 0

    def test_multi_tenant_isolation(
        self, session: Session, helper_setup: dict[str, uuid.UUID]
    ) -> None:
        """Verify strict multi-tenant isolation: User B cannot access or mutate User A's records."""
        repo = GradingRepository(session)
        user_a = helper_setup["user_id"]
        user_b = uuid.uuid4()
        practice_id = helper_setup["practice_id"]
        item_id = helper_setup["item_id_1"]

        record = GradingRecord(
            id=uuid.uuid4(),
            practice_id=practice_id,
            attempt_item_id=item_id,
            channel=GradingChannel.OFFLINE.value,
            status=GradingStatus.SUCCESS.value,
            is_final=True,
            score=2.0,
            max_score=2.0,
        )
        repo.create_record(record, user_id=user_a)

        # User B attempts to read User A's record by id
        assert repo.get_record_by_id(record.id, user_id=user_b) is None
        assert repo.get_grading_record_by_id(record.id, user_id=user_b) is None

        # User B attempts to list User A's item records
        assert repo.list_records_by_attempt_item(item_id, user_id=user_b) == []
        assert repo.list_records_by_attempt_id(item_id, user_id=user_b) == []

        # User B attempts to get final record
        assert repo.get_final_record_for_attempt(item_id, user_id=user_b) is None

        # User B attempts to list final records for practice
        assert repo.list_final_records_by_practice(practice_id, user_id=user_b) == []

        # User B attempts to switch is_final flag
        affected = repo.update_final_flag(item_id, user_id=user_b, is_final=False)
        assert affected == 0

        # User A's record is unaffected
        user_a_final = repo.get_final_record_for_attempt(item_id, user_id=user_a)
        assert user_a_final is not None
        assert user_a_final.is_final is True

        # User B attempts to count pending regrades
        assert repo.count_pending_regrade(practice_id, user_id=user_b) == 0
