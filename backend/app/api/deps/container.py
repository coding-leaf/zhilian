"""FastAPI 应用容器依赖注入模块。

严格遵循 AGENTS.md 规范：
- 集中获取生命周期托管的 AppContainer 实例；
- 缩写白名单仅限 api, id, url, ocr, llm, db, config, env。
"""

from fastapi import Request

from app.container import AppContainer


def get_container(request: Request) -> AppContainer | None:
    """FastAPI 依赖项：从请求上下文安全获取全局应用装配容器。

    Args:
        request: FastAPI 当前请求上下文。

    Returns:
        AppContainer | None: 应用装配容器实例，若未初始化则返回 None。
    """
    if request is not None and getattr(request, "app", None) is not None:
        return getattr(request.app.state, "container", None)
    return None


__all__ = ["get_container"]
