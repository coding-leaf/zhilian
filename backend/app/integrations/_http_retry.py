"""Shared exponential-backoff retry and managed HTTP client helpers for integration adapters."""

import random
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, cast

import httpx

DEFAULT_HTTPX_MAX_CONNECTIONS: int = 30
DEFAULT_HTTPX_MAX_KEEPALIVE_CONNECTIONS: int = 15


def build_httpx_client(
    *,
    timeout: float,
    max_connections: int = DEFAULT_HTTPX_MAX_CONNECTIONS,
    max_keepalive_connections: int = DEFAULT_HTTPX_MAX_KEEPALIVE_CONNECTIONS,
) -> httpx.Client:
    """Create a persistent httpx.Client with explicit pool limits and split timeouts."""
    return httpx.Client(
        limits=httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_keepalive_connections,
        ),
        timeout=httpx.Timeout(
            connect=min(10.0, timeout),
            read=timeout,
            write=min(15.0, timeout),
            pool=min(10.0, timeout),
        ),
    )


def _default_jitter(low: float, high: float) -> float:
    return random.uniform(low, high)  # noqa: S311


class RetryableAdapterError(Exception):
    """Wraps a mapped domain exception that should be retried with backoff."""

    def __init__(self, final_error: Exception) -> None:
        super().__init__(str(final_error))
        self.final_error = final_error


@contextmanager
def managed_httpx_client(
    external_client: Any | None,
    factory: Callable[[], httpx.Client],
) -> Iterator[httpx.Client]:
    """Yield an injected HTTP client untouched, or close a fallback httpx.Client on exit."""
    if external_client is not None:
        yield cast(httpx.Client, external_client)
        return
    with factory() as client:
        yield client


def run_with_retry[T](
    operation: Callable[[], T],
    *,
    max_retries: int,
    retry_delay_base: float,
    should_retry: Callable[[Exception], bool] | None = None,
    map_exhausted: Callable[[Exception, int], Exception] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    total_attempts: int | None = None,
    jitter_fn: Callable[[float, float], float] = _default_jitter,
) -> T:
    """Execute ``operation`` with jittered exponential backoff across retryable failures."""
    attempts = total_attempts if total_attempts is not None else max_retries + 1
    if attempts < 1:
        attempts = 1

    for attempt in range(attempts):
        try:
            return operation()
        except RetryableAdapterError as exc:
            if attempt >= attempts - 1:
                raise exc.final_error from exc.__cause__
            delay = retry_delay_base * (2**attempt) * jitter_fn(0.5, 1.5)
            if delay > 0:
                sleep_fn(delay)
        except Exception as exc:
            retryable = should_retry(exc) if should_retry is not None else False
            if not retryable or attempt >= attempts - 1:
                if map_exhausted is not None:
                    mapped = map_exhausted(exc, attempt + 1)
                    if mapped is not exc:
                        raise mapped from exc
                raise
            delay = retry_delay_base * (2**attempt) * jitter_fn(0.5, 1.5)
            if delay > 0:
                sleep_fn(delay)
    raise AssertionError("unreachable")  # pragma: no cover


def handle_openai_http_response(
    response: httpx.Response,
    *,
    service_label: str,
    auth_error_cls: Callable[..., Exception],
    service_error_cls: Callable[..., Exception],
) -> dict[str, Any]:
    """Validate HTTP status and decode JSON for OpenAI-compatible HTTP responses."""
    if response.status_code in (401, 403):
        raise auth_error_cls(
            f"{service_label}认证失败 (HTTP {response.status_code})",
            details={"status_code": response.status_code, "body": response.text[:200]},
        )
    if response.status_code == 429 or response.status_code >= 500:
        raise RetryableAdapterError(
            service_error_cls(
                f"{service_label}暂时不可用 (HTTP {response.status_code})",
                details={"status_code": response.status_code, "body": response.text[:200]},
            )
        )
    if response.status_code != 200:
        raise service_error_cls(
            f"{service_label}返回异常状态码: {response.status_code}",
            details={"status_code": response.status_code, "body": response.text[:200]},
        )
    try:
        return cast(dict[str, Any], response.json())
    except Exception as json_err:
        raise service_error_cls(f"{service_label}响应 JSON 反序列化失败") from json_err


__all__ = [
    "DEFAULT_HTTPX_MAX_CONNECTIONS",
    "DEFAULT_HTTPX_MAX_KEEPALIVE_CONNECTIONS",
    "RetryableAdapterError",
    "build_httpx_client",
    "handle_openai_http_response",
    "managed_httpx_client",
    "run_with_retry",
]
