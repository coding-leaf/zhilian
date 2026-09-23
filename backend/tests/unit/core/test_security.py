"""Unit tests for the core security module.

Tests JWT token generation, validation, instant invalidation, and irreversible user masking.
Enforces line coverage >= 95% on backend/app/core/security.py.
"""

import uuid
from datetime import timedelta

import jwt
import pytest

from app.core.errors import AuthenticationError
from app.core.security import (
    ALGORITHM,
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_user_ref,
    get_secret_key,
    verify_token_version,
)


class TestSecurityTokenLifecycle:
    """Test suite for JWT token creation, signature verification, and lifecycle states."""

    def test_create_and_decode_access_token_success(self) -> None:
        """Verify normal access token creation and decoding."""
        user_id = uuid.uuid4()
        token_version = 1

        token = create_access_token(user_id=user_id, token_version=token_version)
        assert isinstance(token, str)

        payload = decode_token(token, expected_type="access")
        assert payload["sub"] == str(user_id)
        assert payload["type"] == "access"
        assert payload["token_version"] == token_version
        assert "jti" in payload
        assert "exp" in payload
        assert "iat" in payload

    def test_create_and_decode_refresh_token_success(self) -> None:
        """Verify normal refresh token creation and decoding."""
        user_id = uuid.uuid4()
        token_version = 3

        token = create_refresh_token(user_id=user_id, token_version=token_version)
        assert isinstance(token, str)

        payload = decode_token(token, expected_type="refresh")
        assert payload["sub"] == str(user_id)
        assert payload["type"] == "refresh"
        assert payload["token_version"] == token_version

    def test_custom_expiration_delta(self) -> None:
        """Verify token expiration delta is correctly applied."""
        user_id = uuid.uuid4()
        delta = timedelta(minutes=5)
        token = create_access_token(user_id=user_id, token_version=1, expires_delta=delta)
        payload = decode_token(token)
        # exp - iat should be approximately 300 seconds
        assert payload["exp"] - payload["iat"] == 300

    def test_custom_refresh_expiration_delta(self) -> None:
        """Verify refresh token custom expiration delta is applied."""
        user_id = uuid.uuid4()
        delta = timedelta(days=7)
        token = create_refresh_token(user_id=user_id, token_version=1, expires_delta=delta)
        payload = decode_token(token, expected_type="refresh")
        assert payload["exp"] - payload["iat"] == 7 * 86400

    def test_decode_token_expired_raises_authentication_error(self) -> None:
        """Verify expired token raises AuthenticationError with 401 status."""
        user_id = uuid.uuid4()
        negative_delta = timedelta(seconds=-10)
        token = create_access_token(
            user_id=user_id,
            token_version=1,
            expires_delta=negative_delta,
        )

        with pytest.raises(AuthenticationError) as exc_info:
            decode_token(token)
        assert exc_info.value.status_code == 401
        assert exc_info.value.error_code == 20001
        assert "过期" in exc_info.value.message

    def test_decode_token_tampered_signature_raises_authentication_error(self) -> None:
        """Verify signature mismatch raises AuthenticationError."""
        user_id = uuid.uuid4()
        key_valid = "valid-secret-key-32-chars-for-hmac-sha256"
        key_forged = "forged-secret-key-32-chars-for-hmac-sha256"
        token = create_access_token(user_id=user_id, token_version=1, secret_key=key_valid)

        with pytest.raises(AuthenticationError) as exc_info:
            decode_token(token, secret_key=key_forged)
        assert exc_info.value.status_code == 401
        assert exc_info.value.error_code == 20001

    def test_decode_token_malformed_string_raises_authentication_error(self) -> None:
        """Verify malformed token raises AuthenticationError."""
        with pytest.raises(AuthenticationError) as exc_info:
            decode_token("not.a.valid.jwt.string")
        assert exc_info.value.status_code == 401
        assert exc_info.value.error_code == 20001

    def test_decode_token_mismatched_type_raises_authentication_error(self) -> None:
        """Verify token type mismatch (e.g. passing refresh token as access) is rejected."""
        user_id = uuid.uuid4()
        refresh_token = create_refresh_token(user_id=user_id, token_version=1)

        with pytest.raises(AuthenticationError) as exc_info:
            decode_token(refresh_token, expected_type="access")
        assert exc_info.value.status_code == 401
        assert exc_info.value.error_code == 20001
        assert "期望 access 令牌" in exc_info.value.message

    def test_decode_token_missing_sub_raises_authentication_error(self) -> None:
        """Verify token missing sub claim is rejected."""
        key = get_secret_key()
        incomplete_payload = {
            "type": "access",
            "token_version": 1,
            "exp": 2000000000,
            "iat": 1000000000,
        }
        token = jwt.encode(incomplete_payload, key, algorithm=ALGORITHM)

        with pytest.raises(AuthenticationError) as exc_info:
            decode_token(token)
        assert exc_info.value.status_code == 401
        assert exc_info.value.error_code == 20001

    def test_decode_token_empty_sub_raises_authentication_error(self) -> None:
        """Verify token with empty sub claim is rejected."""
        key = get_secret_key()
        incomplete_payload = {
            "sub": "",
            "type": "access",
            "token_version": 1,
            "exp": 2000000000,
            "iat": 1000000000,
        }
        token = jwt.encode(incomplete_payload, key, algorithm=ALGORITHM)

        with pytest.raises(AuthenticationError) as exc_info:
            decode_token(token)
        assert exc_info.value.status_code == 401
        assert exc_info.value.error_code == 20001
        assert "sub" in exc_info.value.message

    def test_decode_token_missing_token_version_raises_authentication_error(self) -> None:
        """Verify token missing token_version claim is rejected."""
        key = get_secret_key()
        incomplete_payload = {
            "sub": str(uuid.uuid4()),
            "type": "access",
            "exp": 2000000000,
            "iat": 1000000000,
        }
        token = jwt.encode(incomplete_payload, key, algorithm=ALGORITHM)

        with pytest.raises(AuthenticationError) as exc_info:
            decode_token(token)
        assert exc_info.value.status_code == 401
        assert exc_info.value.error_code == 20001
        assert "token_version" in exc_info.value.message


class TestTokenVersionAndUserRef:
    """Test suite for token version comparison and user reference hashing."""

    def test_verify_token_version(self) -> None:
        """Verify version comparison matches identity."""
        assert verify_token_version(1, 1) is True
        assert verify_token_version(2, 2) is True
        assert verify_token_version(1, 2) is False
        assert verify_token_version(3, 1) is False

    def test_generate_user_ref_with_uuid(self) -> None:
        """Verify user_ref generation with UUID input returns exact 8 hex chars."""
        uid = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
        ref1 = generate_user_ref(uid)
        ref2 = generate_user_ref(str(uid))

        assert len(ref1) == 8
        assert ref1 == ref2
        # Hexadecimal character set check
        assert all(c in "0123456789abcdef" for c in ref1)

    def test_generate_user_ref_different_ids(self) -> None:
        """Verify different user IDs generate distinct masked references."""
        uid_a = uuid.uuid4()
        uid_b = uuid.uuid4()
        assert generate_user_ref(uid_a) != generate_user_ref(uid_b)

    def test_get_secret_key_environment_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify SECRET_KEY environment variable overrides default key."""
        custom_key = "my-custom-production-key-999-32-chars-long"
        monkeypatch.setenv("SECRET_KEY", custom_key)
        assert get_secret_key() == custom_key
