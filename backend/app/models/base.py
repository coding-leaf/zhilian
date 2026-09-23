"""持久化实体模型基类与声明式混入类定义。

定义 SQLAlchemy 2.0 声明式基类 Base、审计时间戳混入 TimestampMixin
以及声明式多租户数据隔离混入类 TenantModelMixin。
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """智练持久化实体模型统一基类。"""

    pass


class TimestampMixin:
    """标准时间戳审计混入类。

    为实体提供带时区感知的创建时间与自动更新时间戳。
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(UTC),
        nullable=False,
        comment="实体创建时间戳 (UTC)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        default=lambda: datetime.now(UTC),
        nullable=False,
        comment="实体最后修改时间戳 (UTC)",
    )


class TenantModelMixin:
    """声明式多租户数据隔离混入类。

    所有归属于用户的专属业务表强制继承此类。
    注入非空的 user_id 外键并建立索引，级联删除设置为 CASCADE。
    """

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="归属用户标识 (租户隔离基石)",
    )
