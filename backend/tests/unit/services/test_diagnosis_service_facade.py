"""学情诊断领域服务门面扩展方法单元测试。

测试 DiagnosisService 门面方法：
1. get_knowledge_mastery：正常返回及不存在抛出 MasteryRecordNotFoundError；
2. mark_wrong_record_mastered：正常标记及不存在抛出 WrongRecordNotFoundError；
3. remove_wrong_record：正常删除及不存在抛出 WrongRecordNotFoundError。
严格遵循 AGENTS.md 规范：
- 缩写白名单仅限 api, id, url, ocr, llm, db, config, env；
- 单元测试毫秒级执行，网络与真实数据库隔离。
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from app.core.errors import MasteryRecordNotFoundError, WrongRecordNotFoundError
from app.models.knowledge import KnowledgePoint
from app.models.practice import MasteryRecord, WrongRecord
from app.services.diagnosis import DiagnosisService, KnowledgeMasterySummaryDTO


@pytest.fixture
def mock_session() -> MagicMock:
    """提供模拟 SQLAlchemy 会话。"""
    session = MagicMock()
    session.commit = MagicMock()
    session.flush = MagicMock()
    return session


@pytest.fixture
def mock_repos() -> dict[str, MagicMock]:
    """提供核心仓储 Mock 字典。"""
    return {
        "diagnosis_repo": MagicMock(),
        "practice_repo": MagicMock(),
        "grading_repo": MagicMock(),
        "knowledge_repo": MagicMock(),
    }


@pytest.fixture
def service(mock_session: MagicMock, mock_repos: dict[str, MagicMock]) -> DiagnosisService:
    """初始化装配 Mock 仓储的 DiagnosisService 实例。"""
    return DiagnosisService(
        session=mock_session,
        diagnosis_repo=mock_repos["diagnosis_repo"],
        practice_repo=mock_repos["practice_repo"],
        grading_repo=mock_repos["grading_repo"],
        knowledge_repo=mock_repos["knowledge_repo"],
    )


class TestDiagnosisServiceFacade:
    """门面方法单元测试集。"""

    def test_get_knowledge_mastery_success(
        self,
        service: DiagnosisService,
        mock_repos: dict[str, MagicMock],
    ) -> None:
        """测试获取单个知识点掌握度汇总成功。"""
        user_id = uuid.uuid4()
        point_id = uuid.uuid4()
        now = datetime.now(UTC)

        fake_record = MasteryRecord(
            id=uuid.uuid4(),
            user_id=user_id,
            knowledge_point_id=point_id,
            mastery_score=0.82,
            level="proficient",
            practice_count=10,
            correct_count=8,
            last_practiced_at=now,
        )
        fake_kp = KnowledgePoint(
            id=point_id,
            name="二分查找",
            material_id=uuid.uuid4(),
            user_id=user_id,
        )

        mock_repos["diagnosis_repo"].get_mastery_record.return_value = fake_record
        mock_repos["knowledge_repo"].get_by_id.return_value = fake_kp

        result = service.get_knowledge_mastery(user_id=user_id, knowledge_point_id=point_id)

        assert isinstance(result, KnowledgeMasterySummaryDTO)
        assert result.knowledge_point_id == point_id
        assert result.knowledge_name == "二分查找"
        assert result.mastery_score == 0.82
        assert result.level == "proficient"
        assert result.practice_count == 10
        assert result.correct_count == 8
        assert result.last_practiced_at == now
        mock_repos["diagnosis_repo"].get_mastery_record.assert_called_once_with(
            knowledge_point_id=point_id,
            user_id=user_id,
        )

    def test_get_knowledge_mastery_not_found(
        self,
        service: DiagnosisService,
        mock_repos: dict[str, MagicMock],
    ) -> None:
        """测试获取不存在知识点掌握度时抛出 MasteryRecordNotFoundError (404/40018)。"""
        user_id = uuid.uuid4()
        point_id = uuid.uuid4()

        mock_repos["diagnosis_repo"].get_mastery_record.return_value = None

        with pytest.raises(MasteryRecordNotFoundError) as exc_info:
            service.get_knowledge_mastery(user_id=user_id, knowledge_point_id=point_id)

        assert exc_info.value.error_code == 40018
        assert exc_info.value.status_code == 404
        assert exc_info.value.details.get("knowledge_point_id") == str(point_id)

    def test_mark_wrong_record_mastered_success(
        self,
        service: DiagnosisService,
        mock_session: MagicMock,
        mock_repos: dict[str, MagicMock],
    ) -> None:
        """测试将错题标记为已掌握成功并提交事务。"""
        user_id = uuid.uuid4()
        record_id = uuid.uuid4()
        now = datetime.now(UTC)

        fake_record = WrongRecord(
            id=record_id,
            user_id=user_id,
            question_id=uuid.uuid4(),
            knowledge_point_id=uuid.uuid4(),
            practice_id=uuid.uuid4(),
            attempt_item_id=uuid.uuid4(),
            error_type="conceptual",
            is_mastered=True,
            mastered_at=now,
        )

        mock_repos["diagnosis_repo"].mark_wrong_record_mastered.return_value = fake_record

        result = service.mark_wrong_record_mastered(user_id=user_id, record_id=record_id)

        assert result is fake_record
        assert result.is_mastered is True
        mock_repos["diagnosis_repo"].mark_wrong_record_mastered.assert_called_once_with(
            wrong_record_id=record_id,
            user_id=user_id,
            is_mastered=True,
        )
        mock_session.commit.assert_called_once()

    def test_mark_wrong_record_unmastered(
        self,
        service: DiagnosisService,
        mock_session: MagicMock,
        mock_repos: dict[str, MagicMock],
    ) -> None:
        """测试取消错题攻克状态时透传 is_mastered=False。"""
        user_id = uuid.uuid4()
        record_id = uuid.uuid4()

        fake_record = WrongRecord(
            id=record_id,
            user_id=user_id,
            question_id=uuid.uuid4(),
            knowledge_point_id=uuid.uuid4(),
            practice_id=uuid.uuid4(),
            attempt_item_id=uuid.uuid4(),
            error_type="conceptual",
            is_mastered=False,
            mastered_at=None,
        )
        mock_repos["diagnosis_repo"].mark_wrong_record_mastered.return_value = fake_record

        result = service.mark_wrong_record_mastered(
            user_id=user_id,
            record_id=record_id,
            is_mastered=False,
        )

        assert result is fake_record
        assert result.is_mastered is False
        mock_repos["diagnosis_repo"].mark_wrong_record_mastered.assert_called_once_with(
            wrong_record_id=record_id,
            user_id=user_id,
            is_mastered=False,
        )
        mock_session.commit.assert_called_once()

    def test_mark_wrong_record_mastered_not_found(
        self,
        service: DiagnosisService,
        mock_session: MagicMock,
        mock_repos: dict[str, MagicMock],
    ) -> None:
        """测试标记不存在错题时抛出 WrongRecordNotFoundError (404/40019)。"""
        user_id = uuid.uuid4()
        record_id = uuid.uuid4()

        mock_repos["diagnosis_repo"].mark_wrong_record_mastered.return_value = None

        with pytest.raises(WrongRecordNotFoundError) as exc_info:
            service.mark_wrong_record_mastered(user_id=user_id, record_id=record_id)

        assert exc_info.value.error_code == 40019
        assert exc_info.value.status_code == 404
        assert exc_info.value.details.get("record_id") == str(record_id)
        mock_session.commit.assert_not_called()

    def test_remove_wrong_record_success(
        self,
        service: DiagnosisService,
        mock_session: MagicMock,
        mock_repos: dict[str, MagicMock],
    ) -> None:
        """测试成功删除错题记录并提交事务。"""
        user_id = uuid.uuid4()
        record_id = uuid.uuid4()

        mock_repos["diagnosis_repo"].delete_wrong_record.return_value = True

        result = service.remove_wrong_record(user_id=user_id, record_id=record_id)

        assert result is True
        mock_repos["diagnosis_repo"].delete_wrong_record.assert_called_once_with(
            record_id=record_id,
            user_id=user_id,
        )
        mock_session.commit.assert_called_once()

    def test_remove_wrong_record_not_found(
        self,
        service: DiagnosisService,
        mock_session: MagicMock,
        mock_repos: dict[str, MagicMock],
    ) -> None:
        """测试删除不存在错题时抛出 WrongRecordNotFoundError (404/40019)。"""
        user_id = uuid.uuid4()
        record_id = uuid.uuid4()

        mock_repos["diagnosis_repo"].delete_wrong_record.return_value = False

        with pytest.raises(WrongRecordNotFoundError) as exc_info:
            service.remove_wrong_record(user_id=user_id, record_id=record_id)

        assert exc_info.value.error_code == 40019
        assert exc_info.value.status_code == 404
        assert exc_info.value.details.get("record_id") == str(record_id)
        mock_session.commit.assert_not_called()
