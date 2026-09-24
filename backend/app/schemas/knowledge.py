"""知识点与双向切片溯源数据契约与 DTO 校验模型定义。

严格遵循 AGENTS.md 规范与 spec.md 技术契约：
- 字段类型全标注，支持 Pydantic v2 与 from_attributes 特性；
- 缩写白名单仅限 api, id, url, ocr, llm, db, config, env；
- Google 风格中文 Docstring。
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class KnowledgeTreeNodeResponse(BaseModel):
    """知识点树形拓扑节点响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="知识点主键 UUIDv4")
    material_id: uuid.UUID = Field(..., description="归属学习资料主键")
    version_id: uuid.UUID = Field(..., description="归属资料版本标识")
    parent_id: uuid.UUID | None = Field(default=None, description="父知识点主键")
    name: str = Field(..., description="知识点规范名称")
    description: str = Field(default="", description="知识点概念简述")
    level: int = Field(default=1, ge=1, le=5, description="知识点层级深度 1~5")
    is_low_confidence: bool = Field(default=False, description="是否标记为低置信度")
    children: list["KnowledgeTreeNodeResponse"] = Field(
        default_factory=list,
        description="递归子知识点列表",
    )


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
    level: int = Field(default=1, ge=1, le=5, description="知识点层级深度 1~5")
    is_low_confidence: bool = Field(default=False, description="是否标记为低置信度")
    batch_id: str = Field(default="", description="抽取批次号")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")


class SnippetSourceResponse(BaseModel):
    """来源切片追溯详情响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="切片主键 UUIDv4")
    material_id: uuid.UUID = Field(..., description="归属资料主键")
    version_id: uuid.UUID = Field(..., description="归属版本标识")
    page_index: int = Field(default=1, ge=1, description="所在页码索引 (从 1 起算)")
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
        page_index = getattr(data, "page_index", None)
        if page_index is None:
            source_info = getattr(data, "source_info", None)
            if isinstance(source_info, dict):
                page_index = source_info.get("page_number", source_info.get("page_index", 1))
            else:
                page_index = 1

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
]
