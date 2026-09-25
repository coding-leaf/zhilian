"""智练自主学习平台 FastAPI 应用总入口与生命周期管理服务。

遵循 AGENTS.md 规范与 spec.md 架构契约：
- 采用 FastAPI lifespan 异步上下文管理器全生命周期托管 AppContainer；
- 移除顶层硬编码 SQLite/Fake 全局初始化副作用；
- 提供请求级 AppContainer 容器解析依赖 (get_container)；
- 挂载全套统一业务异常处理器 (AppError / RequestValidationError)；
- 配置跨域中间件 (CORSMiddleware)；
- 聚合加载 API v1 路由总线；
- 提供结构化多组件健康检查端点 (GET /health)。
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import api_v1_router
from app.container import AppContainer
from app.core.config import get_settings
from app.core.errors import AppError


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI 应用全局生命周期异步上下文管理器。

    在启动阶段初始化 AppContainer 并预热核心连接池；
    在应用关闭时优雅停机，释放外部客户端网络连接与连接池。
    """
    container: AppContainer | None = getattr(app.state, "container", None)
    own_container = False
    if container is None:
        settings = get_settings()
        container = AppContainer.create_from_settings(settings)
        app.state.container = container
        own_container = True

    await container.startup()
    try:
        yield
    finally:
        await container.shutdown()
        if own_container and hasattr(app.state, "container"):
            delattr(app.state, "container")


def get_container(request: Request) -> AppContainer:
    """从请求上下文安全获取全局装配容器。

    Args:
        request: FastAPI 当前请求上下文。

    Returns:
        AppContainer: 应用装配容器实例。

    Raises:
        RuntimeError: 当容器尚未初始化时抛出明确指导信息。
    """
    container: AppContainer | None = getattr(request.app.state, "container", None)
    if container is None:
        raise RuntimeError(
            "应用装配容器未初始化，请确保在应用 lifespan 生命周期内访问或注入 container"
        )
    return container


app = FastAPI(
    title="智练自主学习平台 API",
    description="智练平台后端核心领域服务与 RESTful API 总线",
    version="1.0.0",
    lifespan=lifespan,
)

# 允许跨域（本地开发、小程序与真机调试）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AppError)
async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    """全局统一业务异常处理器。"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.error_code,
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """统一 Pydantic 校验错误转换。"""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "code": 10001,
            "message": "请求参数校验失败",
            "details": exc.errors(),
        },
    )


# 挂载 API v1 路由总线
app.include_router(api_v1_router)


@app.get("/health", tags=["system"], summary="服务健康检查")
async def health_check(request: Request) -> JSONResponse:
    """多组件结构化健康检查端点。

    根据 AppContainer 诊断结果返回系统就绪状态：
    - 当核心数据库连通时返回 200 OK；
    - 当数据库不可用时返回 503 Service Unavailable 降级响应。
    """
    container: AppContainer | None = getattr(request.app.state, "container", None)
    if container is None:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"status": "ok", "app": "ZhiLian"},
        )

    health_info: dict[str, Any] = container.check_health()
    overall_status = health_info.get("status", "ok")
    http_status = (
        status.HTTP_200_OK
        if overall_status in ("ok", "healthy")
        else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    return JSONResponse(status_code=http_status, content=health_info)


@app.get("/", tags=["system"], summary="服务根入口")
async def root() -> dict[str, str]:
    """系统入口提示。"""
    return {
        "message": "智练自主学习平台 API 运行中",
        "docs_url": "/docs",
        "health_url": "/health",
    }


__all__ = ["app", "get_container", "lifespan"]
