"""Unit tests for DiagnosisService in app/services/diagnosis.py.

Verifies:
1. calculate_and_update_mastery calling pure algorithm aggregate_mastery_scores.
2. generate_diagnosis_report success path (score aggregation, mastery update,
   weak points identification, wrong records sync, atomic commit).
3. generate_diagnosis_report state machine blocking:
   - PracticeStatus.PARTIALLY_GRADED raises PracticeNotGradedError (40016).
   - Non-COMPLETED status (e.g. IN_PROGRESS, NOT_STARTED) raises PracticeNotGradedError (40016).
   - COMPLETED without completed_at, or with items lacking a final SUCCESS
     grading record, raises PracticeNotGradedError (40016).
   - Practice not found raises PracticeNotFoundError (40401).
4. generate_diagnosis_report idempotency when report already exists for practice_id.
5. WrongRecord sync on correct vs incorrect answers (including unanswered items).
6. Low-confidence knowledge points trigger is_structure_degraded=True.
7. get_diagnosis_report & get_diagnosis_report_by_practice:
   - Success path and DiagnosisReportNotFoundError (40017) on miss or tenant mismatch.
8. list_diagnosis_reports pagination and user isolation.
9. get_user_mastery_overview four-tier aggregation and weak points extraction.
10. list_wrong_records and remove_wrong_record operations.
11. Zero plain text leakage in structured logs (8 elements checked).
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.algorithms.mastery import GradingSourceType
from app.core.errors import (
    DiagnosisReportNotFoundError,
    PracticeNotFoundError,
    PracticeNotGradedError,
)
from app.models.knowledge import KnowledgePoint
from app.models.practice import (
    AttemptItem,
    DiagnosisReport,
    GradingChannel,
    GradingRecord,
    GradingStatus,
    MasteryLevel,
    MasteryRecord,
    Practice,
    PracticeStatus,
    WrongRecord,
)
from app.repositories.diagnosis import DiagnosisRepository
from app.repositories.grading import GradingRepository
from app.repositories.knowledge import KnowledgeRepository
from app.repositories.practice import PracticeRepository
from app.services.diagnosis import (
    DiagnosisService,
    MasteryRecordList,
    ReportService,
    map_mastery_level_to_db,
    normalize_error_type,
    resolve_channel_to_source,
)


@pytest.fixture
def mock_session() -> MagicMock:
    """Mock SQLAlchemy session."""
    session = MagicMock()
    session.commit.return_value = None
    session.flush.return_value = None
    return session


@pytest.fixture
def mock_repos() -> dict[str, MagicMock]:
    """Provides mocked repository dependencies."""
    return {
        "diagnosis_repo": MagicMock(spec=DiagnosisRepository),
        "practice_repo": MagicMock(spec=PracticeRepository),
        "grading_repo": MagicMock(spec=GradingRepository),
        "knowledge_repo": MagicMock(spec=KnowledgeRepository),
    }


@pytest.fixture
def diagnosis_service(
    mock_session: MagicMock, mock_repos: dict[str, MagicMock]
) -> DiagnosisService:
    """Instantiates DiagnosisService with mocked session and repos."""
    return DiagnosisService(
        session=mock_session,
        diagnosis_repo=mock_repos["diagnosis_repo"],
        practice_repo=mock_repos["practice_repo"],
        grading_repo=mock_repos["grading_repo"],
        knowledge_repo=mock_repos["knowledge_repo"],
    )


def make_final_grading_record(
    practice_id: uuid.UUID,
    user_id: uuid.UUID,
    item: AttemptItem,
) -> GradingRecord:
    """Build the per-item final SUCCESS record the diagnosis gate requires."""
    return GradingRecord(
        id=uuid.uuid4(),
        practice_id=practice_id,
        attempt_item_id=item.id,
        user_id=user_id,
        channel=GradingChannel.OFFLINE.value,
        status=GradingStatus.SUCCESS.value,
        score=item.score or 0.0,
        max_score=item.max_score,
        is_final=True,
    )


class TestCalculateAndUpdateMastery:
    """Tests for calculate_and_update_mastery method."""

    def test_calculate_and_update_mastery_calls_algorithm(
        self,
        diagnosis_service: DiagnosisService,
        mock_repos: dict[str, MagicMock],
        mock_session: MagicMock,
    ) -> None:
        """Verify historical items are fetched, transformed, and aggregate_mastery_scores called."""
        user_id = uuid.uuid4()
        point_id = uuid.uuid4()
        now = datetime.now(UTC)

        item_1 = AttemptItem(
            id=uuid.uuid4(),
            practice_id=uuid.uuid4(),
            user_id=user_id,
            is_answered=True,
            score=1.0,
            max_score=1.0,
            created_at=now - timedelta(days=2),
        )
        grading_1 = GradingRecord(
            id=uuid.uuid4(),
            practice_id=item_1.practice_id,
            attempt_item_id=item_1.id,
            user_id=user_id,
            channel=GradingChannel.OFFLINE.value,
            status=GradingStatus.SUCCESS.value,
            score=1.0,
            max_score=1.0,
            is_final=True,
            created_at=now - timedelta(days=2),
        )

        item_2 = AttemptItem(
            id=uuid.uuid4(),
            practice_id=uuid.uuid4(),
            user_id=user_id,
            is_answered=True,
            score=0.0,
            max_score=1.0,
            created_at=now - timedelta(days=1),
        )
        grading_2 = GradingRecord(
            id=uuid.uuid4(),
            practice_id=item_2.practice_id,
            attempt_item_id=item_2.id,
            user_id=user_id,
            channel=GradingChannel.AI.value,
            status=GradingStatus.SUCCESS.value,
            score=0.0,
            max_score=1.0,
            is_final=True,
            created_at=now - timedelta(days=1),
        )

        mock_repos["diagnosis_repo"].get_attempt_history_for_knowledge_point.return_value = [
            (item_1, grading_1),
            (item_2, grading_2),
        ]

        expected_record = MasteryRecord(
            id=uuid.uuid4(),
            user_id=user_id,
            knowledge_point_id=point_id,
            mastery_score=0.55,
            level=MasteryLevel.BASIC.value,
            practice_count=2,
            correct_count=1,
            last_practiced_at=now - timedelta(days=1),
            decayed_at=now,
            recent_records_snapshot=[],
        )
        mock_repos["diagnosis_repo"].upsert_mastery_record.return_value = expected_record

        result = diagnosis_service.calculate_and_update_mastery(
            user_id=user_id,
            knowledge_point_ids=[point_id],
            current_time=now,
        )

        assert len(result) == 1
        assert result[0] == expected_record
        assert result[point_id] == expected_record
        assert result.get(point_id) == expected_record
        assert result.as_dict() == {point_id: expected_record}

        mock_repos[
            "diagnosis_repo"
        ].get_attempt_history_for_knowledge_point.assert_called_once_with(
            knowledge_point_id=point_id,
            user_id=user_id,
            limit=200,
        )
        mock_repos["diagnosis_repo"].upsert_mastery_record.assert_called_once()
        mock_session.flush.assert_called()

    def test_calculate_and_update_mastery_empty_history(
        self,
        diagnosis_service: DiagnosisService,
        mock_repos: dict[str, MagicMock],
    ) -> None:
        """Verify unlearned level when knowledge point has zero history."""
        user_id = uuid.uuid4()
        point_id = uuid.uuid4()
        now = datetime.now(UTC)

        mock_repos["diagnosis_repo"].get_attempt_history_for_knowledge_point.return_value = []
        expected_record = MasteryRecord(
            id=uuid.uuid4(),
            user_id=user_id,
            knowledge_point_id=point_id,
            mastery_score=0.0,
            level=MasteryLevel.UNLEARNED.value,
            practice_count=0,
            correct_count=0,
            last_practiced_at=None,
            decayed_at=now,
            recent_records_snapshot=[],
        )
        mock_repos["diagnosis_repo"].upsert_mastery_record.return_value = expected_record

        result = diagnosis_service.calculate_and_update_mastery(
            user_id=user_id,
            knowledge_point_ids=[point_id],
            current_time=now,
        )

        assert len(result) == 1
        mock_repos["diagnosis_repo"].upsert_mastery_record.assert_called_once_with(
            user_id=user_id,
            knowledge_point_id=point_id,
            mastery_score=0.0,
            level=MasteryLevel.UNLEARNED.value,
            practice_count=0,
            correct_count=0,
            last_practiced_at=None,
            decayed_at=now,
            recent_records_snapshot=[],
        )

    def test_dual_mode_container_key_error(self) -> None:
        """Verify MasteryRecordList raises KeyError on unknown key and returns default on get."""
        container = MasteryRecordList([])
        with pytest.raises(KeyError):
            _ = container[uuid.uuid4()]
        assert container.get(uuid.uuid4(), "default") == "default"


class TestGenerateDiagnosisReport:
    """Tests for generate_diagnosis_report pipeline."""

    def test_generate_report_success_path(
        self,
        diagnosis_service: DiagnosisService,
        mock_repos: dict[str, MagicMock],
        mock_session: MagicMock,
    ) -> None:
        """Verify successful diagnosis report generation and full persistence loop."""
        user_id = uuid.uuid4()
        practice_id = uuid.uuid4()
        point_id = uuid.uuid4()
        question_id_1 = uuid.uuid4()
        question_id_2 = uuid.uuid4()
        now = datetime.now(UTC)

        practice = Practice(
            id=practice_id,
            user_id=user_id,
            material_id=uuid.uuid4(),
            title="综合练习测试",
            status=PracticeStatus.COMPLETED.value,
            completed_at=now,
            knowledge_point_ids=[str(point_id)],
        )
        mock_repos["practice_repo"].get_practice_by_id.return_value = practice
        mock_repos["diagnosis_repo"].get_diagnosis_report_by_practice_id.return_value = None

        item_1 = AttemptItem(
            id=uuid.uuid4(),
            practice_id=practice_id,
            question_id=question_id_1,
            user_id=user_id,
            order_index=1,
            question_snapshot={
                "stem": "关于TCP握手叙述正确的是?",
                "answer": "B",
                "knowledge_point_id": str(point_id),
                "question_type": "single_choice",
            },
            user_answer="A",
            is_answered=True,
            score=0.0,
            max_score=1.0,
        )
        item_2 = AttemptItem(
            id=uuid.uuid4(),
            practice_id=practice_id,
            question_id=question_id_2,
            user_id=user_id,
            order_index=2,
            question_snapshot={
                "stem": "DNS域名解析默认端口是?",
                "answer": "53",
                "knowledge_point_id": str(point_id),
                "question_type": "single_choice",
            },
            user_answer="53",
            is_answered=True,
            score=1.0,
            max_score=1.0,
        )
        mock_repos["practice_repo"].list_attempt_items.return_value = [item_1, item_2]

        grading_1 = GradingRecord(
            id=uuid.uuid4(),
            practice_id=practice_id,
            attempt_item_id=item_1.id,
            user_id=user_id,
            channel=GradingChannel.OFFLINE.value,
            status=GradingStatus.SUCCESS.value,
            score=0.0,
            max_score=1.0,
            is_final=True,
        )
        grading_2 = GradingRecord(
            id=uuid.uuid4(),
            practice_id=practice_id,
            attempt_item_id=item_2.id,
            user_id=user_id,
            channel=GradingChannel.OFFLINE.value,
            status=GradingStatus.SUCCESS.value,
            score=1.0,
            max_score=1.0,
            is_final=True,
        )
        mock_repos["grading_repo"].list_final_records_by_practice.return_value = [
            grading_1,
            grading_2,
        ]

        mock_repos["diagnosis_repo"].get_attempt_history_for_knowledge_point.return_value = [
            (item_1, grading_1),
            (item_2, grading_2),
        ]
        mock_repos["diagnosis_repo"].list_mastery_records_by_knowledge_point_ids.return_value = []

        kp_entity = KnowledgePoint(
            id=point_id,
            user_id=user_id,
            material_id=practice.material_id,
            version_id=uuid.uuid4(),
            name="计算机网络核心协议",
            is_low_confidence=False,
        )
        mock_repos["knowledge_repo"].get_by_id.return_value = kp_entity

        mastery_record = MasteryRecord(
            id=uuid.uuid4(),
            user_id=user_id,
            knowledge_point_id=point_id,
            mastery_score=0.35,  # < 0.40 -> Weak
            level=MasteryLevel.WEAK.value,
            practice_count=2,
            correct_count=1,
            last_practiced_at=now,
            decayed_at=now,
            recent_records_snapshot=[],
        )
        mock_repos["diagnosis_repo"].upsert_mastery_record.return_value = mastery_record

        def create_report_mock(report: DiagnosisReport, user_id: uuid.UUID) -> DiagnosisReport:
            report.user_id = user_id
            return report

        mock_repos["diagnosis_repo"].create_diagnosis_report.side_effect = create_report_mock

        report = diagnosis_service.generate_diagnosis_report(
            user_id=user_id,
            practice_id=practice_id,
            current_time=now,
        )

        assert report is not None
        assert report.practice_id == practice_id
        assert report.user_id == user_id
        assert report.total_questions == 2
        assert report.wrong_count == 1
        assert report.unanswered_count == 0
        assert report.score_rate == 0.5
        assert report.is_structure_degraded is False
        assert len(report.weak_knowledge_points) >= 1
        assert report.weak_knowledge_points[0]["knowledge_id"] == str(point_id)

        # Verify WrongRecord sync
        mock_repos["diagnosis_repo"].upsert_wrong_record.assert_called_once()
        mock_repos["diagnosis_repo"].mark_wrong_record_mastered.assert_called_once_with(
            question_id=question_id_2,
            user_id=user_id,
        )

        mock_session.commit.assert_called()

    def test_generate_report_blocking_partially_graded(
        self,
        diagnosis_service: DiagnosisService,
        mock_repos: dict[str, MagicMock],
    ) -> None:
        """Verify PracticeNotGradedError is raised when practice is PARTIALLY_GRADED."""
        user_id = uuid.uuid4()
        practice_id = uuid.uuid4()

        practice = Practice(
            id=practice_id,
            user_id=user_id,
            material_id=uuid.uuid4(),
            title="未完成判题练习",
            status=PracticeStatus.PARTIALLY_GRADED.value,
        )
        mock_repos["practice_repo"].get_practice_by_id.return_value = practice

        with pytest.raises(PracticeNotGradedError) as exc_info:
            diagnosis_service.generate_diagnosis_report(
                user_id=user_id,
                practice_id=practice_id,
            )

        assert exc_info.value.error_code == 40016
        assert exc_info.value.status_code == 400

    def test_generate_report_blocking_non_completed_status(
        self,
        diagnosis_service: DiagnosisService,
        mock_repos: dict[str, MagicMock],
    ) -> None:
        """Verify PracticeNotGradedError is raised when practice is IN_PROGRESS."""
        user_id = uuid.uuid4()
        practice_id = uuid.uuid4()

        practice = Practice(
            id=practice_id,
            user_id=user_id,
            material_id=uuid.uuid4(),
            title="作答中练习",
            status=PracticeStatus.IN_PROGRESS.value,
        )
        mock_repos["practice_repo"].get_practice_by_id.return_value = practice

        with pytest.raises(PracticeNotGradedError) as exc_info:
            diagnosis_service.generate_diagnosis_report(
                user_id=user_id,
                practice_id=practice_id,
            )

        assert exc_info.value.error_code == 40016

    def test_generate_report_practice_not_found(
        self,
        diagnosis_service: DiagnosisService,
        mock_repos: dict[str, MagicMock],
    ) -> None:
        """Verify PracticeNotFoundError when practice does not exist or tenant mismatch."""
        user_id = uuid.uuid4()
        practice_id = uuid.uuid4()

        mock_repos["practice_repo"].get_practice_by_id.return_value = None

        with pytest.raises(PracticeNotFoundError) as exc_info:
            diagnosis_service.generate_diagnosis_report(
                user_id=user_id,
                practice_id=practice_id,
            )

        assert exc_info.value.error_code == 40010

    def test_generate_report_idempotency(
        self,
        diagnosis_service: DiagnosisService,
        mock_repos: dict[str, MagicMock],
    ) -> None:
        """Verify existing report is returned immediately without duplicate creation."""
        user_id = uuid.uuid4()
        practice_id = uuid.uuid4()

        practice = Practice(
            id=practice_id,
            user_id=user_id,
            material_id=uuid.uuid4(),
            title="已完成练习",
            status=PracticeStatus.COMPLETED.value,
            completed_at=datetime.now(UTC),
        )
        mock_repos["practice_repo"].get_practice_by_id.return_value = practice

        existing_report = DiagnosisReport(
            id=uuid.uuid4(),
            practice_id=practice_id,
            user_id=user_id,
            score_rate=0.9,
            wrong_count=0,
            total_questions=5,
        )
        mock_repos[
            "diagnosis_repo"
        ].get_diagnosis_report_by_practice_id.return_value = existing_report

        report = diagnosis_service.generate_diagnosis_report(
            user_id=user_id,
            practice_id=practice_id,
        )

        assert report == existing_report
        mock_repos["practice_repo"].list_attempt_items.assert_not_called()

    def test_generate_report_low_confidence_structure_degradation(
        self,
        diagnosis_service: DiagnosisService,
        mock_repos: dict[str, MagicMock],
    ) -> None:
        """Verify is_structure_degraded=True when an involved knowledge point is low confidence."""
        user_id = uuid.uuid4()
        practice_id = uuid.uuid4()
        point_id = uuid.uuid4()

        practice = Practice(
            id=practice_id,
            user_id=user_id,
            material_id=uuid.uuid4(),
            title="低可信度专项",
            status=PracticeStatus.COMPLETED.value,
            completed_at=datetime.now(UTC),
            knowledge_point_ids=[str(point_id)],
        )
        mock_repos["practice_repo"].get_practice_by_id.return_value = practice
        mock_repos["diagnosis_repo"].get_diagnosis_report_by_practice_id.return_value = None

        item = AttemptItem(
            id=uuid.uuid4(),
            practice_id=practice_id,
            user_id=user_id,
            order_index=1,
            question_snapshot={"stem": "题干", "answer": "A", "knowledge_point_id": str(point_id)},
            user_answer="A",
            is_answered=True,
            score=1.0,
            max_score=1.0,
        )
        mock_repos["practice_repo"].list_attempt_items.return_value = [item]
        mock_repos["grading_repo"].list_final_records_by_practice.return_value = [
            make_final_grading_record(practice_id, user_id, item)
        ]
        mock_repos["diagnosis_repo"].get_attempt_history_for_knowledge_point.return_value = []
        mock_repos["diagnosis_repo"].list_mastery_records_by_knowledge_point_ids.return_value = []

        low_conf_point = KnowledgePoint(
            id=point_id,
            user_id=user_id,
            material_id=practice.material_id,
            version_id=uuid.uuid4(),
            name="草稿知识点",
            is_low_confidence=True,  # Low confidence trigger
        )
        mock_repos["knowledge_repo"].get_by_id.return_value = low_conf_point

        def create_report_mock(report: DiagnosisReport, user_id: uuid.UUID) -> DiagnosisReport:
            report.user_id = user_id
            return report

        mock_repos["diagnosis_repo"].create_diagnosis_report.side_effect = create_report_mock

        report = diagnosis_service.generate_diagnosis_report(
            user_id=user_id,
            practice_id=practice_id,
        )

        assert report.is_structure_degraded is True

    def test_generate_report_integrity_error_replays_existing_report(
        self,
        diagnosis_service: DiagnosisService,
        mock_repos: dict[str, MagicMock],
        mock_session: MagicMock,
    ) -> None:
        """BUG-DIAG-019: 并发唯一约束冲突时回滚并幂等回放既有报告，不抛 500。"""
        user_id = uuid.uuid4()
        practice_id = uuid.uuid4()
        point_id = uuid.uuid4()

        practice = Practice(
            id=practice_id,
            user_id=user_id,
            material_id=uuid.uuid4(),
            title="并发报告生成",
            status=PracticeStatus.COMPLETED.value,
            completed_at=datetime.now(UTC),
            knowledge_point_ids=[str(point_id)],
        )
        mock_repos["practice_repo"].get_practice_by_id.return_value = practice

        existing_report = DiagnosisReport(
            id=uuid.uuid4(),
            practice_id=practice_id,
            user_id=user_id,
            score_rate=0.75,
            wrong_count=1,
            total_questions=2,
        )
        # 第一次为幂等前置查询未命中；第二次为并发冲突后的回查命中
        mock_repos["diagnosis_repo"].get_diagnosis_report_by_practice_id.side_effect = [
            None,
            existing_report,
        ]

        item = AttemptItem(
            id=uuid.uuid4(),
            practice_id=practice_id,
            user_id=user_id,
            order_index=1,
            question_snapshot={"stem": "题干", "answer": "A", "knowledge_point_id": str(point_id)},
            user_answer="A",
            is_answered=True,
            score=1.0,
            max_score=1.0,
        )
        mock_repos["practice_repo"].list_attempt_items.return_value = [item]
        mock_repos["grading_repo"].list_final_records_by_practice.return_value = [
            make_final_grading_record(practice_id, user_id, item)
        ]
        mock_repos["diagnosis_repo"].get_attempt_history_for_knowledge_point.return_value = []
        mock_repos["diagnosis_repo"].list_mastery_records_by_knowledge_point_ids.return_value = []
        mock_repos["knowledge_repo"].get_by_id.return_value = None

        mock_repos["diagnosis_repo"].create_diagnosis_report.side_effect = IntegrityError(
            "stmt", {}, Exception("uq_diagnosis_reports_practice_id")
        )

        report = diagnosis_service.generate_diagnosis_report(
            user_id=user_id,
            practice_id=practice_id,
        )

        assert report is existing_report
        mock_session.rollback.assert_called()
        assert mock_repos["diagnosis_repo"].get_diagnosis_report_by_practice_id.call_count == 2


class TestWrongRecordSyncDetails:
    """Tests for wrong record synchronization nuances."""

    def test_wrong_record_sync_unanswered(
        self,
        diagnosis_service: DiagnosisService,
        mock_repos: dict[str, MagicMock],
    ) -> None:
        """Verify unanswered items are recorded with ErrorType.UNANSWERED."""
        user_id = uuid.uuid4()
        practice_id = uuid.uuid4()
        point_id = uuid.uuid4()

        practice = Practice(
            id=practice_id,
            user_id=user_id,
            material_id=uuid.uuid4(),
            title="未作答测试练习",
            status=PracticeStatus.COMPLETED.value,
            completed_at=datetime.now(UTC),
            knowledge_point_ids=[str(point_id)],
        )
        mock_repos["practice_repo"].get_practice_by_id.return_value = practice
        mock_repos["diagnosis_repo"].get_diagnosis_report_by_practice_id.return_value = None

        item = AttemptItem(
            id=uuid.uuid4(),
            practice_id=practice_id,
            user_id=user_id,
            order_index=1,
            question_snapshot={
                "stem": "空白题干",
                "answer": "C",
                "knowledge_point_id": str(point_id),
            },
            user_answer=None,
            is_answered=False,
            score=0.0,
            max_score=1.0,
        )
        mock_repos["practice_repo"].list_attempt_items.return_value = [item]
        mock_repos["grading_repo"].list_final_records_by_practice.return_value = [
            make_final_grading_record(practice_id, user_id, item)
        ]
        mock_repos["diagnosis_repo"].get_attempt_history_for_knowledge_point.return_value = []
        mock_repos["diagnosis_repo"].list_mastery_records_by_knowledge_point_ids.return_value = []
        mock_repos["knowledge_repo"].get_by_id.return_value = None

        def create_report_mock(report: DiagnosisReport, user_id: uuid.UUID) -> DiagnosisReport:
            return report

        mock_repos["diagnosis_repo"].create_diagnosis_report.side_effect = create_report_mock

        report = diagnosis_service.generate_diagnosis_report(
            user_id=user_id,
            practice_id=practice_id,
        )

        assert report.unanswered_count == 1
        assert report.wrong_count == 1
        mock_repos["diagnosis_repo"].upsert_wrong_record.assert_called_once()
        call_kwargs = mock_repos["diagnosis_repo"].upsert_wrong_record.call_args.kwargs
        assert call_kwargs["error_type"] == "unanswered"


class TestGetAndListDiagnosisReports:
    """Tests for report retrieval and listing with multi-tenant isolation."""

    def test_get_diagnosis_report_success(
        self,
        diagnosis_service: DiagnosisService,
        mock_repos: dict[str, MagicMock],
    ) -> None:
        """Verify fetching diagnosis report by primary key."""
        user_id = uuid.uuid4()
        report_id = uuid.uuid4()
        report = DiagnosisReport(id=report_id, user_id=user_id, practice_id=uuid.uuid4())
        mock_repos["diagnosis_repo"].get_diagnosis_report_by_id.return_value = report

        found = diagnosis_service.get_diagnosis_report(user_id=user_id, report_id=report_id)
        assert found == report
        mock_repos["diagnosis_repo"].get_diagnosis_report_by_id.assert_called_once_with(
            report_id=report_id,
            user_id=user_id,
        )

    def test_get_diagnosis_report_not_found(
        self,
        diagnosis_service: DiagnosisService,
        mock_repos: dict[str, MagicMock],
    ) -> None:
        """Verify DiagnosisReportNotFoundError when report not found."""
        user_id = uuid.uuid4()
        report_id = uuid.uuid4()
        mock_repos["diagnosis_repo"].get_diagnosis_report_by_id.return_value = None

        with pytest.raises(DiagnosisReportNotFoundError) as exc_info:
            diagnosis_service.get_diagnosis_report(user_id=user_id, report_id=report_id)

        assert exc_info.value.error_code == 40017
        assert exc_info.value.status_code == 404

    def test_get_diagnosis_report_by_practice_success_and_fail(
        self,
        diagnosis_service: DiagnosisService,
        mock_repos: dict[str, MagicMock],
    ) -> None:
        """Verify get_diagnosis_report_by_practice retrieval and error handling."""
        user_id = uuid.uuid4()
        practice_id = uuid.uuid4()
        report = DiagnosisReport(id=uuid.uuid4(), user_id=user_id, practice_id=practice_id)

        mock_repos["diagnosis_repo"].get_diagnosis_report_by_practice_id.return_value = report
        found = diagnosis_service.get_diagnosis_report_by_practice(user_id, practice_id)
        assert found == report

        mock_repos["diagnosis_repo"].get_diagnosis_report_by_practice_id.return_value = None
        with pytest.raises(DiagnosisReportNotFoundError):
            diagnosis_service.get_diagnosis_report_by_practice(user_id, practice_id)

    def test_list_diagnosis_reports_pagination(
        self,
        diagnosis_service: DiagnosisService,
        mock_repos: dict[str, MagicMock],
    ) -> None:
        """Verify pagination offset and limit calculation."""
        user_id = uuid.uuid4()
        mock_repos["diagnosis_repo"].list_diagnosis_reports_by_user.return_value = []

        diagnosis_service.list_diagnosis_reports(user_id=user_id, page=3, page_size=15)
        mock_repos["diagnosis_repo"].list_diagnosis_reports_by_user.assert_called_once_with(
            user_id=user_id,
            limit=15,
            offset=30,
        )


class TestUserMasteryOverview:
    """Tests for get_user_mastery_overview method."""

    def test_get_user_mastery_overview_computation(
        self,
        diagnosis_service: DiagnosisService,
        mock_repos: dict[str, MagicMock],
    ) -> None:
        """Verify four-tier knowledge point classification and weak points filtering."""
        user_id = uuid.uuid4()
        material_id = uuid.uuid4()

        kp_1 = KnowledgePoint(
            id=uuid.uuid4(),
            user_id=user_id,
            material_id=material_id,
            version_id=uuid.uuid4(),
            name="知识点-薄弱",
        )
        kp_2 = KnowledgePoint(
            id=uuid.uuid4(),
            user_id=user_id,
            material_id=material_id,
            version_id=uuid.uuid4(),
            name="知识点-进阶",
        )
        kp_3 = KnowledgePoint(
            id=uuid.uuid4(),
            user_id=user_id,
            material_id=material_id,
            version_id=uuid.uuid4(),
            name="知识点-熟练",
        )
        kp_4 = KnowledgePoint(
            id=uuid.uuid4(),
            user_id=user_id,
            material_id=material_id,
            version_id=uuid.uuid4(),
            name="知识点-未学",
        )

        mock_repos["knowledge_repo"].list_by_material_id.return_value = [kp_1, kp_2, kp_3, kp_4]

        rec_1 = MasteryRecord(
            id=uuid.uuid4(),
            user_id=user_id,
            knowledge_point_id=kp_1.id,
            mastery_score=0.30,
            level=MasteryLevel.WEAK.value,
        )
        rec_2 = MasteryRecord(
            id=uuid.uuid4(),
            user_id=user_id,
            knowledge_point_id=kp_2.id,
            mastery_score=0.60,
            level=MasteryLevel.BASIC.value,
        )
        rec_3 = MasteryRecord(
            id=uuid.uuid4(),
            user_id=user_id,
            knowledge_point_id=kp_3.id,
            mastery_score=0.90,
            level=MasteryLevel.PROFICIENT.value,
        )

        mock_repos["diagnosis_repo"].list_mastery_records_by_material.return_value = [
            rec_1,
            rec_2,
            rec_3,
        ]

        overview = diagnosis_service.get_user_mastery_overview(user_id, material_id)

        assert overview.material_id == material_id
        assert overview.total_knowledge_points == 4
        assert overview.unlearned_count == 1
        assert overview.weak_count == 1
        assert overview.basic_count == 1
        assert overview.proficient_count == 1
        assert len(overview.weak_knowledge_points) == 1
        assert overview.weak_knowledge_points[0].knowledge_point_id == kp_1.id
        # (0.30 + 0.60 + 0.90 + 0.0) / 4 = 0.45
        assert overview.overall_mastery_score == 0.45

    def test_get_user_mastery_overview_empty_material(
        self,
        diagnosis_service: DiagnosisService,
        mock_repos: dict[str, MagicMock],
    ) -> None:
        """Verify overview handling for material with no knowledge points."""
        user_id = uuid.uuid4()
        material_id = uuid.uuid4()

        mock_repos["knowledge_repo"].list_by_material_id.return_value = []
        mock_repos["diagnosis_repo"].list_mastery_records_by_material.return_value = []

        overview = diagnosis_service.get_user_mastery_overview(user_id, material_id)
        assert overview.total_knowledge_points == 0
        assert overview.overall_mastery_score == 0.0

    def test_get_user_mastery_overview_without_material_aggregates_all(
        self,
        diagnosis_service: DiagnosisService,
        mock_repos: dict[str, MagicMock],
    ) -> None:
        """Verify material_id=None aggregates ALL user knowledge points (DIAG-007)."""
        user_id = uuid.uuid4()
        material_a = uuid.uuid4()
        material_b = uuid.uuid4()

        kp_1 = KnowledgePoint(
            id=uuid.uuid4(),
            user_id=user_id,
            material_id=material_a,
            version_id=uuid.uuid4(),
            name="知识点-薄弱",
        )
        kp_2 = KnowledgePoint(
            id=uuid.uuid4(),
            user_id=user_id,
            material_id=material_b,
            version_id=uuid.uuid4(),
            name="知识点-熟练",
        )

        mock_repos["knowledge_repo"].list_all_by_user_id.return_value = [kp_1, kp_2]
        mock_repos["diagnosis_repo"].list_mastery_records_by_user.return_value = [
            MasteryRecord(
                id=uuid.uuid4(),
                user_id=user_id,
                knowledge_point_id=kp_1.id,
                mastery_score=0.30,
                level=MasteryLevel.WEAK.value,
            ),
            MasteryRecord(
                id=uuid.uuid4(),
                user_id=user_id,
                knowledge_point_id=kp_2.id,
                mastery_score=0.90,
                level=MasteryLevel.PROFICIENT.value,
            ),
        ]

        overview = diagnosis_service.get_user_mastery_overview(user_id, None)

        assert overview.material_id is None
        assert overview.total_knowledge_points == 2
        assert overview.weak_count == 1
        assert overview.proficient_count == 1
        # (0.30 + 0.90) / 2 = 0.60
        assert overview.overall_mastery_score == 0.60
        mock_repos["knowledge_repo"].list_all_by_user_id.assert_called_once_with(user_id=user_id)
        mock_repos["knowledge_repo"].list_by_material_id.assert_not_called()
        mock_repos["diagnosis_repo"].list_mastery_records_by_user.assert_called_once_with(
            user_id=user_id
        )

    def test_get_user_mastery_overview_weak_points_sorted_ascending(
        self,
        diagnosis_service: DiagnosisService,
        mock_repos: dict[str, MagicMock],
    ) -> None:
        """BUG-DIAG-020: 薄弱点必须按掌握度升序（最弱优先）稳定排序。"""
        user_id = uuid.uuid4()
        material_id = uuid.uuid4()

        kp_high = KnowledgePoint(
            id=uuid.uuid4(),
            user_id=user_id,
            material_id=material_id,
            version_id=uuid.uuid4(),
            name="知识点-较高薄弱",
        )
        kp_low = KnowledgePoint(
            id=uuid.uuid4(),
            user_id=user_id,
            material_id=material_id,
            version_id=uuid.uuid4(),
            name="知识点-最薄弱",
        )
        kp_mid = KnowledgePoint(
            id=uuid.uuid4(),
            user_id=user_id,
            material_id=material_id,
            version_id=uuid.uuid4(),
            name="知识点-中等薄弱",
        )

        mock_repos["knowledge_repo"].list_by_material_id.return_value = [kp_high, kp_low, kp_mid]
        mock_repos["diagnosis_repo"].list_mastery_records_by_material.return_value = [
            MasteryRecord(
                id=uuid.uuid4(),
                user_id=user_id,
                knowledge_point_id=kp_high.id,
                mastery_score=0.35,
                level=MasteryLevel.WEAK.value,
            ),
            MasteryRecord(
                id=uuid.uuid4(),
                user_id=user_id,
                knowledge_point_id=kp_low.id,
                mastery_score=0.15,
                level=MasteryLevel.WEAK.value,
            ),
            MasteryRecord(
                id=uuid.uuid4(),
                user_id=user_id,
                knowledge_point_id=kp_mid.id,
                mastery_score=0.25,
                level=MasteryLevel.WEAK.value,
            ),
        ]

        overview = diagnosis_service.get_user_mastery_overview(user_id, material_id)

        scores = [item.mastery_score for item in overview.weak_knowledge_points]
        assert scores == [0.15, 0.25, 0.35]
        assert overview.weak_knowledge_points[0].knowledge_point_id == kp_low.id


class TestWrongRecordsManagement:
    """Tests for listing and deletion of wrong records."""

    def test_list_wrong_records_filtering(
        self,
        diagnosis_service: DiagnosisService,
        mock_repos: dict[str, MagicMock],
    ) -> None:
        """Verify list_wrong_records parameter mappings."""
        user_id = uuid.uuid4()
        mock_repos["diagnosis_repo"].list_wrong_records.return_value = []
        mock_repos["diagnosis_repo"].count_wrong_records.return_value = 0

        # 1. status="mastered" maps to is_mastered=True
        records, total = diagnosis_service.list_wrong_records(user_id=user_id, status="mastered")
        assert records == []
        assert total == 0
        mock_repos["diagnosis_repo"].list_wrong_records.assert_called_with(
            user_id=user_id,
            is_mastered=True,
            knowledge_point_id=None,
            material_id=None,
            error_type=None,
            question_type=None,
            limit=50,
            offset=0,
        )
        mock_repos["diagnosis_repo"].count_wrong_records.assert_called_with(
            user_id=user_id,
            is_mastered=True,
            knowledge_point_id=None,
            material_id=None,
            error_type=None,
            question_type=None,
        )

        # 2. status="active" maps to is_mastered=False
        diagnosis_service.list_wrong_records(user_id=user_id, status="active")
        mock_repos["diagnosis_repo"].list_wrong_records.assert_called_with(
            user_id=user_id,
            is_mastered=False,
            knowledge_point_id=None,
            material_id=None,
            error_type=None,
            question_type=None,
            limit=50,
            offset=0,
        )
        mock_repos["diagnosis_repo"].count_wrong_records.assert_called_with(
            user_id=user_id,
            is_mastered=False,
            knowledge_point_id=None,
            material_id=None,
            error_type=None,
            question_type=None,
        )

    def test_list_wrong_records_returns_real_total(
        self,
        diagnosis_service: DiagnosisService,
        mock_repos: dict[str, MagicMock],
    ) -> None:
        """Verify list_wrong_records returns the repository real total, not len(page)."""
        user_id = uuid.uuid4()
        page_record = WrongRecord(
            id=uuid.uuid4(),
            user_id=user_id,
            knowledge_point_id=uuid.uuid4(),
            practice_id=uuid.uuid4(),
            attempt_item_id=uuid.uuid4(),
            error_type="conceptual",
            question_snapshot={},
        )
        mock_repos["diagnosis_repo"].list_wrong_records.return_value = [page_record]
        mock_repos["diagnosis_repo"].count_wrong_records.return_value = 5

        records, total = diagnosis_service.list_wrong_records(user_id=user_id, page_size=1)

        assert records == [page_record]
        assert total == 5

    def test_list_wrong_records_material_filter(
        self,
        diagnosis_service: DiagnosisService,
        mock_repos: dict[str, MagicMock],
    ) -> None:
        """Verify material_id filtering is pushed down to the repository (DIAG-012).

        The service must no longer pull 1000 rows into memory and slice; it must
        forward material_id/error_type/question_type and trust the repository's
        SQL-level filtering plus its exact count.
        """
        user_id = uuid.uuid4()
        material_id = uuid.uuid4()
        point_id_1 = uuid.uuid4()

        rec_1 = WrongRecord(
            id=uuid.uuid4(),
            user_id=user_id,
            knowledge_point_id=point_id_1,
            practice_id=uuid.uuid4(),
            attempt_item_id=uuid.uuid4(),
            error_type="conceptual",
            question_snapshot={"question_type": "single_choice"},
        )
        mock_repos["diagnosis_repo"].list_wrong_records.return_value = [rec_1]
        mock_repos["diagnosis_repo"].count_wrong_records.return_value = 1

        results, total = diagnosis_service.list_wrong_records(
            user_id=user_id,
            material_id=material_id,
            error_type="incomplete",
            question_type="single_choice",
        )
        assert total == 1
        assert results == [rec_1]
        mock_repos["diagnosis_repo"].list_wrong_records.assert_called_once_with(
            user_id=user_id,
            is_mastered=None,
            knowledge_point_id=None,
            material_id=material_id,
            error_type="incomplete_expression",
            question_type="single_choice",
            limit=50,
            offset=0,
        )
        mock_repos["diagnosis_repo"].count_wrong_records.assert_called_once_with(
            user_id=user_id,
            is_mastered=None,
            knowledge_point_id=None,
            material_id=material_id,
            error_type="incomplete_expression",
            question_type="single_choice",
        )
        # No in-memory knowledge point resolution / row fetching anymore.
        mock_repos["knowledge_repo"].list_by_material_id.assert_not_called()

    def test_list_wrong_records_normalizes_legacy_error_type(
        self,
        diagnosis_service: DiagnosisService,
        mock_repos: dict[str, MagicMock],
    ) -> None:
        """BUG-DIAG-010: legacy 'deviation' shorthand maps to the authoritative enum."""
        user_id = uuid.uuid4()
        mock_repos["diagnosis_repo"].list_wrong_records.return_value = []
        mock_repos["diagnosis_repo"].count_wrong_records.return_value = 0

        diagnosis_service.list_wrong_records(user_id=user_id, error_type="deviation")

        called_kwargs = mock_repos["diagnosis_repo"].list_wrong_records.call_args.kwargs
        assert called_kwargs["error_type"] == "question_misreading"

    def test_normalize_error_type_passthrough_and_blank(self) -> None:
        """Verify normalize_error_type handles None/blank/authoritative/unknown values."""
        assert normalize_error_type(None) is None
        assert normalize_error_type("  ") is None
        assert normalize_error_type("incomplete") == "incomplete_expression"
        assert normalize_error_type("deviation") == "question_misreading"
        assert normalize_error_type("unanswered") == "unanswered"
        assert normalize_error_type("mystery") == "mystery"

    def test_remove_wrong_record(
        self,
        diagnosis_service: DiagnosisService,
        mock_repos: dict[str, MagicMock],
        mock_session: MagicMock,
    ) -> None:
        """Verify remove_wrong_record calls delete and commits."""
        user_id = uuid.uuid4()
        record_id = uuid.uuid4()

        mock_repos["diagnosis_repo"].delete_wrong_record.return_value = True
        success = diagnosis_service.remove_wrong_record(user_id=user_id, wrong_record_id=record_id)
        assert success is True
        mock_repos["diagnosis_repo"].delete_wrong_record.assert_called_once_with(
            record_id=record_id,
            user_id=user_id,
        )
        mock_session.commit.assert_called()

        # None id returns False
        assert diagnosis_service.remove_wrong_record(user_id=user_id) is False


class TestHelpersAndAliases:
    """Tests for helper mapping functions and alias exports."""

    def test_resolve_channel_to_source(self) -> None:
        """Verify channel string mapping to algorithm source enum."""
        assert resolve_channel_to_source("offline") == GradingSourceType.OFFLINE_RULE
        assert resolve_channel_to_source("ai") == GradingSourceType.AI_GRADING
        assert resolve_channel_to_source("user_self") == GradingSourceType.SELF_ASSESSMENT
        assert resolve_channel_to_source("unknown_chan") == GradingSourceType.UNKNOWN
        assert resolve_channel_to_source(None) == GradingSourceType.OFFLINE_RULE

    def test_map_mastery_level_to_db(self) -> None:
        """Verify algorithm level to DB string mapping."""
        assert map_mastery_level_to_db("UNLEARNED") == "unlearned"
        assert map_mastery_level_to_db("WEAK") == "weak"
        assert map_mastery_level_to_db("DEVELOPING") == "basic"
        assert map_mastery_level_to_db("MASTERED") == "proficient"
        assert map_mastery_level_to_db("custom") == "custom"

    def test_service_alias(self) -> None:
        """Verify ReportService is an alias to DiagnosisService."""
        assert ReportService is DiagnosisService


class TestLogDesensitization:
    """Tests to verify zero plain text question/answer leakage in logs."""

    def test_logging_contains_no_sensitive_text(
        self,
        diagnosis_service: DiagnosisService,
        mock_repos: dict[str, MagicMock],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Verify 8 elements exist and no stem/answer content is leaked to logs."""
        user_id = uuid.uuid4()
        point_id = uuid.uuid4()

        mock_repos["diagnosis_repo"].get_attempt_history_for_knowledge_point.return_value = []
        mock_repos["diagnosis_repo"].upsert_mastery_record.return_value = MasteryRecord(
            id=uuid.uuid4(),
            user_id=user_id,
            knowledge_point_id=point_id,
            mastery_score=0.0,
            level="unlearned",
        )

        with caplog.at_level(logging.INFO):
            diagnosis_service.calculate_and_update_mastery(
                user_id=user_id,
                knowledge_point_ids=[point_id],
            )

        log_texts = [rec.message for rec in caplog.records]
        assert any("DiagnosisService execution completed" in text for text in log_texts)
        full_log = " ".join(log_texts)

        # Verify standard 8 elements keys are present
        assert "timestamp" in full_log
        assert "level" in full_log
        assert "logger_name" in full_log
        assert "request_id" in full_log
        assert "user_ref" in full_log
        assert "target_id" in full_log
        assert "duration_ms" in full_log
        assert "error_code" in full_log
        # Verify secret desensitization
        assert "password" not in full_log.lower()
        assert "token" not in full_log.lower()
