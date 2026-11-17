"""Unit tests verifying all HTTP route handlers run synchronously off the asyncio event loop."""

import inspect

from fastapi.routing import APIRoute

from app.api.v1 import api_v1_router
from app.main import app as fastapi_app


def test_all_api_v1_routes_are_sync_def_for_threadpool_dispatch() -> None:
    """All v1 routes calling sync Session/Services/httpx must be plain def."""
    async_endpoints: list[str] = []
    for route in api_v1_router.routes:
        if isinstance(route, APIRoute) and inspect.iscoroutinefunction(route.endpoint):
            async_endpoints.append(f"{','.join(sorted(route.methods))} {route.path}")
    assert async_endpoints == []


def test_app_health_and_mounted_api_routes_are_sync_def() -> None:
    """Mounted application /health and /api/v1 routes must not freeze uvicorn event loop."""
    async_endpoints: list[str] = []
    for route in fastapi_app.routes:
        if (
            isinstance(route, APIRoute)
            and (route.path == "/health" or route.path.startswith("/api/v1"))
            and inspect.iscoroutinefunction(route.endpoint)
        ):
            async_endpoints.append(f"{','.join(sorted(route.methods))} {route.path}")
    assert async_endpoints == []
