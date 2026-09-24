"""Unit tests for authentication router endpoints in app/api/v1/auth.py.

Verifies:
1. POST /api/v1/auth/login (new user auto-registration, existing user profile update, 422, 401).
2. POST /api/v1/auth/refresh (token refresh, expired/invalid token, type mismatch, version expired).
3. POST /api/v1/auth/revoke (authenticated revocation, unauthenticated 401 rejection).
4. Dependency injection isolation and exception mapping compliance.
"""

import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import APIRouter, FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.api.deps.auth import get_auth_service, get_current_user
from app.api.v1.auth import router as auth_router
from app.core.errors import AppError, AuthenticationError
from app.models.user import User
from app.schemas.auth import TokenResponse
from app.services.auth import AuthService


def create_test_app() -> FastAPI:
    """创建挂载了 auth 路由与 AppError 异常处理器的测试 FastAPI 应用。"""
    app = FastAPI(title="Auth Router Test App")

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

    api_router = APIRouter(prefix="/api/v1")
    api_router.include_router(auth_router)
    app.include_router(api_router)
    return app


@pytest.fixture
def mock_user() -> User:
    """提供当前已认证的用户实体对象。"""
    return User(
        id=uuid.uuid4(),
        nickname="test_auth_user",
        avatar_url="https://example.com/avatar.jpg",
        is_active=True,
        is_deleted=False,
        token_version=1,
    )


@pytest.fixture
def mock_auth_service() -> MagicMock:
    """提供打桩的 AuthService 实例。"""
    return MagicMock(spec=AuthService)


@pytest.fixture
def client(mock_auth_service: MagicMock, mock_user: User) -> TestClient:
    """提供已注入打桩依赖的 TestClient 实例。"""
    app = create_test_app()
    app.dependency_overrides[get_auth_service] = lambda: mock_auth_service
    app.dependency_overrides[get_current_user] = lambda: mock_user
    return TestClient(app)


# ==============================================================================
# 1. POST /api/v1/auth/login 测试用例
# ==============================================================================


def test_login_new_user_success(
    client: TestClient,
    mock_auth_service: MagicMock,
    mock_user: User,
) -> None:
    """测试新用户通过微信临时凭证登录注册成功返回 200 与双令牌对。"""
    mock_tokens = TokenResponse(
        access_token="mock_new_access_token_12345",  # noqa: S106
        refresh_token="mock_new_refresh_token_12345",  # noqa: S106
        token_type="Bearer",  # noqa: S106
        expires_in=7200,
    )
    mock_auth_service.login_with_wechat.return_value = (mock_user, mock_tokens)

    request_body = {
        "code": "wx_code_fresh_user",
        "nickname": "WechatStudent",
        "avatar_url": "https://thirdwx.qlogo.cn/avatar.jpg",
    }
    response = client.post("/api/v1/auth/login", json=request_body)

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["access_token"] == "mock_new_access_token_12345"  # noqa: S105
    assert data["refresh_token"] == "mock_new_refresh_token_12345"  # noqa: S105
    assert data["token_type"] == "Bearer"  # noqa: S105
    assert data["expires_in"] == 7200
    mock_auth_service.login_with_wechat.assert_called_once_with(
        code="wx_code_fresh_user",
        nickname="WechatStudent",
        avatar_url="https://thirdwx.qlogo.cn/avatar.jpg",
    )


def test_login_existing_user_update_profile(
    client: TestClient,
    mock_auth_service: MagicMock,
    mock_user: User,
) -> None:
    """测试老用户通过微信登录重新同步头像与昵称成功返回 200 与双令牌对。"""
    mock_tokens = TokenResponse(
        access_token="mock_updated_access_token",  # noqa: S106
        refresh_token="mock_updated_refresh_token",  # noqa: S106
        token_type="Bearer",  # noqa: S106
        expires_in=7200,
    )
    mock_auth_service.login_with_wechat.return_value = (mock_user, mock_tokens)

    request_body = {
        "code": "wx_code_existing_user",
        "nickname": "UpdatedNickname",
        "avatar_url": "https://thirdwx.qlogo.cn/new_avatar.jpg",
    }
    response = client.post("/api/v1/auth/login", json=request_body)

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["access_token"] == "mock_updated_access_token"  # noqa: S105
    assert data["refresh_token"] == "mock_updated_refresh_token"  # noqa: S105
    mock_auth_service.login_with_wechat.assert_called_once_with(
        code="wx_code_existing_user",
        nickname="UpdatedNickname",
        avatar_url="https://thirdwx.qlogo.cn/new_avatar.jpg",
    )


def test_login_missing_code_422(client: TestClient) -> None:
    """测试微信登录缺少 code 字段时触发 Pydantic 参数校验拦截返回 422。"""
    response = client.post(
        "/api/v1/auth/login",
        json={"nickname": "OnlyNickname"},
    )
    assert response.status_code == 422


def test_login_empty_code_422(client: TestClient) -> None:
    """测试微信登录 code 字段为空字符串时触发最小长度限制返回 422。"""
    response = client.post(
        "/api/v1/auth/login",
        json={"code": ""},
    )
    assert response.status_code == 422


def test_login_extra_fields_forbidden_422(client: TestClient) -> None:
    """测试微信登录请求体携带额外未定义字段时被 extra='forbid' 拦截返回 422。"""
    response = client.post(
        "/api/v1/auth/login",
        json={
            "code": "valid_wx_code_123",
            "forbidden_extra_payload": "malicious_injection",
        },
    )
    assert response.status_code == 422


def test_login_user_deleted_401(
    client: TestClient,
    mock_auth_service: MagicMock,
) -> None:
    """测试已注销用户尝试登录被鉴权机制拦截返回 401 及错误码 20001。"""
    mock_auth_service.login_with_wechat.side_effect = AuthenticationError("用户账号已被注销")

    response = client.post(
        "/api/v1/auth/login",
        json={"code": "code_for_deleted_user"},
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    data = response.json()
    assert data["code"] == 20001
    assert "用户账号已被注销" in data["message"]


def test_login_user_inactive_401(
    client: TestClient,
    mock_auth_service: MagicMock,
) -> None:
    """测试已停用用户尝试登录被鉴权机制拦截返回 401 及错误码 20001。"""
    mock_auth_service.login_with_wechat.side_effect = AuthenticationError("用户账号已被停用")

    response = client.post(
        "/api/v1/auth/login",
        json={"code": "code_for_inactive_user"},
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    data = response.json()
    assert data["code"] == 20001
    assert "用户账号已被停用" in data["message"]


# ==============================================================================
# 2. POST /api/v1/auth/refresh 测试用例
# ==============================================================================


def test_refresh_tokens_success(
    client: TestClient,
    mock_auth_service: MagicMock,
) -> None:
    """测试使用合法 Refresh Token 成功置换新双令牌对返回 200。"""
    mock_tokens = TokenResponse(
        access_token="new_rotated_access_token",  # noqa: S106
        refresh_token="new_rotated_refresh_token",  # noqa: S106
        token_type="Bearer",  # noqa: S106
        expires_in=7200,
    )
    mock_auth_service.refresh_tokens.return_value = mock_tokens

    valid_token_string = "header.payload_with_refresh_claims.signature"  # noqa: S105
    response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": valid_token_string},
    )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["access_token"] == "new_rotated_access_token"  # noqa: S105
    assert data["refresh_token"] == "new_rotated_refresh_token"  # noqa: S105
    assert data["token_type"] == "Bearer"  # noqa: S105
    assert data["expires_in"] == 7200
    mock_auth_service.refresh_tokens.assert_called_once_with(refresh_token=valid_token_string)


def test_refresh_tokens_expired_or_invalid_401(
    client: TestClient,
    mock_auth_service: MagicMock,
) -> None:
    """测试过期或签名损坏的 Refresh Token 被拒绝返回 401 及错误码 20001。"""
    mock_auth_service.refresh_tokens.side_effect = AuthenticationError("令牌已过期或签名无效")

    response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "expired_corrupted_refresh_token_payload"},
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    data = response.json()
    assert data["code"] == 20001
    assert "令牌已过期或签名无效" in data["message"]


def test_refresh_tokens_type_mismatch_401(
    client: TestClient,
    mock_auth_service: MagicMock,
) -> None:
    """测试误将 Access Token 提交至刷新端点被类型检查拦截返回 401 及错误码 20001。"""
    mock_auth_service.refresh_tokens.side_effect = AuthenticationError(
        "令牌类型不匹配: 期望 refresh 令牌"
    )

    response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "access_token_passed_as_refresh_token"},
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    data = response.json()
    assert data["code"] == 20001
    assert "令牌类型不匹配" in data["message"]


def test_refresh_tokens_version_expired_401(
    client: TestClient,
    mock_auth_service: MagicMock,
) -> None:
    """测试令牌版本落后于持久化版本时被版本校验拦截返回 401 及错误码 20001。"""
    mock_auth_service.refresh_tokens.side_effect = AuthenticationError(
        "令牌已被即时吊销或版本已过期，请重新登录"
    )

    response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "stale_version_refresh_token_value"},
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    data = response.json()
    assert data["code"] == 20001
    assert "令牌已被即时吊销或版本已过期" in data["message"]


def test_refresh_tokens_invalid_request_422(client: TestClient) -> None:
    """测试刷新请求体缺失或 token 长度小于 16 字节时返回 422。"""
    # 1. 缺失 refresh_token 字段
    response1 = client.post("/api/v1/auth/refresh", json={})
    assert response1.status_code == 422

    # 2. 字段过短 (min_length=16)
    response2 = client.post("/api/v1/auth/refresh", json={"refresh_token": "short"})
    assert response2.status_code == 422


# ==============================================================================
# 3. POST /api/v1/auth/revoke 测试用例
# ==============================================================================


def test_revoke_tokens_authenticated_success(
    client: TestClient,
    mock_auth_service: MagicMock,
    mock_user: User,
) -> None:
    """测试已认证用户请求主动吊销成功返回 200 并正确传递用户 UUID。"""
    mock_auth_service.revoke_tokens.return_value = True

    response = client.post("/api/v1/auth/revoke")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["success"] is True
    assert data["message"] == "已成功注销所有登录凭据"
    mock_auth_service.revoke_tokens.assert_called_once_with(user_id=mock_user.id)


def test_revoke_tokens_unauthenticated_missing_header_401(
    mock_auth_service: MagicMock,
) -> None:
    """测试未携带 Authorization 凭证头访问 revoke 端点被 401 拦截。"""
    app = create_test_app()
    app.dependency_overrides[get_auth_service] = lambda: mock_auth_service
    unauth_client = TestClient(app)

    response = unauth_client.post("/api/v1/auth/revoke")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    data = response.json()
    assert data["code"] == 20001
    assert "请求头缺失认证凭据" in data["message"]


def test_revoke_tokens_unauthenticated_dependency_rejection_401(
    mock_auth_service: MagicMock,
) -> None:
    """测试认证依赖校验失败抛出 AuthenticationError 时统一返回 401 与 20001。"""
    app = create_test_app()
    app.dependency_overrides[get_auth_service] = lambda: mock_auth_service

    def raise_auth_error() -> User:
        raise AuthenticationError("用户凭据失效，请重新登录")

    app.dependency_overrides[get_current_user] = raise_auth_error
    unauth_client = TestClient(app)

    response = unauth_client.post("/api/v1/auth/revoke")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    data = response.json()
    assert data["code"] == 20001
    assert "用户凭据失效" in data["message"]
