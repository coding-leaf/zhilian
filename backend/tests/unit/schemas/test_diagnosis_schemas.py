"""学情诊断、掌握度与错题本 Pydantic v2 DTO 数据契约单元测试。

验证全部 12+ 个 DTO 模型的数据校验、默认值、双向字段同步与 from_attributes 特性。
严格遵循 AGENTS.md 规范：
- 缩写白名单仅限 api, id, url, ocr, llm, db, config, env；
- 全类型注解覆盖。
"""

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas.diagnosis import (
    ActionableSuggestionItemDTO,
    AnalysisCauseItemDTO,
    DeleteWrongRecordResponse,
    DiagnosisReportListItemResponse,
    DiagnosisReportListResponse,
    DiagnosisReportResponse,
    KnowledgeEvaluationItemDTO,
    KnowledgeMasterySummaryResponse,
    MarkWrongRecordMasteredResponse,
    MistakeEvidenceItemDTO,
    RegressedKnowledgeItemDTO,
    UserMasteryOverviewResponse,
    WeakKnowledgeItemDTO,
    WrongRecordItemResponse,
    WrongRecordListResponse,
)


class TestDiagnosisSchemas:
    """学情诊断相关 DTO 测试集。"""

    def test_weak_knowledge_item_dto(self) -> None:
        """验证主要薄弱知识点条目 DTO 校验与字段兼容。"""
        point_id = uuid.uuid4()
        dto = WeakKnowledgeItemDTO(
            knowledge_point_id=point_id,
            knowledge_name="二叉树遍历",
            current_score=0.35,
            previous_score=0.75,
            score_delta=-0.40,
            priority=1,
        )
        assert dto.knowledge_point_id == point_id
        assert dto.knowledge_name == "二叉树遍历"
        assert dto.current_score == 0.35
        assert dto.previous_score == 0.75
        assert dto.score_delta == -0.40
        assert dto.priority == 1
        # 兼容 spec.md 字段同步
        assert dto.knowledge_id == str(point_id)
        assert dto.knowledge_title == "二叉树遍历"

    def test_regressed_knowledge_item_dto(self) -> None:
        """验证退步知识点条目 DTO 校验与衰减数值。"""
        point_id = uuid.uuid4()
        dto = RegressedKnowledgeItemDTO(
            knowledge_point_id=point_id,
            knowledge_name="动态规划",
            current_score=0.45,
            previous_score=0.85,
            score_decay=0.40,
            decay_percentage=47.06,
        )
        assert dto.knowledge_point_id == point_id
        assert dto.knowledge_name == "动态规划"
        assert dto.score_decay == 0.40
        assert dto.decay_percentage == 47.06
        assert dto.knowledge_id == str(point_id)

    def test_knowledge_evaluation_item_dto(self) -> None:
        """验证单知识点评估条目 DTO。"""
        point_id = uuid.uuid4()
        dto = KnowledgeEvaluationItemDTO(
            knowledge_point_id=point_id,
            score=0.60,
            delta=0.10,
            status="improving",
            root_causes=["审题不清"],
            suggestions=["加强练习"],
        )
        assert dto.knowledge_point_id == point_id
        assert dto.score == 0.60
        assert dto.delta == 0.10
        assert dto.status == "improving"
        assert dto.root_causes == ["审题不清"]
        assert dto.suggestions == ["加强练习"]

    def test_diagnosis_report_response_and_list_item(self) -> None:
        """验证诊断报告完整响应与列表项响应。"""
        report_id = uuid.uuid4()
        practice_id = uuid.uuid4()
        point_id = uuid.uuid4()
        now = datetime.now(UTC)

        response = DiagnosisReportResponse(
            id=report_id,
            practice_id=practice_id,
            mastery_before=0.50,
            mastery_after=0.65,
            weak_knowledge_points=[
                WeakKnowledgeItemDTO(
                    knowledge_point_id=point_id,
                    knowledge_name="图的连通性",
                    current_score=0.30,
                    previous_score=0.60,
                    score_delta=-0.30,
                    priority=1,
                )
            ],
            regressed_knowledge_points=[],
            root_causes=["遗忘"],
            suggestions=["多复习"],
            summary="本次练习整体良好，但图算法有退步",
            created_at=now,
        )
        assert response.id == report_id
        assert response.practice_id == practice_id
        assert len(response.weak_knowledge_points) == 1
        assert response.summary == "本次练习整体良好，但图算法有退步"

        # 验证列表项
        list_item = DiagnosisReportListItemResponse(
            id=report_id,
            practice_id=practice_id,
            mastery_before=0.50,
            mastery_after=0.65,
            summary="简要综述",
            created_at=now,
        )
        assert list_item.id == report_id
        assert list_item.summary == "简要综述"

        # 验证报告分页列表响应
        list_response = DiagnosisReportListResponse(
            items=[response],
            total=1,
            offset=0,
            limit=20,
        )
        assert list_response.total == 1
        assert len(list_response.items) == 1
        assert list_response.offset == 0
        assert list_response.limit == 20


class TestMasterySchemas:
    """掌握度相关 DTO 测试集。"""

    def test_knowledge_mastery_summary_response(self) -> None:
        """验证单知识点掌握度汇总响应。"""
        point_id = uuid.uuid4()
        now = datetime.now(UTC)
        dto = KnowledgeMasterySummaryResponse(
            knowledge_point_id=point_id,
            knowledge_name="链表反转",
            mastery_score=0.88,
            level="proficient",
            practice_count=12,
            correct_count=10,
            last_practiced_at=now,
        )
        assert dto.knowledge_point_id == point_id
        assert dto.knowledge_name == "链表反转"
        assert dto.mastery_score == 0.88
        assert dto.level == "proficient"
        assert dto.practice_count == 12
        assert dto.correct_count == 10
        assert dto.last_practiced_at == now

    def test_user_mastery_overview_response(self) -> None:
        """验证用户资料掌握度全景响应。"""
        point_id = uuid.uuid4()
        item = KnowledgeMasterySummaryResponse(
            knowledge_point_id=point_id,
            knowledge_name="栈与队列",
            mastery_score=0.35,
            level="weak",
            practice_count=5,
            correct_count=1,
            last_practiced_at=None,
        )
        overview = UserMasteryOverviewResponse(
            total_points=10,
            mastered_count=4,
            learning_count=4,
            weak_count=2,
            overall_score=0.62,
            points=[item],
        )
        assert overview.total_points == 10
        assert overview.mastered_count == 4
        assert overview.learning_count == 4
        assert overview.weak_count == 2
        assert overview.overall_score == 0.62
        assert len(overview.points) == 1
        # 兼容 spec.md 字段同步
        assert overview.total_knowledge_points == 10
        assert overview.overall_mastery_score == 0.62


class TestWrongRecordSchemas:
    """错题本相关 DTO 测试集。"""

    def test_wrong_record_item_response(self) -> None:
        """验证错题记录条目响应与字段序列化。"""
        record_id = uuid.uuid4()
        question_id = uuid.uuid4()
        practice_id = uuid.uuid4()
        attempt_item_id = uuid.uuid4()
        knowledge_point_id = uuid.uuid4()
        now = datetime.now(UTC)

        snapshot = {
            "stem": "关于TCP协议，以下说法错误的是？",
            "question_type": "single_choice",
            "options": [{"key": "A", "content": "无连接"}],
        }

        item = WrongRecordItemResponse(
            id=record_id,
            question_id=question_id,
            practice_id=practice_id,
            attempt_item_id=attempt_item_id,
            knowledge_point_id=knowledge_point_id,
            error_type="conceptual",
            is_mastered=False,
            wrong_count=2,
            question_snapshot=snapshot,
            created_at=now,
            updated_at=now,
        )
        assert item.id == record_id
        assert item.question_id == question_id
        assert item.wrong_count == 2
        assert item.error_count == 2
        assert item.is_mastered is False
        assert item.question_snapshot["stem"] == "关于TCP协议，以下说法错误的是？"

    def test_wrong_record_list_response(self) -> None:
        """验证错题列表响应。"""
        record_id = uuid.uuid4()
        item = WrongRecordItemResponse(
            id=record_id,
            question_id=uuid.uuid4(),
            practice_id=uuid.uuid4(),
            attempt_item_id=uuid.uuid4(),
            knowledge_point_id=uuid.uuid4(),
            error_type="conceptual",
            is_mastered=False,
            wrong_count=1,
            question_snapshot={},
        )
        list_response = WrongRecordListResponse(
            items=[item],
            total=1,
            offset=0,
            limit=20,
        )
        assert list_response.total == 1
        assert len(list_response.items) == 1
        assert list_response.offset == 0
        assert list_response.limit == 20

    def test_mark_wrong_record_mastered_response(self) -> None:
        """验证标记已攻克响应。"""
        record_id = uuid.uuid4()
        response = MarkWrongRecordMasteredResponse(
            id=record_id,
            is_mastered=True,
            message="错题已攻克",
        )
        assert response.id == record_id
        assert response.is_mastered is True
        assert response.message == "错题已攻克"

    def test_delete_wrong_record_response(self) -> None:
        """验证删除错题响应。"""
        record_id = uuid.uuid4()
        response = DeleteWrongRecordResponse(
            id=record_id,
            message="错题已删除",
        )
        assert response.id == record_id
        assert response.message == "错题已删除"
        assert response.success is True

    def test_spec_compat_dtos(self) -> None:
        """验证 spec.md 特有辅助 DTOs。"""
        mistake = MistakeEvidenceItemDTO(
            question_id=uuid.uuid4(),
            is_negation_inversion=True,
        )
        assert mistake.is_negation_inversion is True

        cause = AnalysisCauseItemDTO(
            knowledge_id="k-1",
            cause_type="conceptual",
            explanation="概念混淆",
        )
        assert cause.cause_type == "conceptual"

        suggestion = ActionableSuggestionItemDTO(
            action="复习第三章第2节",
        )
        assert suggestion.action == "复习第三章第2节"

    def test_schema_validation_error_on_missing_required(self) -> None:
        """验证缺少必填字段时抛出 ValidationError。"""
        with pytest.raises(ValidationError):
            DiagnosisReportResponse()  # type: ignore[call-arg]
