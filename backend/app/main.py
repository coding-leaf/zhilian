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

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from app.api.v1 import api_v1_router
from app.container import AppContainer
from app.core.config import (
    AppSettings,
    get_settings,
    validate_secret_key,
    validate_wechat_credentials,
)
from app.core.errors import AppError

logger = logging.getLogger(__name__)


def build_cors_options(settings: AppSettings) -> dict[str, Any]:
    """按运行配置生成安全的 CORSMiddleware 参数（避免通配符与 credentials 混用）。"""
    origins = list(settings.cors_allow_origins)
    allow_wildcard = "*" in origins
    return {
        "allow_origins": origins,
        "allow_credentials": bool(origins) and not allow_wildcard,
        "allow_methods": ["*"],
        "allow_headers": ["*"],
    }


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
        # 生产环境使用开发默认密钥或缺失微信登录凭据时启动期 fail-fast（安全基线红线）
        validate_secret_key(settings)
        validate_wechat_credentials(settings)
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

# 允许跨域（按环境配置白名单，通配符模式自动关闭 allow_credentials）
app.add_middleware(
    CORSMiddleware,
    **build_cors_options(get_settings()),
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
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "code": 10001,
            "message": "请求参数校验失败",
            "details": jsonable_encoder(exc.errors()),
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """全局兜底未捕获异常处理器：记录结构化堆栈并返回脱敏 JSON 500。"""
    logger.exception(
        "unhandled server exception",
        extra={
            "path": request.url.path,
            "method": request.method,
            "error_code": 50000,
            "exception_type": type(exc).__name__,
        },
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "code": 50000,
            "message": "服务暂时繁忙，请稍后重试",
            "details": {},
        },
    )


# 挂载 API v1 路由总线
app.include_router(api_v1_router)

_KATEX_FONTS_DIR = (Path(__file__).resolve().parent / "static" / "fonts" / "katex").resolve()
_ALLOWED_FONT_MEDIA_TYPES: dict[str, str] = {
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
}
_FONT_CACHE_HEADERS: dict[str, str] = {
    "Cache-Control": "public, max-age=31536000, immutable",
    "Access-Control-Allow-Origin": "*",
}


@app.get(
    "/static/fonts/katex/{font_path:path}",
    tags=["static"],
    include_in_schema=False,
)
async def serve_katex_font(font_path: str) -> FileResponse:
    """只读提供自托管 KaTeX 数学字体（.woff2 / .ttf），带强缓存与路径穿越防护。"""
    if (
        not font_path
        or "/" in font_path
        or "\\" in font_path
        or "\x00" in font_path
        or ".." in font_path
        or font_path.startswith(".")
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Font not found")

    suffix = Path(font_path).suffix.lower()
    media_type = _ALLOWED_FONT_MEDIA_TYPES.get(suffix)
    if media_type is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Font not found")

    target = (_KATEX_FONTS_DIR / font_path).resolve()
    if not target.is_relative_to(_KATEX_FONTS_DIR) or not target.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Font not found")

    return FileResponse(path=target, media_type=media_type, headers=_FONT_CACHE_HEADERS)


@app.get("/health", tags=["system"], summary="服务健康检查")
def health_check(request: Request) -> JSONResponse:
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
