"""课程文件夹模块 Pydantic 数据契约与数据传输对象 (DTO) 定义。

定义课程文件夹 CRUD 的请求校验与响应序列化模型。
严格遵循 AGENTS.md 规范：
- 字段类型全标注，支持 Pydantic v2 与 from_attributes 特性；
- 缩写白名单仅限 api, id, url, ocr, llm, db, config, env；
- Google 风格中文 Docstring。
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# 依据：数据库 material_folders 表 name 字段长度上限 100 字符
MAX_FOLDER_NAME_LENGTH: int = 100


class FolderCreateRequest(BaseModel):
    """课程文件夹创建请求模型。"""

    name: str = Field(
        ...,
        min_length=1,
        max_length=MAX_FOLDER_NAME_LENGTH,
        description="课程文件夹名称",
    )


class FolderUpdateRequest(BaseModel):
    """课程文件夹重命名请求模型。"""

    name: str = Field(
        ...,
        min_length=1,
        max_length=MAX_FOLDER_NAME_LENGTH,
        description="课程文件夹新名称",
    )


class FolderDetailResponse(BaseModel):
    """课程文件夹详情响应模型 (含聚合统计)。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="课程文件夹主键 UUIDv4")
    name: str = Field(..., max_length=MAX_FOLDER_NAME_LENGTH, description="课程文件夹名称")
    parent_id: uuid.UUID | None = Field(default=None, description="父文件夹主键 (本期恒为 NULL)")
    sort_order: int = Field(default=0, description="课程列表排序权重")
    is_archived: bool = Field(..., description="是否处于归档状态")
    archived_at: datetime | None = Field(default=None, description="归档时间")
    purge_after: datetime | None = Field(
        default=None, description="归档后物理清理时间 (archived_at + 7 天)"
    )
    material_count: int = Field(default=0, ge=0, description="课程内有效资料总数")
    ready_material_count: int = Field(default=0, ge=0, description="课程内解析就绪资料数")
    knowledge_point_count: int = Field(default=0, ge=0, description="课程内知识点总数")
    question_count: int = Field(default=0, ge=0, description="课程内题目总数")
    last_practice_at: datetime | None = Field(default=None, description="课程内最近练习时间")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="最后更新时间")


class FolderListResponse(BaseModel):
    """课程文件夹列表响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    items: list[FolderDetailResponse] = Field(..., description="课程文件夹列表")
    total: int = Field(..., ge=0, description="符合条件的课程文件夹总数")


class FolderDeleteResponse(BaseModel):
    """课程文件夹归档/清理结果响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="课程文件夹主键 UUIDv4")
    is_deleted: bool = Field(..., description="是否已删除/归档")
    archived_at: datetime | None = Field(default=None, description="归档时间")
    purge_after: datetime | None = Field(default=None, description="物理清理时间")
    message: str = Field(..., description="操作结果说明")


class FolderKnowledgePointItem(BaseModel):
    """课程内单个考点条目响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="知识点主键 UUIDv4")
    name: str = Field(..., description="知识点名称")
    level: int = Field(default=1, ge=1, description="知识点层级深度 (根节点为 1)")
    parent_id: uuid.UUID | None = Field(default=None, description="父知识点主键 (根节点为空)")


class FolderKnowledgePointGroup(BaseModel):
    """按来源资料分组的课程考点集合响应模型。"""

    material_id: uuid.UUID = Field(..., description="来源资料主键 UUIDv4")
    material_title: str = Field(..., description="来源资料标题")
    knowledge_points: list[FolderKnowledgePointItem] = Field(
        default_factory=list, description="该资料下的考点列表 (按层级排序)"
    )


class FolderKnowledgePointsResponse(BaseModel):
    """课程考点列表响应模型 (按资料分组，用于课程范围出题选考点)。"""

    folder_id: uuid.UUID = Field(..., description="课程文件夹主键 UUIDv4")
    groups: list[FolderKnowledgePointGroup] = Field(
        default_factory=list, description="按来源资料分组的考点集合"
    )
    total: int = Field(default=0, ge=0, description="考点总数")
