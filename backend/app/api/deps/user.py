"""FastAPI 用户管理服务依赖注入模块。

提供解析与获取用户管理服务的依赖项。
严格遵循 AGENTS.md 架构分层规范：
- 本模块严禁直接跨层导入仓储层 (app.repositories)；
- 缩写白名单仅限 api, id, url, ocr, llm, db, config, env。
"""

from collections.abc import Generator
from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.api.deps.db import get_db_session
from app.container import AppContainer
from app.services.auth import AuthService

_DEFAULT_REQUEST: Any = None


def get_user_service(
    request: Request = _DEFAULT_REQUEST,
    session: Annotated[Session | None, Depends(get_db_session)] = None,
) -> Generator[AuthService, None, None]:
    """FastAPI 依赖项：获取用户管理服务实例 (AuthService 门面)。

    优先从请求生命周期的 AppContainer 中以单请求独立 Session 装配服务实例；
    在单元测试中通过 app.dependency_overrides[get_user_service] 注入。
    本依赖为生成器依赖：当请求级 Session 不可用时，fallback 自建 Session
    由上下文管理器托管，并在请求结束时（生成器 teardown）自动 close，杜绝连接泄漏。

    Args:
        request: FastAPI 请求上下文对象。
        session: 单请求生命周期的数据库会话（由 get_db_session 供给）。

    Yields:
        AuthService: 用户管理编排服务。

    Raises:
        NotImplementedError: 在服务装配前直接调用时抛出。
    """
    if request is not None and getattr(request, "app", None) is not None:
        container: AppContainer | None = getattr(request.app.state, "container", None)
        if container is not None:
            if isinstance(session, Session):
                yield container.create_user_service(session=session)
                return

            with container.get_session() as managed_session:
                yield container.create_user_service(session=managed_session)
            return

    raise NotImplementedError(
        "AuthService 生产装配工厂尚未挂载，"
        "请在测试或路由中使用 dependency_overrides[get_user_service] 注入"
    )


__all__ = ["get_user_service"]
