"""学习资料、版本与知识切片持久化模型定义。

包含学习资料主表、历史版本与快照表、向量化知识切片表 (pgvector HNSW)
以及页级 OCR 质量门禁与就地重拍记录表。
"""

import enum
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, TypeEngine

from app.models.base import Base, TenantModelMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User  # noqa: F401


class MaterialStatus(enum.StrEnum):
    """资料主表生命周期状态枚举。"""

    PENDING = "pending"  # 等待解析/新建就绪
    PARSING = "parsing"  # 流水线解析中
    READY = "ready"  # 解析质检全部通过，可正常用于出题
    FAILED = "failed"  # 解析或质检失败


class ParseStatus(enum.StrEnum):
    """版本表细粒度解析流水线状态枚举。"""

    QUEUED = "queued"
    PARSING_DOC = "parsing_doc"
    OCR_PROCESSING = "ocr_processing"
    EXTRACTING_KNOWLEDGE = "extracting_knowledge"
    AUDITING_KNOWLEDGE = "auditing_knowledge"
    EMBEDDING_GENERATION = "embedding_generation"
    READY = "ready"
    FAILED = "failed"


class SourceType(enum.StrEnum):
    """资料导入渠道枚举。"""

    WECHAT = "wechat"  # 微信聊天会话/文档转发导入
    LOCAL = "local"  # 本地设备直接上传


class MaterialDocType(enum.StrEnum):
    """资料文档格式枚举。"""

    PDF = "pdf"
    DOCX = "docx"
    PPTX = "pptx"
    MARKDOWN = "md"
    TXT = "txt"
    IMAGE = "image"


def get_vector_type(dimensions: int = 1024) -> TypeEngine[Any]:
    """获取兼容多数据库方言的向量字段类型。

    在生产 PostgreSQL 环境下使用 pgvector.sqlalchemy.Vector(dimensions)；
    在 SQLite 单元测试环境下自动适配为 JSON，保证无原生 pgvector 环境下的 DDL 执行与普通字段断言。
    """
    try:
        from pgvector.sqlalchemy import Vector

        return Vector(dimensions).with_variant(JSON, "sqlite")
    except ImportError:
        return JSON()


class Material(Base, TimestampMixin, TenantModelMixin):
    """学习资料主实体模型。

    代表用户上传的一份独立学习资料，管理其全局生命周期与当前激活版本。
    """

    __tablename__ = "materials"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="资料主键 UUIDv4",
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="资料标题 (展示文件名)",
    )
    file_format: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="资料格式扩展名 (如 pdf, docx, pptx, md, txt, png, jpg)",
    )
    file_size: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="原文件大小 (字节数)",
    )
    source_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=SourceType.LOCAL.value,
        comment="导入来源渠道 (wechat/local)",
    )
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "material_versions.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_materials_current_version_id",
        ),
        nullable=True,
        default=None,
        comment="当前激活的版本标识 UUIDv4",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=MaterialStatus.PENDING.value,
        index=True,
        comment="资料生命周期主状态 (MaterialStatus)",
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        index=True,
        comment="软删除标记 (True表示回收站状态)",
    )

    # 关系映射
    versions: Mapped[list["MaterialVersion"]] = relationship(
        "MaterialVersion",
        back_populates="material",
        foreign_keys="MaterialVersion.material_id",
        cascade="all, delete-orphan",
        order_by="MaterialVersion.version_number.desc()",
    )
    current_version: Mapped["MaterialVersion | None"] = relationship(
        "MaterialVersion",
        foreign_keys=[current_version_id],
        post_update=True,
    )

    __table_args__ = (
        Index("ix_materials_user_is_deleted", "user_id", "is_deleted"),
        Index("ix_materials_user_status", "user_id", "status"),
    )

    def __repr__(self) -> str:
        """安全脱敏日志展示，严禁泄漏敏感凭证或全文。"""
        return (
            f"<Material id={self.id} user_id={self.user_id} "
            f"title={self.title[:20]} status={self.status}>"
        )


class MaterialVersion(Base, TimestampMixin, TenantModelMixin):
    """学习资料历史版本与解析快照实体。

    承载每次上传/重新导入的不可变历史记录及 MinIO 路径映射。
    """

    __tablename__ = "material_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="版本主键 UUIDv4",
    )
    material_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("materials.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联资料主表标识",
    )
    version_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="递增版本号 (1, 2, 3...)",
    )
    storage_key: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        comment="MinIO 原始文件存储键 (防重命名脱敏散列路径)",
    )
    content_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="原文件 SHA-256 摘要 (用于查重与秒传判定)",
    )
    parse_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ParseStatus.QUEUED.value,
        comment="细粒度解析状态 (ParseStatus)",
    )
    failed_stage: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        default=None,
        comment="解析失败发生的阶段名称",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
        comment="面向客户端展示的脱敏错误原因",
    )
    raw_text_storage_key: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
        default=None,
        comment="MinIO 提取全量纯文本对象存储键 (规避大对象 TOAST 逃逸)",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="是否为当前激活版本",
    )

    # 关系映射
    material: Mapped["Material"] = relationship(
        "Material",
        back_populates="versions",
        foreign_keys=[material_id],
    )
    snippets: Mapped[list["MaterialSnippet"]] = relationship(
        "MaterialSnippet",
        back_populates="version",
        foreign_keys="MaterialSnippet.version_id",
        cascade="all, delete-orphan",
        order_by="MaterialSnippet.snippet_index.asc()",
    )
    ocr_pages: Mapped[list["MaterialOCRPage"]] = relationship(
        "MaterialOCRPage",
        back_populates="version",
        foreign_keys="MaterialOCRPage.version_id",
        cascade="all, delete-orphan",
        order_by="MaterialOCRPage.page_number.asc()",
    )

    __table_args__ = (
        UniqueConstraint(
            "material_id", "version_number", name="uq_material_versions_material_version"
        ),
        Index("ix_material_versions_user_material", "user_id", "material_id"),
        Index("ix_material_versions_user_content_hash", "user_id", "content_hash"),
    )

    def __repr__(self) -> str:
        return (
            f"<MaterialVersion id={self.id} material_id={self.material_id} "
            f"v={self.version_number} status={self.parse_status}>"
        )


class MaterialSnippet(Base, TimestampMixin, TenantModelMixin):
    """资料知识切片实体 (向量检索核心底座)。

    存储经 ZL-107 分块纯函数切分后的文本片段与 pgvector 1024 维嵌入向量。
    """

    __tablename__ = "material_snippets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="切片主键 UUIDv4",
    )
    material_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("materials.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="归属资料主键",
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("material_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="归属版本标识",
    )
    snippet_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="版本内连续片段序号 (0, 1, 2...)",
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="切片纯文本内容 (硬性约束 <=800 字符)",
    )
    char_length: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="片段字符总数",
    )
    start_offset: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="原文档全文起始字符偏移量",
    )
    end_offset: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="原文档全文终止字符偏移量",
    )
    chapter_title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="",
        comment="所属章节或标题上下文",
    )
    source_info: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
        comment="来源结构化元数据 (如 doc_type, page_number, paragraph_index)",
    )
    embedding: Mapped[Any] = mapped_column(
        get_vector_type(1024),
        nullable=True,
        comment="1024 维定长语义向量 (bge-large-zh-v1.5 / text-embedding-v3)",
    )

    # 关系映射
    version: Mapped["MaterialVersion"] = relationship(
        "MaterialVersion",
        back_populates="snippets",
        foreign_keys=[version_id],
    )
    material: Mapped["Material"] = relationship(
        "Material",
        foreign_keys=[material_id],
    )

    __table_args__ = (
        UniqueConstraint("version_id", "snippet_index", name="uq_material_snippets_version_index"),
        # 三元组隔离索引: 确保多租户与版本防交叉污染查询走覆盖索引
        Index(
            "ix_material_snippets_user_mat_ver",
            "user_id",
            "material_id",
            "version_id",
        ),
        # HNSW 向量余弦索引定义 (仅在 PostgreSQL 生产环境中激活)
        Index(
            "ix_material_snippets_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 200},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    def __repr__(self) -> str:
        """安全脱敏日志展示，严禁打印 content 全文。"""
        return (
            f"<MaterialSnippet id={self.id} ver_id={self.version_id} "
            f"idx={self.snippet_index} len={self.char_length}>"
        )


class MaterialOCRPage(Base, TimestampMixin, TenantModelMixin):
    """页级 OCR 质量门禁与就地重拍记录实体。

    承载逐页乱码率校验、字数质检、标黄展示与就地重拍 (<=3 次)。
    """

    __tablename__ = "material_ocr_pages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="页级记录主键 UUIDv4",
    )
    material_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("materials.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="归属资料主键",
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("material_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="归属版本标识",
    )
    page_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="页码序号 (从 1 开始)",
    )
    image_storage_key: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        comment="MinIO 页面渲染切图存储键 (用于前端不合格高亮标黄展示)",
    )
    raw_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        comment="页面识别所得原始文本",
    )
    gibberish_ratio: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        comment="乱码率 (0.00 ~ 1.00，门禁阈值 <= 0.15)",
    )
    valid_char_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="有效识别字数统计 (门禁阈值 >= 40)",
    )
    is_qualified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
        comment="页面是否达到质检准出标准",
    )
    unqualified_reason: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        default=None,
        comment="不合格质检原因 (如: 乱码率过高[18.5%] 或 有效字数不足[22字])",
    )
    reshoot_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="已就地重拍次数计数 (上限 3 次)",
    )

    # 关系映射
    version: Mapped["MaterialVersion"] = relationship(
        "MaterialVersion",
        back_populates="ocr_pages",
        foreign_keys=[version_id],
    )

    __table_args__ = (
        UniqueConstraint("version_id", "page_number", name="uq_material_ocr_pages_version_page"),
        Index(
            "ix_material_ocr_pages_user_mat_ver",
            "user_id",
            "material_id",
            "version_id",
        ),
        Index("ix_material_ocr_pages_version_qualified", "version_id", "is_qualified"),
    )

    def __repr__(self) -> str:
        return (
            f"<MaterialOCRPage id={self.id} ver_id={self.version_id} "
            f"page={self.page_number} qualified={self.is_qualified}>"
        )
