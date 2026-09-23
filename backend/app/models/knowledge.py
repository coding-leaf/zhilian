"""知识点树形拓扑与切片关联持久化模型定义。

包含大模型抽取生成的知识点树 (自引用 1:N 拓扑) 以及知识点与切片的双向追溯关联表。
"""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantModelMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.material import Material, MaterialSnippet, MaterialVersion  # noqa: F401
    from app.models.question import Question


class KnowledgePoint(Base, TimestampMixin, TenantModelMixin):
    """知识点树形拓扑实体模型。

    承载大模型从知识片段中全自动抽取建树的知识点，支持 2~5 级层级结构。
    """

    __tablename__ = "knowledge_points"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="知识点主键 UUIDv4",
    )
    material_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("materials.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="归属学习资料主键",
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("material_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="归属资料版本标识",
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_points.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        default=None,
        comment="父知识点主键 (自引用外键，根节点为空)",
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="知识点名称 (质检约束 2~30 字符)",
    )
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        comment="知识点简述/抽取摘要",
    )
    level: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="知识点层级深度 (根节点为1，最大深度5)",
    )
    batch_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="抽取批次号",
    )
    is_low_confidence: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="低可信度标记 (重抽2次超限后降级标记，对应 FR-19/FR-53)",
    )

    # 关系映射
    parent: Mapped["KnowledgePoint | None"] = relationship(
        "KnowledgePoint",
        remote_side="KnowledgePoint.id",
        back_populates="children",
    )
    children: Mapped[list["KnowledgePoint"]] = relationship(
        "KnowledgePoint",
        back_populates="parent",
        cascade="all, delete-orphan",
    )
    snippet_mappings: Mapped[list["KnowledgePointSnippet"]] = relationship(
        "KnowledgePointSnippet",
        back_populates="knowledge_point",
        cascade="all, delete-orphan",
    )
    questions: Mapped[list["Question"]] = relationship(
        "Question",
        back_populates="knowledge_point",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        # 三元组隔离联合索引
        Index("ix_knowledge_points_user_mat_ver", "user_id", "material_id", "version_id"),
        # 父子拓扑检索索引
        Index("ix_knowledge_points_user_parent", "user_id", "parent_id"),
    )

    def __repr__(self) -> str:
        """安全脱敏表示，严禁泄漏敏感长文本。"""
        return (
            f"<KnowledgePoint id={self.id} user_id={self.user_id} "
            f"name={self.name[:20]} level={self.level} low_conf={self.is_low_confidence}>"
        )


class KnowledgePointSnippet(Base, TimestampMixin, TenantModelMixin):
    """知识点与切片双向溯源关联实体模型。

    落实需求 FR-15：从知识点可查到来源片段，从片段可查到知识点。
    """

    __tablename__ = "knowledge_point_snippets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="关联主键 UUIDv4",
    )
    knowledge_point_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_points.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联知识点标识",
    )
    snippet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("material_snippets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联来源切片标识",
    )

    # 关系映射
    knowledge_point: Mapped["KnowledgePoint"] = relationship(
        "KnowledgePoint",
        back_populates="snippet_mappings",
    )
    snippet: Mapped["MaterialSnippet"] = relationship(
        "MaterialSnippet",
    )

    __table_args__ = (
        UniqueConstraint(
            "knowledge_point_id",
            "snippet_id",
            name="uq_knowledge_point_snippets_kp_snippet",
        ),
        Index("ix_kp_snippets_user_snippet", "user_id", "snippet_id"),
        Index("ix_kp_snippets_user_kp", "user_id", "knowledge_point_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<KnowledgePointSnippet id={self.id} kp_id={self.knowledge_point_id} "
            f"snippet_id={self.snippet_id}>"
        )
