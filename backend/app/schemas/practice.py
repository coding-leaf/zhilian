"""练习会话、作答暂存与交卷数据契约与 DTO 校验模型定义。

严格遵循 AGENTS.md 规范与 spec.md 技术契约：
- 字段类型全标注，支持 Pydantic v2 与 from_attributes 特性；
- 缩写白名单仅限 api, id, url, ocr, llm, db, config, env；
- Google 风格中文 Docstring。
"""

import ast
import json
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# 允许的组卷模式白名单集合
VALID_PRACTICE_MODES: set[str] = {"sequential", "random", "weak_points"}
# 允许的练习来源类型白名单集合
VALID_PRACTICE_SOURCE_TYPES: set[str] = {"normal", "weakness", "wrong_record"}


def _normalize_persisted_user_answer(value: str) -> str:
    """将历史 Python repr 多选题作答规范化为标准 JSON 字符串。

    仅当字符串形如字符串列表的 Python repr（如 ``"['A', 'B']"``）时转换，
    其他普通文本作答原样返回，保证跨端传输格式一致 (BUG-PRAC-016)。

    Args:
        value: 数据库存储的原始作答字符串。

    Returns:
        str: 规范化后的标准 JSON 字符串或原字符串。
    """
    stripped = value.strip()
    if not (stripped.startswith("[") and stripped.endswith("]")):
        return value
    try:
        parsed = ast.literal_eval(stripped)
    except (ValueError, SyntaxError):
        return value
    if isinstance(parsed, list) and all(isinstance(item, str) for item in parsed):
        return json.dumps(sorted(parsed), ensure_ascii=False)
    return value


class PracticeCreateRequest(BaseModel):
    """创建练习会话 (组卷) 请求入参模型。"""

    title: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="练习标题 (如: 计算机网络第3章-专项练习)",
    )
    material_id: uuid.UUID | None = Field(
        default=None,
        description="归属学习资料主键 UUIDv4；缺省时由所选题目资料自动解析",
    )
    folder_id: uuid.UUID | None = Field(
        default=None,
        description="归属课程文件夹主键 UUIDv4；提供时按课程范围抽题，material_id 可为空",
    )
    knowledge_point_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="练习覆盖的知识点主键 UUID 列表；folder_id 缺省时至少包含 1 个知识点",
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
    question_ids: list[uuid.UUID] | None = Field(
        default=None,
        description="指定题目主键列表（用于错题本勾选题精确组卷；提供时优先直接以此题目列表生成练习试卷）",
    )
    idempotency_key: str | None = Field(
        default=None,
        max_length=128,
        description="客户端幂等键 (用于防止快速重复连击创建重复练习，缺省时不启用)",
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

    @model_validator(mode="after")
    def _require_practice_scope(self) -> "PracticeCreateRequest":
        """校验 folder_id / question_ids 缺省时必须显式提供至少一个知识点。"""
        if self.folder_id is None and not self.knowledge_point_ids and not self.question_ids:
            raise ValueError("folder_id、knowledge_point_ids 与 question_ids 至少提供一个")
        return self

    @model_validator(mode="after")
    def _sync_question_count_with_ids(self) -> "PracticeCreateRequest":
        """当指定 question_ids 且 question_count 缺省或大于题目数时，自动同步为实际题量。"""
        if self.question_ids and (
            self.question_count == 10 or self.question_count > len(self.question_ids)
        ):
            self.question_count = len(self.question_ids)
        return self


class SourceSnippetDTO(BaseModel):
    """题目来源切片摘要数据传输对象模型。

    承载原文溯源抽屉渲染所需的最小切片信息 (章节/页码/正文)。
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID | str | None = Field(default=None, description="切片主键标识")
    chapter_title: str = Field(default="", description="所属章节标题")
    page_index: int = Field(default=1, ge=1, description="所在页码 (从 1 起算)")
    snippet_content: str = Field(default="", description="切片纯文本内容")


def _pick_final_grading_record(records: Any) -> Any:
    """从判题记录集合中挑选当前生效的终态记录。

    优先返回标记 ``is_final=True`` 的记录；若均未标记，则回退最后一条记录。
    兼容 ORM 实体与纯字典两类数据源。

    Args:
        records: 判题记录集合 (ORM 实体列表或字典列表)。

    Returns:
        Any: 命中的生效判题记录；集合为空或非法时返回 None。
    """
    if not isinstance(records, (list, tuple)) or len(records) == 0:
        return None

    def _is_final(record: Any) -> bool:
        if isinstance(record, dict):
            return bool(record.get("is_final"))
        return bool(getattr(record, "is_final", False))

    final_records = [record for record in records if _is_final(record)]
    candidates = final_records or list(records)
    return candidates[-1]


def _extract_keyword_list(record: Any, field_name: str) -> list[str] | None:
    """从判题记录安全提取关键词列表字段。

    Args:
        record: 判题记录 ORM 实体或字典。
        field_name: 目标字段名 (hit_keywords / missing_keywords)。

    Returns:
        list[str] | None: 规范化后的字符串列表；字段缺失或非法时返回 None。
    """
    if record is None:
        return None
    value = (
        record.get(field_name) if isinstance(record, dict) else getattr(record, field_name, None)
    )
    if not isinstance(value, list):
        return None
    return [str(item) for item in value if item is not None]


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
    knowledge_point_id: uuid.UUID | None = Field(
        default=None,
        description="出题瞬间所属知识点标识 (用于错题溯源与考点归因)",
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
    source_snippet: SourceSnippetDTO | dict[str, Any] | None = Field(
        default=None,
        description="来源切片追溯详情对象 (章节/页码/正文)",
    )
    hit_keywords: list[str] = Field(
        default_factory=list,
        description="命中要点关键词列表 (由生效判题记录合并)",
    )
    missing_keywords: list[str] = Field(
        default_factory=list,
        description="遗漏核心要点列表 (由生效判题记录合并)",
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
    grading_status: str | None = Field(
        default=None,
        description="作答项判题状态 (unanswered/pending_regrade/graded)",
    )
    max_score: float = Field(default=1.0, description="本题满分基准分值")
    hit_keywords: list[str] = Field(
        default_factory=list,
        description="命中要点关键词列表 (由生效判题记录合并)",
    )
    missing_keywords: list[str] = Field(
        default_factory=list,
        description="遗漏核心要点列表 (由生效判题记录合并)",
    )
    source_snippet: SourceSnippetDTO | dict[str, Any] | None = Field(
        default=None,
        description="来源切片追溯详情对象 (章节/页码/正文)",
    )
    question_snapshot: QuestionSnapshotDTO | dict[str, Any] = Field(
        ...,
        description="题目 6 要素快照",
    )

    @model_validator(mode="before")
    @classmethod
    def synchronize_item_fields(cls, data: Any) -> Any:
        """同步主键、耗时、作答标记、要点关键词及来源切片字段。"""
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
                "grading_status",
                "max_score",
                "hit_keywords",
                "missing_keywords",
                "source_snippet",
                "question_snapshot",
            )
            extracted = {name: getattr(data, name) for name in field_names if hasattr(data, name)}
            # 仅消费已预加载的判题记录关系，避免触发 N+1 惰性查询
            loaded_records = getattr(data, "__dict__", {}).get("grading_records")
            if loaded_records is not None:
                extracted["grading_records"] = loaded_records
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

            # 兼容历史 Python repr 多选作答，规范化为标准 JSON 字符串 (BUG-PRAC-016)
            if isinstance(data.get("user_answer"), str):
                data["user_answer"] = _normalize_persisted_user_answer(data["user_answer"])

            # 合并生效判题记录中的命中/遗漏要点 (BUG-GRADE-003)
            final_record = _pick_final_grading_record(data.get("grading_records"))
            if data.get("hit_keywords") is None:
                hit_keywords = _extract_keyword_list(final_record, "hit_keywords")
                if hit_keywords is not None:
                    data["hit_keywords"] = hit_keywords
            if data.get("missing_keywords") is None:
                missing_keywords = _extract_keyword_list(final_record, "missing_keywords")
                if missing_keywords is not None:
                    data["missing_keywords"] = missing_keywords

            # 同步来源切片对象并回填快照 (BUG-GRADE-004)
            snapshot = data.get("question_snapshot")
            source_snippet = data.get("source_snippet")
            if isinstance(snapshot, dict):
                snapshot = dict(snapshot)
                data["question_snapshot"] = snapshot
                if source_snippet is None and snapshot.get("source_snippet") is not None:
                    source_snippet = snapshot.get("source_snippet")
                    data["source_snippet"] = source_snippet
                if data.get("hit_keywords") is not None:
                    snapshot.setdefault("hit_keywords", data["hit_keywords"])
                if data.get("missing_keywords") is not None:
                    snapshot.setdefault("missing_keywords", data["missing_keywords"])
                if source_snippet is not None:
                    snapshot.setdefault("source_snippet", source_snippet)

            # 计算判题状态 (仅在未显式提供时)，使“待重判”不被误判为“判错”
            if data.get("grading_status") is None:
                if data.get("is_answered") is False:
                    data["grading_status"] = "unanswered"
                elif data.get("score") is None:
                    data["grading_status"] = "pending_regrade"
                else:
                    data["grading_status"] = "graded"
        return data


# 别名定义以保持兼容性
AttemptItemDetailResponse = PracticeItemDetailResponse


class PracticeDetailResponse(BaseModel):
    """练习会话详情与卷面题目快照完整响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    practice_id: uuid.UUID = Field(..., description="练习主键 UUIDv4")
    id: uuid.UUID | None = Field(default=None, description="练习主键标识别名")
    title: str = Field(..., description="练习标题")
    material_id: uuid.UUID | None = Field(
        default=None, description="关联学习资料标识（课程范围练习为空）"
    )
    folder_id: uuid.UUID | None = Field(default=None, description="关联课程文件夹标识")
    mode: str = Field(default="sequential", description="组卷模式")
    status: str = Field(..., description="练习生命周期状态")
    total_count: int = Field(..., ge=0, description="练习题目总数")
    question_count: int | None = Field(default=None, ge=0, description="题目总数别名")
    completed_count: int = Field(default=0, ge=0, description="已完成作答题目数")
    time_elapsed_seconds: int = Field(
        default=0,
        ge=0,
        description="练习累计已消耗秒数 (由各题作答耗时聚合)",
    )
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
                "folder_id",
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

            if data.get("mode") is None:
                data["mode"] = "sequential"

            if "practice_id" not in data and "id" in data:
                data["practice_id"] = data["id"]
            elif "id" not in data and "practice_id" in data:
                data["id"] = data["practice_id"]

            if "total_count" not in data and "question_count" in data:
                data["total_count"] = data["question_count"]
            elif "question_count" not in data and "total_count" in data:
                data["question_count"] = data["total_count"]

            # 自动统计已作答题目数：未显式提供非零 completed_count 时由 items 派生 (BUG-PRAC-011)
            if not data.get("completed_count"):
                items = data.get("items") or []
                computed_completed = 0
                for item in items:
                    if isinstance(item, dict):
                        if item.get("is_answered"):
                            computed_completed += 1
                    elif getattr(item, "is_answered", False):
                        computed_completed += 1
                data["completed_count"] = computed_completed

            # 自动聚合累计耗时：未显式提供时由 items 单题耗时求和 (BUG-PRAC-015)
            if not data.get("time_elapsed_seconds"):
                items = data.get("items") or []
                total_duration = 0
                for item in items:
                    if isinstance(item, dict):
                        raw_duration = item.get("duration_seconds")
                        if raw_duration is None:
                            raw_duration = item.get("time_spent_seconds")
                        total_duration += int(raw_duration or 0)
                    else:
                        total_duration += int(getattr(item, "duration_seconds", 0) or 0)
                data["time_elapsed_seconds"] = total_duration
        return data


class PracticeSummaryResponse(BaseModel):
    """练习会话列表项精简摘要响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="练习主键 UUIDv4")
    practice_id: uuid.UUID | None = Field(default=None, description="练习主键标识别名")
    material_id: uuid.UUID | None = Field(
        default=None, description="关联学习资料主键（课程范围练习为空）"
    )
    folder_id: uuid.UUID | None = Field(default=None, description="关联课程文件夹标识")
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
                "folder_id",
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
    material_id: uuid.UUID | None = Field(
        default=None, description="归属学习资料主键（课程范围练习为空）"
    )
    folder_id: uuid.UUID | None = Field(default=None, description="归属课程文件夹标识")
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
    status: str = Field(
        ..., description="交卷后练习状态 (submitted / partially_graded / completed)"
    )
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
