"""自定义题单与题单收纳请求/响应契约模型。"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _strip_required_name(value: str) -> str:
    """去除首尾空白并校验题单名称非空。"""
    trimmed = value.strip()
    if not trimmed:
        raise ValueError("题单名称不能为空白字符")
    return trimmed


class CollectionCreateRequest(BaseModel):
    """创建自定义题单请求体。"""

    name: str = Field(..., min_length=1, max_length=80, description="题单名称")
    description: str = Field(default="", max_length=255, description="题单简介")
    folder_id: uuid.UUID | None = Field(default=None, description="可选关联课程文件夹主键")
    color_token: str | None = Field(default=None, max_length=32, description="语义化色盘 token")
    is_pinned: bool = Field(default=False, description="是否置顶展示")

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _strip_required_name(value)


class CollectionUpdateRequest(BaseModel):
    """更新自定义题单请求体（严格走 PUT，禁用 PATCH）。"""

    name: str | None = Field(default=None, min_length=1, max_length=80, description="题单名称")
    description: str | None = Field(default=None, max_length=255, description="题单简介")
    folder_id: uuid.UUID | None = Field(default=None, description="关联课程文件夹主键")
    clear_folder: bool = Field(default=False, description="是否解除与课程文件夹的绑定")
    color_token: str | None = Field(default=None, max_length=32, description="语义化色盘 token")
    is_pinned: bool | None = Field(default=None, description="是否置顶展示")

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _strip_required_name(value)


class QuestionCollectionResponse(BaseModel):
    """自定义题单详情与列表项响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="题单主键")
    name: str = Field(..., description="题单名称")
    description: str = Field(default="", description="题单简介")
    folder_id: uuid.UUID | None = Field(default=None, description="关联课程主键")
    folder_name: str | None = Field(default=None, description="关联课程名称")
    color_token: str | None = Field(default=None, description="语义化色盘 token")
    is_pinned: bool = Field(default=False, description="是否置顶")
    sort_order: int = Field(default=0, description="排序权重")
    question_count: int = Field(default=0, ge=0, description="活跃题目数量（不含软删除）")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")


class CollectionListResponse(BaseModel):
    """自定义题单列表响应模型。"""

    items: list[QuestionCollectionResponse] = Field(default_factory=list, description="题单列表")
    total: int = Field(..., ge=0, description="题单总数")


class CollectionQuestionItemResponse(BaseModel):
    """题单内单道题目详情响应模型。"""

    id: uuid.UUID = Field(..., description="收纳条目主键")
    collection_id: uuid.UUID = Field(..., description="所属题单主键")
    question_id: uuid.UUID = Field(..., description="题目主键")
    question_type: str = Field(..., description="题型")
    difficulty: int = Field(..., description="难度 1~5")
    content: str = Field(..., description="题干内容")
    options: list[dict[str, Any]] = Field(default_factory=list, description="题目选项")
    answer: str = Field(..., description="参考答案")
    explanation: str = Field(default="", description="题目解析")
    kp_id: uuid.UUID | None = Field(default=None, description="知识点主键")
    kp_name: str | None = Field(default=None, description="知识点名称")
    material_id: uuid.UUID | None = Field(default=None, description="所属讲义主键")
    material_title: str | None = Field(default=None, description="所属讲义标题")
    note: str | None = Field(default=None, description="个人收纳备注")
    added_at: datetime = Field(..., description="收纳时间")


class CollectionQuestionListResponse(BaseModel):
    """题单内题目分页列表响应模型。"""

    items: list[CollectionQuestionItemResponse] = Field(
        default_factory=list, description="题单题目列表"
    )
    total: int = Field(..., ge=0, description="活跃题目总数")
    page: int = Field(..., ge=1, description="当前页码")
    page_size: int = Field(..., ge=1, description="每页容量")


class CollectionItemsAddRequest(BaseModel):
    """批量向题单收纳题目请求体。"""

    question_ids: list[uuid.UUID] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="待收纳题目主键列表",
    )
    note: str | None = Field(default=None, max_length=500, description="可选收纳备注")


class CollectionItemsAddResponse(BaseModel):
    """批量向题单收纳题目响应体。"""

    added_count: int = Field(..., ge=0, description="本次新增数量")
    skipped_count: int = Field(..., ge=0, description="已存在跳过数量")
    total_count: int = Field(..., ge=0, description="当前题单活跃题目总数")


class QuestionCollectionsResponse(BaseModel):
    """查询单题已加入题单标识列表响应。"""

    question_id: uuid.UUID = Field(..., description="题目主键")
    collection_ids: list[uuid.UUID] = Field(default_factory=list, description="已归属题单主键列表")


class QuestionCollectionsSyncRequest(BaseModel):
    """同步单题归属的全部题单请求体。"""

    collection_ids: list[uuid.UUID] = Field(default_factory=list, description="目标题单主键列表")


class QuestionCollectionsSyncResponse(BaseModel):
    """同步单题归属题单响应体。"""

    question_id: uuid.UUID = Field(..., description="题目主键")
    collection_ids: list[uuid.UUID] = Field(default_factory=list, description="同步后题单主键列表")
    added_count: int = Field(..., ge=0, description="新增归属数量")
    removed_count: int = Field(..., ge=0, description="移除归属数量")


__all__ = [
    "CollectionCreateRequest",
    "CollectionItemsAddRequest",
    "CollectionItemsAddResponse",
    "CollectionListResponse",
    "CollectionQuestionItemResponse",
    "CollectionQuestionListResponse",
    "CollectionUpdateRequest",
    "QuestionCollectionResponse",
    "QuestionCollectionsResponse",
    "QuestionCollectionsSyncRequest",
    "QuestionCollectionsSyncResponse",
]
