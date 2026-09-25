"""FastAPI 数据库会话依赖注入模块。

提供获取单请求生命周期独立数据库会话的依赖项。
严格遵循 AGENTS.md 规范与租户隔离原则：
- 单请求独立 Session，请求结束或异常时自动关闭释放连接池资源；
- 严禁跨请求共享同一数据库会话实例。
"""

from collections.abc import Generator
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.container import AppContainer

_DEFAULT_REQUEST: Any = None


def _db_session_generator(
    request: Request = _DEFAULT_REQUEST,
) -> Generator[Session, None, None]:
    """底层生成器实现：从 container.get_session() 产出会话并在退出时关闭。"""
    if request is not None and getattr(request, "app", None) is not None:
        container: AppContainer | None = getattr(request.app.state, "container", None)
        if container is not None:
            with container.get_session() as session:
                yield session
            return

    raise NotImplementedError(
        "数据库会话工厂尚未挂载，请在测试或路由中使用 dependency_overrides[get_db_session] 注入"
    )


def get_db_session(
    request: Request = _DEFAULT_REQUEST,
) -> Generator[Session, None, None]:
    """FastAPI 依赖项：获取单请求生命周期的独立数据库会话。

    优先自 request.app.state.container.get_session() 生成并在请求结束时 close()；
    在单元测试中可通过 app.dependency_overrides[get_db_session] 注入。

    Yields:
        Session: 独立的数据库会话。

    Raises:
        NotImplementedError: 数据库会话工厂尚未挂载且未被 overrides。
    """
    if request is None or getattr(request, "app", None) is None:
        raise NotImplementedError(
            "数据库会话工厂尚未挂载，请在测试或路由中使用 dependency_overrides[get_db_session] 注入"
        )

    return _db_session_generator(request)


# 将 __wrapped__ 设置为真正的生成器函数，使得 FastAPI 识别其为生成器依赖并在请求退出时清理
get_db_session.__wrapped__ = _db_session_generator  # type: ignore[attr-defined]

__all__ = ["get_db_session"]
