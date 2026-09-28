"""异步任务队列适配器工厂模块。

严格遵循 AGENTS.md 规范：
- 根据类型分发创建符合 QueueProtocol 契约的适配器实例；
- 单元测试与离线环境默认分发 MemoryQueueAdapter，具备零外部网络依赖特性；
- 生产环境支持创建 RedisQueueAdapter。
"""

from typing import Any

from app.core.errors import QueueError
from app.integrations.queue.memory import MemoryQueueAdapter
from app.integrations.queue.protocol import QueueProtocol
from app.integrations.queue.rq_adapter import RQQueueAdapter


def create_queue_adapter(
    adapter_type: str = "memory",
    *,
    redis_url: str | None = None,
    redis_client: Any | None = None,
    immediate_mode: bool = False,
    **kwargs: Any,
) -> QueueProtocol:
    """根据类型与配置创建任务队列适配器实例。

    Args:
        adapter_type: 队列类型 ("memory" 或 "redis")，默认 "memory"。
        redis_url: Redis 连接 URI（当 adapter_type 为 "redis" 时可选配置）。
        redis_client: 外部注入的 Redis 客户端（供测试打桩）。
        immediate_mode: 是否开启即时同步执行模式（仅 memory 生效）。
        kwargs: 附加关键字参数。

    Returns:
        QueueProtocol: 具备标准协议能力的任务队列适配器实例。

    Raises:
        QueueError: adapter_type 不支持或配置参数错误。
    """
    normalized_type = adapter_type.strip().lower()

    if normalized_type == "memory":
        return MemoryQueueAdapter(immediate_mode=immediate_mode)

    if normalized_type == "redis":
        return RQQueueAdapter(
            redis_url=redis_url,
            redis_client=redis_client,
            **kwargs,
        )

    raise QueueError(f"不支持的任务队列类型: '{adapter_type}'，仅支持 'memory', 'redis'")


__all__ = ["create_queue_adapter"]
