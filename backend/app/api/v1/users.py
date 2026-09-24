"""用户管理与画像详情 API 路由控制模块。

处理当前登录用户画像查询与账号注销操作。
严格遵循 AGENTS.md 规范与 spec.md 技术契约：
- 路由层只负责 HTTP 协议解析、参数校验、调用 Service 层与响应转换；
- 严禁直接跨层导入仓储层 (app.repositories)；
- 严禁在路由层开启数据库事务或执行超过 1 行的业务逻辑判断；
- 缩写白名单仅限 api, id, url, ocr, llm, db, config, env。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps.auth import get_current_user
from app.api.deps.user import get_user_service
from app.models.user import User
from app.schemas.user import UserActionResponse, UserProfileResponse
from app.services.auth import AuthService

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "/me",
    response_model=UserProfileResponse,
    status_code=status.HTTP_200_OK,
    summary="获取当前登录用户画像资料",
)
async def get_current_user_profile(
    current_user: Annotated[User, Depends(get_current_user)],
    user_service: Annotated[AuthService, Depends(get_user_service)],
) -> UserProfileResponse:
    """查询当前登录用户的个人画像资料详情。

    Args:
        current_user: 当前已认证登录的用户实体。
        user_service: 用户管理业务编排服务。

    Returns:
        UserProfileResponse: 包含用户 ID、昵称、头像及注册时间的响应对象。
    """
    return user_service.get_user_profile(user_id=current_user.id)


@router.delete(
    "/me",
    response_model=UserActionResponse,
    status_code=status.HTTP_200_OK,
    summary="注销当前登录用户账号",
)
async def delete_current_user_account(
    current_user: Annotated[User, Depends(get_current_user)],
    user_service: Annotated[AuthService, Depends(get_user_service)],
) -> UserActionResponse:
    """软删除当前用户账号，并即刻作废全端所有签发令牌。

    Args:
        current_user: 当前已认证登录的用户实体。
        user_service: 用户管理业务编排服务。

    Returns:
        UserActionResponse: 账号注销成功提示响应对象。
    """
    user_service.delete_account(user_id=current_user.id)
    return UserActionResponse(success=True, message="账号已成功注销")


__all__ = ["router"]
