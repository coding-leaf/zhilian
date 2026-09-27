"""Unit and negative matrix tests for authentication dependencies.

Fully covers the 10-dimensional negative authorization attack matrix (AUTH-NEG-01 to AUTH-NEG-10)
and tenant isolation security guarantees required by AGENTS.md and spec.md.
"""

import uuid
from collections.abc import Generator
from contextlib import contextmanager
from datetime import timedelta
from typing import Annotated, Any
from unittest.mock import MagicMock

import jwt
import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from app.api.deps.auth import (
    get_auth_service,
    get_current_token_payload,
    get_current_user,
    get_current_user_id,
    validate_user_status,
)
from app.core.errors import AppError, AuthenticationError, PermissionDeniedError
from app.core.security import (
    ALGORITHM,
    create_access_token,
    create_refresh_token,
    get_secret_key,
)
from app.models.user import User

# In-memory mock user database for tests
MOCK_USERS: dict[uuid.UUID, User] = {}


def create_test_application() -> FastAPI:
    """Create a FastAPI test application with error handlers and test routes."""
    app = FastAPI(title="Auth Dependency Test App")

    @app.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.error_code,
                "message": exc.message,
                "details": exc.details,
                "data": None,
            },
        )

    @app.get("/api/v1/test/user-id")
    async def route_user_id(
        current_user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    ) -> dict[str, str]:
        return {"user_id": str(current_user_id)}

    @app.get("/api/v1/test/user-entity")
    async def route_user_entity(
        payload: Annotated[dict[str, Any], Depends(get_current_token_payload)],
    ) -> dict[str, Any]:
        user_uuid = uuid.UUID(payload["sub"])
        user = MOCK_USERS.get(user_uuid)
        valid_user = validate_user_status(user, payload["token_version"])
        return {
            "user_id": str(valid_user.id),
            "nickname": valid_user.nickname,
            "token_version": valid_user.token_version,
        }

    @app.post("/api/v1/test/tenant-resource")
    async def route_tenant_resource(
        request_body: dict[str, Any],
        current_user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    ) -> dict[str, Any]:
        # Enforce tenant isolation: if caller maliciously attempts to forge user_id in payload,
        # the system either overrides it with current_user_id or rejects with PermissionDeniedError
        target_user_id = request_body.get("target_user_id")
        if target_user_id and target_user_id != str(current_user_id):
            raise PermissionDeniedError("越权访问被拦截: 无法操作非本用户的数据资源")

        return {
            "bound_user_id": str(current_user_id),
            "resource_name": request_body.get("resource_name"),
        }

    return app


@pytest.fixture
def test_app() -> FastAPI:
    """Fixture providing a fresh test FastAPI app."""
    return create_test_application()


@pytest.fixture
def client(test_app: FastAPI) -> AsyncClient:
    """Fixture providing an HTTPX AsyncClient for FastAPI test app."""
    transport = ASGITransport(app=test_app)
    return AsyncClient(transport=transport, base_url="http://testserver")


class TestAuthNegativeMatrix:
    """10-Dimensional Negative Auth Test Matrix (AUTH-NEG-01 ~ AUTH-NEG-10)."""

    @pytest.mark.asyncio
    async def test_auth_neg_01_missing_authorization_header(self, client: AsyncClient) -> None:
        """AUTH-NEG-01: Verify missing Authorization header is intercepted with HTTP 401."""
        response = await client.get("/api/v1/test/user-id")
        assert response.status_code == 401
        data = response.json()
        assert data["code"] == 20001
        assert "缺失认证凭据" in data["message"]

    @pytest.mark.asyncio
    async def test_auth_neg_02_non_bearer_scheme(self, client: AsyncClient) -> None:
        """AUTH-NEG-02: Verify non-Bearer scheme (e.g. Basic auth) is intercepted with HTTP 401."""
        headers = {"Authorization": "Basic dXNlcjpwYXNzd29yZA=="}
        response = await client.get("/api/v1/test/user-id", headers=headers)
        assert response.status_code == 401
        data = response.json()
        assert data["code"] == 20001
        assert "必须采用 Bearer 协议" in data["message"]

    @pytest.mark.asyncio
    async def test_auth_neg_03_tampered_token_signature(self, client: AsyncClient) -> None:
        """AUTH-NEG-03: Verify token signed with an invalid/forged secret key is intercepted."""
        forged_key = "forged-secret-key-that-does-not-match-system-key-32b"
        token = create_access_token(
            user_id=uuid.uuid4(),
            token_version=1,
            secret_key=forged_key,
        )
        headers = {"Authorization": f"Bearer {token}"}
        response = await client.get("/api/v1/test/user-id", headers=headers)
        assert response.status_code == 401
        data = response.json()
        assert data["code"] == 20001
        assert "无效" in data["message"] or "损坏" in data["message"]

    @pytest.mark.asyncio
    async def test_auth_neg_04_malformed_truncated_token(self, client: AsyncClient) -> None:
        """AUTH-NEG-04: Verify malformed or truncated token string is intercepted."""
        headers = {"Authorization": "Bearer eyJhbGciOiJIUzI1NiI...invalid_truncated_signature"}
        response = await client.get("/api/v1/test/user-id", headers=headers)
        assert response.status_code == 401
        data = response.json()
        assert data["code"] == 20001

    @pytest.mark.asyncio
    async def test_auth_neg_05_expired_access_token(self, client: AsyncClient) -> None:
        """AUTH-NEG-05: Verify expired token (past 2h) is intercepted."""
        user_id = uuid.uuid4()
        token = create_access_token(
            user_id=user_id,
            token_version=1,
            expires_delta=timedelta(seconds=-1),
        )
        headers = {"Authorization": f"Bearer {token}"}
        response = await client.get("/api/v1/test/user-id", headers=headers)
        assert response.status_code == 401
        data = response.json()
        assert data["code"] == 20001
        assert "过期" in data["message"]

    @pytest.mark.asyncio
    async def test_auth_neg_06_confused_token_type(self, client: AsyncClient) -> None:
        """AUTH-NEG-06: Verify refresh token used on business route is rejected."""
        user_id = uuid.uuid4()
        refresh_token = create_refresh_token(user_id=user_id, token_version=1)
        headers = {"Authorization": f"Bearer {refresh_token}"}
        response = await client.get("/api/v1/test/user-id", headers=headers)
        assert response.status_code == 401
        data = response.json()
        assert data["code"] == 20001
        assert "期望 access 令牌" in data["message"]

    @pytest.mark.asyncio
    async def test_auth_neg_07_missing_sub_or_version_or_invalid_uuid(
        self, client: AsyncClient
    ) -> None:
        """AUTH-NEG-07: Verify payload missing required fields or non-UUID sub is rejected."""
        # 7a: sub is not a valid UUID
        key = get_secret_key()
        invalid_uuid_payload = {
            "sub": "not-a-valid-uuid-value",
            "type": "access",
            "token_version": 1,
            "exp": 2500000000,
            "iat": 1000000000,
            "jti": str(uuid.uuid4()),
        }
        token_invalid_uuid = jwt.encode(invalid_uuid_payload, key, algorithm=ALGORITHM)
        headers = {"Authorization": f"Bearer {token_invalid_uuid}"}
        response = await client.get("/api/v1/test/user-id", headers=headers)
        assert response.status_code == 401
        assert "用户标识格式错误" in response.json()["message"]

        # 7b: token_version missing
        no_version_payload = {
            "sub": str(uuid.uuid4()),
            "type": "access",
            "exp": 2500000000,
            "iat": 1000000000,
            "jti": str(uuid.uuid4()),
        }
        token_no_version = jwt.encode(no_version_payload, key, algorithm=ALGORITHM)
        headers = {"Authorization": f"Bearer {token_no_version}"}
        response = await client.get("/api/v1/test/user-id", headers=headers)
        assert response.status_code == 401
        assert "缺失令牌版本号" in response.json()["message"]

    @pytest.mark.asyncio
    async def test_auth_neg_08_revoked_token_version(self, client: AsyncClient) -> None:
        """AUTH-NEG-08: Verify token with stale token_version is instantly revoked."""
        user_id = uuid.uuid4()
        user = User(
            id=user_id,
            openid="wx_openid_revoked_test",
            nickname="TestUser",
            token_version=2,  # Database token_version is 2
            is_active=True,
            is_deleted=False,
        )
        MOCK_USERS[user_id] = user

        # Token issued with older version 1 (e.g. before user logged out)
        stale_token = create_access_token(user_id=user_id, token_version=1)
        headers = {"Authorization": f"Bearer {stale_token}"}
        response = await client.get("/api/v1/test/user-entity", headers=headers)
        assert response.status_code == 401
        data = response.json()
        assert data["code"] == 20001
        assert "吊销" in data["message"] or "版本已过期" in data["message"]

    @pytest.mark.asyncio
    async def test_auth_neg_09_inactive_or_deleted_account(self, client: AsyncClient) -> None:
        """AUTH-NEG-09: Verify disabled (is_active=False) or deleted account is intercepted."""
        # 9a: Inactive account
        user_inactive_id = uuid.uuid4()
        user_inactive = User(
            id=user_inactive_id,
            openid="wx_openid_inactive",
            token_version=1,
            is_active=False,
            is_deleted=False,
        )
        MOCK_USERS[user_inactive_id] = user_inactive

        token_inactive = create_access_token(user_id=user_inactive_id, token_version=1)
        headers = {"Authorization": f"Bearer {token_inactive}"}
        res_inactive = await client.get("/api/v1/test/user-entity", headers=headers)
        assert res_inactive.status_code == 401
        assert "停用" in res_inactive.json()["message"]

        # 9b: Deleted account
        user_deleted_id = uuid.uuid4()
        user_deleted = User(
            id=user_deleted_id,
            openid="wx_openid_deleted",
            token_version=1,
            is_active=True,
            is_deleted=True,
        )
        MOCK_USERS[user_deleted_id] = user_deleted

        token_deleted = create_access_token(user_id=user_deleted_id, token_version=1)
        headers = {"Authorization": f"Bearer {token_deleted}"}
        res_deleted = await client.get("/api/v1/test/user-entity", headers=headers)
        assert res_deleted.status_code == 401
        assert "注销" in res_deleted.json()["message"]

    @pytest.mark.asyncio
    async def test_auth_neg_10_horizontal_privilege_escalation_attempt(
        self, client: AsyncClient
    ) -> None:
        """AUTH-NEG-10: Verify horizontal privilege escalation attempt is strictly blocked."""
        user_a_id = uuid.uuid4()
        user_b_id = uuid.uuid4()

        # User A authenticates legally
        token_a = create_access_token(user_id=user_a_id, token_version=1)
        headers = {"Authorization": f"Bearer {token_a}"}

        # User A tries to operate on User B's resource by passing user_b_id in body
        malicious_body = {
            "target_user_id": str(user_b_id),
            "resource_name": "Sensitive Notes of User B",
        }
        response = await client.post(
            "/api/v1/test/tenant-resource",
            json=malicious_body,
            headers=headers,
        )
        # Should be intercepted with 403 Forbidden
        assert response.status_code == 403
        data = response.json()
        assert data["code"] == 20002
        assert "越权" in data["message"]


class TestAuthPositiveFlow:
    """Test suite for positive authorization and dependency injection flows."""

    @pytest.mark.asyncio
    async def test_valid_access_token_success(self, client: AsyncClient) -> None:
        """Verify valid access token successfully returns current user ID."""
        user_id = uuid.uuid4()
        token = create_access_token(user_id=user_id, token_version=1)
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.get("/api/v1/test/user-id", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == str(user_id)

    @pytest.mark.asyncio
    async def test_valid_user_entity_success(self, client: AsyncClient) -> None:
        """Verify active user with matching version passes user entity validation."""
        user_id = uuid.uuid4()
        user = User(
            id=user_id,
            openid="wx_openid_active_ok",
            nickname="ActiveLearner",
            token_version=3,
            is_active=True,
            is_deleted=False,
        )
        MOCK_USERS[user_id] = user

        token = create_access_token(user_id=user_id, token_version=3)
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.get("/api/v1/test/user-entity", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == str(user_id)
        assert data["nickname"] == "ActiveLearner"
        assert data["token_version"] == 3

    @pytest.mark.asyncio
    async def test_legitimate_tenant_resource_operation(self, client: AsyncClient) -> None:
        """Verify normal tenant operation bound to current user passes."""
        user_id = uuid.uuid4()
        token = create_access_token(user_id=user_id, token_version=1)
        headers = {"Authorization": f"Bearer {token}"}

        legit_body = {
            "target_user_id": str(user_id),
            "resource_name": "My Own Notes",
        }
        response = await client.post(
            "/api/v1/test/tenant-resource",
            json=legit_body,
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["bound_user_id"] == str(user_id)
        assert data["resource_name"] == "My Own Notes"

    def test_validate_user_status_not_found(self) -> None:
        """Verify validate_user_status raises AuthenticationError if user is None."""
        with pytest.raises(AuthenticationError) as exc_info:
            validate_user_status(None, 1)
        assert exc_info.value.status_code == 401
        assert "不存在" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_empty_bearer_credentials(self, client: AsyncClient) -> None:
        """Verify Authorization header with empty Bearer payload is intercepted."""
        headers = {"Authorization": "Bearer "}
        response = await client.get("/api/v1/test/user-id", headers=headers)
        assert response.status_code == 401
        data = response.json()
        assert data["code"] == 20001
        assert "凭据为空" in data["message"]

    @pytest.mark.asyncio
    async def test_get_current_user_id_missing_sub(self) -> None:
        """Verify get_current_user_id raises AuthenticationError when sub is missing."""
        with pytest.raises(AuthenticationError) as exc_info:
            await get_current_user_id(payload={"token_version": 1})
        assert exc_info.value.status_code == 401
        assert "缺少用户标识" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_get_current_token_payload_credentials_none(self) -> None:
        """Verify get_current_token_payload with credentials=None raises AuthenticationError."""

        # Create a mock request with valid Bearer header but credentials parameter None
        class DummyRequest:
            def __init__(self) -> None:
                self.headers = {"Authorization": "Bearer some-token"}

        with pytest.raises(AuthenticationError) as exc_info:
            await get_current_token_payload(request=DummyRequest(), credentials=None)  # type: ignore[arg-type]
        assert exc_info.value.status_code == 401
        assert "凭据为空" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_get_current_user_unimplemented_dependency(self) -> None:
        """Verify calling default get_current_user raises NotImplementedError."""
        payload = {"sub": str(uuid.uuid4()), "token_version": 1}
        with pytest.raises(NotImplementedError) as exc_info:
            await get_current_user(payload)
        assert "用户服务数据加载器尚未装配" in str(exc_info.value)


class _FakeAuthService:
    """Minimal AuthService facade returning a canned user entity."""

    def __init__(self, user: User | None) -> None:
        self._user = user

    def get_user_by_id(self, user_id: uuid.UUID) -> User | None:
        return self._user


class _FakeContainer:
    """Minimal AppContainer stand-in tracking managed session teardown."""

    def __init__(self, user: User | None) -> None:
        self._user = user
        self.closed = False

    @contextmanager
    def get_session(self) -> Generator[object, None, None]:
        try:
            yield object()
        finally:
            self.closed = True

    def create_auth_service(self, session: object) -> _FakeAuthService:
        return _FakeAuthService(self._user)

    def create_user_service(self, session: object) -> _FakeAuthService:
        return _FakeAuthService(self._user)


class TestAuthDependencySessionRecycling:
    """BUG-AUTH-011: fallback database sessions must be managed and closed."""

    @pytest.mark.asyncio
    async def test_get_current_user_fallback_closes_managed_session(self) -> None:
        """Verify get_current_user fallback uses get_session() and closes it on return."""
        user_id = uuid.uuid4()
        user = User(
            id=user_id,
            openid="wx_fallback_recycle",
            nickname="FallbackUser",
            token_version=1,
            is_active=True,
            is_deleted=False,
        )
        fake_container = _FakeContainer(user=user)
        fake_request = MagicMock(spec=Request)
        fake_request.app.state.container = fake_container

        payload = {"sub": str(user_id), "token_version": 1}
        result = await get_current_user(payload, request=fake_request, auth_service=None)

        assert result is user
        assert fake_container.closed is True

    def test_get_auth_service_fallback_closes_session_on_teardown(self) -> None:
        """Verify get_auth_service fallback session is closed when the dependency tears down."""
        fake_container = _FakeContainer(user=None)
        fake_request = MagicMock(spec=Request)
        fake_request.app.state.container = fake_container

        service_gen = get_auth_service(fake_request)
        service = next(service_gen)

        assert service is not None
        assert fake_container.closed is False

        service_gen.close()
        assert fake_container.closed is True
