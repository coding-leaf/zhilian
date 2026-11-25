"""知识点与双向切片溯源数据契约与 DTO 校验模型定义。

严格遵循 AGENTS.md 规范与 spec.md 技术契约：
- 字段类型全标注，支持 Pydantic v2 与 from_attributes 特性；
- 缩写白名单仅限 api, id, url, ocr, llm, db, config, env；
- Google 风格中文 Docstring。
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class KnowledgeTreeNodeResponse(BaseModel):
    """知识点树形拓扑节点响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="知识点主键 UUIDv4")
    material_id: uuid.UUID = Field(..., description="归属学习资料主键")
    version_id: uuid.UUID = Field(..., description="归属资料版本标识")
    parent_id: uuid.UUID | None = Field(default=None, description="父知识点主键")
    name: str = Field(..., description="知识点规范名称")
    description: str = Field(default="", description="知识点概念简述")
    structured_content: dict[str, Any] | None = Field(
        default=None,
        description=(
            "知识点结构化内容 (core_summary/key_takeaways/key_formulas/"
            "boundary_notes/可选 derivation_steps/common_mistakes)"
        ),
    )
    sort_order: int = Field(default=0, description="资料内顺序序号")
    level: int = Field(default=1, ge=1, le=5, description="知识点层级深度 1~5")
    is_low_confidence: bool = Field(default=False, description="是否标记为低置信度")
    has_study_guide: bool = Field(default=False, description="是否已生成考前精讲笔记缓存")
    children: list["KnowledgeTreeNodeResponse"] = Field(
        default_factory=list,
        description="递归子知识点列表",
    )

    @field_validator("sort_order", mode="before")
    @classmethod
    def _coerce_sort_order(cls, value: Any) -> int:
        return 0 if value is None else int(value)


class KnowledgeTreeResponse(BaseModel):
    """资料知识树根节点树形拓扑响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    material_id: uuid.UUID = Field(..., description="归属学习资料主键")
    version_id: uuid.UUID = Field(..., description="归属资料版本标识")
    nodes: list[KnowledgeTreeNodeResponse] = Field(
        default_factory=list,
        description="根级知识点及其子树节点列表",
    )


class KnowledgePointDetailResponse(BaseModel):
    """单个知识点详细元数据响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="知识点主键 UUIDv4")
    material_id: uuid.UUID = Field(..., description="归属学习资料主键")
    version_id: uuid.UUID = Field(..., description="归属资料版本标识")
    parent_id: uuid.UUID | None = Field(default=None, description="父知识点主键")
    name: str = Field(..., description="知识点规范名称")
    description: str = Field(default="", description="知识点概念简述")
    structured_content: dict[str, Any] | None = Field(
        default=None,
        description=(
            "知识点结构化内容 (core_summary/key_takeaways/key_formulas/"
            "boundary_notes/可选 derivation_steps/common_mistakes)"
        ),
    )
    sort_order: int = Field(default=0, description="资料内顺序序号")
    level: int = Field(default=1, ge=1, le=5, description="知识点层级深度 1~5")
    is_low_confidence: bool = Field(default=False, description="是否标记为低置信度")
    batch_id: str = Field(default="", description="抽取批次号")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")

    @field_validator("sort_order", mode="before")
    @classmethod
    def _coerce_sort_order(cls, value: Any) -> int:
        return 0 if value is None else int(value)


class SnippetSourceResponse(BaseModel):
    """来源切片追溯详情响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="切片主键 UUIDv4")
    material_id: uuid.UUID = Field(..., description="归属资料主键")
    version_id: uuid.UUID = Field(..., description="归属版本标识")
    page_index: int = Field(default=1, ge=1, description="所在页码索引 (从 1 起算)")
    page_end: int | None = Field(default=None, ge=1, description="跨页合并时的结束页码索引 (可选)")
    snippet_index: int = Field(..., ge=0, description="版本内连续切片序号")
    chapter_title: str = Field(default="", description="所属章节标题")
    content: str = Field(..., description="切片纯文本内容")
    char_length: int = Field(..., ge=0, description="切片字符总数")

    @model_validator(mode="before")
    @classmethod
    def _extract_snippet_attributes(cls, data: Any) -> Any:
        """兼容 ORM 实体与字典数据源的页码及长度解析。

        Args:
            data: 输入数据字典或 ORM 实体。

        Returns:
            Any: 规整后的属性字典或原始对象。
        """
        if isinstance(data, dict):
            return data

        # 处理 ORM 实体
        source_info = getattr(data, "source_info", None)
        page_index = getattr(data, "page_index", None)
        if page_index is None:
            if isinstance(source_info, dict):
                page_index = source_info.get("page_number", source_info.get("page_index", 1))
            else:
                page_index = 1

        raw_page_end = getattr(data, "page_end", None)
        if raw_page_end is None and isinstance(source_info, dict):
            raw_page_end = source_info.get("page_end")
        page_end: int | None = None
        if (
            isinstance(raw_page_end, int)
            and not isinstance(raw_page_end, bool)
            and raw_page_end >= 1
        ):
            page_end = raw_page_end

        content = getattr(data, "content", "")
        char_length = getattr(data, "char_length", None)
        if char_length is None:
            char_length = len(content)

        return {
            "id": data.id,
            "material_id": data.material_id,
            "version_id": data.version_id,
            "snippet_index": data.snippet_index,
            "content": content,
            "char_length": char_length,
            "chapter_title": getattr(data, "chapter_title", "") or "",
            "page_index": page_index,
            "page_end": page_end,
        }


class PointSourceListResponse(BaseModel):
    """反向溯源：知识点来源切片列表响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    knowledge_point_id: uuid.UUID = Field(..., description="查询的知识点主键")
    snippets: list[SnippetSourceResponse] = Field(
        default_factory=list,
        description="关联的来源资料切片列表",
    )


class SnippetKnowledgePointsResponse(BaseModel):
    """正向溯源：切片关联知识点列表响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    snippet_id: uuid.UUID = Field(..., description="查询的资料切片主键")
    knowledge_points: list[KnowledgePointDetailResponse] = Field(
        default_factory=list,
        description="关联的知识点列表",
    )


class ExtractKnowledgeRequest(BaseModel):
    """触发知识点抽取建树请求模型。"""

    version_id: uuid.UUID | None = Field(
        default=None,
        description="指定资料版本主键 (可选，缺省时自动使用最新激活版本)",
    )


class ExtractKnowledgeResponse(BaseModel):
    """触发知识点抽取建树响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    material_id: uuid.UUID = Field(..., description="归属资料主键")
    version_id: uuid.UUID = Field(..., description="处理的资料版本标识")
    extracted_count: int = Field(..., ge=0, description="抽取的知识点总数量")
    has_low_confidence: bool = Field(default=False, description="是否存在低置信度降级标记")
    status: str = Field(default="ready", description="解析处理状态")


# ==============================================================================
# Stage 2: 考前精讲笔记强类型 Schema 与预热状态契约
# ==============================================================================


class StudyGuideSymbol(BaseModel):
    """考前精讲符号速查条目。"""

    symbol: str = Field(..., description="LaTeX 符号，如 $w$")
    meaning: str = Field(..., description="物理或数学含义")
    note: str = Field(default="", description="维度、取值范围或易错提示")


class StudyGuideDerivationStep(BaseModel):
    """考前精讲逐步推导步骤。"""

    step_title: str = Field(..., description="步骤标题")
    formula: str = Field(default="", description="对应展示公式 $$...$$")
    explanation: str = Field(..., description="讲清成立依据与关键变换")


class StudyGuideWorkedExample(BaseModel):
    """考前精讲典型例题与分步解答。"""

    title: str = Field(..., description="例题标题")
    question_type: str = Field(default="综合应用", description="题型标签")
    problem: str = Field(..., description="完整题干")
    solution_idea: str = Field(..., description="解题切入点与标准套路")
    solution_steps: list[str] = Field(default_factory=list, description="分步标准解答")
    final_answer: str = Field(..., description="明确结论/最终答案")


class StudyGuideComparison(BaseModel):
    """相邻易混概念对比条目。"""

    target_concept: str = Field(..., description="相邻易混概念名称")
    similarities: str = Field(..., description="共同点")
    differences: str = Field(..., description="本质区别")
    exam_distinction: str = Field(..., description="考场快速区分口诀或判别依据")


class StudyGuidePitfall(BaseModel):
    """考场高频避坑条目。"""

    mistake: str = Field(..., description="考场常见错误做法/误解")
    why_wrong: str = Field(..., description="错因剖析")
    correction: str = Field(..., description="正确做法与记忆锚点")


class StudyGuideContent(BaseModel):
    """考前精讲笔记 9 要素结构化输出契约。"""

    schema_version: int = Field(default=1, description="精讲笔记 Schema 版本号")
    exam_positioning: str = Field(..., description="1. 直观定位与考法")
    core_definition: str = Field(..., description="2. 完整严谨定义与通俗直觉类比")
    symbol_table: list[StudyGuideSymbol] = Field(
        default_factory=list, description="3. 核心符号速查表"
    )
    key_formulas: list[str] = Field(default_factory=list, description="4. 核心结论公式组")
    derivation_steps: list[StudyGuideDerivationStep] = Field(
        default_factory=list, description="5. 逐步推导/算法流程链"
    )
    worked_examples: list[StudyGuideWorkedExample] = Field(
        default_factory=list, description="6. 1~2 道典型例题"
    )
    comparisons: list[StudyGuideComparison] = Field(
        default_factory=list, description="7. 相邻易混概念对比"
    )
    pitfalls: list[StudyGuidePitfall] = Field(default_factory=list, description="8. 高频避坑")
    memory_anchors: list[str] = Field(default_factory=list, description="9. 考前 30 秒速记锚点")

    @model_validator(mode="before")
    @classmethod
    def _coerce_null_lists(cls, data: Any) -> Any:
        """兼容大模型偶发将可选列表字段输出为 null 的情况。"""
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        for field_name in (
            "symbol_table",
            "key_formulas",
            "derivation_steps",
            "worked_examples",
            "comparisons",
            "pitfalls",
            "memory_anchors",
        ):
            if normalized.get(field_name) is None:
                normalized[field_name] = []
        if normalized.get("schema_version") is None:
            normalized["schema_version"] = 1
        return normalized


class StudyGuideGenerateRequest(BaseModel):
    """触发单考点考前精讲生成请求模型。"""

    force: bool = Field(default=False, description="是否忽略永久缓存强制重新生成")


class StudyGuideResponse(BaseModel):
    """单考点考前精讲查询与生成响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    knowledge_point_id: uuid.UUID = Field(..., description="知识点主键")
    status: Literal["empty", "generating", "ready"] = Field(..., description="精讲状态")
    study_guide: StudyGuideContent | None = Field(default=None, description="精讲笔记内容")
    generated_at: datetime | None = Field(default=None, description="生成时间 (UTC)")


class StudyGuidePrewarmRequest(BaseModel):
    """一键预生成整章考前精讲请求模型。"""

    version_id: uuid.UUID | None = Field(default=None, description="可选指定资料版本标识")
    force: bool = Field(default=False, description="是否强制重新生成已有精讲")


class StudyGuidePrewarmResponse(BaseModel):
    """一键预生成整章考前精讲入队响应模型。"""

    material_id: uuid.UUID = Field(..., description="学习资料主键")
    version_id: uuid.UUID = Field(..., description="资料版本标识")
    status: Literal["queued", "running", "completed"] = Field(..., description="预热状态")
    total_kps: int = Field(..., ge=0, description="目标叶子核心考点总数")
    ready_kps: int = Field(..., ge=0, description="当前已就绪精讲考点数")


class StudyGuidePrewarmStatusResponse(BaseModel):
    """整章考前精讲预热进度查询响应模型。"""

    material_id: uuid.UUID = Field(..., description="学习资料主键")
    version_id: uuid.UUID = Field(..., description="资料版本标识")
    status: Literal["idle", "queued", "running", "completed", "partial_failed"] = Field(
        ..., description="预热任务状态"
    )
    total_kps: int = Field(..., ge=0, description="目标叶子核心考点总数")
    ready_kps: int = Field(..., ge=0, description="当前已就绪精讲考点数")
    failed_kps: int = Field(..., ge=0, description="本轮预热失败考点数")
    current_kp_name: str | None = Field(default=None, description="当前正在生成的考点名称")


# 别名兼容导出 (与 spec.md / plan.md 命名对齐)
KnowledgeTreeNode = KnowledgeTreeNodeResponse
KnowledgeSnippetsResponse = PointSourceListResponse
KnowledgeExtractRequest = ExtractKnowledgeRequest
KnowledgeExtractResponse = ExtractKnowledgeResponse

__all__ = [
    "ExtractKnowledgeRequest",
    "ExtractKnowledgeResponse",
    "KnowledgeExtractRequest",
    "KnowledgeExtractResponse",
    "KnowledgePointDetailResponse",
    "KnowledgeSnippetsResponse",
    "KnowledgeTreeNode",
    "KnowledgeTreeNodeResponse",
    "KnowledgeTreeResponse",
    "PointSourceListResponse",
    "SnippetKnowledgePointsResponse",
    "SnippetSourceResponse",
    "StudyGuideComparison",
    "StudyGuideContent",
    "StudyGuideDerivationStep",
    "StudyGuideGenerateRequest",
    "StudyGuidePitfall",
    "StudyGuidePrewarmRequest",
    "StudyGuidePrewarmResponse",
    "StudyGuidePrewarmStatusResponse",
    "StudyGuideResponse",
    "StudyGuideSymbol",
    "StudyGuideWorkedExample",
]
