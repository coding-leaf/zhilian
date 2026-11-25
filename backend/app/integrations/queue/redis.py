"""基于 Redis 的异步任务队列适配器实现模块。

严格遵循 AGENTS.md 规范：
- 实现 QueueProtocol 协议；
- 支持指数退避重试（最多 3 次针对网络抖动与超时）；
- 异常统一转译为 QueueError 或 QueueTimeoutError；
- 强校验 user_id 租户隔离，防止越权；
- 凭据绝密脱敏：__repr__ 中严禁打印 Redis 明文密码。
"""

import json
import re
import time
import uuid
from collections.abc import Callable
from typing import Any, TypeVar

from app.core.config import RedisSettings
from app.core.errors import PermissionDeniedError, QueueError, QueueTimeoutError
from app.integrations._http_retry import run_with_retry
from app.integrations.queue.protocol import (
    QueueProtocol,
    TaskMessage,
    TaskResult,
    serialize_task_message,
)
from app.integrations.redis_client import build_redis_client, close_redis_client, mask_redis_url

T = TypeVar("T")

_DEFAULT_MAX_RETRIES: int = 3
_BASE_BACKOFF_SECONDS: float = 0.05


def _mask_redis_url(url: str | None) -> str:
    """脱敏 Redis 连接 URL 中的密码凭据。

    Args:
        url: 原始 Redis 连接字符串。

    Returns:
        str: 脱敏后的连接字符串。
    """
    if not url:
        return "redis://localhost:6379/0"
    # 替换 :password@ 为 :***@
    return re.sub(r":([^:@]+)@", r":***@", url)


class RedisQueueAdapter(QueueProtocol):
    """基于 Redis 的分布式任务队列适配器。"""

    def __init__(
        self,
        *,
        redis_url: str | None = None,
        redis_client: Any | None = None,
        redis_settings: RedisSettings | None = None,
        socket_timeout: float | None = None,
        max_connections: int | None = None,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        queue_prefix: str = "queue",
    ) -> None:
        """初始化 Redis 任务队列适配器。

        Args:
            redis_url: Redis 连接 URI（如 redis://:pass@host:port/0）。
            redis_client: 可选外部注入的 Redis 客户端实例（支持 Fake / Mock 打桩）。
            redis_settings: 可选 RedisSettings 强类型配置。
            socket_timeout: 可选单命令读写超时（秒）。
            max_connections: 可选连接池上限。
            max_retries: 最大重试次数，默认 3 次。
            queue_prefix: 队列命名空间前缀。

        Raises:
            QueueError: 当缺少客户端且未能成功建立连接时抛出。
        """
        self._max_retries = max_retries
        self._queue_prefix = queue_prefix
        resolved_url = redis_url or (redis_settings.redis_url if redis_settings else None)
        self._masked_url = mask_redis_url(resolved_url)

        if redis_client is not None:
            self._client = redis_client
        else:
            try:
                self._client = build_redis_client(
                    redis_url=redis_url,
                    settings=redis_settings,
                    socket_timeout=socket_timeout,
                    max_connections=max_connections,
                    decode_responses=True,
                )
            except ImportError as exception:
                raise QueueError(
                    "未安装 redis 依赖包，请安装 redis 后重试",
                    details={"error": str(exception)},
                ) from exception
            except Exception as exception:
                raise QueueError(
                    f"初始化 Redis 客户端连接失败: {exception}",
                    details={"url": self._masked_url},
                ) from exception

    def close(self) -> None:
        """释放 Redis 客户端与底层连接池。"""
        close_redis_client(self._client)

    def ping(self) -> bool:
        """健康探测 Redis 连通性。"""
        return bool(self._client.ping())

    @staticmethod
    def _classify_redis_error(exception: Exception) -> tuple[bool, bool]:
        """判断异常是否为 (可重试异常, 是否属于超时异常)。"""
        if isinstance(exception, PermissionDeniedError):
            return False, False
        if isinstance(exception, (TimeoutError, OSError)):
            is_timeout = isinstance(exception, TimeoutError) or "timeout" in str(exception).lower()
            return True, is_timeout
        exception_type = type(exception).__name__
        is_timeout = "Timeout" in exception_type or "timeout" in str(exception).lower()
        is_connection = "Connection" in exception_type or "connection" in str(exception).lower()
        return (is_timeout or is_connection), is_timeout

    @classmethod
    def _map_redis_error(cls, exception: Exception, attempt: int) -> Exception:
        """将未恢复的 Redis 队列异常转译为标准 QueueError / QueueTimeoutError。"""
        if isinstance(exception, PermissionDeniedError):
            return exception
        retryable, is_timeout = cls._classify_redis_error(exception)
        if retryable:
            if is_timeout:
                return QueueTimeoutError(
                    f"Redis 队列操作响应超时: {exception}",
                    details={"attempt": attempt},
                )
            msg = (
                f"Redis 队列网络异常: {exception}"
                if isinstance(exception, OSError)
                else f"Redis 队列网络故障: {exception}"
            )
            return QueueError(msg, details={"attempt": attempt})
        return QueueError(
            f"Redis 队列操作失败: {exception}",
            details={"exception_type": type(exception).__name__},
        )

    def _execute_with_retry(self, operation: Callable[[], T]) -> T:
        """带指数退避的 Redis 操作重试执行器。"""
        return run_with_retry(
            operation,
            max_retries=max(0, self._max_retries - 1),
            retry_delay_base=_BASE_BACKOFF_SECONDS,
            should_retry=lambda exc: self._classify_redis_error(exc)[0],
            map_exhausted=self._map_redis_error,
            sleep_fn=lambda delay: time.sleep(delay),
            total_attempts=self._max_retries,
        )

    def enqueue(
        self,
        task_name: str,
        payload: dict[str, Any],
        user_id: str,
        *,
        task_id: str | None = None,
        delay_seconds: int = 0,
        priority: int = 0,
    ) -> str:
        """任务下发入队。

        Args:
            task_name: 任务名称。
            payload: 任务参数字典。
            user_id: 提交用户 ID。
            task_id: 可选任务 ID，默认自动生成 UUIDv4。
            delay_seconds: 延迟执行时间（秒）。
            priority: 优先级。

        Returns:
            str: 任务唯一标识 task_id。

        Raises:
            QueueTimeoutError: 网络连接超时。
            QueueError: 入队异常。
        """
        resolved_task_id = (task_id or str(uuid.uuid4())).strip()
        message = TaskMessage(
            task_id=resolved_task_id,
            task_name=task_name,
            payload=payload,
            user_id=user_id,
            priority=priority,
        )
        serialized_message = serialize_task_message(message)
        task_hash_key = f"task:{resolved_task_id}"
        queue_key = f"{self._queue_prefix}:{task_name}"

        def _do_enqueue() -> str:
            mapping = {
                "task_id": resolved_task_id,
                "task_name": task_name,
                "user_id": user_id,
                "status": "pending",
                "result": "",
                "error": "",
                "duration_ms": "0.0",
            }
            # 记录任务初始状态 Hash
            if hasattr(self._client, "hset"):
                self._client.hset(task_hash_key, mapping=mapping)
            else:
                self._client.hmset(task_hash_key, mapping)

            # 推送进入任务队列 List
            self._client.lpush(queue_key, serialized_message)
            return resolved_task_id

        return self._execute_with_retry(_do_enqueue)

    def get_status(self, task_id: str, user_id: str) -> TaskResult | None:
        """查询任务状态与执行结果（严格校验 user_id 租户归属）。

        Args:
            task_id: 任务唯一标识。
            user_id: 当前请求用户 ID。

        Returns:
            TaskResult | None: 任务结果，不存在返回 None。

        Raises:
            PermissionDeniedError: 非本人归属时阻断越权。
            QueueError: 查询异常。
        """
        task_hash_key = f"task:{task_id}"

        def _do_get() -> dict[str, Any] | None:
            raw = self._client.hgetall(task_hash_key)
            if not raw:
                return None
            # 确保转换字节为字符串（若客户端未开启 decode_responses）
            decoded: dict[str, str] = {}
            for key, value in raw.items():
                decoded_key = key.decode("utf-8") if isinstance(key, bytes) else str(key)
                decoded_val = value.decode("utf-8") if isinstance(value, bytes) else str(value)
                decoded[decoded_key] = decoded_val
            return decoded

        data = self._execute_with_retry(_do_get)
        if not data:
            return None

        stored_user_id = data.get("user_id", "")
        if stored_user_id != user_id:
            raise PermissionDeniedError(
                f"无权访问任务 {task_id}",
                details={"task_id": task_id, "user_id": user_id},
            )

        status = data.get("status", "pending")
        raw_result = data.get("result", "")
        result_value: Any = None
        if raw_result:
            try:
                result_value = json.loads(raw_result)
            except Exception:
                result_value = raw_result

        raw_error = data.get("error", "")
        error_value = raw_error if raw_error else None

        try:
            duration_ms = float(data.get("duration_ms", "0.0"))
        except ValueError:
            duration_ms = 0.0

        return TaskResult(
            task_id=task_id,
            status=status,
            result=result_value,
            error=error_value,
            duration_ms=duration_ms,
        )

    def cancel(self, task_id: str, user_id: str) -> bool:
        """取消排队中的任务。

        Args:
            task_id: 任务唯一标识。
            user_id: 当前请求用户 ID。

        Returns:
            bool: 成功取消返回 True；任务不存在或非 pending 返回 False。

        Raises:
            PermissionDeniedError: 非本人归属时阻断越权。
            QueueError: 取消异常。
        """
        task_hash_key = f"task:{task_id}"

        def _do_cancel() -> bool:
            raw = self._client.hgetall(task_hash_key)
            if not raw:
                return False

            decoded: dict[str, str] = {}
            for key, value in raw.items():
                decoded_key = key.decode("utf-8") if isinstance(key, bytes) else str(key)
                decoded_val = value.decode("utf-8") if isinstance(value, bytes) else str(value)
                decoded[decoded_key] = decoded_val

            stored_user_id = decoded.get("user_id", "")
            if stored_user_id != user_id:
                raise PermissionDeniedError(
                    f"无权取消任务 {task_id}",
                    details={"task_id": task_id, "user_id": user_id},
                )

            current_status = decoded.get("status", "")
            if current_status != "pending":
                return False

            if hasattr(self._client, "hset"):
                self._client.hset(task_hash_key, "status", "cancelled")
            else:
                self._client.hmset(task_hash_key, {"status": "cancelled"})
            return True

        return self._execute_with_retry(_do_cancel)

    def __repr__(self) -> str:
        """安全脱敏的字符串表示。"""
        return (
            f"<RedisQueueAdapter url={self._masked_url} "
            f"max_retries={self._max_retries} prefix={self._queue_prefix}>"
        )


__all__ = ["RedisQueueAdapter"]
