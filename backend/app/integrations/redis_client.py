"""Shared Redis client factory with explicit timeouts, health checks, and safe cleanup.

Centralizes Redis connection-pool construction across queue, idempotency, and worker
components so `RedisSettings` (timeout, max_connections) is never silently ignored.
"""

import logging
import re
from typing import TYPE_CHECKING, Any

from app.core.config import RedisSettings

if TYPE_CHECKING:
    from redis import Redis

logger = logging.getLogger(__name__)

DEFAULT_REDIS_URL = "redis://localhost:6379/0"
DEFAULT_HEALTH_CHECK_INTERVAL = 30
DEFAULT_REDIS_TIMEOUT = 5.0
DEFAULT_MAX_CONNECTIONS = 10


def mask_redis_url(url: str | None) -> str:
    """Mask password credentials in a Redis URL for safe logging and repr."""
    if not url:
        return DEFAULT_REDIS_URL
    return re.sub(r":([^:@]+)@", r":***@", url)


def build_redis_client(
    *,
    redis_url: str | None = None,
    settings: RedisSettings | None = None,
    socket_timeout: float | None = None,
    socket_connect_timeout: float | None = None,
    max_connections: int | None = None,
    health_check_interval: int = DEFAULT_HEALTH_CHECK_INTERVAL,
    retry_on_timeout: bool = True,
    decode_responses: bool = False,
    blocking: bool = False,
) -> "Redis":
    """Create a configured `redis.Redis` client honoring `RedisSettings`.

    Args:
        redis_url: Optional explicit Redis URI (overrides `settings.redis_url`).
        settings: Optional `RedisSettings` instance.
        socket_timeout: Optional per-command socket timeout in seconds.
        socket_connect_timeout: Optional TCP connect timeout in seconds.
        max_connections: Optional connection pool size cap.
        health_check_interval: Periodic socket health check interval in seconds.
        retry_on_timeout: Whether redis-py retries timed-out commands once.
        decode_responses: Whether to decode byte responses into strings.
        blocking: When True (e.g. RQ worker BLPOP consumer), leaves `socket_timeout=None`
            while still enforcing `socket_connect_timeout`, `health_check_interval`,
            and `max_connections`.

    Returns:
        Redis: Configured `redis.Redis` client instance.
    """
    import redis

    target_url = redis_url or (settings.redis_url if settings is not None else DEFAULT_REDIS_URL)
    resolved_timeout = (
        socket_timeout
        if socket_timeout is not None
        else (settings.timeout if settings is not None else DEFAULT_REDIS_TIMEOUT)
    )
    resolved_connect_timeout = (
        socket_connect_timeout if socket_connect_timeout is not None else resolved_timeout
    )
    resolved_max_connections = (
        max_connections
        if max_connections is not None
        else (settings.max_connections if settings is not None else DEFAULT_MAX_CONNECTIONS)
    )

    return redis.from_url(
        target_url,
        socket_connect_timeout=resolved_connect_timeout,
        socket_timeout=None if blocking else resolved_timeout,
        health_check_interval=health_check_interval,
        max_connections=resolved_max_connections,
        retry_on_timeout=retry_on_timeout,
        decode_responses=decode_responses,
    )


def close_redis_client(client: Any | None) -> None:
    """Safely close a Redis client and disconnect its underlying connection pool."""
    if client is None:
        return
    try:
        close_fn = getattr(client, "close", None)
        if callable(close_fn):
            close_fn()
    except Exception as exc:
        logger.warning("redis client close failed: %s", type(exc).__name__)
    try:
        pool = getattr(client, "connection_pool", None)
        disconnect_fn = getattr(pool, "disconnect", None)
        if callable(disconnect_fn):
            disconnect_fn()
    except Exception as exc:
        logger.warning("redis connection_pool disconnect failed: %s", type(exc).__name__)


__all__ = [
    "DEFAULT_HEALTH_CHECK_INTERVAL",
    "DEFAULT_MAX_CONNECTIONS",
    "DEFAULT_REDIS_TIMEOUT",
    "DEFAULT_REDIS_URL",
    "build_redis_client",
    "close_redis_client",
    "mask_redis_url",
]
