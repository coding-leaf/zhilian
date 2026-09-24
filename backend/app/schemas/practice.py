"""练习会话、作答暂存与交卷数据契约与 DTO 校验模型定义。

严格遵循 AGENTS.md 规范与 spec.md 技术契约：
- 字段类型全标注，支持 Pydantic v2 与 from_attributes 特性；
- 缩写白名单仅限 api, id, url, ocr, llm, db, config, env；
- Google 风格中文 Docstring。
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# 允许的组卷模式白名单集合
VALID_PRACTICE_MODES: set[str] = {"sequential", "random", "weak_points"}
# 允许的练习来源类型白名单集合
VALID_PRACTICE_SOURCE_TYPES: set[str] = {"normal", "weakness"}


class PracticeCreateRequest(BaseModel):
    """创建练习会话 (组卷) 请求入参模型。"""

    title: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="练习标题 (如: 计算机网络第3章-专项练习)",
    )
    material_id: uuid.UUID = Field(..., description="归属学习资料主键 UUIDv4")
    knowledge_point_ids: list[uuid.UUID] = Field(
        ...,
        min_length=1,
        description="练习覆盖的知识点主键 UUID 列表，至少包含 1 个知识点",
    )
    question_count: int = Field(
        default=10,
        ge=1,
        le=50,
        description="练习题目总数，范围 1~50，默认 10 题",
    )
    question_types: list[str] | None = Field(
        default=None,
        description="目标题型过滤范围 (如: single_choice, multiple_choice, short_answer)",
    )
    difficulty: int | None = Field(
        default=None,
        ge=1,
        le=5,
        description="期望难度系数偏好 (1~5，空为混合难度)",
    )
    mode: str = Field(
        default="sequential",
        description="组卷抽题模式 (sequential: 顺序, random: 随机, weak_points: 薄弱点优先)",
    )
    source_type: str = Field(
        default="normal",
        description="练习来源类型 (normal: 常规练习, weakness: 薄弱点继续练习)",
    )
    source_report_id: uuid.UUID | None = Field(
        default=None,
        description="来源诊断报告主键标识 (用于继续练习防重合并)",
    )

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, value: str) -> str:
        """校验抽题模式枚举合法性。"""
        if value not in VALID_PRACTICE_MODES:
            raise ValueError(f"mode 必须为 {VALID_PRACTICE_MODES} 之一，当前输入: {value}")
        return value

    @field_validator("source_type")
    @classmethod
    def validate_source_type(cls, value: str) -> str:
        """校验练习来源类型枚举合法性。"""
        if value not in VALID_PRACTICE_SOURCE_TYPES:
            raise ValueError(
                f"source_type 必须为 {VALID_PRACTICE_SOURCE_TYPES} 之一，当前输入: {value}"
            )
        return value


class QuestionSnapshotDTO(BaseModel):
    """题目 6 要素快照数据传输对象模型。

    物理彻底解耦历史作答与原题库，存储出题瞬间题目的完整快照。
    """

    model_config = ConfigDict(from_attributes=True)

    stem: str = Field(..., min_length=1, description="题干内容全文")
    question_type: str = Field(
        ...,
        description="题型标识 (single_choice, multiple_choice, true_false, short_answer)",
    )
    options: list[dict[str, Any]] = Field(
        default_factory=list,
        description="客观选择题选项列表 (包含 key 和 content)",
    )
    answer: str = Field(..., min_length=1, description="参考答案或标准答案")
    explanation: str | None = Field(
        default=None,
        description="题目解析与知识点阐述",
    )
    analysis: str | None = Field(
        default=None,
        description="题目解析别名 (兼容 analysis 字段)",
    )
    source_snippet_id: uuid.UUID | None = Field(
        default=None,
        description="主来源资料切片主键标识",
    )
    source_snippet_ids: list[Any] = Field(
        default_factory=list,
        description="多切片出题上下文标识列表",
    )
    difficulty: int = Field(
        default=3,
        ge=1,
        le=5,
        description="题目难度系数 (1~5)",
    )
    grading_rubric: dict[str, Any] = Field(
        default_factory=dict,
        description="主观题评分细则字典",
    )

    @model_validator(mode="before")
    @classmethod
    def synchronize_explanation_and_analysis(cls, data: Any) -> Any:
        """双向同步 explanation 与 analysis 字段值。"""
        if isinstance(data, dict):
            explanation_val = data.get("explanation")
            analysis_val = data.get("analysis")
            if explanation_val is not None and analysis_val is None:
                data["analysis"] = explanation_val
            elif analysis_val is not None and explanation_val is None:
                data["explanation"] = analysis_val
        return data


class PracticeItemDetailResponse(BaseModel):
    """练习会话单题作答项详情响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    attempt_item_id: uuid.UUID = Field(..., description="作答项主键 UUIDv4")
    id: uuid.UUID | None = Field(default=None, description="作答项主键标识别名")
    question_id: uuid.UUID | None = Field(
        default=None,
        description="关联题目弱外键标识",
    )
    order_index: int = Field(..., ge=1, description="卷面题目序号 (从 1 起始)")
    status: str = Field(
        default="unanswered",
        description="作答项当前状态 (unanswered, answered, graded)",
    )
    user_answer: Any | None = Field(
        default=None,
        description="用户作答原文或选项标识 (绝密数据，严禁记录入日志)",
    )
    time_spent_seconds: int = Field(
        default=0,
        ge=0,
        description="单题作答耗时 (秒)",
    )
    duration_seconds: int = Field(
        default=0,
        ge=0,
        description="单题作答耗时别名 (秒)",
    )
    is_answered: bool = Field(default=False, description="是否已作答")
    score: float | None = Field(default=None, description="本题判定得分")
    max_score: float = Field(default=1.0, description="本题满分基准分值")
    question_snapshot: QuestionSnapshotDTO | dict[str, Any] = Field(
        ...,
        description="题目 6 要素快照",
    )

    @model_validator(mode="before")
    @classmethod
    def synchronize_item_fields(cls, data: Any) -> Any:
        """同步主键、耗时及作答标记字段。"""
        if not isinstance(data, dict):
            field_names = (
                "id",
                "attempt_item_id",
                "question_id",
                "order_index",
                "status",
                "user_answer",
                "time_spent_seconds",
                "duration_seconds",
                "is_answered",
                "score",
                "max_score",
                "question_snapshot",
            )
            extracted = {name: getattr(data, name) for name in field_names if hasattr(data, name)}
            if extracted:
                data = extracted

        if isinstance(data, dict):
            if data.get("max_score") is None:
                data["max_score"] = 1.0

            # 同步 attempt_item_id 与 id
            if "attempt_item_id" not in data and "id" in data:
                data["attempt_item_id"] = data["id"]
            elif "id" not in data and "attempt_item_id" in data:
                data["id"] = data["attempt_item_id"]

            # 同步 time_spent_seconds 与 duration_seconds
            if "time_spent_seconds" not in data and "duration_seconds" in data:
                data["time_spent_seconds"] = data["duration_seconds"]
            elif "duration_seconds" not in data and "time_spent_seconds" in data:
                data["duration_seconds"] = data["time_spent_seconds"]

            # 用户作答不为空时更新 is_answered 与 status
            if data.get("user_answer") is not None:
                data.setdefault("is_answered", True)
                if data.get("status") == "unanswered":
                    data["status"] = "answered"
        return data


# 别名定义以保持兼容性
AttemptItemDetailResponse = PracticeItemDetailResponse


class PracticeDetailResponse(BaseModel):
    """练习会话详情与卷面题目快照完整响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    practice_id: uuid.UUID = Field(..., description="练习主键 UUIDv4")
    id: uuid.UUID | None = Field(default=None, description="练习主键标识别名")
    title: str = Field(..., description="练习标题")
    material_id: uuid.UUID = Field(..., description="关联学习资料标识")
    mode: str = Field(default="sequential", description="组卷模式")
    status: str = Field(..., description="练习生命周期状态")
    total_count: int = Field(..., ge=0, description="练习题目总数")
    question_count: int | None = Field(default=None, ge=0, description="题目总数别名")
    completed_count: int = Field(default=0, ge=0, description="已完成作答题目数")
    total_score: float | None = Field(default=None, description="卷面最终累计得分")
    max_score: float | None = Field(default=None, description="卷面总满分分值")
    source_type: str = Field(default="normal", description="练习来源类型")
    source_report_id: uuid.UUID | None = Field(
        default=None,
        description="来源诊断报告标识",
    )
    created_at: datetime | None = Field(default=None, description="创建时间")
    submitted_at: datetime | None = Field(default=None, description="提交时间")
    completed_at: datetime | None = Field(default=None, description="判分完成时间")
    items: list[PracticeItemDetailResponse] = Field(
        default_factory=list,
        description="卷面题目作答项列表 (按 order_index 升序排列)",
    )

    @model_validator(mode="before")
    @classmethod
    def synchronize_detail_fields(cls, data: Any) -> Any:
        """同步 practice_id 与 id，以及 total_count 与 question_count。"""
        if not isinstance(data, dict):
            field_names = (
                "id",
                "practice_id",
                "title",
                "material_id",
                "mode",
                "status",
                "total_count",
                "question_count",
                "completed_count",
                "total_score",
                "max_score",
                "source_type",
                "source_report_id",
                "created_at",
                "submitted_at",
                "completed_at",
                "items",
            )
            extracted = {name: getattr(data, name) for name in field_names if hasattr(data, name)}
            if extracted:
                data = extracted

        if isinstance(data, dict):
            if data.get("source_type") is None:
                data["source_type"] = "normal"

            if "practice_id" not in data and "id" in data:
                data["practice_id"] = data["id"]
            elif "id" not in data and "practice_id" in data:
                data["id"] = data["practice_id"]

            if "total_count" not in data and "question_count" in data:
                data["total_count"] = data["question_count"]
            elif "question_count" not in data and "total_count" in data:
                data["question_count"] = data["total_count"]
        return data


class PracticeSummaryResponse(BaseModel):
    """练习会话列表项精简摘要响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="练习主键 UUIDv4")
    practice_id: uuid.UUID | None = Field(default=None, description="练习主键标识别名")
    material_id: uuid.UUID = Field(..., description="关联学习资料主键")
    title: str = Field(..., description="练习标题")
    status: str = Field(..., description="练习生命周期状态")
    question_count: int = Field(default=0, ge=0, description="题目总数")
    total_count: int | None = Field(default=None, ge=0, description="题目总数别名")
    completed_count: int | None = Field(default=None, ge=0, description="已完成题数")
    mode: str | None = Field(default=None, description="组卷模式")
    total_score: float | None = Field(default=None, description="卷面最终得分")
    max_score: float | None = Field(default=None, description="卷面满分分值")
    source_type: str = Field(default="normal", description="练习来源类型")
    created_at: datetime | None = Field(default=None, description="创建时间")
    submitted_at: datetime | None = Field(default=None, description="提交时间")
    completed_at: datetime | None = Field(default=None, description="完成时间")

    @model_validator(mode="before")
    @classmethod
    def synchronize_summary_fields(cls, data: Any) -> Any:
        """同步 id 与 practice_id，以及 question_count 与 total_count。"""
        if not isinstance(data, dict):
            field_names = (
                "id",
                "practice_id",
                "material_id",
                "title",
                "status",
                "question_count",
                "total_count",
                "completed_count",
                "mode",
                "total_score",
                "max_score",
                "source_type",
                "created_at",
                "submitted_at",
                "completed_at",
            )
            extracted = {name: getattr(data, name) for name in field_names if hasattr(data, name)}
            if extracted:
                data = extracted

        if isinstance(data, dict):
            if data.get("source_type") is None:
                data["source_type"] = "normal"

            if "id" not in data and "practice_id" in data:
                data["id"] = data["practice_id"]
            elif "practice_id" not in data and "id" in data:
                data["practice_id"] = data["id"]

            if "question_count" not in data and "total_count" in data:
                data["question_count"] = data["total_count"]
            elif "total_count" not in data and "question_count" in data:
                data["total_count"] = data["question_count"]
        return data


# 别名定义以保持兼容性
PracticeListItemResponse = PracticeSummaryResponse


class PracticeListResponse(BaseModel):
    """练习会话历史列表分页响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    items: list[PracticeSummaryResponse] = Field(
        default_factory=list,
        description="练习摘要列表",
    )
    total: int = Field(..., ge=0, description="总匹配记录数")
    limit: int = Field(default=20, ge=1, le=100, description="分页大小")
    offset: int = Field(default=0, ge=0, description="分页偏移量")


class PracticeCreateResponse(BaseModel):
    """创建练习会话响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="练习主键 UUIDv4")
    material_id: uuid.UUID = Field(..., description="归属学习资料主键")
    title: str = Field(..., description="练习标题")
    status: str = Field(default="not_started", description="练习生命周期状态")
    question_count: int = Field(..., ge=1, le=50, description="练习题目总数")
    source_type: str = Field(default="normal", description="练习来源类型")
    source_report_id: uuid.UUID | None = Field(
        default=None,
        description="来源诊断报告标识",
    )
    created_at: datetime = Field(..., description="创建时间")


class SaveAnswerRequest(BaseModel):
    """逐题作答草稿实时暂存请求入参模型。"""

    question_id: uuid.UUID = Field(..., description="关联题目主键 UUIDv4")
    user_answer: str | list[Any] | dict[str, Any] | None = Field(
        default=None,
        description="用户作答文本或选项标识 (允许字符串、多选数组、组合题字典或空)",
    )
    time_spent_seconds: int = Field(
        default=0,
        ge=0,
        description="单题作答耗时 (秒)",
    )
    duration_seconds: int | None = Field(
        default=None,
        ge=0,
        description="单题作答耗时别名 (秒)",
    )

    @model_validator(mode="before")
    @classmethod
    def synchronize_duration_and_time(cls, data: Any) -> Any:
        """同步 time_spent_seconds 与 duration_seconds。"""
        if isinstance(data, dict):
            if "time_spent_seconds" not in data and "duration_seconds" in data:
                data["time_spent_seconds"] = data["duration_seconds"]
            elif "duration_seconds" not in data and "time_spent_seconds" in data:
                data["duration_seconds"] = data["time_spent_seconds"]
        return data


# 别名定义以保持兼容性
PracticeSaveAnswerRequest = SaveAnswerRequest


class SaveAnswerResponse(BaseModel):
    """逐题作答草稿实时暂存响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    attempt_item_id: uuid.UUID = Field(..., description="作答项主键 UUIDv4")
    status: str = Field(default="answered", description="作答项当前状态")
    updated_at: datetime | None = Field(default=None, description="保存更新时间戳")
    practice_id: uuid.UUID | None = Field(default=None, description="归属练习主键")
    question_id: uuid.UUID | None = Field(default=None, description="关联题目主键")
    user_answer: Any | None = Field(default=None, description="保存的作答内容")
    is_answered: bool = Field(default=True, description="是否已标记作答")
    duration_seconds: int = Field(default=0, ge=0, description="累计作答耗时 (秒)")
    time_spent_seconds: int = Field(default=0, ge=0, description="累计作答耗时别名 (秒)")

    @model_validator(mode="before")
    @classmethod
    def synchronize_response_time(cls, data: Any) -> Any:
        """同步耗时字段。"""
        if isinstance(data, dict):
            if "time_spent_seconds" not in data and "duration_seconds" in data:
                data["time_spent_seconds"] = data["duration_seconds"]
            elif "duration_seconds" not in data and "time_spent_seconds" in data:
                data["duration_seconds"] = data["time_spent_seconds"]
        return data


# 别名定义以保持兼容性
PracticeSaveAnswerResponse = SaveAnswerResponse


class PracticeStatusResponse(BaseModel):
    """练习会话状态变更 (暂停/恢复) 响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    practice_id: uuid.UUID = Field(..., description="练习主键 UUIDv4")
    id: uuid.UUID | None = Field(default=None, description="练习主键标识别名")
    status: str = Field(..., description="变更后的练习状态")
    message: str = Field(default="", description="状态流转提示信息")

    @model_validator(mode="before")
    @classmethod
    def synchronize_practice_id(cls, data: Any) -> Any:
        """同步 practice_id 与 id。"""
        if isinstance(data, dict):
            if "practice_id" not in data and "id" in data:
                data["practice_id"] = data["id"]
            elif "id" not in data and "practice_id" in data:
                data["id"] = data["practice_id"]
        return data


# 别名定义以保持兼容性
PracticeStatusActionResponse = PracticeStatusResponse


class PracticeSubmitRequest(BaseModel):
    """交卷提交请求入参模型。"""

    confirm_unanswered: bool = Field(
        default=False,
        description="若存在未作答题目是否确认提交 (False 时若有未作答则拒绝交卷)",
    )


class SubmitPracticeResponse(BaseModel):
    """交卷提交与调度响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    practice_id: uuid.UUID = Field(..., description="练习主键 UUIDv4")
    status: str = Field(..., description="交卷后练习状态 (completed / partially_graded)")
    message: str = Field(default="", description="交卷处理提示说明")
    uncompleted_count: int = Field(default=0, ge=0, description="未完成作答题目数")
    unanswered_count: int | None = Field(default=None, ge=0, description="未作答题数别名")
    is_idempotent_replay: bool = Field(
        default=False,
        description="是否命中强幂等缓存快照回放",
    )
    task_id: str | None = Field(default=None, description="异步判题调度任务标识")
    total_questions: int | None = Field(default=None, ge=0, description="卷面总题数")
    answered_questions: int | None = Field(default=None, ge=0, description="已作答题数")
    submitted_at: datetime | None = Field(default=None, description="交卷提交时间戳")

    @model_validator(mode="before")
    @classmethod
    def synchronize_unanswered_count(cls, data: Any) -> Any:
        """同步 uncompleted_count 与 unanswered_count。"""
        if isinstance(data, dict):
            if "uncompleted_count" not in data and "unanswered_count" in data:
                data["uncompleted_count"] = data["unanswered_count"]
            elif "unanswered_count" not in data and "uncompleted_count" in data:
                data["unanswered_count"] = data["uncompleted_count"]
        return data


# 别名定义以保持兼容性
PracticeSubmitResponse = SubmitPracticeResponse
