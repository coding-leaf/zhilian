"""Unit tests for authentication and user schemas."""

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas.auth import (
    RefreshTokenRequest,
    RevokeTokenResponse,
    TokenResponse,
    WechatLoginRequest,
)
from app.schemas.user import UserActionResponse, UserProfileResponse


class DummyORMUser:
    """Mock ORM model object for testing schema attribute conversion."""

    def __init__(
        self,
        user_id: uuid.UUID,
        nickname: str,
        avatar_url: str,
        created_at: datetime,
    ) -> None:
        self.id = user_id
        self.nickname = nickname
        self.avatar_url = avatar_url
        self.created_at = created_at


class TestAuthSchemas:
    """Test suite for authentication Pydantic DTO contracts."""

    def test_wechat_login_request_valid(self) -> None:
        """Verify valid WechatLoginRequest parsing."""
        req = WechatLoginRequest(
            code="test_code_123",
            nickname="TestUser",
            avatar_url="https://example.com/avatar.png",
        )
        assert req.code == "test_code_123"
        assert req.nickname == "TestUser"
        assert req.avatar_url == "https://example.com/avatar.png"

    def test_wechat_login_request_minimal(self) -> None:
        """Verify minimal WechatLoginRequest parsing with defaults."""
        req = WechatLoginRequest(code="test_code_minimal")
        assert req.code == "test_code_minimal"
        assert req.nickname is None
        assert req.avatar_url is None

    def test_wechat_login_request_empty_code_fails(self) -> None:
        """Verify empty code raises validation error."""
        with pytest.raises(ValidationError):
            WechatLoginRequest(code="")

    def test_wechat_login_request_forbid_extra(self) -> None:
        """Verify extra fields are rejected."""
        with pytest.raises(ValidationError):
            WechatLoginRequest(code="code_123", unknown_field="invalid")  # type: ignore[call-arg]

    def test_refresh_token_request_valid(self) -> None:
        """Verify valid RefreshTokenRequest parsing."""
        req = RefreshTokenRequest(refresh_token="valid_long_refresh_token_string")  # noqa: S106
        assert req.refresh_token == "valid_long_refresh_token_string"  # noqa: S105

    def test_refresh_token_request_too_short_fails(self) -> None:
        """Verify short refresh token raises validation error."""
        with pytest.raises(ValidationError):
            RefreshTokenRequest(refresh_token="short_token")  # noqa: S106

    def test_refresh_token_request_forbid_extra(self) -> None:
        """Verify extra fields in RefreshTokenRequest are rejected."""
        with pytest.raises(ValidationError):
            RefreshTokenRequest(
                refresh_token="valid_long_refresh_token_string",  # noqa: S106
                extra_payload=123,  # type: ignore[call-arg]
            )

    def test_token_response_defaults(self) -> None:
        """Verify TokenResponse fields and default values."""
        res = TokenResponse(
            access_token="test_access_token",  # noqa: S106
            refresh_token="test_refresh_token",  # noqa: S106
        )
        assert res.access_token == "test_access_token"  # noqa: S105
        assert res.refresh_token == "test_refresh_token"  # noqa: S105
        assert res.token_type == "Bearer"  # noqa: S105
        assert res.expires_in == 7200

    def test_revoke_token_response_defaults(self) -> None:
        """Verify RevokeTokenResponse defaults."""
        res = RevokeTokenResponse()
        assert res.success is True
        assert res.message == "已成功注销所有登录凭据"


class TestUserSchemas:
    """Test suite for user management Pydantic DTO contracts."""

    def test_user_profile_response_from_attributes(self) -> None:
        """Verify UserProfileResponse builds from ORM-like object."""
        user_id = uuid.uuid4()
        now = datetime.now(UTC)
        orm_user = DummyORMUser(
            user_id=user_id,
            nickname="ZhiLianLearner",
            avatar_url="https://example.com/avatar.jpg",
            created_at=now,
        )
        profile = UserProfileResponse.model_validate(orm_user)
        assert profile.id == user_id
        assert profile.nickname == "ZhiLianLearner"
        assert profile.avatar_url == "https://example.com/avatar.jpg"
        assert profile.created_at == now

    def test_user_action_response(self) -> None:
        """Verify UserActionResponse field population."""
        res = UserActionResponse(success=True, message="操作成功")
        assert res.success is True
        assert res.message == "操作成功"
