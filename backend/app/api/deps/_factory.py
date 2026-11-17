"""FastAPI 领域服务依赖注入公共工厂。

统一从请求生命周期的 AppContainer 以单请求独立 Session 装配领域服务实例；
当请求级 Session 不可用时，fallback 自建 Session 由 `container.get_session()`
上下文管理器托管，在生成器 teardown 时自动回滚并关闭，杜绝连接泄漏。
严格遵循 AGENTS.md 架构分层规范：
- 本模块严禁直接跨层导入仓储层 (app.repositories)；
- 缩写白名单仅限 api, id, url, ocr, llm, db, config, env。
"""

from collections.abc import Callable, Generator
from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.api.deps.db import get_db_session
from app.container import AppContainer

_DEFAULT_REQUEST: Any = None


def make_service_dep[T](
    service_name: str,
    dep_name: str,
    builder: Callable[[AppContainer, Session], T],
) -> Callable[..., Generator[T, None, None]]:
    """构建标准 FastAPI 生成器依赖项以装配指定领域服务。

    Args:
        service_name: 领域服务类名，用于未挂载容器时的诊断提示。
        dep_name: 依赖注入函数名称，用于提示 `dependency_overrides` 键名与调试追踪。
        builder: 接收 `(container, session)` 并返回服务实例的纯工厂回调。

    Returns:
        Callable[..., Generator[T, None, None]]: 可直接作为 FastAPI `Depends(...)` 的生成器依赖。
    """

    def _dep(
        request: Request = _DEFAULT_REQUEST,
        session: Annotated[Session | None, Depends(get_db_session)] = None,
    ) -> Generator[T, None, None]:
        if request is not None and getattr(request, "app", None) is not None:
            container: AppContainer | None = getattr(request.app.state, "container", None)
            if container is not None:
                if isinstance(session, Session):
                    yield builder(container, session)
                    return

                with container.get_session() as managed_session:
                    yield builder(container, managed_session)
                return

        raise NotImplementedError(
            f"{service_name} 生产装配工厂尚未挂载，"
            f"请在测试或路由中使用 dependency_overrides[{dep_name}] 注入"
        )

    _dep.__name__ = dep_name
    _dep.__qualname__ = dep_name
    return _dep


__all__ = ["make_service_dep"]
