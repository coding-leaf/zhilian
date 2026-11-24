"""自定义题单与题单收纳条目数据模型定义模块。

提供用户自定义题单 (QuestionCollection) 及多对多收纳明细 (QuestionCollectionItem)，
严格继承 Base、TimestampMixin 与 TenantModelMixin，SQLite 与 PostgreSQL 完全兼容。
"""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    false,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantModelMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.question import Question


class QuestionCollection(Base, TimestampMixin, TenantModelMixin):
    """用户自定义题单实体。

    允许学生按专题（如「期中必刷」「高频易错」）自由收纳题目，
    支持可选绑定课程文件夹 (``folder_id = NULL`` 表示跨课程通用题单)。
    """

    __tablename__ = "question_collections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="题单主键 UUIDv4",
    )
    name: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        comment="题单名称",
    )
    description: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="",
        server_default="",
        comment="题单简介说明",
    )
    folder_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("material_folders.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
        comment="可选关联课程文件夹主键 (NULL=跨课程通用题单)",
    )
    color_token: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        default=None,
        comment="语义化色盘标签 token",
    )
    is_pinned: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
        comment="是否置顶展示",
    )
    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="题单排序权重",
    )

    items: Mapped[list["QuestionCollectionItem"]] = relationship(
        "QuestionCollectionItem",
        back_populates="collection",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_question_collections_user_name"),
        Index("ix_question_collections_user_folder", "user_id", "folder_id"),
        Index(
            "ix_question_collections_user_pinned_updated",
            "user_id",
            "is_pinned",
            "updated_at",
        ),
    )

    def __repr__(self) -> str:
        """安全脱敏日志展示。"""
        return (
            f"<QuestionCollection id={self.id} user_id={self.user_id} "
            f"name={self.name[:20]} pinned={self.is_pinned}>"
        )


class QuestionCollectionItem(Base, TimestampMixin, TenantModelMixin):
    """题单与题目的多对多收纳关联实体。

    删除题单或移出条目仅删除本关联行，绝不级联删除原题目。
    """

    __tablename__ = "question_collection_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="收纳关联主键 UUIDv4",
    )
    collection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("question_collections.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属题单主键",
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
        comment="收纳的题目主键",
    )
    note: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        default=None,
        comment="学生对该题目的个人收纳备注/口诀",
    )
    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="题单内排序权重",
    )

    collection: Mapped["QuestionCollection"] = relationship(
        "QuestionCollection",
        back_populates="items",
    )
    question: Mapped["Question"] = relationship("Question")

    __table_args__ = (
        UniqueConstraint(
            "collection_id",
            "question_id",
            name="uq_collection_items_collection_question",
        ),
        Index("ix_collection_items_user_collection", "user_id", "collection_id"),
        Index("ix_collection_items_user_question", "user_id", "question_id"),
    )

    def __repr__(self) -> str:
        """安全脱敏日志展示。"""
        return (
            f"<QuestionCollectionItem id={self.id} collection_id={self.collection_id} "
            f"question_id={self.question_id}>"
        )


__all__ = ["QuestionCollection", "QuestionCollectionItem"]
