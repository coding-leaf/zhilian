"""Unit tests for AuthService in app/services/auth.py."""

import uuid
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import AuthenticationError
from app.models.base import Base
from app.repositories.user import UserRepository
from app.services.auth import AuthService


@pytest.fixture
def session() -> Generator[Session, None, None]:
    """Provides an isolated in-memory SQLite database session."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as sess:
        yield sess
    engine.dispose()


class TestAuthService:
    """Test suite for AuthService business orchestration."""

    def test_login_with_wechat_new_user(self, session: Session) -> None:
        """Verify new WeChat user registration and dual-token issuance."""
        service = AuthService(session)
        user, token_response = service.login_with_wechat(
            code="test_code_1",
            nickname="Newbie",
            avatar_url="https://example.com/avatar.png",
        )

        assert user.id is not None
        assert user.nickname == "Newbie"
        assert user.avatar_url == "https://example.com/avatar.png"
        assert token_response.access_token is not None
        assert token_response.refresh_token is not None
        assert token_response.token_type == "Bearer"  # noqa: S105
        assert token_response.expires_in == 7200

        # Verify DB persisted
        user_repo = UserRepository(session)
        persisted = user_repo.get_user_by_id(user.id)
        assert persisted is not None
        assert persisted.openid == user.openid

    def test_login_with_wechat_existing_user(self, session: Session) -> None:
        """Verify existing WeChat user login and profile update."""
        service = AuthService(session)
        user1, _ = service.login_with_wechat(
            code="test_code_existing",
            nickname="OldName",
            avatar_url="https://example.com/old.png",
        )

        user2, token_response = service.login_with_wechat(
            code="test_code_existing",
            nickname="UpdatedName",
            avatar_url="https://example.com/updated.png",
        )

        assert user1.id == user2.id
        assert user2.nickname == "UpdatedName"
        assert user2.avatar_url == "https://example.com/updated.png"
        assert token_response.access_token is not None

    def test_login_with_wechat_inactive_user_raises(self, session: Session) -> None:
        """Verify inactive user login raises AuthenticationError."""
        service = AuthService(session)
        user, _ = service.login_with_wechat(code="test_code_inactive")

        # Deactivate user
        user.is_active = False
        session.commit()

        with pytest.raises(AuthenticationError) as exc_info:
            service.login_with_wechat(code="test_code_inactive")
        assert exc_info.value.code == 20001
        assert "停用" in exc_info.value.message

    def test_login_with_wechat_deleted_user_raises(self, session: Session) -> None:
        """Verify soft-deleted user login raises AuthenticationError."""
        service = AuthService(session)
        user, _ = service.login_with_wechat(code="test_code_deleted")

        # Soft delete user
        user.is_deleted = True
        session.commit()

        with pytest.raises(AuthenticationError) as exc_info:
            service.login_with_wechat(code="test_code_deleted")
        assert exc_info.value.code == 20001
        assert "注销" in exc_info.value.message

    def test_refresh_tokens_success(self, session: Session) -> None:
        """Verify valid refresh token issues new token pair."""
        service = AuthService(session)
        _user, initial_tokens = service.login_with_wechat(code="test_refresh_ok")

        new_tokens = service.refresh_tokens(initial_tokens.refresh_token)
        assert new_tokens.access_token is not None
        assert new_tokens.refresh_token is not None
        assert new_tokens.token_type == "Bearer"  # noqa: S105

    def test_refresh_tokens_wrong_type_raises(self, session: Session) -> None:
        """Verify using access token in refresh endpoint raises AuthenticationError."""
        service = AuthService(session)
        _, initial_tokens = service.login_with_wechat(code="test_refresh_wrong_type")

        with pytest.raises(AuthenticationError) as exc_info:
            service.refresh_tokens(initial_tokens.access_token)
        assert exc_info.value.code == 20001

    def test_refresh_tokens_stale_version_raises(self, session: Session) -> None:
        """Verify stale token version raises AuthenticationError."""
        service = AuthService(session)
        user, initial_tokens = service.login_with_wechat(code="test_refresh_stale")

        # Revoke tokens to increment version
        service.revoke_tokens(user.id)

        with pytest.raises(AuthenticationError) as exc_info:
            service.refresh_tokens(initial_tokens.refresh_token)
        assert exc_info.value.code == 20001
        assert "吊销" in exc_info.value.message or "版本" in exc_info.value.message

    def test_refresh_tokens_inactive_or_deleted_raises(self, session: Session) -> None:
        """Verify inactive or deleted user cannot refresh tokens."""
        service = AuthService(session)
        user, tokens = service.login_with_wechat(code="test_refresh_inactive")

        # Inactive
        user.is_active = False
        session.commit()
        with pytest.raises(AuthenticationError) as exc_info:
            service.refresh_tokens(tokens.refresh_token)
        assert exc_info.value.code == 20001

        # Deleted
        user.is_active = True
        user.is_deleted = True
        session.commit()
        with pytest.raises(AuthenticationError) as exc_info:
            service.refresh_tokens(tokens.refresh_token)
        assert exc_info.value.code == 20001

    def test_revoke_tokens(self, session: Session) -> None:
        """Verify revoking tokens increments token_version."""
        service = AuthService(session)
        user, _ = service.login_with_wechat(code="test_revoke")
        initial_version = user.token_version

        success = service.revoke_tokens(user.id)
        assert success is True

        user_repo = UserRepository(session)
        reloaded = user_repo.get_user_by_id(user.id)
        assert reloaded is not None
        assert reloaded.token_version == initial_version + 1

    def test_get_user_profile_success(self, session: Session) -> None:
        """Verify fetching user profile."""
        service = AuthService(session)
        user, _ = service.login_with_wechat(
            code="test_profile",
            nickname="ProfileUser",
            avatar_url="https://example.com/p.jpg",
        )

        profile = service.get_user_profile(user.id)
        assert profile.id == user.id
        assert profile.nickname == "ProfileUser"
        assert profile.avatar_url == "https://example.com/p.jpg"

    def test_get_user_profile_not_found_or_deleted(self, session: Session) -> None:
        """Verify get_user_profile raises for non-existent or deleted user."""
        service = AuthService(session)
        with pytest.raises(AuthenticationError):
            service.get_user_profile(uuid.uuid4())

        user, _ = service.login_with_wechat(code="test_profile_del")
        service.delete_account(user.id)
        with pytest.raises(AuthenticationError):
            service.get_user_profile(user.id)

    def test_delete_account(self, session: Session) -> None:
        """Verify account deletion marks user deleted and invalidates tokens."""
        service = AuthService(session)
        user, tokens = service.login_with_wechat(code="test_delete_acc")

        success = service.delete_account(user.id)
        assert success is True

        user_repo = UserRepository(session)
        deleted = user_repo.get_user_by_id(user.id)
        assert deleted is not None
        assert deleted.is_deleted is True
        assert deleted.is_active is False

        # Attempt to refresh should fail
        with pytest.raises(AuthenticationError):
            service.refresh_tokens(tokens.refresh_token)
