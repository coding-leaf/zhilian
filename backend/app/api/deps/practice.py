"""FastAPI 练习服务依赖注入模块。

提供解析与获取 PracticeService 业务编排服务实例的依赖项。
严格遵循 AGENTS.md 架构分层规范：
- 本模块严禁直接跨层导入仓储层 (app.repositories)；
- 缩写白名单仅限 api, id, url, ocr, llm, db, config, env。
"""

from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.api.deps.db import get_db_session
from app.container import AppContainer
from app.services.practice import PracticeService

_DEFAULT_REQUEST: Any = None


def get_practice_service(
    request: Request = _DEFAULT_REQUEST,
    session: Annotated[Session | None, Depends(get_db_session)] = None,
) -> PracticeService:
    """FastAPI 依赖项：获取 PracticeService 服务实例。

    优先从请求生命周期的 AppContainer 中以单请求独立 Session 装配服务实例；
    在单元测试中通过 app.dependency_overrides[get_practice_service] 注入。

    Args:
        request: FastAPI 请求上下文对象。
        session: 单请求生命周期的数据库会话（由 get_db_session 供给）。

    Returns:
        PracticeService: 练习会话与组卷编排服务。

    Raises:
        NotImplementedError: 在外部服务层装配前直接调用时提醒依赖注入覆盖。
    """
    if request is not None and getattr(request, "app", None) is not None:
        container: AppContainer | None = getattr(request.app.state, "container", None)
        if container is not None:
            actual_session = (
                session if isinstance(session, Session) else container.session_factory()
            )
            return container.create_practice_service(session=actual_session)

    raise NotImplementedError(
        "PracticeService 生产装配工厂尚未挂载，"
        "请在测试或路由中使用 dependency_overrides[get_practice_service] 注入"
    )


__all__ = ["get_practice_service"]
