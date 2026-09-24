"""异步任务队列适配层包入口。

严格遵循 AGENTS.md 规范：
- 导出规范协议、数据契约、适配器实现与工厂方法；
- __all__ 保持严格 ASCII 字典序。
"""

from app.integrations.queue.factory import create_queue_adapter
from app.integrations.queue.memory import MemoryQueueAdapter
from app.integrations.queue.protocol import (
    QueueProtocol,
    TaskHandler,
    TaskMessage,
    TaskResult,
    deserialize_task_message,
    serialize_task_message,
)
from app.integrations.queue.redis import RedisQueueAdapter

__all__ = [
    "MemoryQueueAdapter",
    "QueueProtocol",
    "RedisQueueAdapter",
    "TaskHandler",
    "TaskMessage",
    "TaskResult",
    "create_queue_adapter",
    "deserialize_task_message",
    "serialize_task_message",
]
