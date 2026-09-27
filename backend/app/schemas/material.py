"""学习资料模块 Pydantic 数据契约与数据传输对象 (DTO) 定义。

定义请求校验模型与响应序列化模型，实现接口入参验证与出参脱敏转换。
严格遵循 AGENTS.md 规范：
- 字段类型全标注，支持 Pydantic v2 与 from_attributes 特性；
- 缩写白名单仅限 api, id, url, ocr, llm, db, config, env；
- Google 风格中文 Docstring。
"""

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# 依据：数据库 materials 表 title 字段长度上限 255 字符
MAX_TITLE_LENGTH: int = 255

# 依据：控制字符正则匹配模式（去除 ASCII 0-31 及 127-159 范围的非法控制符）
CONTROL_CHAR_PATTERN: re.Pattern[str] = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def sanitize_material_title(
    filename: str | None,
    default_title: str = "未命名资料",
) -> str:
    """清洗资料展示标题纯函数。

    去除首尾空白字符、过滤非法二进制控制字符，截断超长字符串至 255 字符。
    若清洗后为空或入参为 None，返回默认标题。

    Args:
        filename: 待清洗的原始文件名或用户输入标题。
        default_title: 当输入为空或清洗后无效时的保底默认标题。

    Returns:
        str: 规整脱敏后的合规资料标题。
    """
    if not filename:
        return default_title

    # 过滤控制字符并剔除首尾空白
    cleaned = CONTROL_CHAR_PATTERN.sub("", filename).strip()
    if not cleaned:
        return default_title

    # 截断超长字符
    return cleaned[:MAX_TITLE_LENGTH]


class MaterialUploadResponse(BaseModel):
    """资料上传创建成功响应模型 (201 Created)。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="资料主表唯一标识 UUIDv4")
    version_id: uuid.UUID = Field(..., description="初始化版本主键 UUIDv4")
    title: str = Field(..., max_length=MAX_TITLE_LENGTH, description="资料展示标题")
    file_format: str = Field(..., description="文件格式扩展名 (如 pdf, docx, png)")
    file_size: int = Field(..., ge=0, description="文件总字节数")
    source_type: str = Field(..., description="导入渠道来源 (local/wechat)")
    status: str = Field(..., description="资料生命周期主状态 (pending/parsing/ready/failed)")
    created_at: datetime = Field(..., description="创建时间")


class MaterialDetailResponse(BaseModel):
    """资料详情查询响应模型 (200 OK)。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="资料主表唯一标识 UUIDv4")
    title: str = Field(..., max_length=MAX_TITLE_LENGTH, description="资料展示标题")
    file_format: str = Field(..., description="文件格式扩展名")
    file_size: int = Field(..., ge=0, description="文件总字节数")
    source_type: str = Field(..., description="导入渠道来源 (local/wechat)")
    status: str = Field(..., description="资料生命周期主状态")
    current_version_id: uuid.UUID | None = Field(
        default=None, description="当前激活版本标识 UUIDv4"
    )
    parse_status: str | None = Field(default=None, description="细粒度解析流水线状态")
    progress_percentage: int | None = Field(
        default=None, ge=0, le=100, description="解析进度百分比 (0-100)"
    )
    versions_count: int = Field(default=0, ge=0, description="关联历史版本总数")
    key_points_count: int | None = Field(default=None, ge=0, description="当前激活版本考点总数")
    page_count: int | None = Field(default=None, ge=0, description="当前激活版本 OCR 总页数")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="最后更新时间")


class MaterialListItem(BaseModel):
    """资料列表条目轻量 DTO。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="资料主表唯一标识 UUIDv4")
    title: str = Field(..., max_length=MAX_TITLE_LENGTH, description="资料展示标题")
    file_format: str = Field(..., description="文件格式扩展名")
    file_size: int = Field(..., ge=0, description="文件总字节数")
    source_type: str = Field(..., description="导入渠道来源 (local/wechat)")
    status: str = Field(..., description="资料生命周期主状态")
    current_version_id: uuid.UUID | None = Field(
        default=None, description="当前激活版本标识 UUIDv4"
    )
    parse_status: str | None = Field(default=None, description="细粒度解析流水线状态")
    progress_percentage: int | None = Field(
        default=None, ge=0, le=100, description="解析进度百分比 (0-100)"
    )
    key_points_count: int | None = Field(default=None, ge=0, description="当前激活版本考点总数")
    page_count: int | None = Field(default=None, ge=0, description="当前激活版本 OCR 总页数")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="最后更新时间")


class MaterialListResponse(BaseModel):
    """资料分页检索列表响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    items: list[MaterialListItem] = Field(..., description="当前页资料记录列表")
    total: int = Field(..., ge=0, description="满足检索条件的总记录数")
    limit: int = Field(..., ge=1, le=100, description="单页容量限制")
    offset: int = Field(..., ge=0, description="分页游标偏移量")


class MaterialParseRequest(BaseModel):
    """资料解析流水线调度触发入参模型。"""

    version_id: uuid.UUID | None = Field(default=None, description="指定待解析版本，默认最新")
    sync: bool = Field(default=False, description="是否以同步阻塞模式执行解析")


class MaterialParseResponse(BaseModel):
    """资料解析流水线调度结果响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    material_id: uuid.UUID = Field(..., description="资料标识 UUIDv4")
    version_id: uuid.UUID = Field(..., description="版本标识 UUIDv4")
    parse_status: str = Field(..., description="细粒度解析状态")
    is_active: bool = Field(..., description="是否已激活")
    message: str = Field(..., description="调度或执行结果说明")


class MaterialVersionItem(BaseModel):
    """资料历史版本简要条目 DTO。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="版本主键 UUIDv4")
    material_id: uuid.UUID = Field(..., description="关联资料主键 UUIDv4")
    version_number: int = Field(..., ge=1, description="递增版本号")
    parse_status: str = Field(..., description="解析状态")
    content_hash: str = Field(..., description="原文件 SHA-256 摘要")
    is_active: bool = Field(..., description="是否为当前激活版本")
    created_at: datetime = Field(..., description="版本创建时间")


class MaterialVersionListResponse(BaseModel):
    """资料版本列表响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    material_id: uuid.UUID = Field(..., description="资料标识 UUIDv4")
    versions: list[MaterialVersionItem] = Field(..., description="历史版本按序号倒序列表")


class MaterialReshootResponse(BaseModel):
    """资料单页重拍质检响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    material_id: uuid.UUID = Field(..., description="资料标识 UUIDv4")
    version_id: uuid.UUID = Field(..., description="版本标识 UUIDv4")
    page_index: int = Field(..., ge=1, description="重拍页码序号 (从 1 开始)")
    is_qualified: bool = Field(..., description="页面重检是否达标合格")
    reshoot_count: int = Field(..., ge=0, le=3, description="累计重拍尝试次数 (<=3)")
    parse_status: str = Field(..., description="更新后细粒度解析状态")
    unqualified_reason: str | None = Field(default=None, description="不合格原因说明")


class MaterialOCRPageItem(BaseModel):
    """单页 OCR 质检结果条目 DTO。"""

    model_config = ConfigDict(from_attributes=True)

    page_number: int = Field(..., ge=1, description="页码序号 (从 1 开始)")
    is_qualified: bool = Field(..., description="页面是否达到质检准出标准")
    reshoot_count: int = Field(..., ge=0, le=3, description="累计重拍次数 (<=3)")
    unqualified_reason: str | None = Field(default=None, description="不合格原因说明")


class MaterialOCRPagesResponse(BaseModel):
    """资料页级 OCR 质检列表响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    material_id: uuid.UUID = Field(..., description="资料标识 UUIDv4")
    version_id: uuid.UUID | None = Field(default=None, description="版本标识 UUIDv4")
    items: list[MaterialOCRPageItem] = Field(..., description="页级质检记录列表")


class MaterialDeleteResponse(BaseModel):
    """资料删除结果响应模型 (软删除与硬删除复用)。"""

    model_config = ConfigDict(from_attributes=True)

    material_id: uuid.UUID = Field(..., description="已删除资料标识 UUIDv4")
    is_deleted: bool = Field(..., description="是否已删除标记")
    permanent: bool = Field(..., description="是否为物理级联硬删除")
    message: str = Field(..., description="操作结果说明")
