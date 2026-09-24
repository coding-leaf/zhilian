"""分布式幂等拦截器适配器工厂模块。

严格遵循 AGENTS.md 规范：
- 根据类型分发创建符合 IdempotencyProtocol 契约的适配器实例；
- 单元测试与离线环境默认分发 MemoryIdempotencyAdapter，具备零外部网络依赖特性；
- 生产环境支持创建 RedisIdempotencyAdapter。
"""

from typing import Any

from app.core.errors import AppError
from app.integrations.idempotency.memory import MemoryIdempotencyAdapter
from app.integrations.idempotency.protocol import IdempotencyProtocol
from app.integrations.idempotency.redis import RedisIdempotencyAdapter


def create_idempotency_adapter(
    adapter_type: str = "memory",
    *,
    redis_url: str | None = None,
    redis_client: Any | None = None,
    **kwargs: Any,
) -> IdempotencyProtocol:
    """根据类型与配置创建幂等拦截适配器实例。

    Args:
        adapter_type: 适配器类型 ("memory" 或 "redis")，默认 "memory"。
        redis_url: Redis 连接 URI（当 adapter_type 为 "redis" 时可选配置）。
        redis_client: 外部注入的 Redis 客户端（供测试打桩）。
        kwargs: 附加关键字参数。

    Returns:
        IdempotencyProtocol: 具备标准协议能力的幂等拦截适配器实例。

    Raises:
        AppError: adapter_type 不支持或配置参数错误。
    """
    normalized_type = adapter_type.strip().lower()

    if normalized_type == "memory":
        return MemoryIdempotencyAdapter()

    if normalized_type == "redis":
        return RedisIdempotencyAdapter(
            redis_url=redis_url,
            redis_client=redis_client,
            **kwargs,
        )

    raise AppError(
        error_code=30015,
        message=f"不支持的幂等拦截器类型: '{adapter_type}'，仅支持 'memory', 'redis'",
    )


__all__ = ["create_idempotency_adapter"]
