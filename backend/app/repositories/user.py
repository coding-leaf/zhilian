"""用户实体领域数据仓储模块。

封装针对 users 数据表的数据库持久化原子操作。
严格遵循 AGENTS.md 规范：
- 仓储层严禁导入 fastapi 与 app.integrations；
- 涉及个人数据的方法必须以 user_id / openid 为基准条件，确保租户隔离；
- 缩写白名单仅限 8 个 (api, id, url, ocr, llm, db, config, env)。
"""

import uuid

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.models.user import User


class UserRepository:
    """用户领域数据仓储。"""

    def __init__(self, session: Session) -> None:
        """初始化用户数据仓储。

        Args:
            session: SQLAlchemy 数据库会话。
        """
        self.session = session

    def create_user(
        self,
        *,
        openid: str,
        unionid: str | None = None,
        nickname: str = "",
        avatar_url: str = "",
    ) -> User:
        """创建新用户实体并提交变更至持久化上下文。

        Args:
            openid: 微信小程序用户唯一标识。
            unionid: 微信开放平台跨应用唯一标识 (可选)。
            nickname: 用户昵称，默认空字符串。
            avatar_url: 用户头像 URL 地址，默认空字符串。

        Returns:
            User: 刚创建并刷入数据库的用户实体实例。
        """
        user = User(
            openid=openid,
            unionid=unionid,
            nickname=nickname,
            avatar_url=avatar_url,
            token_version=1,
            is_active=True,
            is_deleted=False,
        )
        self.session.add(user)
        self.session.flush()
        return user

    def get_user_by_id(self, user_id: uuid.UUID) -> User | None:
        """根据用户主键 UUID 检索用户实体。

        Args:
            user_id: 用户唯一标识 UUID。

        Returns:
            User | None: 若存在返回用户实体，不存在返回 None。
        """
        stmt = select(User).where(User.id == user_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def get_user_by_openid(self, openid: str) -> User | None:
        """根据微信 OpenID 检索用户实体。

        Args:
            openid: 微信小程序用户标识。

        Returns:
            User | None: 若存在返回用户实体，不存在返回 None。
        """
        stmt = select(User).where(User.openid == openid)
        return self.session.execute(stmt).scalar_one_or_none()

    def update_profile(
        self,
        user_id: uuid.UUID,
        *,
        nickname: str | None = None,
        avatar_url: str | None = None,
    ) -> User | None:
        """更新指定用户的基础画像资料 (昵称、头像)。

        Args:
            user_id: 用户唯一标识 UUID。
            nickname: 更新后的新昵称，传入 None 表示不修改。
            avatar_url: 更新后的新头像 URL，传入 None 表示不修改。

        Returns:
            User | None: 更新成功返回用户实体，若用户不存在返回 None。
        """
        user = self.get_user_by_id(user_id)
        if user is None:
            return None

        if nickname is not None:
            user.nickname = nickname
        if avatar_url is not None:
            user.avatar_url = avatar_url

        self.session.flush()
        return user

    def increment_token_version(self, user_id: uuid.UUID) -> int:
        """原子递增用户的 token_version，用于全端历史凭据即时失效。

        Args:
            user_id: 用户唯一标识 UUID。

        Returns:
            int: 递增后的最新版本号；若用户不存在返回 0。
        """
        stmt = (
            update(User)
            .where(User.id == user_id)
            .values(token_version=User.token_version + 1)
            .returning(User.token_version)
        )
        result = self.session.execute(stmt).scalar_one_or_none()
        self.session.flush()
        return result if result is not None else 0

    def soft_delete_user(self, user_id: uuid.UUID) -> bool:
        """将用户标记为软删除 (is_deleted=True, is_active=False)。

        Args:
            user_id: 用户唯一标识 UUID。

        Returns:
            bool: 若用户存在且更新成功返回 True，若不存在返回 False。
        """
        stmt = update(User).where(User.id == user_id).values(is_deleted=True, is_active=False)
        result = self.session.execute(stmt)
        self.session.flush()
        count = result.rowcount if isinstance(result, CursorResult) else 0
        return bool(count > 0)


__all__ = ["UserRepository"]
