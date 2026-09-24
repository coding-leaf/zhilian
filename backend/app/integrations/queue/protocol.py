"""异步任务队列协议与数据契约定义模块。

严格遵循 AGENTS.md 规范：
- 适配层通过 Protocol 抽象接口与外部供应商解耦；
- 纯协议与值对象定义，无网络驱动依赖；
- 支持运行时类型检查与多态注入。
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from app.core.errors import QueueError

TaskHandler = Callable[[dict[str, Any]], Any]


@dataclass(frozen=True)
class TaskMessage:
    """异步任务消息载荷契约（不可变值对象）。"""

    task_id: str
    task_name: str
    payload: dict[str, Any]
    user_id: str
    priority: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.task_id or not self.task_id.strip():
            raise ValueError("task_id 不能为空")
        if not self.task_name or not self.task_name.strip():
            raise ValueError("task_name 不能为空")
        if not self.user_id or not self.user_id.strip():
            raise ValueError("user_id 不能为空")
        if self.priority < 0:
            raise ValueError("priority 必须大于等于 0")


@dataclass(frozen=True)
class TaskResult:
    """异步任务执行结果与状态追踪契约。"""

    task_id: str
    status: str  # "pending", "running", "success", "failed", "cancelled"
    result: Any = None
    error: str | None = None
    duration_ms: float = 0.0

    def __post_init__(self) -> None:
        valid_statuses = {"pending", "running", "success", "failed", "cancelled"}
        if self.status not in valid_statuses:
            raise ValueError(f"status '{self.status}' 不合法，可选值: {valid_statuses}")
        if self.duration_ms < 0:
            raise ValueError("duration_ms 不能为负数")


@runtime_checkable
class QueueProtocol(Protocol):
    """异步任务队列统一抽象协议。"""

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
            task_name: 任务名称（如 material_chunking, generate_questions）。
            payload: 任务参数字典。
            user_id: 提交用户/租户 ID（用于隔离保护）。
            task_id: 可选指定任务唯一标识，默认自动生成 UUIDv4。
            delay_seconds: 延迟执行时间（秒），默认 0。
            priority: 优先级，数值越大优先级越高。

        Returns:
            str: 任务唯一标识 task_id。

        Raises:
            QueueError: 入队失败或网络异常。
        """
        ...

    def get_status(self, task_id: str, user_id: str) -> TaskResult | None:
        """查询任务状态与执行结果（严格校验 user_id 租户归属）。

        Args:
            task_id: 任务唯一标识。
            user_id: 当前请求用户 ID。

        Returns:
            TaskResult | None: 任务结果对象，不存在返回 None。

        Raises:
            PermissionDeniedError: 非任务所有者查询时抛出。
            QueueError: 查询异常。
        """
        ...

    def cancel(self, task_id: str, user_id: str) -> bool:
        """取消处于排队中的任务。

        Args:
            task_id: 任务唯一标识。
            user_id: 当前请求用户 ID。

        Returns:
            bool: 成功取消返回 True；任务不存在或已进入 running/completed 返回 False。

        Raises:
            PermissionDeniedError: 非任务所有者取消时抛出。
            QueueError: 取消异常。
        """
        ...


def serialize_task_message(message: TaskMessage) -> str:
    """序列化任务消息为 JSON 格式字符串。

    Args:
        message: 待序列化的任务消息对象。

    Returns:
        str: JSON 格式字符串。
    """
    return json.dumps(
        {
            "task_id": message.task_id,
            "task_name": message.task_name,
            "payload": message.payload,
            "user_id": message.user_id,
            "priority": message.priority,
            "created_at": message.created_at.isoformat(),
        },
        ensure_ascii=False,
    )


def deserialize_task_message(data: str) -> TaskMessage:
    """反序列化 JSON 字符串为任务消息对象。

    Args:
        data: JSON 格式字符串。

    Returns:
        TaskMessage: 结构化任务消息对象。

    Raises:
        QueueError: 反序列化失败或缺少必须字段。
    """
    try:
        raw_data = json.loads(data)
        created_at_raw = raw_data.get("created_at")
        created_at = datetime.fromisoformat(created_at_raw) if created_at_raw else datetime.now(UTC)
        return TaskMessage(
            task_id=raw_data["task_id"],
            task_name=raw_data["task_name"],
            payload=raw_data.get("payload", {}),
            user_id=raw_data["user_id"],
            priority=raw_data.get("priority", 0),
            created_at=created_at,
        )
    except Exception as exception:
        raise QueueError(
            f"反序列化任务消息失败: {exception}",
            details={"raw_length": len(data)},
        ) from exception


__all__ = [
    "QueueProtocol",
    "TaskHandler",
    "TaskMessage",
    "TaskResult",
    "deserialize_task_message",
    "serialize_task_message",
]
