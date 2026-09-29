"""Unit tests for DiagnosisRepository in app/repositories/diagnosis.py.

Verifies:
1. DiagnosisReport: create, get_by_id, get_by_practice_id, list_by_user, pagination.
2. MasteryRecord: upsert (insert and update), get, list_by_points, list_by_user,
   list_by_material (with KnowledgePoint join).
3. WrongRecord: upsert (insert and error_count increment), get by question_id and by id,
   mark_mastered, update_status, list_wrong_records, delete (and remove alias).
4. Strict multi-tenant isolation across all three domain entities.
"""

import uuid
from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.base import Base
from app.models.knowledge import KnowledgePoint
from app.models.material import Material, MaterialVersion
from app.models.practice import (
    AttemptItem,
    DiagnosisReport,
    ErrorType,
    MasteryLevel,
    MasteryRecord,
    Practice,
    PracticeStatus,
    WrongRecord,
)
from app.repositories.diagnosis import DiagnosisRepository


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
    """Sets up prerequisite material, version, knowledge points, questions, and practice."""
    user_id = uuid.uuid4()
    material_id = uuid.uuid4()
    version_id = uuid.uuid4()
    point_id_1 = uuid.uuid4()
    point_id_2 = uuid.uuid4()
    question_id_1 = uuid.uuid4()
    question_id_2 = uuid.uuid4()
    practice_id = uuid.uuid4()
    attempt_item_id_1 = uuid.uuid4()
    attempt_item_id_2 = uuid.uuid4()

    material = Material(
        id=material_id,
        user_id=user_id,
        title="网络协议教材.pdf",
        file_format="pdf",
        file_size=2048,
    )
    version = MaterialVersion(
        id=version_id,
        material_id=material_id,
        user_id=user_id,
        version_number=1,
        storage_key="raw/v1.pdf",
        content_hash="hash_v1",
    )
    point_1 = KnowledgePoint(
        id=point_id_1,
        material_id=material_id,
        version_id=version_id,
        user_id=user_id,
        name="TCP三次握手",
        batch_id="batch_001",
    )
    point_2 = KnowledgePoint(
        id=point_id_2,
        material_id=material_id,
        version_id=version_id,
        user_id=user_id,
        name="DNS解析过程",
        batch_id="batch_001",
    )
    practice = Practice(
        id=practice_id,
        material_id=material_id,
        title="网络协议专项练习",
        user_id=user_id,
        status=PracticeStatus.COMPLETED.value,
        question_count=2,
    )
    attempt_item_1 = AttemptItem(
        id=attempt_item_id_1,
        practice_id=practice_id,
        user_id=user_id,
        order_index=1,
        question_snapshot={"stem": "TCP握手题干", "answer": "B"},
        user_answer="A",
        is_answered=True,
    )
    attempt_item_2 = AttemptItem(
        id=attempt_item_id_2,
        practice_id=practice_id,
        user_id=user_id,
        order_index=2,
        question_snapshot={"stem": "DNS解析题干", "answer": "C"},
        user_answer="C",
        is_answered=True,
    )

    session.add_all([material, version, point_1, point_2, practice, attempt_item_1, attempt_item_2])
    session.commit()

    return {
        "user_id": user_id,
        "material_id": material_id,
        "version_id": version_id,
        "point_id_1": point_id_1,
        "point_id_2": point_id_2,
        "question_id_1": question_id_1,
        "question_id_2": question_id_2,
        "practice_id": practice_id,
        "attempt_item_id_1": attempt_item_id_1,
        "attempt_item_id_2": attempt_item_id_2,
    }


class TestDiagnosisReportCRUD:
    """Test suite for DiagnosisReport operations in DiagnosisRepository."""

    def test_create_and_get_diagnosis_report_by_id(
        self,
        session: Session,
        helper_setup: dict[str, uuid.UUID],
    ) -> None:
        """Verify report creation and retrieval by primary key."""
        repo = DiagnosisRepository(session)
        user_id = helper_setup["user_id"]
        practice_id = helper_setup["practice_id"]
        report_id = uuid.uuid4()

        report = DiagnosisReport(
            id=report_id,
            practice_id=practice_id,
            user_id=user_id,
            weak_knowledge_points=[{"id": str(helper_setup["point_id_1"]), "name": "TCP三次握手"}],
            regressed_knowledge_points=[],
            analysis_causes=[{"cause": "概念混淆"}],
            actionable_suggestions=[{"suggestion": "重温TCP状态机"}],
            unanswered_count=0,
            wrong_count=1,
            pending_regrade_count=0,
            total_questions=2,
            score_rate=0.5,
            is_structure_degraded=False,
        )

        saved = repo.create_diagnosis_report(report, user_id=user_id)
        assert saved.id == report_id
        assert saved.user_id == user_id

        fetched = repo.get_diagnosis_report_by_id(report_id, user_id=user_id)
        assert fetched is not None
        assert fetched.id == report_id
        assert fetched.score_rate == 0.5
        assert fetched.wrong_count == 1
        assert len(fetched.weak_knowledge_points) == 1

    def test_get_diagnosis_report_by_practice_id(
        self,
        session: Session,
        helper_setup: dict[str, uuid.UUID],
    ) -> None:
        """Verify retrieval by 1:1 linked practice_id."""
        repo = DiagnosisRepository(session)
        user_id = helper_setup["user_id"]
        practice_id = helper_setup["practice_id"]
        report_id = uuid.uuid4()

        report = DiagnosisReport(
            id=report_id,
            practice_id=practice_id,
            user_id=user_id,
            weak_knowledge_points=[],
            regressed_knowledge_points=[],
            analysis_causes=[],
            actionable_suggestions=[],
            unanswered_count=0,
            wrong_count=0,
            pending_regrade_count=0,
            total_questions=2,
            score_rate=1.0,
            is_structure_degraded=False,
        )
        repo.create_diagnosis_report(report, user_id=user_id)

        fetched = repo.get_diagnosis_report_by_practice_id(practice_id, user_id=user_id)
        assert fetched is not None
        assert fetched.id == report_id
        assert fetched.practice_id == practice_id

    def test_list_diagnosis_reports_and_pagination(
        self,
        session: Session,
        helper_setup: dict[str, uuid.UUID],
    ) -> None:
        """Verify listing and pagination of diagnosis reports."""
        repo = DiagnosisRepository(session)
        user_id = helper_setup["user_id"]
        material_id = helper_setup["material_id"]

        practice_ids = []
        for index in range(3):
            pid = uuid.uuid4()
            practice_ids.append(pid)
            practice = Practice(
                id=pid,
                material_id=material_id,
                title=f"练习-{index}",
                user_id=user_id,
                status=PracticeStatus.COMPLETED.value,
                question_count=1,
            )
            session.add(practice)
            report = DiagnosisReport(
                id=uuid.uuid4(),
                practice_id=pid,
                user_id=user_id,
                weak_knowledge_points=[],
                regressed_knowledge_points=[],
                analysis_causes=[],
                actionable_suggestions=[],
                unanswered_count=0,
                wrong_count=index,
                pending_regrade_count=0,
                total_questions=1,
                score_rate=0.8,
                is_structure_degraded=False,
            )
            repo.create_diagnosis_report(report, user_id=user_id)

        # list_diagnosis_reports_by_user
        reports_page = repo.list_diagnosis_reports_by_user(user_id=user_id, limit=2, offset=0)
        assert len(reports_page) == 2

        # alias list_diagnosis_reports
        reports_all = repo.list_diagnosis_reports(user_id=user_id, limit=10, offset=0)
        assert len(reports_all) == 3

    def test_diagnosis_report_tenant_isolation(
        self,
        session: Session,
        helper_setup: dict[str, uuid.UUID],
    ) -> None:
        """Verify user B cannot access user A's diagnosis report."""
        repo = DiagnosisRepository(session)
        user_a = helper_setup["user_id"]
        user_b = uuid.uuid4()
        practice_id = helper_setup["practice_id"]
        report_id = uuid.uuid4()

        report = DiagnosisReport(
            id=report_id,
            practice_id=practice_id,
            user_id=user_a,
            weak_knowledge_points=[],
            regressed_knowledge_points=[],
            analysis_causes=[],
            actionable_suggestions=[],
            total_questions=1,
            score_rate=1.0,
        )
        repo.create_diagnosis_report(report, user_id=user_a)

        assert repo.get_diagnosis_report_by_id(report_id, user_id=user_b) is None
        assert repo.get_diagnosis_report_by_practice_id(practice_id, user_id=user_b) is None
        assert repo.list_diagnosis_reports(user_id=user_b) == []


class TestMasteryRecordCRUD:
    """Test suite for MasteryRecord operations in DiagnosisRepository."""

    def test_upsert_mastery_record_insert_and_update(
        self,
        session: Session,
        helper_setup: dict[str, uuid.UUID],
    ) -> None:
        """Verify initial insert followed by subsequent update."""
        repo = DiagnosisRepository(session)
        user_id = helper_setup["user_id"]
        point_id = helper_setup["point_id_1"]
        now = datetime.now(UTC)

        # 1. Insert
        inserted = repo.upsert_mastery_record(
            user_id=user_id,
            knowledge_point_id=point_id,
            mastery_score=0.35,
            level=MasteryLevel.WEAK.value,
            practice_count=3,
            correct_count=1,
            last_practiced_at=now,
            decayed_at=now,
            recent_records_snapshot=[{"score": 0.0}, {"score": 1.0}],
        )
        assert isinstance(inserted, MasteryRecord)
        assert inserted.user_id == user_id
        assert inserted.knowledge_point_id == point_id
        assert inserted.mastery_score == 0.35
        assert inserted.level == MasteryLevel.WEAK.value
        assert inserted.practice_count == 3
        assert len(inserted.recent_records_snapshot) == 2

        # 2. Update existing
        updated = repo.upsert_mastery_record(
            user_id=user_id,
            knowledge_point_id=point_id,
            mastery_score=0.85,
            level=MasteryLevel.PROFICIENT.value,
            practice_count=5,
            correct_count=4,
            last_practiced_at=now,
            decayed_at=now,
            recent_records_snapshot=[{"score": 1.0}],
        )
        assert updated.id == inserted.id
        assert updated.mastery_score == 0.85
        assert updated.level == MasteryLevel.PROFICIENT.value
        assert updated.practice_count == 5
        assert updated.correct_count == 4

        # Confirm persisted
        fetched = repo.get_mastery_record(point_id, user_id=user_id)
        assert fetched is not None
        assert fetched.id == inserted.id
        assert fetched.mastery_score == 0.85

    def test_list_mastery_records_by_points(
        self,
        session: Session,
        helper_setup: dict[str, uuid.UUID],
    ) -> None:
        """Verify bulk retrieval by point IDs and handling of empty input."""
        repo = DiagnosisRepository(session)
        user_id = helper_setup["user_id"]
        point_id_1 = helper_setup["point_id_1"]
        point_id_2 = helper_setup["point_id_2"]

        assert repo.list_mastery_records_by_points([], user_id=user_id) == []

        repo.upsert_mastery_record(
            user_id=user_id,
            knowledge_point_id=point_id_1,
            mastery_score=0.5,
            level=MasteryLevel.BASIC.value,
            practice_count=2,
            correct_count=1,
            last_practiced_at=None,
            decayed_at=None,
            recent_records_snapshot=[],
        )
        repo.upsert_mastery_record(
            user_id=user_id,
            knowledge_point_id=point_id_2,
            mastery_score=0.9,
            level=MasteryLevel.PROFICIENT.value,
            practice_count=4,
            correct_count=4,
            last_practiced_at=None,
            decayed_at=None,
            recent_records_snapshot=[],
        )

        records = repo.list_mastery_records_by_points([point_id_1, point_id_2], user_id=user_id)
        assert len(records) == 2
        # Check alias
        records_alias = repo.list_mastery_records_by_knowledge_point_ids(
            [point_id_1], user_id=user_id
        )
        assert len(records_alias) == 1
        assert records_alias[0].knowledge_point_id == point_id_1

    def test_list_mastery_records_by_user_and_material(
        self,
        session: Session,
        helper_setup: dict[str, uuid.UUID],
    ) -> None:
        """Verify retrieval by user and by material_id with join."""
        repo = DiagnosisRepository(session)
        user_id = helper_setup["user_id"]
        material_id = helper_setup["material_id"]
        point_id_1 = helper_setup["point_id_1"]
        point_id_2 = helper_setup["point_id_2"]

        repo.upsert_mastery_record(
            user_id=user_id,
            knowledge_point_id=point_id_1,
            mastery_score=0.4,
            level=MasteryLevel.BASIC.value,
            practice_count=2,
            correct_count=1,
            last_practiced_at=None,
            decayed_at=None,
            recent_records_snapshot=[],
        )
        repo.upsert_mastery_record(
            user_id=user_id,
            knowledge_point_id=point_id_2,
            mastery_score=0.75,
            level=MasteryLevel.PROFICIENT.value,
            practice_count=3,
            correct_count=3,
            last_practiced_at=None,
            decayed_at=None,
            recent_records_snapshot=[],
        )

        by_user = repo.list_mastery_records_by_user(user_id=user_id)
        assert len(by_user) == 2

        by_material = repo.list_mastery_records_by_material(material_id, user_id=user_id)
        assert len(by_material) == 2

        # Non-matching material
        assert repo.list_mastery_records_by_material(uuid.uuid4(), user_id=user_id) == []

    def test_mastery_record_tenant_isolation(
        self,
        session: Session,
        helper_setup: dict[str, uuid.UUID],
    ) -> None:
        """Verify tenant isolation for mastery records."""
        repo = DiagnosisRepository(session)
        user_a = helper_setup["user_id"]
        user_b = uuid.uuid4()
        point_id = helper_setup["point_id_1"]
        material_id = helper_setup["material_id"]

        repo.upsert_mastery_record(
            user_id=user_a,
            knowledge_point_id=point_id,
            mastery_score=0.8,
            level=MasteryLevel.PROFICIENT.value,
            practice_count=2,
            correct_count=2,
            last_practiced_at=None,
            decayed_at=None,
            recent_records_snapshot=[],
        )

        assert repo.get_mastery_record(point_id, user_id=user_b) is None
        assert repo.list_mastery_records_by_points([point_id], user_id=user_b) == []
        assert repo.list_mastery_records_by_user(user_id=user_b) == []
        assert repo.list_mastery_records_by_material(material_id, user_id=user_b) == []


class TestWrongRecordCRUD:
    """Test suite for WrongRecord operations in DiagnosisRepository."""

    def test_upsert_wrong_record_create_and_increment(
        self,
        session: Session,
        helper_setup: dict[str, uuid.UUID],
    ) -> None:
        """Verify wrong record creation and error_count accumulation upon repeated errors."""
        repo = DiagnosisRepository(session)
        user_id = helper_setup["user_id"]
        question_id = helper_setup["question_id_1"]
        point_id = helper_setup["point_id_1"]
        practice_id = helper_setup["practice_id"]
        item_id = helper_setup["attempt_item_id_1"]

        # 1. Initial wrong record creation
        record = repo.upsert_wrong_record(
            user_id=user_id,
            question_id=question_id,
            knowledge_point_id=point_id,
            practice_id=practice_id,
            attempt_item_id=item_id,
            error_type="CONCEPT_CONFUSION",
            question_snapshot={"stem": "TCP握手题干", "answer": "B"},
            last_wrong_answer="A",
        )
        assert isinstance(record, WrongRecord)
        assert record.user_id == user_id
        assert record.question_id == question_id
        assert record.error_count == 1
        assert not record.is_mastered
        assert record.last_wrong_answer == "A"
        assert record.mastered_at is None

        # 2. Repeated wrong answer for same question
        second = repo.upsert_wrong_record(
            user_id=user_id,
            question_id=question_id,
            knowledge_point_id=point_id,
            practice_id=practice_id,
            attempt_item_id=item_id,
            error_type="CARELESSNESS",
            question_snapshot={"stem": "TCP握手题干", "answer": "B"},
            last_wrong_answer="C",
        )
        assert second.id == record.id
        assert second.error_count == 2
        assert second.error_type == "CARELESSNESS"
        assert second.last_wrong_answer == "C"
        assert not second.is_mastered

    def test_manual_upsert_preserves_judged_practice_provenance(
        self,
        session: Session,
        helper_setup: dict[str, uuid.UUID],
    ) -> None:
        """手工标记（无练习归属）不得抹掉判题写下的 practice_id / attempt_item_id。

        回归看守：更新分支曾无条件覆盖这两个字段，使得「先判题写入真实归属、
        再从题库手工标记同一题」这条路径静默把判题来源抹成 NULL（无错误信号）。
        """
        repo = DiagnosisRepository(session)
        user_id = helper_setup["user_id"]
        question_id = helper_setup["question_id_1"]
        point_id = helper_setup["point_id_1"]
        practice_id = helper_setup["practice_id"]
        item_id = helper_setup["attempt_item_id_1"]

        # 1. 判题路径先写入带真实练习归属的错题记录。
        repo.upsert_wrong_record(
            user_id=user_id,
            question_id=question_id,
            knowledge_point_id=point_id,
            practice_id=practice_id,
            attempt_item_id=item_id,
            error_type=ErrorType.CONCEPTUAL.value,
            question_snapshot={"stem": "题干", "answer": "B"},
        )

        # 2. 用户从题库手工标记同一题：该路径没有练习归属，传 None。
        manual = repo.upsert_wrong_record(
            user_id=user_id,
            question_id=question_id,
            knowledge_point_id=point_id,
            practice_id=None,
            attempt_item_id=None,
            error_type=ErrorType.MANUAL.value,
            question_snapshot={"stem": "题干", "answer": "B"},
        )

        # 3. 练习归属一旦写下不得被无归属的 upsert 清除；累加与重置语义照旧。
        assert manual.practice_id == practice_id
        assert manual.attempt_item_id == item_id
        assert manual.error_count == 2
        assert manual.is_mastered is False
        assert manual.error_type == ErrorType.MANUAL.value

    def test_upsert_wrong_record_resets_is_mastered(
        self,
        session: Session,
        helper_setup: dict[str, uuid.UUID],
    ) -> None:
        """Verify that making an error again resets is_mastered back to False."""
        repo = DiagnosisRepository(session)
        user_id = helper_setup["user_id"]
        question_id = helper_setup["question_id_1"]
        point_id = helper_setup["point_id_1"]
        practice_id = helper_setup["practice_id"]
        item_id = helper_setup["attempt_item_id_1"]

        repo.upsert_wrong_record(
            user_id=user_id,
            question_id=question_id,
            knowledge_point_id=point_id,
            practice_id=practice_id,
            attempt_item_id=item_id,
            error_type="CONCEPT_CONFUSION",
            question_snapshot={"stem": "题干"},
        )
        # Mark mastered
        repo.mark_wrong_record_mastered(question_id, user_id=user_id)
        mastered = repo.get_wrong_record(question_id, user_id=user_id)
        assert mastered is not None and mastered.is_mastered is True
        assert mastered.mastered_at is not None

        # Answer wrong again -> should reset is_mastered to False
        regressed = repo.upsert_wrong_record(
            user_id=user_id,
            question_id=question_id,
            knowledge_point_id=point_id,
            practice_id=practice_id,
            attempt_item_id=item_id,
            error_type="FORGOTTEN",
            question_snapshot={"stem": "题干"},
        )
        assert regressed.is_mastered is False
        assert regressed.mastered_at is None
        assert regressed.error_count == 2

    def test_get_wrong_record_and_get_by_id(
        self,
        session: Session,
        helper_setup: dict[str, uuid.UUID],
    ) -> None:
        """Verify retrieving wrong record by question_id and by primary key."""
        repo = DiagnosisRepository(session)
        user_id = helper_setup["user_id"]
        question_id = helper_setup["question_id_1"]
        point_id = helper_setup["point_id_1"]
        practice_id = helper_setup["practice_id"]
        item_id = helper_setup["attempt_item_id_1"]

        created = repo.upsert_wrong_record(
            user_id=user_id,
            question_id=question_id,
            knowledge_point_id=point_id,
            practice_id=practice_id,
            attempt_item_id=item_id,
            error_type="BLIND_SPOT",
            question_snapshot={"stem": "题干"},
        )

        by_qid = repo.get_wrong_record(question_id, user_id=user_id)
        assert by_qid is not None
        assert by_qid.id == created.id

        by_id = repo.get_wrong_record_by_id(created.id, user_id=user_id)
        assert by_id is not None
        assert by_id.id == created.id

        # Nonexistent
        assert repo.get_wrong_record(uuid.uuid4(), user_id=user_id) is None
        assert repo.get_wrong_record_by_id(uuid.uuid4(), user_id=user_id) is None

    def test_mark_and_update_wrong_record_status(
        self,
        session: Session,
        helper_setup: dict[str, uuid.UUID],
    ) -> None:
        """Verify status update methods for wrong records."""
        repo = DiagnosisRepository(session)
        user_id = helper_setup["user_id"]
        question_id = helper_setup["question_id_1"]
        point_id = helper_setup["point_id_1"]
        practice_id = helper_setup["practice_id"]
        item_id = helper_setup["attempt_item_id_1"]

        # Nonexistent question returns None
        assert repo.mark_wrong_record_mastered(uuid.uuid4(), user_id=user_id) is None
        assert (
            repo.update_wrong_record_status(uuid.uuid4(), user_id=user_id, is_mastered=True) is None
        )

        repo.upsert_wrong_record(
            user_id=user_id,
            question_id=question_id,
            knowledge_point_id=point_id,
            practice_id=practice_id,
            attempt_item_id=item_id,
            error_type="CARELESSNESS",
            question_snapshot={"stem": "题干"},
        )

        # mark_wrong_record_mastered
        updated = repo.mark_wrong_record_mastered(question_id, user_id=user_id)
        assert updated is not None
        assert updated.is_mastered is True
        assert updated.mastered_at is not None

        # update_wrong_record_status to False
        reopened = repo.update_wrong_record_status(question_id, user_id=user_id, is_mastered=False)
        assert reopened is not None
        assert reopened.is_mastered is False
        assert reopened.mastered_at is None

    def test_list_wrong_records_filtered(
        self,
        session: Session,
        helper_setup: dict[str, uuid.UUID],
    ) -> None:
        """Verify filtering by is_mastered and knowledge_point_id with pagination."""
        repo = DiagnosisRepository(session)
        user_id = helper_setup["user_id"]
        point_id_1 = helper_setup["point_id_1"]
        point_id_2 = helper_setup["point_id_2"]
        practice_id = helper_setup["practice_id"]
        item_id_1 = helper_setup["attempt_item_id_1"]
        item_id_2 = helper_setup["attempt_item_id_2"]
        qid_1 = helper_setup["question_id_1"]
        qid_2 = helper_setup["question_id_2"]

        r1 = repo.upsert_wrong_record(
            user_id=user_id,
            question_id=qid_1,
            knowledge_point_id=point_id_1,
            practice_id=practice_id,
            attempt_item_id=item_id_1,
            error_type="BLIND_SPOT",
            question_snapshot={"stem": "题干1"},
        )
        repo.upsert_wrong_record(
            user_id=user_id,
            question_id=qid_2,
            knowledge_point_id=point_id_2,
            practice_id=practice_id,
            attempt_item_id=item_id_2,
            error_type="FORGOTTEN",
            question_snapshot={"stem": "题干2"},
        )
        repo.mark_wrong_record_mastered(qid_1, user_id=user_id)

        # All records
        all_records = repo.list_wrong_records(user_id=user_id)
        assert len(all_records) == 2

        # Filter by is_mastered=True
        mastered_list = repo.list_wrong_records(user_id=user_id, is_mastered=True)
        assert len(mastered_list) == 1
        assert mastered_list[0].id == r1.id

        # Filter by is_mastered=False
        unmastered_list = repo.list_wrong_records(user_id=user_id, is_mastered=False)
        assert len(unmastered_list) == 1
        assert unmastered_list[0].question_id == qid_2

        # Filter by knowledge_point_id
        point_2_list = repo.list_wrong_records(user_id=user_id, knowledge_point_id=point_id_2)
        assert len(point_2_list) == 1
        assert point_2_list[0].knowledge_point_id == point_id_2

        # Pagination
        paged = repo.list_wrong_records(user_id=user_id, limit=1, offset=0)
        assert len(paged) == 1

    def test_count_wrong_records_filtered(
        self,
        session: Session,
        helper_setup: dict[str, uuid.UUID],
    ) -> None:
        """Verify count_wrong_records mirrors list_wrong_records filtering conditions."""
        repo = DiagnosisRepository(session)
        user_id = helper_setup["user_id"]
        point_id_1 = helper_setup["point_id_1"]
        point_id_2 = helper_setup["point_id_2"]
        practice_id = helper_setup["practice_id"]
        item_id_1 = helper_setup["attempt_item_id_1"]
        item_id_2 = helper_setup["attempt_item_id_2"]
        qid_1 = helper_setup["question_id_1"]
        qid_2 = helper_setup["question_id_2"]

        repo.upsert_wrong_record(
            user_id=user_id,
            question_id=qid_1,
            knowledge_point_id=point_id_1,
            practice_id=practice_id,
            attempt_item_id=item_id_1,
            error_type="BLIND_SPOT",
            question_snapshot={"stem": "题干1"},
        )
        repo.upsert_wrong_record(
            user_id=user_id,
            question_id=qid_2,
            knowledge_point_id=point_id_2,
            practice_id=practice_id,
            attempt_item_id=item_id_2,
            error_type="FORGOTTEN",
            question_snapshot={"stem": "题干2"},
        )
        repo.mark_wrong_record_mastered(qid_1, user_id=user_id)

        assert repo.count_wrong_records(user_id=user_id) == 2
        assert repo.count_wrong_records(user_id=user_id, is_mastered=True) == 1
        assert repo.count_wrong_records(user_id=user_id, is_mastered=False) == 1
        assert repo.count_wrong_records(user_id=user_id, knowledge_point_id=point_id_2) == 1
        assert repo.count_wrong_records(user_id=uuid.uuid4()) == 0

    def test_mark_wrong_record_mastered_toggle(
        self,
        session: Session,
        helper_setup: dict[str, uuid.UUID],
    ) -> None:
        """Verify mark_wrong_record_mastered supports is_mastered=False (clear mastered_at)."""
        repo = DiagnosisRepository(session)
        user_id = helper_setup["user_id"]
        qid = helper_setup["question_id_1"]
        point_id = helper_setup["point_id_1"]
        practice_id = helper_setup["practice_id"]
        item_id = helper_setup["attempt_item_id_1"]

        rec = repo.upsert_wrong_record(
            user_id=user_id,
            question_id=qid,
            knowledge_point_id=point_id,
            practice_id=practice_id,
            attempt_item_id=item_id,
            error_type="BLIND_SPOT",
            question_snapshot={"stem": "题干"},
        )

        mastered = repo.mark_wrong_record_mastered(
            wrong_record_id=rec.id, user_id=user_id, is_mastered=True
        )
        assert mastered is not None
        assert mastered.is_mastered is True
        assert mastered.mastered_at is not None

        unmastered = repo.mark_wrong_record_mastered(
            wrong_record_id=rec.id, user_id=user_id, is_mastered=False
        )
        assert unmastered is not None
        assert unmastered.is_mastered is False
        assert unmastered.mastered_at is None

    def test_delete_wrong_record(
        self,
        session: Session,
        helper_setup: dict[str, uuid.UUID],
    ) -> None:
        """Verify deletion of wrong records and alias remove_wrong_record."""
        repo = DiagnosisRepository(session)
        user_id = helper_setup["user_id"]
        qid = helper_setup["question_id_1"]
        point_id = helper_setup["point_id_1"]
        practice_id = helper_setup["practice_id"]
        item_id = helper_setup["attempt_item_id_1"]

        rec = repo.upsert_wrong_record(
            user_id=user_id,
            question_id=qid,
            knowledge_point_id=point_id,
            practice_id=practice_id,
            attempt_item_id=item_id,
            error_type="BLIND_SPOT",
            question_snapshot={"stem": "题干"},
        )

        # Deleting nonexistent record returns False
        assert repo.delete_wrong_record(uuid.uuid4(), user_id=user_id) is False

        # Successful deletion
        assert repo.delete_wrong_record(rec.id, user_id=user_id) is True
        assert repo.get_wrong_record_by_id(rec.id, user_id=user_id) is None

        # Re-create and test alias remove_wrong_record
        rec2 = repo.upsert_wrong_record(
            user_id=user_id,
            question_id=qid,
            knowledge_point_id=point_id,
            practice_id=practice_id,
            attempt_item_id=item_id,
            error_type="BLIND_SPOT",
            question_snapshot={"stem": "题干"},
        )
        assert repo.remove_wrong_record(rec2.id, user_id=user_id) is True
        assert repo.get_wrong_record_by_id(rec2.id, user_id=user_id) is None

    def test_wrong_record_tenant_isolation(
        self,
        session: Session,
        helper_setup: dict[str, uuid.UUID],
    ) -> None:
        """Verify tenant isolation for wrong records."""
        repo = DiagnosisRepository(session)
        user_a = helper_setup["user_id"]
        user_b = uuid.uuid4()
        qid = helper_setup["question_id_1"]
        point_id = helper_setup["point_id_1"]
        practice_id = helper_setup["practice_id"]
        item_id = helper_setup["attempt_item_id_1"]

        rec = repo.upsert_wrong_record(
            user_id=user_a,
            question_id=qid,
            knowledge_point_id=point_id,
            practice_id=practice_id,
            attempt_item_id=item_id,
            error_type="BLIND_SPOT",
            question_snapshot={"stem": "题干"},
        )

        assert repo.get_wrong_record(qid, user_id=user_b) is None
        assert repo.get_wrong_record_by_id(rec.id, user_id=user_b) is None
        assert repo.list_wrong_records(user_id=user_b) == []
        assert repo.mark_wrong_record_mastered(qid, user_id=user_b) is None
        assert repo.update_wrong_record_status(qid, user_id=user_b, is_mastered=True) is None
        assert repo.delete_wrong_record(rec.id, user_id=user_b) is False

    def test_list_wrong_records_material_error_question_type_filters(
        self,
        session: Session,
        helper_setup: dict[str, uuid.UUID],
    ) -> None:
        """Verify material_id/error_type/question_type SQL pushdown (DIAG-010/011/012)."""
        repo = DiagnosisRepository(session)
        user_id = helper_setup["user_id"]
        point_id_1 = helper_setup["point_id_1"]
        point_id_2 = helper_setup["point_id_2"]
        material_id = helper_setup["material_id"]
        practice_id = helper_setup["practice_id"]
        item_id_1 = helper_setup["attempt_item_id_1"]
        item_id_2 = helper_setup["attempt_item_id_2"]

        # Second material with its own knowledge point to prove the join filter.
        other_material_id = uuid.uuid4()
        other_version_id = uuid.uuid4()
        other_point_id = uuid.uuid4()
        session.add(
            Material(
                id=other_material_id,
                user_id=user_id,
                title="其他教材.pdf",
                file_format="pdf",
                file_size=1024,
            )
        )
        session.add(
            MaterialVersion(
                id=other_version_id,
                material_id=other_material_id,
                user_id=user_id,
                version_number=1,
                storage_key="raw/other.pdf",
                content_hash="hash_other",
            )
        )
        session.add(
            KnowledgePoint(
                id=other_point_id,
                material_id=other_material_id,
                version_id=other_version_id,
                user_id=user_id,
                name="其他知识点",
                batch_id="batch_other",
            )
        )
        session.commit()

        repo.upsert_wrong_record(
            user_id=user_id,
            question_id=uuid.uuid4(),
            knowledge_point_id=point_id_1,
            practice_id=practice_id,
            attempt_item_id=item_id_1,
            error_type="incomplete_expression",
            question_snapshot={"stem": "题1", "question_type": "single_choice"},
        )
        repo.upsert_wrong_record(
            user_id=user_id,
            question_id=uuid.uuid4(),
            knowledge_point_id=point_id_2,
            practice_id=practice_id,
            attempt_item_id=item_id_2,
            error_type="question_misreading",
            question_snapshot={"stem": "题2", "question_type": "multiple_choice"},
        )
        repo.upsert_wrong_record(
            user_id=user_id,
            question_id=uuid.uuid4(),
            knowledge_point_id=other_point_id,
            practice_id=practice_id,
            attempt_item_id=item_id_1,
            error_type="incomplete_expression",
            question_snapshot={"stem": "题3", "question_type": "single_choice"},
        )

        # material_id filter joins KnowledgePoint
        material_records = repo.list_wrong_records(user_id=user_id, material_id=material_id)
        assert len(material_records) == 2
        assert repo.count_wrong_records(user_id=user_id, material_id=material_id) == 2
        assert repo.count_wrong_records(user_id=user_id, material_id=other_material_id) == 1

        # error_type filter
        incomplete = repo.list_wrong_records(user_id=user_id, error_type="incomplete_expression")
        assert len(incomplete) == 2
        assert repo.count_wrong_records(user_id=user_id, error_type="incomplete_expression") == 2
        assert repo.count_wrong_records(user_id=user_id, error_type="mystery") == 0

        # question_type filter on JSON snapshot
        single = repo.list_wrong_records(user_id=user_id, question_type="single_choice")
        assert len(single) == 2
        assert repo.count_wrong_records(user_id=user_id, question_type="single_choice") == 2
        assert repo.count_wrong_records(user_id=user_id, question_type="true_false") == 0

        # combined filters
        combined = repo.list_wrong_records(
            user_id=user_id,
            material_id=material_id,
            question_type="multiple_choice",
        )
        assert len(combined) == 1

    def test_count_and_page_wrong_records_no_1000_truncation(
        self,
        session: Session,
        helper_setup: dict[str, uuid.UUID],
    ) -> None:
        """BUG-DIAG-012: material_id filtering must not truncate at 1000 rows."""
        repo = DiagnosisRepository(session)
        user_id = helper_setup["user_id"]
        material_id = helper_setup["material_id"]
        point_id = helper_setup["point_id_1"]
        practice_id = helper_setup["practice_id"]
        attempt_item_id = helper_setup["attempt_item_id_1"]

        total_rows = 1005
        session.add_all(
            [
                WrongRecord(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    question_id=None,
                    knowledge_point_id=point_id,
                    practice_id=practice_id,
                    attempt_item_id=attempt_item_id,
                    error_type="conceptual",
                    question_snapshot={"stem": f"题{i}", "question_type": "single_choice"},
                )
                for i in range(total_rows)
            ]
        )
        session.commit()

        assert repo.count_wrong_records(user_id=user_id, material_id=material_id) == total_rows
        first_page = repo.list_wrong_records(
            user_id=user_id, material_id=material_id, limit=50, offset=0
        )
        assert len(first_page) == 50
        last_page = repo.list_wrong_records(
            user_id=user_id, material_id=material_id, limit=50, offset=1000
        )
        assert len(last_page) == 5
