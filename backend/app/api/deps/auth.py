"""FastAPI 鉴权与租户上下文提取依赖注入模块。

提供解析 JWT 令牌载荷、提取租户用户 UUID，以及校验用户状态与令牌版本一致性的依赖项。
严格遵循 AGENTS.md 架构分层规范：
- 本模块严禁直接跨层导入仓储层 (app.repositories)；
- 鉴权失败统一抛出规范的 AuthenticationError 异常；
- 缩写白名单仅限 api, id, url, ocr, llm, db, config, env。
"""

import uuid
from typing import Annotated, Any

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.api.deps.db import get_db_session
from app.container import AppContainer
from app.core.errors import AuthenticationError
from app.core.security import decode_token, verify_token_version
from app.models.user import User
from app.services.auth import AuthService

# 设置 auto_error=False，以便本模块自主拦截缺失凭证并转化为规范的 AuthenticationError (HTTP 401)
http_bearer = HTTPBearer(auto_error=False)
_DEFAULT_REQUEST: Any = None


async def get_current_token_payload(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(http_bearer)] = None,
) -> dict[str, Any]:
    """从 HTTP 请求头中提取并校验 JWT 访问令牌有效性。

    验证 Authorization 请求头存在性、Bearer 协议方案，并调用纯函数 decode_token 验证签名与类型。

    Args:
        request: FastAPI 请求上下文对象。
        credentials: 由 HTTPBearer 提取的凭据对象（若头存在且格式合法）。

    Returns:
        dict[str, Any]: 经签名校验与有效期校验通过的令牌载荷字典。

    Raises:
        AuthenticationError: 当请求头缺失、认证协议非 Bearer、凭据为空或令牌非法时抛出。
    """
    authorization_header = request.headers.get("Authorization")
    if not authorization_header:
        raise AuthenticationError("请求头缺失认证凭据 (Authorization Header)")

    trimmed_header = authorization_header.strip()
    if not trimmed_header.lower().startswith("bearer"):
        raise AuthenticationError("认证协议方案错误: 必须采用 Bearer 协议")

    parts = trimmed_header.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        raise AuthenticationError("请求头认证凭据为空")

    if credentials is None or not credentials.credentials:
        raise AuthenticationError("请求头认证凭据为空")

    return decode_token(credentials.credentials, expected_type="access")


async def get_current_user_id(
    payload: Annotated[dict[str, Any], Depends(get_current_token_payload)],
) -> uuid.UUID:
    """从已通过校验的令牌载荷中提取当前租户用户的 UUID。

    用于无需加载完整 User 实体的轻量级租户隔离路由。

    Args:
        payload: get_current_token_payload 解析并验签后的载荷字典。

    Returns:
        uuid.UUID: 当前租户用户标识。

    Raises:
        AuthenticationError: 当用户标识缺失或非合法 UUID 格式时抛出。
    """
    raw_sub = payload.get("sub")
    if not raw_sub:
        raise AuthenticationError("令牌载荷无效: 缺少用户标识 (sub)")

    try:
        return uuid.UUID(str(raw_sub))
    except (ValueError, TypeError) as exc:
        raise AuthenticationError("令牌载荷无效: 用户标识格式错误") from exc


def validate_user_status(user: User | None, payload_token_version: int) -> User:
    """核对用户实体存在性、激活状态、软删除标记及令牌版本一致性。

    纯校验逻辑，阻断停用用户、已注销用户或版本已过期的失效凭证。

    Args:
        user: 从持久化存储或服务层加载的用户实体（若不存在则为 None）。
        payload_token_version: 令牌载荷中声明的 token_version。

    Returns:
        User: 经校验状态合法的活跃用户实体。

    Raises:
        AuthenticationError: 当用户不存在、未激活、已注销或令牌版本失效时抛出。
    """
    if user is None:
        raise AuthenticationError("用户不存在或已被移除")

    if not user.is_active:
        raise AuthenticationError("用户账号已被停用")

    if getattr(user, "is_deleted", False):
        raise AuthenticationError("用户账号已被注销")

    if not verify_token_version(payload_token_version, user.token_version):
        raise AuthenticationError("令牌已被即时吊销或版本已过期，请重新登录")

    return user


def get_auth_service(
    request: Request = _DEFAULT_REQUEST,
    session: Annotated[Session | None, Depends(get_db_session)] = None,
) -> AuthService:
    """FastAPI 依赖项：获取 AuthService 服务实例。

    优先从请求生命周期的 AppContainer 中以单请求独立 Session 装配服务实例；
    在单元测试中通过 app.dependency_overrides[get_auth_service] 注入。

    Args:
        request: FastAPI 请求上下文对象。
        session: 单请求生命周期的数据库会话（由 get_db_session 供给）。

    Returns:
        AuthService: 认证与账号管理业务编排服务。

    Raises:
        NotImplementedError: 在外部服务层装配前直接调用时提醒依赖注入覆盖。
    """
    if request is not None and getattr(request, "app", None) is not None:
        container: AppContainer | None = getattr(request.app.state, "container", None)
        if container is not None:
            actual_session = (
                session if isinstance(session, Session) else container.session_factory()
            )
            return container.create_auth_service(session=actual_session)

    raise NotImplementedError(
        "AuthService 生产装配工厂尚未挂载，"
        "请在测试或路由中使用 dependency_overrides[get_auth_service] 注入"
    )


async def get_current_user(
    payload: Annotated[dict[str, Any], Depends(get_current_token_payload)],
    request: Request = _DEFAULT_REQUEST,
    auth_service: Annotated[AuthService | None, Depends(get_auth_service)] = None,
) -> User:
    """FastAPI 依赖项：获取当前已认证且处于活跃状态的用户实体。

    遵循架构单向分层，路由和依赖严禁直接导入 app.repositories。
    优先通过 AuthService 依赖项检索用户实体并校验状态；
    测试中通过 app.dependency_overrides[get_current_user] 注入。

    Args:
        payload: 已经过校验的令牌载荷。
        request: FastAPI 请求上下文对象。
        auth_service: 注入的 AuthService 实例。

    Returns:
        User: 经校验合法的活跃用户实体。

    Raises:
        AuthenticationError: 令牌解析失败、用户不存在或用户状态异常。
        NotImplementedError: 容器未初始化且未通过 dependency_overrides 覆盖。
    """
    raw_sub = payload.get("sub")
    if not raw_sub:
        raise AuthenticationError("令牌载荷缺少用户标识 (sub)")
    try:
        user_uuid = uuid.UUID(str(raw_sub))
    except (ValueError, TypeError) as exc:
        raise AuthenticationError("用户标识格式无效") from exc

    if isinstance(auth_service, AuthService):
        user = auth_service.get_user_by_id(user_uuid)
        token_version = payload.get("token_version", 1)
        return validate_user_status(user, token_version)

    if request is not None and getattr(request, "app", None) is not None:
        container: AppContainer | None = getattr(request.app.state, "container", None)
        if container is not None:
            active_auth_svc = container.create_auth_service(session=container.session_factory())
            user = active_auth_svc.get_user_by_id(user_uuid)
            token_version = payload.get("token_version", 1)
            return validate_user_status(user, token_version)

    raise NotImplementedError(
        "用户服务数据加载器尚未装配，"
        "请在测试或路由中使用 dependency_overrides[get_current_user] 注入"
    )


__all__ = [
    "get_auth_service",
    "get_current_token_payload",
    "get_current_user",
    "get_current_user_id",
    "http_bearer",
    "validate_user_status",
]
