"""认证与授权相关 API 路由控制模块。

处理微信登录、令牌刷新及凭据主动吊销。
严格遵循 AGENTS.md 规范与 spec.md 技术契约：
- 路由层只负责 HTTP 协议解析、参数校验、调用 Service 层与响应转换；
- 严禁直接跨层导入仓储层 (app.repositories)；
- 严禁在路由层开启数据库事务或执行超过 1 行的业务逻辑判断；
- 缩写白名单仅限 api, id, url, ocr, llm, db, config, env。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps.auth import get_auth_service, get_current_user
from app.models.user import User
from app.schemas.auth import RefreshTokenRequest, TokenResponse, WechatLoginRequest
from app.schemas.user import UserActionResponse
from app.services.auth import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="微信登录或自动注册",
)
async def login(
    request: WechatLoginRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    """通过微信小程序临时凭证 code 登录或自动注册，签发双令牌。

    Args:
        request: 微信登录请求数据契约。
        auth_service: 认证与账号管理业务编排服务。

    Returns:
        TokenResponse: 包含 access_token 与 refresh_token 的响应对象。
    """
    _, token_response = auth_service.login_with_wechat(
        code=request.code,
        nickname=request.nickname,
        avatar_url=request.avatar_url,
    )
    return token_response


@router.post(
    "/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="长效凭证刷新双令牌",
)
async def refresh(
    request: RefreshTokenRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    """使用长效 Refresh Token 校验版本并置换新的一套双令牌。

    Args:
        request: 刷新令牌请求数据契约。
        auth_service: 认证与账号管理业务编排服务。

    Returns:
        TokenResponse: 包含新 access_token 与 refresh_token 的响应对象。
    """
    return auth_service.refresh_tokens(refresh_token=request.refresh_token)


@router.post(
    "/revoke",
    response_model=UserActionResponse,
    status_code=status.HTTP_200_OK,
    summary="主动吊销全端历史凭据",
)
async def revoke(
    current_user: Annotated[User, Depends(get_current_user)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> UserActionResponse:
    """主动递增令牌版本，使当前登录用户在所有端签发的历史凭据即刻失效。

    Args:
        current_user: 当前已认证登录的用户实体。
        auth_service: 认证与账号管理业务编排服务。

    Returns:
        UserActionResponse: 操作执行结果提示响应对象。
    """
    auth_service.revoke_tokens(user_id=current_user.id)
    return UserActionResponse(success=True, message="已成功注销所有登录凭据")


__all__ = ["router"]
