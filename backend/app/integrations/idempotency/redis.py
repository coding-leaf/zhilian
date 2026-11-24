"""基于 Redis 的分布式幂等拦截器适配器实现模块。

严格遵循 AGENTS.md 规范：
- 实现 IdempotencyProtocol 协议；
- 基于 Redis SET NX EX 实现原子分布式锁抢占；
- 维护结果快照持久化并支持 24h 自动物理过期；
- 强校验 user_id 租户隔离，防止越权；
- 凭据绝密脱敏：__repr__ 中严禁打印 Redis 明文密码。
"""

import json
from typing import Any

from app.core.config import RedisSettings
from app.core.errors import AppError, IdempotencyConflictError
from app.integrations.idempotency.protocol import (
    IdempotencyProtocol,
    validate_idempotency_key,
)
from app.integrations.redis_client import build_redis_client, close_redis_client, mask_redis_url


def _mask_redis_url(url: str | None) -> str:
    """脱敏 Redis 连接 URL 中的密码凭据。"""
    return mask_redis_url(url)


class RedisIdempotencyAdapter(IdempotencyProtocol):
    """基于 Redis 的分布式幂等拦截适配器。"""

    def __init__(
        self,
        *,
        redis_url: str | None = None,
        redis_client: Any | None = None,
        redis_settings: RedisSettings | None = None,
        socket_timeout: float | None = None,
        max_connections: int | None = None,
        key_prefix: str = "idempotency",
    ) -> None:
        """初始化 Redis 幂等适配器。

        Args:
            redis_url: Redis 连接 URI。
            redis_client: 可选外部注入的 Redis 客户端。
            redis_settings: 可选 RedisSettings 强类型配置。
            socket_timeout: 可选单命令读写超时（秒）。
            max_connections: 可选连接池上限。
            key_prefix: 命名空间前缀。

        Raises:
            AppError: 当缺少依赖或初始化失败时抛出。
        """
        self._key_prefix = key_prefix
        resolved_url = redis_url or (redis_settings.redis_url if redis_settings else None)
        self._masked_url = _mask_redis_url(resolved_url)

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
                raise AppError(
                    error_code=30015,
                    message="未安装 redis 依赖包，请安装 redis 后重试",
                    details={"error": str(exception)},
                ) from exception
            except Exception as exception:
                raise AppError(
                    error_code=30015,
                    message=f"初始化 Redis 客户端连接失败: {exception}",
                    details={"url": self._masked_url},
                ) from exception

    def close(self) -> None:
        """释放 Redis 客户端与底层连接池。"""
        close_redis_client(self._client)

    def ping(self) -> bool:
        """健康探测 Redis 连通性。"""
        return bool(self._client.ping())

    def _build_lock_key(self, user_id: str, key: str) -> str:
        """生成带租户隔离的锁键。"""
        return f"user:{user_id}:{self._key_prefix}:{key}:lock"

    def _build_result_key(self, user_id: str, key: str) -> str:
        """生成带租户隔离的结果快照键。"""
        return f"user:{user_id}:{self._key_prefix}:{key}:result"

    def acquire_lock(
        self,
        key: str,
        user_id: str,
        ttl_seconds: int = 60,
        *,
        raise_on_conflict: bool = True,
    ) -> bool:
        """原子抢占幂等锁。

        Args:
            key: 幂等键。
            user_id: 租户用户 ID。
            ttl_seconds: 锁最大持有租期（秒）。
            raise_on_conflict: 冲突时是否直接抛出 IdempotencyConflictError。

        Returns:
            bool: 抢占成功返回 True；已被占用且 raise_on_conflict=False 时返回 False。

        Raises:
            IdempotencyConflictError: 发生并发抢占冲突。
            IdempotencyKeyInvalidError: 幂等键非法。
        """
        clean_key = validate_idempotency_key(key)
        if not user_id or not user_id.strip():
            raise ValueError("user_id 不能为空")

        lock_key = self._build_lock_key(user_id, clean_key)
        result_key = self._build_result_key(user_id, clean_key)

        try:
            # 优先检查是否存在已完成的结果快照
            if self._client.exists(result_key):
                if raise_on_conflict:
                    raise IdempotencyConflictError(
                        f"请求正在并发处理中，请勿重复提交: {clean_key}",
                        details={"key": clean_key, "user_id": user_id},
                    )
                return False

            # 使用 SET key value NX EX 进行原子抢占
            acquired = self._client.set(lock_key, "LOCKED", nx=True, ex=ttl_seconds)
            if acquired:
                return True

            if raise_on_conflict:
                raise IdempotencyConflictError(
                    f"请求正在并发处理中，请勿重复提交: {clean_key}",
                    details={"key": clean_key, "user_id": user_id},
                )
            return False
        except IdempotencyConflictError:
            raise
        except Exception as exception:
            raise AppError(
                error_code=30015,
                message=f"Redis 幂等锁抢占失败: {exception}",
                details={"key": clean_key},
            ) from exception

    def set_result(
        self,
        key: str,
        user_id: str,
        response_data: dict[str, Any],
        ttl_seconds: int = 86400,
    ) -> None:
        """持久化保存已完成的响应快照，并释放处理中锁。

        Args:
            key: 幂等键。
            user_id: 租户用户 ID。
            response_data: 待缓存的响应数据字典。
            ttl_seconds: 快照保留时长（秒）。

        Raises:
            IdempotencyKeyInvalidError: 幂等键非法。
        """
        clean_key = validate_idempotency_key(key)
        if not user_id or not user_id.strip():
            raise ValueError("user_id 不能为空")

        lock_key = self._build_lock_key(user_id, clean_key)
        result_key = self._build_result_key(user_id, clean_key)

        try:
            serialized_data = json.dumps(response_data, ensure_ascii=False)
            self._client.set(result_key, serialized_data, ex=ttl_seconds)
            self._client.delete(lock_key)
        except Exception as exception:
            raise AppError(
                error_code=30015,
                message=f"持久化幂等结果失败: {exception}",
                details={"key": clean_key},
            ) from exception

    def get_result(self, key: str, user_id: str) -> dict[str, Any] | None:
        """获取已成功完成的幂等请求响应快照。

        Args:
            key: 幂等键。
            user_id: 租户用户 ID。

        Returns:
            dict[str, Any] | None: 历史响应快照，未完成或不存在返回 None。

        Raises:
            IdempotencyKeyInvalidError: 幂等键非法。
        """
        clean_key = validate_idempotency_key(key)
        if not user_id or not user_id.strip():
            raise ValueError("user_id 不能为空")

        result_key = self._build_result_key(user_id, clean_key)

        try:
            raw = self._client.get(result_key)
            if raw is None:
                return None
            decoded = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
            parsed = json.loads(decoded)
            if isinstance(parsed, dict):
                return parsed
            return None
        except Exception as exception:
            raise AppError(
                error_code=30015,
                message=f"获取幂等结果失败: {exception}",
                details={"key": clean_key},
            ) from exception

    def release_lock(self, key: str, user_id: str) -> None:
        """业务执行失败或异常退出时，主动释放正在处理中的幂等锁。

        Args:
            key: 幂等键。
            user_id: 租户用户 ID。

        Raises:
            IdempotencyKeyInvalidError: 幂等键非法。
        """
        clean_key = validate_idempotency_key(key)
        if not user_id or not user_id.strip():
            raise ValueError("user_id 不能为空")

        lock_key = self._build_lock_key(user_id, clean_key)

        try:
            self._client.delete(lock_key)
        except Exception as exception:
            raise AppError(
                error_code=30015,
                message=f"释放幂等锁失败: {exception}",
                details={"key": clean_key},
            ) from exception

    def __repr__(self) -> str:
        """安全脱敏的字符串表示。"""
        return f"<RedisIdempotencyAdapter url={self._masked_url} prefix={self._key_prefix}>"


__all__ = ["RedisIdempotencyAdapter"]
