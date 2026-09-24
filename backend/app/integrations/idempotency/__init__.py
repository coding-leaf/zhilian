"""分布式幂等拦截适配层包入口。

严格遵循 AGENTS.md 规范：
- 导出规范协议、数据契约、适配器实现与工厂方法；
- __all__ 保持严格 ASCII 字典序。
"""

from app.integrations.idempotency.factory import create_idempotency_adapter
from app.integrations.idempotency.memory import MemoryIdempotencyAdapter
from app.integrations.idempotency.protocol import (
    IdempotencyProtocol,
    IdempotencyRecord,
    build_idempotency_storage_key,
    validate_idempotency_key,
)
from app.integrations.idempotency.redis import RedisIdempotencyAdapter

__all__ = [
    "IdempotencyProtocol",
    "IdempotencyRecord",
    "MemoryIdempotencyAdapter",
    "RedisIdempotencyAdapter",
    "build_idempotency_storage_key",
    "create_idempotency_adapter",
    "validate_idempotency_key",
]
