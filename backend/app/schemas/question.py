"""题目管理、生成与质检拦截数据契约与 DTO 校验模型定义。

严格遵循 AGENTS.md 规范与 spec.md 技术契约：
- 字段类型全标注，支持 Pydantic v2 与 from_attributes 特性；
- 缩写白名单仅限 api, id, url, ocr, llm, db, config, env；
- Google 风格中文 Docstring。
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.question import QuestionType


class QuestionGenerateRequest(BaseModel):
    """触发出题生成请求入参模型。"""

    material_id: uuid.UUID | None = Field(
        default=None, description="归属学习资料主键 UUIDv4（与 folder_id 至少提供一个）"
    )
    folder_id: uuid.UUID | None = Field(
        default=None, description="归属课程文件夹主键 UUIDv4（提供时走文件夹范围出题）"
    )
    version_id: uuid.UUID | None = Field(
        default=None, description="归属资料版本主键 UUIDv4，若缺省或不匹配将智能对齐"
    )
    knowledge_point_id: uuid.UUID | None = Field(
        default=None,
        description="出题目标知识点主键 UUIDv4（单考点，向后兼容；优先 knowledge_point_ids）",
    )
    knowledge_point_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="出题目标知识点主键列表（多考点，优先于 knowledge_point_id）",
    )

    @field_validator("version_id", mode="before")
    @classmethod
    def _coerce_empty_version_id(cls, v: Any) -> Any:
        if v == "" or v is None:
            return None
        return v

    @model_validator(mode="after")
    def _require_generation_target(self) -> "QuestionGenerateRequest":
        """校验提供 material_id 或 folder_id，且单资料范围必须显式提供考点。"""
        if self.material_id is None and self.folder_id is None:
            raise ValueError("material_id 与 folder_id 至少提供一个")
        if (
            self.folder_id is None
            and not self.knowledge_point_ids
            and self.knowledge_point_id is None
        ):
            raise ValueError("knowledge_point_id 与 knowledge_point_ids 至少提供一个")
        return self

    count: int = Field(default=5, ge=1, le=20, description="出题目标数量，1~20，默认 5")
    difficulty: int = Field(default=3, ge=1, le=5, description="题目难度系数，1~5，默认 3")
    question_types: list[str] = Field(
        default_factory=lambda: [
            "single_choice",
            "multiple_choice",
            "true_false",
            "short_answer",
        ],
        min_length=1,
        description="目标生成的题型列表，至少 1 项且取值必须为合法 QuestionType",
    )

    @field_validator("question_types")
    @classmethod
    def _validate_question_types(cls, value: list[str]) -> list[str]:
        """校验题型列表非空且每一项均为合法 QuestionType 枚举值。"""
        valid_types = {item.value for item in QuestionType}
        invalid_types = [item for item in value if item not in valid_types]
        if invalid_types:
            raise ValueError(f"question_types 含非法题型: {', '.join(invalid_types)}")
        return value

    max_retries: int = Field(
        default=2, ge=0, le=5, description="质检未通过最大重抽轮次，0~5，默认 2"
    )


class QuestionDetailResponse(BaseModel):
    """题目详情数据传输对象模型。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="题目主键 UUIDv4")
    material_id: uuid.UUID = Field(..., description="归属学习资料主键")
    version_id: uuid.UUID = Field(..., description="归属资料版本标识")
    knowledge_point_id: uuid.UUID = Field(..., description="所属知识点标识")
    source_snippet_id: uuid.UUID | None = Field(default=None, description="主来源切片标识")
    question_type: str = Field(..., description="题型 (如 single_choice, multiple_choice 等)")
    status: str = Field(..., description="题目可用状态 (available / pending_review)")
    is_deleted: bool = Field(default=False, description="软删除标记")
    batch_id: str | None = Field(
        default=None, description="出题生成批次标识 (同一次生成共享；历史数据可空)"
    )
    stem: str = Field(..., description="题干全文")
    options: list[dict[str, Any]] = Field(default_factory=list, description="客观题选项列表")
    answer: str = Field(..., description="参考答案或标准答案")
    analysis: str = Field(default="", description="题目解析与知识点阐述")
    difficulty: int = Field(default=3, ge=1, le=5, description="难度系数 1~5")
    grading_rubric: dict[str, Any] = Field(default_factory=dict, description="主观题评分细则")
    source_snippet_ids: list[dict[str, Any]] = Field(
        default_factory=list, description="多切片出题上下文列表"
    )
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")


class QuestionQualityCheckResponse(BaseModel):
    """题目质检明细记录响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="质检记录主键 UUIDv4")
    question_id: uuid.UUID = Field(..., description="关联题目标识")
    batch_id: str = Field(..., description="出题生成批次号")
    check_type: str = Field(..., description="质检项类型")
    is_passed: bool = Field(..., description="该质检项是否通过")
    reason: str | None = Field(default=None, description="未通过原因说明")
    similarity_score: float | None = Field(default=None, description="比对相似度度量值")
    check_metadata: dict[str, Any] = Field(default_factory=dict, description="质检上下文诊断元数据")
    created_at: datetime = Field(..., description="记录创建时间")


class QuestionGenerateResponse(BaseModel):
    """出题生成执行响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    batch_id: str = Field(..., description="出题生成批次号")
    material_id: uuid.UUID | None = Field(
        default=None, description="归属学习资料主键（课程文件夹范围可为空）"
    )
    version_id: uuid.UUID | None = Field(
        default=None, description="归属资料版本标识（课程文件夹范围可为空）"
    )
    knowledge_point_id: uuid.UUID | None = Field(
        default=None, description="所属知识点标识（课程文件夹范围为首个考点）"
    )
    knowledge_point_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="本次覆盖的全部知识点标识（多考点；单考点时等于 [knowledge_point_id]）",
    )
    total_generated: int = Field(..., description="本次总生成题目数")
    qualified_count: int = Field(default=0, description="质检合格入库题数")
    pending_count: int = Field(default=0, description="质检未通过进入待处理区题数")
    retry_count: int = Field(default=0, description="实际重抽轮次")
    qualified_questions: list[QuestionDetailResponse] = Field(
        default_factory=list, description="质检合格题目列表"
    )
    pending_questions: list[QuestionDetailResponse] = Field(
        default_factory=list, description="待处理区题目列表"
    )
    quality_checks: list[QuestionQualityCheckResponse] = Field(
        default_factory=list, description="题目质检检查记录"
    )


class QuestionListQuery(BaseModel):
    """题目多条件分页筛选查询参数模型。"""

    material_id: uuid.UUID | None = Field(default=None, description="按学习资料标识过滤")
    folder_id: uuid.UUID | None = Field(default=None, description="按课程文件夹标识过滤")
    knowledge_point_id: uuid.UUID | None = Field(default=None, description="按知识点标识过滤")
    question_type: str | None = Field(default=None, description="按题型过滤")
    difficulty: int | None = Field(default=None, ge=1, le=5, description="按难度过滤")
    review_status: str | None = Field(
        default=None, description="按审核/可用状态过滤 (available / pending_review)"
    )
    status: str | None = Field(default=None, description="题目状态过滤 (别名兼容)")
    page: int = Field(default=1, ge=1, description="当前页码，默认 1")
    page_size: int = Field(default=20, ge=1, le=100, description="每页条数，默认 20")
    limit: int | None = Field(default=None, ge=1, le=100, description="单页限制 (兼容)")
    offset: int | None = Field(default=None, ge=0, description="游标偏移量 (兼容)")


class QuestionListResponse(BaseModel):
    """题目多条件筛选列表分页响应模型。"""

    items: list[QuestionDetailResponse] = Field(default_factory=list, description="题目数据列表")
    total: int = Field(..., ge=0, description="符合条件的总记录数")
    limit: int = Field(default=20, ge=1, description="单页记录数限制")
    offset: int = Field(default=0, ge=0, description="分页游标偏移量")


class QuestionUpdateRequest(BaseModel):
    """题目审核修改请求入参模型。"""

    stem: str | None = Field(default=None, min_length=1, description="修改后的题干全文")
    options: list[dict[str, Any]] | None = Field(default=None, description="修改后的选项列表")
    answer: str | None = Field(default=None, min_length=1, description="修改后的标准答案")
    analysis: str | None = Field(default=None, description="修改后的题目解析")
    difficulty: int | None = Field(default=None, ge=1, le=5, description="修改后的难度系数 1~5")
    grading_rubric: dict[str, Any] | None = Field(default=None, description="修改后的评分细则")
    status: str | None = Field(
        default=None, description="修改后的状态 (available / pending_review)"
    )
    reason: str | None = Field(default=None, max_length=255, description="修改原因说明")
    edit_reason: str | None = Field(
        default=None, max_length=255, description="修改原因说明 (别名兼容)"
    )


class QuestionUpdateResponse(QuestionDetailResponse):
    """题目修改更新成功响应模型。"""


class QuestionDeleteResponse(BaseModel):
    """题目软删除结果响应模型。"""

    id: uuid.UUID = Field(..., description="已软删除的题目主键")
    is_deleted: bool = Field(default=True, description="是否已软删除")
    message: str = Field(default="题目已软删除", description="操作结果说明")


class QuestionEditLogResponse(BaseModel):
    """单个题目修改痕迹审计日志响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="审计日志主键 UUIDv4")
    question_id: uuid.UUID = Field(..., description="关联题目标识")
    action: str = Field(..., description="操作动作类型 (CREATE / EDIT / DELETE / REGENERATE)")
    changed_fields: list[str] = Field(
        default_factory=list, description="本次变更涉及修改的字段列表"
    )
    before_payload: dict[str, Any] = Field(default_factory=dict, description="变更前快照数据")
    after_payload: dict[str, Any] = Field(default_factory=dict, description="变更后快照数据")
    reason: str | None = Field(default=None, description="修改原因说明")
    created_at: datetime = Field(..., description="操作记录时间")


class QuestionAuditLogsResponse(BaseModel):
    """题目修改审计日志列表响应模型。"""

    question_id: uuid.UUID = Field(..., description="关联题目主键 UUIDv4")
    logs: list[QuestionEditLogResponse] = Field(
        default_factory=list, description="修改痕迹日志列表"
    )


QuestionEditLogListResponse = QuestionAuditLogsResponse


class MaterialQualityChecksResponse(BaseModel):
    """资料下题目质检拦截记录响应模型。"""

    material_id: uuid.UUID = Field(..., description="归属学习资料主键 UUIDv4")
    quality_checks: list[QuestionQualityCheckResponse] = Field(
        default_factory=list, description="质检明细记录列表"
    )


class QuestionQualityCheckListResponse(MaterialQualityChecksResponse):
    """题目质检拦截记录响应模型 (兼容别名)。"""


class AskCoachRequest(BaseModel):
    """AI 助教深度答疑追问请求入参模型。"""

    user_prompt: str = Field(..., min_length=1, max_length=1000, description="学生追问内容")
    user_answer: str | None = Field(default=None, description="学生的原始作答")
    grading_points: list[str] | None = Field(default=None, description="相关采分点")


class AskCoachResponse(BaseModel):
    """AI 助教深度答疑响应模型。"""

    reply: str = Field(..., description="AI 助教通俗生动的深度解析内容")
    suggestions: list[str] = Field(default_factory=list, description="推荐延伸思考提示")


class ScopedCoachRequest(BaseModel):
    """Ask about exactly one authorized course, material, or knowledge point."""

    folder_id: uuid.UUID | None = None
    material_id: uuid.UUID | None = None
    knowledge_point_id: uuid.UUID | None = None
    user_prompt: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_scope(self) -> "ScopedCoachRequest":
        if (
            sum(
                value is not None
                for value in (self.folder_id, self.material_id, self.knowledge_point_id)
            )
            != 1
        ):
            raise ValueError("必须且只能指定一个答疑范围")
        return self


class CoachSourceResponse(BaseModel):
    snippet_id: uuid.UUID
    material_id: uuid.UUID
    chapter_title: str
    excerpt: str
    source_info: dict[str, Any] = Field(default_factory=dict)


class ScopedCoachResponse(AskCoachResponse):
    sources: list[CoachSourceResponse] = Field(default_factory=list)


__all__ = [
    "AskCoachRequest",
    "AskCoachResponse",
    "CoachSourceResponse",
    "MaterialQualityChecksResponse",
    "QuestionAuditLogsResponse",
    "QuestionDeleteResponse",
    "QuestionDetailResponse",
    "QuestionEditLogListResponse",
    "QuestionEditLogResponse",
    "QuestionGenerateRequest",
    "QuestionGenerateResponse",
    "QuestionListQuery",
    "QuestionListResponse",
    "QuestionQualityCheckListResponse",
    "QuestionQualityCheckResponse",
    "QuestionUpdateRequest",
    "QuestionUpdateResponse",
    "ScopedCoachRequest",
    "ScopedCoachResponse",
]
