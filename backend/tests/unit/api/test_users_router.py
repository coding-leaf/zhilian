"""Unit tests for user profile router endpoints in app/api/v1/users.py.

Verifies:
1. GET /api/v1/users/me (profile query success, unauthenticated 401 rejection, user status error).
2. DELETE /api/v1/users/me (account deletion success, unauthenticated 401 rejection).
3. Tenant isolation and user_id propagation (prevent horizontal privilege escalation).
4. Dependency injection isolation and exception mapping compliance.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi import APIRouter, FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.api.deps.auth import get_current_user
from app.api.deps.user import get_user_service
from app.api.v1.users import router as users_router
from app.core.errors import AppError, AuthenticationError
from app.models.user import User
from app.schemas.user import UserProfileResponse
from app.services.auth import AuthService


def create_test_app() -> FastAPI:
    """创建挂载了 users 路由与 AppError 异常处理器的测试 FastAPI 应用。"""
    app = FastAPI(title="Users Router Test App")

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
    api_router.include_router(users_router)
    app.include_router(api_router)
    return app


@pytest.fixture
def mock_user() -> User:
    """提供当前已认证的用户实体对象。"""
    return User(
        id=uuid.uuid4(),
        nickname="test_learner_me",
        avatar_url="https://example.com/avatar_me.jpg",
        is_active=True,
        is_deleted=False,
        token_version=1,
    )


@pytest.fixture
def mock_user_service() -> MagicMock:
    """提供打桩的 AuthService (作为用户管理编排门面) 实例。"""
    return MagicMock(spec=AuthService)


@pytest.fixture
def client(mock_user_service: MagicMock, mock_user: User) -> TestClient:
    """提供已注入打桩依赖的 TestClient 实例。"""
    app = create_test_app()
    app.dependency_overrides[get_user_service] = lambda: mock_user_service
    app.dependency_overrides[get_current_user] = lambda: mock_user
    return TestClient(app)


# ==============================================================================
# 1. GET /api/v1/users/me 测试用例
# ==============================================================================


def test_get_users_me_success(
    client: TestClient,
    mock_user_service: MagicMock,
    mock_user: User,
) -> None:
    """测试获取当前登录用户画像成功返回 200 并包含完整字段信息。"""
    registered_time = datetime(2026, 9, 24, 10, 0, 0, tzinfo=UTC)
    mock_user_service.get_user_profile.return_value = UserProfileResponse(
        id=mock_user.id,
        nickname=mock_user.nickname,
        avatar_url=mock_user.avatar_url or "",
        created_at=registered_time,
    )

    response = client.get("/api/v1/users/me")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["id"] == str(mock_user.id)
    assert data["nickname"] == mock_user.nickname
    assert data["avatar_url"] == mock_user.avatar_url
    assert data["created_at"] is not None
    assert "2026-09-24" in data["created_at"]
    mock_user_service.get_user_profile.assert_called_once_with(user_id=mock_user.id)


def test_get_users_me_unauthenticated_missing_header_401(
    mock_user_service: MagicMock,
) -> None:
    """测试未携带 Authorization 凭据头访问 GET /users/me 被 401 (20001) 拦截。"""
    app = create_test_app()
    app.dependency_overrides[get_user_service] = lambda: mock_user_service
    unauth_client = TestClient(app)

    response = unauth_client.get("/api/v1/users/me")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    data = response.json()
    assert data["code"] == 20001
    assert "请求头缺失认证凭据" in data["message"]


def test_get_users_me_unauthenticated_invalid_token_401(
    mock_user_service: MagicMock,
) -> None:
    """测试依赖抛出 AuthenticationError 时统一返回 401 与业务错误码 20001。"""
    app = create_test_app()
    app.dependency_overrides[get_user_service] = lambda: mock_user_service

    def raise_auth_error() -> User:
        raise AuthenticationError("用户凭证失效，请重新登录")

    app.dependency_overrides[get_current_user] = raise_auth_error
    unauth_client = TestClient(app)

    response = unauth_client.get("/api/v1/users/me")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    data = response.json()
    assert data["code"] == 20001
    assert "用户凭证失效" in data["message"]


def test_get_users_me_user_deleted_401(
    client: TestClient,
    mock_user_service: MagicMock,
) -> None:
    """测试获取画像时服务层识别用户已注销并抛出 401 (20001)。"""
    mock_user_service.get_user_profile.side_effect = AuthenticationError("用户不存在或已注销")

    response = client.get("/api/v1/users/me")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    data = response.json()
    assert data["code"] == 20001
    assert "用户不存在或已注销" in data["message"]


def test_get_users_me_user_inactive_401(
    client: TestClient,
    mock_user_service: MagicMock,
) -> None:
    """测试获取画像时服务层识别用户已被停用并抛出 401 (20001)。"""
    mock_user_service.get_user_profile.side_effect = AuthenticationError("用户账号已被停用")

    response = client.get("/api/v1/users/me")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    data = response.json()
    assert data["code"] == 20001
    assert "用户账号已被停用" in data["message"]


# ==============================================================================
# 2. DELETE /api/v1/users/me 测试用例
# ==============================================================================


def test_delete_users_me_success(
    client: TestClient,
    mock_user_service: MagicMock,
    mock_user: User,
) -> None:
    """测试已认证用户注销当前账号成功返回 200 与统一提示文案。"""
    mock_user_service.delete_account.return_value = True

    response = client.delete("/api/v1/users/me")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["success"] is True
    assert data["message"] == "账号已成功注销"
    mock_user_service.delete_account.assert_called_once_with(user_id=mock_user.id)


def test_delete_users_me_unauthenticated_missing_header_401(
    mock_user_service: MagicMock,
) -> None:
    """测试未携带 Authorization 凭据头访问 DELETE /users/me 被 401 (20001) 拦截。"""
    app = create_test_app()
    app.dependency_overrides[get_user_service] = lambda: mock_user_service
    unauth_client = TestClient(app)

    response = unauth_client.delete("/api/v1/users/me")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    data = response.json()
    assert data["code"] == 20001
    assert "请求头缺失认证凭据" in data["message"]


def test_delete_users_me_unauthenticated_invalid_token_401(
    mock_user_service: MagicMock,
) -> None:
    """测试注销账号时依赖凭证校验失败统一返回 401 与 20001。"""
    app = create_test_app()
    app.dependency_overrides[get_user_service] = lambda: mock_user_service

    def raise_auth_error() -> User:
        raise AuthenticationError("用户凭据失效，请重新登录")

    app.dependency_overrides[get_current_user] = raise_auth_error
    unauth_client = TestClient(app)

    response = unauth_client.delete("/api/v1/users/me")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    data = response.json()
    assert data["code"] == 20001
    assert "用户凭据失效" in data["message"]


# ==============================================================================
# 3. 租户隔离与越权防御测试用例 (Tenant Isolation & Anti-Tampering)
# ==============================================================================


def test_tenant_isolation_propagation_get_profile(
    mock_user_service: MagicMock,
) -> None:
    """测试 GET /users/me 严格将当前登录用户的 user_id 传给 Service，杜绝越权。"""
    user_alice = User(
        id=uuid.uuid4(),
        nickname="Alice",
        avatar_url="https://example.com/alice.jpg",
        is_active=True,
        is_deleted=False,
        token_version=1,
    )
    user_bob = User(
        id=uuid.uuid4(),
        nickname="Bob",
        avatar_url="https://example.com/bob.jpg",
        is_active=True,
        is_deleted=False,
        token_version=1,
    )

    app = create_test_app()
    app.dependency_overrides[get_user_service] = lambda: mock_user_service

    # 1. 登录用户为 Alice
    app.dependency_overrides[get_current_user] = lambda: user_alice
    mock_user_service.get_user_profile.return_value = UserProfileResponse(
        id=user_alice.id,
        nickname=user_alice.nickname,
        avatar_url=user_alice.avatar_url or "",
        created_at=datetime.now(UTC),
    )
    client_alice = TestClient(app)
    # 模拟攻击者尝试通过 Query 参数篡改目标 user_id
    client_alice.get(f"/api/v1/users/me?user_id={user_bob.id}")
    assert mock_user_service.get_user_profile.call_args.kwargs["user_id"] == user_alice.id

    # 2. 登录用户切换为 Bob
    mock_user_service.reset_mock()
    app.dependency_overrides[get_current_user] = lambda: user_bob
    mock_user_service.get_user_profile.return_value = UserProfileResponse(
        id=user_bob.id,
        nickname=user_bob.nickname,
        avatar_url=user_bob.avatar_url or "",
        created_at=datetime.now(UTC),
    )
    client_bob = TestClient(app)
    client_bob.get("/api/v1/users/me")
    assert mock_user_service.get_user_profile.call_args.kwargs["user_id"] == user_bob.id


def test_tenant_isolation_propagation_delete_account(
    mock_user_service: MagicMock,
) -> None:
    """测试 DELETE /users/me 严格将当前登录用户的 user_id 传给 Service，杜绝越权。"""
    user_alice = User(
        id=uuid.uuid4(),
        nickname="Alice",
        avatar_url="https://example.com/alice.jpg",
        is_active=True,
        is_deleted=False,
        token_version=1,
    )
    user_bob = User(
        id=uuid.uuid4(),
        nickname="Bob",
        avatar_url="https://example.com/bob.jpg",
        is_active=True,
        is_deleted=False,
        token_version=1,
    )

    app = create_test_app()
    app.dependency_overrides[get_user_service] = lambda: mock_user_service
    mock_user_service.delete_account.return_value = True

    # 1. 登录用户为 Alice
    app.dependency_overrides[get_current_user] = lambda: user_alice
    client_alice = TestClient(app)
    client_alice.delete(f"/api/v1/users/me?user_id={user_bob.id}")
    assert mock_user_service.delete_account.call_args.kwargs["user_id"] == user_alice.id

    # 2. 登录用户切换为 Bob
    mock_user_service.reset_mock()
    app.dependency_overrides[get_current_user] = lambda: user_bob
    client_bob = TestClient(app)
    client_bob.delete("/api/v1/users/me")
    assert mock_user_service.delete_account.call_args.kwargs["user_id"] == user_bob.id


# ==============================================================================
# 4. PUT /api/v1/users/me 画像更新测试用例 (BUG-AUTH-004)
# ==============================================================================


def test_put_users_me_update_success(
    client: TestClient,
    mock_user_service: MagicMock,
    mock_user: User,
) -> None:
    """测试已认证用户通过 PUT 更新昵称与头像返回 200 与最新画像。"""
    updated_profile = UserProfileResponse(
        id=mock_user.id,
        nickname="更新后的昵称",
        avatar_url="https://example.com/updated_avatar.jpg",
        created_at=datetime(2026, 9, 24, 10, 0, 0, tzinfo=UTC),
    )
    mock_user_service.update_user_profile.return_value = updated_profile

    response = client.put(
        "/api/v1/users/me",
        json={
            "nickname": "更新后的昵称",
            "avatar_url": "https://example.com/updated_avatar.jpg",
        },
    )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["id"] == str(mock_user.id)
    assert data["nickname"] == "更新后的昵称"
    assert data["avatar_url"] == "https://example.com/updated_avatar.jpg"
    mock_user_service.update_user_profile.assert_called_once_with(
        user_id=mock_user.id,
        nickname="更新后的昵称",
        avatar_url="https://example.com/updated_avatar.jpg",
    )


def test_put_users_me_partial_update_single_field(
    client: TestClient,
    mock_user_service: MagicMock,
    mock_user: User,
) -> None:
    """测试仅提交 nickname 时头像字段保持 None 透传，服务层不覆盖既有头像。"""
    mock_user_service.update_user_profile.return_value = UserProfileResponse(
        id=mock_user.id,
        nickname="仅改昵称",
        avatar_url=mock_user.avatar_url or "",
        created_at=None,
    )

    response = client.put("/api/v1/users/me", json={"nickname": "仅改昵称"})

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["nickname"] == "仅改昵称"
    mock_user_service.update_user_profile.assert_called_once_with(
        user_id=mock_user.id,
        nickname="仅改昵称",
        avatar_url=None,
    )


def test_post_users_me_avatar_uploads_image(
    client: TestClient,
    mock_user_service: MagicMock,
    mock_user: User,
) -> None:
    profile = UserProfileResponse(
        id=mock_user.id,
        nickname=mock_user.nickname,
        avatar_url="https://storage.example/signed-avatar",
        created_at=None,
    )
    mock_user_service.upload_user_avatar.return_value = profile

    response = client.post(
        "/api/v1/users/me/avatar",
        files={"file": ("avatar.png", b"png bytes", "image/png")},
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["avatar_url"] == "https://storage.example/signed-avatar"
    mock_user_service.upload_user_avatar.assert_called_once_with(
        user_id=mock_user.id,
        data=b"png bytes",
    )


def test_put_users_me_extra_fields_forbidden_422(client: TestClient) -> None:
    """测试更新画像请求体携带未定义字段被 extra='forbid' 拦截返回 422。"""
    response = client.put(
        "/api/v1/users/me",
        json={"nickname": "合法昵称", "forbidden_extra_payload": "malicious"},
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_put_users_me_user_not_found_401(
    client: TestClient,
    mock_user_service: MagicMock,
) -> None:
    """测试服务层识别用户不存在时抛出 401 (20001)。"""
    mock_user_service.update_user_profile.side_effect = AuthenticationError("用户不存在或已注销")

    response = client.put("/api/v1/users/me", json={"nickname": "幽灵"})

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    data = response.json()
    assert data["code"] == 20001
    assert "用户不存在或已注销" in data["message"]


def test_put_users_me_unauthenticated_missing_header_401(
    mock_user_service: MagicMock,
) -> None:
    """测试未携带 Authorization 凭据头访问 PUT /users/me 被 401 (20001) 拦截。"""
    app = create_test_app()
    app.dependency_overrides[get_user_service] = lambda: mock_user_service
    unauth_client = TestClient(app)

    response = unauth_client.put("/api/v1/users/me", json={"nickname": "anonymous"})

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    data = response.json()
    assert data["code"] == 20001
    assert "请求头缺失认证凭据" in data["message"]


def test_delete_users_me_service_failure_returns_false(
    client: TestClient,
    mock_user_service: MagicMock,
) -> None:
    """测试 DELETE /users/me 在 service 返回 False 时透传 success=False (BUG-AUTH-009)。"""
    mock_user_service.delete_account.return_value = False

    response = client.delete("/api/v1/users/me")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["success"] is False
    assert "失败" in data["message"]
