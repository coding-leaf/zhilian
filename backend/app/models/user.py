"""用户空间核心实体模型定义。

存储微信用户标识、昵称头像、令牌版本控制及状态标记。
"""

import uuid

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    """用户空间核心实体模型。

    存储微信登录身份、小程序 OpenID、状态标记及防重放令牌版本。
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="用户主键 UUIDv4",
    )
    openid: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True,
        nullable=False,
        comment="微信小程序 OpenID (唯一索引)",
    )
    unionid: Mapped[str | None] = mapped_column(
        String(64),
        unique=False,
        index=True,
        nullable=True,
        default=None,
        comment="微信开放平台 UnionID (普通稀疏索引)",
    )
    nickname: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="",
        comment="用户微信昵称",
    )
    avatar_url: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        default="",
        comment="用户头像 URL",
    )
    avatar_object_key: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
        default=None,
        comment="应用托管头像对象键",
    )
    token_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="令牌版本号，累加递增用于全端历史凭据即时失效",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="账号是否激活启用",
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="账号软删除标记",
    )
