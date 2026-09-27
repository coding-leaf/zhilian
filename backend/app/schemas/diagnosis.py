"""学情诊断报告、掌握度沉淀与错题本 Pydantic v2 数据契约 DTO 模块。

严格遵循 AGENTS.md 规范与 spec.md 2.2 契约：
- 严格遵循 Pydantic v2 规范，配置 ConfigDict(from_attributes=True)；
- 缩写白名单仅限 8 个: api, id, url, ocr, llm, db, config, env；
- 绝密脱敏红线：严禁在错题 DTO 中记录未经允许的敏感字段，仅下发 question_snapshot 供前端渲染。
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ==============================================================================
# 1. 诊断报告相关 DTO
# ==============================================================================


class MistakeEvidenceItemDTO(BaseModel):
    """关联错题证据条目数据传输对象。"""

    model_config = ConfigDict(from_attributes=True)

    question_id: uuid.UUID | str = Field(..., description="关联题目主键或标识")
    is_negation_inversion: bool = Field(default=False, description="是否属于否定词反转混淆题目")


class WeakKnowledgeItemDTO(BaseModel):
    """主要薄弱知识点条目数据传输对象。"""

    model_config = ConfigDict(from_attributes=True)

    knowledge_point_id: uuid.UUID | str | None = Field(default=None, description="知识点主键标识")
    knowledge_name: str | None = Field(default=None, description="知识点名称")
    current_score: float = Field(default=0.0, description="当前掌握度得分 (0.0~1.0)")
    previous_score: float | None = Field(default=None, description="上次掌握度得分 (0.0~1.0)")
    score_delta: float = Field(default=0.0, description="掌握度变化量")
    priority: int | str | None = Field(default=None, description="复习推荐优先级")

    # spec.md 兼容字段
    knowledge_id: str | None = Field(default=None, description="知识点标识字符串")
    knowledge_title: str | None = Field(default=None, description="知识点标题")
    cause_type: str | None = Field(default=None, description="认知成因类型")
    cause_explanation: str | None = Field(default=None, description="认知归因详细阐释")
    actionable_advice: str | None = Field(default=None, description="可执行复习改进建议")
    associated_mistakes: list[MistakeEvidenceItemDTO] = Field(
        default_factory=list, description="关联错题证据列表"
    )

    @model_validator(mode="before")
    @classmethod
    def _sync_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # 兼容 knowledge_point_id 与 knowledge_id
            if data.get("knowledge_point_id") is not None and not data.get("knowledge_id"):
                data["knowledge_id"] = str(data["knowledge_point_id"])
            elif data.get("knowledge_id") is not None and not data.get("knowledge_point_id"):
                data["knowledge_point_id"] = data["knowledge_id"]

            # 兼容 knowledge_name 与 knowledge_title
            if data.get("knowledge_name") is not None and not data.get("knowledge_title"):
                data["knowledge_title"] = data["knowledge_name"]
            elif data.get("knowledge_title") is not None and not data.get("knowledge_name"):
                data["knowledge_name"] = data["knowledge_title"]
        return data

    @model_validator(mode="after")
    def _sync_after(self) -> "WeakKnowledgeItemDTO":
        if self.knowledge_point_id is not None and self.knowledge_id is None:
            self.knowledge_id = str(self.knowledge_point_id)
        elif self.knowledge_id is not None and self.knowledge_point_id is None:
            self.knowledge_point_id = self.knowledge_id

        if self.knowledge_name is not None and self.knowledge_title is None:
            self.knowledge_title = self.knowledge_name
        elif self.knowledge_title is not None and self.knowledge_name is None:
            self.knowledge_name = self.knowledge_title
        return self


class RegressedKnowledgeItemDTO(BaseModel):
    """退步知识点条目数据传输对象。"""

    model_config = ConfigDict(from_attributes=True)

    knowledge_point_id: uuid.UUID | str | None = Field(default=None, description="知识点主键标识")
    knowledge_name: str | None = Field(default=None, description="知识点名称")
    current_score: float = Field(default=0.0, description="当前掌握度得分 (0.0~1.0)")
    previous_score: float | None = Field(default=None, description="上次掌握度得分 (0.0~1.0)")
    score_decay: float | None = Field(default=None, description="掌握度绝对衰减量")
    decay_percentage: float | None = Field(default=None, description="衰减百分比")
    score_delta: float = Field(default=0.0, description="掌握度变化量 (负数)")

    # spec.md 兼容字段
    knowledge_id: str | None = Field(default=None, description="知识点标识字符串")
    knowledge_title: str | None = Field(default=None, description="知识点标题")
    cause_type: str | None = Field(default=None, description="认知成因类型")
    cause_explanation: str | None = Field(default=None, description="退步归因详细阐释")
    actionable_advice: str | None = Field(default=None, description="可执行复习改进建议")

    @model_validator(mode="before")
    @classmethod
    def _sync_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if data.get("knowledge_point_id") is not None and not data.get("knowledge_id"):
                data["knowledge_id"] = str(data["knowledge_point_id"])
            elif data.get("knowledge_id") is not None and not data.get("knowledge_point_id"):
                data["knowledge_point_id"] = data["knowledge_id"]

            if data.get("knowledge_name") is not None and not data.get("knowledge_title"):
                data["knowledge_title"] = data["knowledge_name"]
            elif data.get("knowledge_title") is not None and not data.get("knowledge_name"):
                data["knowledge_name"] = data["knowledge_title"]

            if data.get("score_decay") is not None and "score_delta" not in data:
                data["score_delta"] = -abs(float(data["score_decay"]))
            elif data.get("score_delta") is not None and "score_decay" not in data:
                data["score_decay"] = abs(float(data["score_delta"]))
        return data

    @model_validator(mode="after")
    def _sync_after(self) -> "RegressedKnowledgeItemDTO":
        if self.knowledge_point_id is not None and self.knowledge_id is None:
            self.knowledge_id = str(self.knowledge_point_id)
        elif self.knowledge_id is not None and self.knowledge_point_id is None:
            self.knowledge_point_id = self.knowledge_id

        if self.knowledge_name is not None and self.knowledge_title is None:
            self.knowledge_title = self.knowledge_name
        elif self.knowledge_title is not None and self.knowledge_name is None:
            self.knowledge_name = self.knowledge_title

        if self.score_decay is not None and self.score_delta == 0.0:
            self.score_delta = -abs(self.score_decay)
        elif self.score_decay is None and self.score_delta != 0.0:
            self.score_decay = abs(self.score_delta)
        return self


class KnowledgeEvaluationItemDTO(BaseModel):
    """单知识点学情综合评估条目数据传输对象。"""

    model_config = ConfigDict(from_attributes=True)

    knowledge_point_id: uuid.UUID | str = Field(..., description="知识点主键标识")
    score: float = Field(default=0.0, description="当前掌握度得分 (0.0~1.0)")
    delta: float = Field(default=0.0, description="得分相较上次练习的变化量")
    status: str = Field(default="normal", description="状态评估 (stable, improving, regressed)")
    root_causes: list[str] = Field(default_factory=list, description="薄弱主要归因列表")
    suggestions: list[str] = Field(default_factory=list, description="针对性提升建议列表")


class AnalysisCauseItemDTO(BaseModel):
    """单知识点作答归因明细条目。"""

    model_config = ConfigDict(from_attributes=True)

    knowledge_id: str = Field(..., description="知识点主键标识")
    cause_type: str = Field(..., description="认知成因分类代码")
    explanation: str = Field(..., description="成因详细诊断文案")


class ActionableSuggestionItemDTO(BaseModel):
    """复习行动建议明细条目。"""

    model_config = ConfigDict(from_attributes=True)

    action: str = Field(..., description="建议执行的具体学习动作描述")


class DiagnosisReportResponse(BaseModel):
    """学情诊断报告完整响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="诊断报告主键 UUID")
    practice_id: uuid.UUID = Field(..., description="关联练习会话主键 UUID")

    # 宏观掌握度流转
    mastery_before: float | None = Field(default=None, description="练习前综合掌握度")
    mastery_after: float | None = Field(default=None, description="练习后综合掌握度")

    # 评估与薄弱条目
    knowledge_evaluations: list[KnowledgeEvaluationItemDTO] = Field(
        default_factory=list, description="各知识点评估列表"
    )
    weak_knowledge_points: list[WeakKnowledgeItemDTO] = Field(
        default_factory=list, description="主要薄弱知识点列表"
    )
    regressed_knowledge_points: list[RegressedKnowledgeItemDTO] = Field(
        default_factory=list, description="退步知识点列表"
    )
    analysis_causes: list[AnalysisCauseItemDTO] = Field(
        default_factory=list, description="结构化作答归因明细"
    )
    actionable_suggestions: list[ActionableSuggestionItemDTO] = Field(
        default_factory=list, description="行动建议明细"
    )
    root_causes: list[str] = Field(default_factory=list, description="核心成因总结")
    suggestions: list[str] = Field(default_factory=list, description="核心建议总结")
    summary: str | None = Field(default=None, description="学情综合诊断总评文案")

    # 卷面统计
    unanswered_count: int = Field(default=0, description="未作答题数")
    wrong_count: int = Field(default=0, description="答错题数")
    pending_regrade_count: int = Field(default=0, description="待重新判题题目数")
    total_questions: int = Field(default=0, description="卷面题目总数")
    score_rate: float = Field(default=0.0, description="卷面整体得分率 (0.0~1.0)")
    is_structure_degraded: bool = Field(default=False, description="是否处于知识点结构降级状态")
    created_at: datetime | None = Field(default=None, description="报告生成时间戳")


class DiagnosisReportListItemResponse(BaseModel):
    """学情诊断报告列表项简要响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="诊断报告主键 UUID")
    practice_id: uuid.UUID = Field(..., description="关联练习会话主键 UUID")
    mastery_before: float | None = Field(default=None, description="练习前综合掌握度")
    mastery_after: float | None = Field(default=None, description="练习后综合掌握度")
    summary: str | None = Field(default=None, description="简要综述评价")
    created_at: datetime | None = Field(default=None, description="报告生成时间戳")


class DiagnosisReportListResponse(BaseModel):
    """学情诊断报告分页列表响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    items: list[DiagnosisReportResponse] = Field(default_factory=list, description="诊断报告列表")
    total: int = Field(default=0, description="总报告记录数")
    offset: int = Field(default=0, description="分页偏移量")
    limit: int = Field(default=20, description="每页记录上限")
    page: int | None = Field(default=None, description="页码 (从 1 起始)")
    page_size: int | None = Field(default=None, description="每页大小")

    @model_validator(mode="before")
    @classmethod
    def _sync_pagination(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if data.get("page") is not None:
                page = int(data["page"])
                page_size = int(data.get("page_size", 20) or 20)
                if "offset" not in data:
                    data["offset"] = max(0, (page - 1) * page_size)
                if "limit" not in data:
                    data["limit"] = page_size
            elif data.get("offset") is not None:
                offset = int(data["offset"])
                limit = int(data.get("limit", 20) or 20)
                if "page" not in data:
                    data["page"] = (offset // limit) + 1 if limit > 0 else 1
                if "page_size" not in data:
                    data["page_size"] = limit
        return data


# ==============================================================================
# 2. 掌握度相关 DTO
# ==============================================================================


class KnowledgeMasterySummaryResponse(BaseModel):
    """单知识点掌握度汇总响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    knowledge_point_id: uuid.UUID = Field(..., description="知识点主键 UUID")
    knowledge_name: str = Field(..., description="知识点名称")
    mastery_score: float = Field(default=0.0, description="当前艾宾浩斯时间衰减掌握度 (0.0~1.0)")
    level: str = Field(
        default="unlearned",
        description="掌握度档次 (unlearned/weak/basic/proficient)",
    )
    practice_count: int = Field(default=0, description="累计有效作答题数")
    correct_count: int = Field(default=0, description="累计正确/达标题数")
    last_practiced_at: datetime | None = Field(default=None, description="最后有效练习时间戳")


class UserMasteryOverviewResponse(BaseModel):
    """用户资料掌握度宏观全景响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    total_points: int = Field(default=0, description="教材下知识点总数")
    mastered_count: int = Field(default=0, description="已精通/掌握知识点数量")
    learning_count: int = Field(default=0, description="学习中/待巩固知识点数量")
    weak_count: int = Field(default=0, description="薄弱知识点数量")
    overall_score: float = Field(default=0.0, description="宏观平均掌握度得分 (0.0~1.0)")
    points: list[KnowledgeMasterySummaryResponse] = Field(
        default_factory=list, description="知识点掌握度汇总条目列表"
    )

    # spec.md 兼容字段
    material_id: uuid.UUID | None = Field(default=None, description="关联学习资料标识")
    overall_mastery_score: float = Field(default=0.0, description="宏观平均掌握度得分")
    total_knowledge_points: int = Field(default=0, description="教材下知识点总数")
    unlearned_count: int = Field(default=0, description="未学知识点数量")
    basic_count: int = Field(default=0, description="基础知识点数量")
    proficient_count: int = Field(default=0, description="精通知识点数量")
    weak_knowledge_points: list[KnowledgeMasterySummaryResponse] = Field(
        default_factory=list, description="薄弱知识点列表"
    )
    weak_points: list[KnowledgeMasterySummaryResponse] = Field(
        default_factory=list,
        description="薄弱知识点列表别名 (与 weak_knowledge_points 双向同步，对齐前端契约)",
    )

    @model_validator(mode="before")
    @classmethod
    def _sync_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # 薄弱点列表别名同步 (weak_points <-> weak_knowledge_points)
            if data.get("weak_knowledge_points") is not None and not data.get("weak_points"):
                data["weak_points"] = data["weak_knowledge_points"]
            elif data.get("weak_points") is not None and not data.get("weak_knowledge_points"):
                data["weak_knowledge_points"] = data["weak_points"]

            # 分数同步
            if data.get("overall_score") is not None and not data.get("overall_mastery_score"):
                data["overall_mastery_score"] = data["overall_score"]
            elif data.get("overall_mastery_score") is not None and not data.get("overall_score"):
                data["overall_score"] = data["overall_mastery_score"]

            # 总数同步
            if data.get("total_points") is not None and not data.get("total_knowledge_points"):
                data["total_knowledge_points"] = data["total_points"]
            elif data.get("total_knowledge_points") is not None and not data.get("total_points"):
                data["total_points"] = data["total_knowledge_points"]

            # 列表同步
            if data.get("points") is not None and not data.get("weak_knowledge_points"):
                data["weak_knowledge_points"] = data["points"]
            elif data.get("weak_knowledge_points") is not None and not data.get("points"):
                data["points"] = data["weak_knowledge_points"]

            # 档次统计同步
            if data.get("mastered_count") is not None and not data.get("proficient_count"):
                data["proficient_count"] = data["mastered_count"]
            elif data.get("proficient_count") is not None and not data.get("mastered_count"):
                data["mastered_count"] = data["proficient_count"]

            if data.get("learning_count") is not None and not data.get("basic_count"):
                data["basic_count"] = data["learning_count"]
            elif data.get("basic_count") is not None and not data.get("learning_count"):
                data["learning_count"] = data["basic_count"]
        return data

    @model_validator(mode="after")
    def _sync_after(self) -> "UserMasteryOverviewResponse":
        if self.overall_score != 0.0 and self.overall_mastery_score == 0.0:
            self.overall_mastery_score = self.overall_score
        elif self.overall_mastery_score != 0.0 and self.overall_score == 0.0:
            self.overall_score = self.overall_mastery_score

        if self.total_points != 0 and self.total_knowledge_points == 0:
            self.total_knowledge_points = self.total_points
        elif self.total_knowledge_points != 0 and self.total_points == 0:
            self.total_points = self.total_knowledge_points

        if self.points and not self.weak_knowledge_points:
            self.weak_knowledge_points = self.points
        elif self.weak_knowledge_points and not self.points:
            self.points = self.weak_knowledge_points

        # 薄弱点别名同步 (ORM/DTO from_attributes 路径会跳过 before 校验器)
        if self.weak_knowledge_points and not self.weak_points:
            self.weak_points = self.weak_knowledge_points
        elif self.weak_points and not self.weak_knowledge_points:
            self.weak_knowledge_points = self.weak_points

        # BUG-DIAG-009: ORM/DTO 对象经 from_attributes 进入校验器时 before 分支
        # (仅处理 dict) 会被跳过，导致档次统计不同步；在 after 分支补齐双向同步。
        if self.mastered_count != 0 and self.proficient_count == 0:
            self.proficient_count = self.mastered_count
        elif self.proficient_count != 0 and self.mastered_count == 0:
            self.mastered_count = self.proficient_count

        if self.learning_count != 0 and self.basic_count == 0:
            self.basic_count = self.learning_count
        elif self.basic_count != 0 and self.learning_count == 0:
            self.learning_count = self.basic_count
        return self


# ==============================================================================
# 3. 错题本相关 DTO
# ==============================================================================


class WrongRecordItemResponse(BaseModel):
    """错题记录明细响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="错题记录主键 UUID")
    question_id: uuid.UUID | None = Field(default=None, description="关联题目主键 UUID")
    practice_id: uuid.UUID = Field(..., description="最近答错练习主键 UUID")
    attempt_item_id: uuid.UUID = Field(..., description="最近答错作答项主键 UUID")
    knowledge_point_id: uuid.UUID = Field(..., description="关联知识点标识 UUID")
    error_type: str = Field(default="conceptual", description="错误类型分类 (ErrorType)")
    is_mastered: bool = Field(default=False, description="是否已攻克掌握")
    wrong_count: int = Field(default=1, description="连续答错累计次数")
    error_count: int = Field(default=1, description="连续答错累计次数 (对齐持久化字段)")
    question_snapshot: dict[str, Any] = Field(
        default_factory=dict, description="原题快照字典 (题干/选项/解析)"
    )
    first_wrong_at: datetime | None = Field(default=None, description="首次答错时间戳")
    mastered_at: datetime | None = Field(default=None, description="攻克掌握时间戳")
    created_at: datetime | None = Field(default=None, description="创建时间戳")
    updated_at: datetime | None = Field(default=None, description="更新时间戳")
    user_answer: str | None = Field(default=None, description="用户最近一次作答内容")

    @model_validator(mode="before")
    @classmethod
    def _sync_counts(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            # ORM from_attributes 路径：抽取实体字段为字典，兼容 last_wrong_answer 映射。
            # 未 flush 的实体其列默认值仍为 None，跳过以便应用模型默认值。
            extracted: dict[str, Any] = {}
            for field in (
                "id",
                "question_id",
                "practice_id",
                "attempt_item_id",
                "knowledge_point_id",
                "error_type",
                "is_mastered",
                "error_count",
                "wrong_count",
                "question_snapshot",
                "first_wrong_at",
                "mastered_at",
                "created_at",
                "updated_at",
                "last_wrong_answer",
                "user_answer",
            ):
                if not hasattr(data, field):
                    continue
                value = getattr(data, field)
                if value is not None:
                    extracted[field] = value
            data = extracted
        if "wrong_count" in data and "error_count" not in data:
            data["error_count"] = data["wrong_count"]
        elif "error_count" in data and "wrong_count" not in data:
            data["wrong_count"] = data["error_count"]
        if not data.get("user_answer") and data.get("last_wrong_answer") is not None:
            data["user_answer"] = data["last_wrong_answer"]
        return data

    @model_validator(mode="after")
    def _ensure_counts_consistent(self) -> "WrongRecordItemResponse":
        if self.wrong_count != self.error_count:
            if self.wrong_count == 1 and self.error_count != 1:
                self.wrong_count = self.error_count
            elif self.error_count == 1 and self.wrong_count != 1:
                self.error_count = self.wrong_count
        return self


class WrongRecordListResponse(BaseModel):
    """错题本记录分页列表响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    items: list[WrongRecordItemResponse] = Field(
        default_factory=list, description="错题记录明细列表"
    )
    total: int = Field(default=0, description="符合过滤条件的总错题数")
    offset: int = Field(default=0, description="分页偏移量")
    limit: int = Field(default=20, description="每页记录上限")
    page: int | None = Field(default=None, description="当前页码 (从 1 起始)")
    page_size: int | None = Field(default=None, description="每页条数")

    @model_validator(mode="before")
    @classmethod
    def _sync_pagination(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if data.get("page") is not None:
                page = int(data["page"])
                page_size = int(data.get("page_size", 20) or 20)
                if "offset" not in data:
                    data["offset"] = max(0, (page - 1) * page_size)
                if "limit" not in data:
                    data["limit"] = page_size
            elif data.get("offset") is not None:
                offset = int(data["offset"])
                limit = int(data.get("limit", 20) or 20)
                if "page" not in data:
                    data["page"] = (offset // limit) + 1 if limit > 0 else 1
                if "page_size" not in data:
                    data["page_size"] = limit
        return data


class MarkWrongRecordMasteredRequest(BaseModel):
    """标记/取消错题攻克状态请求模型 (请求体可选)。"""

    is_mastered: bool | None = Field(
        default=None, description="目标攻克状态；缺省时按 True (置为已攻克) 处理"
    )


class MarkWrongRecordMasteredResponse(BaseModel):
    """标记错题已掌握响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="错题记录主键 UUID")
    is_mastered: bool = Field(default=True, description="是否已攻克掌握")
    mastered_at: datetime | None = Field(default=None, description="攻克时间戳")
    message: str = Field(default="错题已成功标记为已攻克", description="操作结果文案")


class DeleteWrongRecordResponse(BaseModel):
    """移除错题记录响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="移除的错题记录主键 UUID")
    success: bool = Field(default=True, description="是否成功移除")
    removed: bool = Field(default=True, description="是否成功移除 (契约对齐字段)")
    message: str = Field(default="错题记录已成功移除", description="操作结果文案")


__all__ = [
    "ActionableSuggestionItemDTO",
    "AnalysisCauseItemDTO",
    "DeleteWrongRecordResponse",
    "DiagnosisReportListItemResponse",
    "DiagnosisReportListResponse",
    "DiagnosisReportResponse",
    "KnowledgeEvaluationItemDTO",
    "KnowledgeMasterySummaryResponse",
    "MarkWrongRecordMasteredRequest",
    "MarkWrongRecordMasteredResponse",
    "MistakeEvidenceItemDTO",
    "RegressedKnowledgeItemDTO",
    "UserMasteryOverviewResponse",
    "WeakKnowledgeItemDTO",
    "WrongRecordItemResponse",
    "WrongRecordListResponse",
]
