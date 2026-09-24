"""Unit tests for UserRepository in app/repositories/user.py."""

import uuid
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.base import Base
from app.repositories.user import UserRepository


@pytest.fixture
def session() -> Generator[Session, None, None]:
    """Provides an isolated in-memory SQLite database session."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as sess:
        yield sess
    engine.dispose()


class TestUserRepository:
    """Test suite for UserRepository operations."""

    def test_create_user_minimal(self, session: Session) -> None:
        """Verify creating a user with minimal required parameters."""
        repo = UserRepository(session)
        user = repo.create_user(openid="wx_test_minimal")
        session.commit()

        assert user.id is not None
        assert user.openid == "wx_test_minimal"
        assert user.unionid is None
        assert user.nickname == ""
        assert user.avatar_url == ""
        assert user.token_version == 1
        assert user.is_active is True
        assert user.is_deleted is False

    def test_create_user_full(self, session: Session) -> None:
        """Verify creating a user with all profile attributes."""
        repo = UserRepository(session)
        user = repo.create_user(
            openid="wx_test_full",
            unionid="union_123",
            nickname="ZhiLianUser",
            avatar_url="https://example.com/avatar.jpg",
        )
        session.commit()

        assert user.id is not None
        assert user.openid == "wx_test_full"
        assert user.unionid == "union_123"
        assert user.nickname == "ZhiLianUser"
        assert user.avatar_url == "https://example.com/avatar.jpg"
        assert user.token_version == 1
        assert user.is_active is True
        assert user.is_deleted is False

    def test_get_user_by_id(self, session: Session) -> None:
        """Verify retrieval by user UUID."""
        repo = UserRepository(session)
        created = repo.create_user(openid="wx_get_by_id")
        session.commit()

        found = repo.get_user_by_id(created.id)
        assert found is not None
        assert found.id == created.id
        assert found.openid == "wx_get_by_id"

        non_existent = repo.get_user_by_id(uuid.uuid4())
        assert non_existent is None

    def test_get_user_by_openid(self, session: Session) -> None:
        """Verify retrieval by OpenID."""
        repo = UserRepository(session)
        repo.create_user(openid="wx_unique_openid")
        session.commit()

        found = repo.get_user_by_openid("wx_unique_openid")
        assert found is not None
        assert found.openid == "wx_unique_openid"

        not_found = repo.get_user_by_openid("wx_non_existent")
        assert not_found is None

    def test_update_profile(self, session: Session) -> None:
        """Verify updating nickname and avatar_url."""
        repo = UserRepository(session)
        user = repo.create_user(
            openid="wx_update_profile",
            nickname="OldNick",
            avatar_url="https://example.com/old.png",
        )
        session.commit()

        # Update both
        updated = repo.update_profile(
            user.id,
            nickname="NewNick",
            avatar_url="https://example.com/new.png",
        )
        session.commit()
        assert updated is not None
        assert updated.nickname == "NewNick"
        assert updated.avatar_url == "https://example.com/new.png"

        # Partial update
        updated_again = repo.update_profile(user.id, nickname="BrandNewNick")
        session.commit()
        assert updated_again is not None
        assert updated_again.nickname == "BrandNewNick"
        assert updated_again.avatar_url == "https://example.com/new.png"

        # Update non-existent user returns None
        non_existent = repo.update_profile(uuid.uuid4(), nickname="Ghost")
        assert non_existent is None

    def test_increment_token_version(self, session: Session) -> None:
        """Verify atomic increment of token_version."""
        repo = UserRepository(session)
        user = repo.create_user(openid="wx_version_inc")
        session.commit()
        assert user.token_version == 1

        v2 = repo.increment_token_version(user.id)
        session.commit()
        assert v2 == 2

        refreshed = repo.get_user_by_id(user.id)
        assert refreshed is not None
        assert refreshed.token_version == 2

        v3 = repo.increment_token_version(user.id)
        session.commit()
        assert v3 == 3

        # Increment for non-existent user returns 0
        v_ghost = repo.increment_token_version(uuid.uuid4())
        assert v_ghost == 0

    def test_soft_delete_user(self, session: Session) -> None:
        """Verify soft deletion sets is_deleted=True and is_active=False."""
        repo = UserRepository(session)
        user = repo.create_user(openid="wx_soft_delete")
        session.commit()

        success = repo.soft_delete_user(user.id)
        session.commit()
        assert success is True

        deleted_user = repo.get_user_by_id(user.id)
        assert deleted_user is not None
        assert deleted_user.is_deleted is True
        assert deleted_user.is_active is False

        # Soft delete non-existent user returns False
        assert repo.soft_delete_user(uuid.uuid4()) is False
