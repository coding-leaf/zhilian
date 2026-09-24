"""内存虚拟异步任务队列适配器实现模块。

严格遵循 AGENTS.md 规范：
- 专为单元测试与本地开发环境提供高性能内存 Fake 实现；
- 单元测试运行在网络绝对阻断环境下，零套接字连接；
- 并发安全（采用 threading.Lock 保护内部队列与状态字典）；
- 严格进行 user_id 租户隔离校验，禁止越权操作；
- 绝密脱敏保护：__repr__ 禁止打印载荷明文或用户敏感信息。
"""

import threading
import time
import uuid
from typing import Any

from app.core.errors import PermissionDeniedError
from app.integrations.queue.protocol import (
    QueueProtocol,
    TaskHandler,
    TaskMessage,
    TaskResult,
)


class MemoryQueueAdapter(QueueProtocol):
    """基于内存的并发安全虚拟任务队列适配器。"""

    def __init__(self, *, immediate_mode: bool = False) -> None:
        """初始化内存队列适配器。

        Args:
            immediate_mode: 是否开启即时同步执行模式，开启后入队即执行完成。
        """
        self._lock = threading.Lock()
        self._immediate_mode = immediate_mode
        self._queue: list[TaskMessage] = []
        self._tasks: dict[str, tuple[TaskMessage, TaskResult]] = {}
        self._handlers: dict[str, TaskHandler] = {}
        self._fault_injections: dict[str, Exception] = {}
        self._latency_seconds: float = 0.0

    def _check_hooks(self, operation: str) -> None:
        """触发延迟与故障注入钩子。

        Args:
            operation: 操作名称（如 "enqueue", "get_status", "cancel"）。

        Raises:
            Exception: 注入的模拟异常。
        """
        if self._latency_seconds > 0.0:
            time.sleep(self._latency_seconds)

        if operation in self._fault_injections:
            raise self._fault_injections[operation]

    def register_handler(self, task_name: str, handler: TaskHandler) -> None:
        """注册任务执行处理函数（主要用于单元测试与即时模式）。

        Args:
            task_name: 任务名称。
            handler: 处理回调纯函数。
        """
        with self._lock:
            self._handlers[task_name] = handler

    def set_fault_injection(self, operation: str, exception: Exception | None) -> None:
        """配置模拟故障注入。

        Args:
            operation: 操作标识（如 "enqueue", "get_status", "cancel"）。
            exception: 待抛出异常实例，传 None 表示清除故障。
        """
        with self._lock:
            if exception is None:
                self._fault_injections.pop(operation, None)
            else:
                self._fault_injections[operation] = exception

    def set_latency(self, seconds: float) -> None:
        """设置模拟调度延迟（秒）。

        Args:
            seconds: 延迟时长（秒）。
        """
        with self._lock:
            self._latency_seconds = max(0.0, seconds)

    def reset(self) -> None:
        """重置适配器内部所有状态（清理队列、任务与注入）。"""
        with self._lock:
            self._queue.clear()
            self._tasks.clear()
            self._handlers.clear()
            self._fault_injections.clear()
            self._latency_seconds = 0.0

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
            priority: 任务优先级。

        Returns:
            str: 任务唯一标识 task_id。

        Raises:
            QueueError: 入队失败或注入异常。
        """
        self._check_hooks("enqueue")

        resolved_task_id = (task_id or str(uuid.uuid4())).strip()
        message = TaskMessage(
            task_id=resolved_task_id,
            task_name=task_name,
            payload=payload,
            user_id=user_id,
            priority=priority,
        )

        with self._lock:
            if self._immediate_mode:
                start_time = time.perf_counter()
                handler = self._handlers.get(task_name)
                if handler is not None:
                    try:
                        handler_result = handler(payload)
                        duration_ms = (time.perf_counter() - start_time) * 1000.0
                        result = TaskResult(
                            task_id=resolved_task_id,
                            status="success",
                            result=handler_result,
                            duration_ms=duration_ms,
                        )
                    except Exception as exception:
                        duration_ms = (time.perf_counter() - start_time) * 1000.0
                        result = TaskResult(
                            task_id=resolved_task_id,
                            status="failed",
                            error=str(exception),
                            duration_ms=duration_ms,
                        )
                else:
                    duration_ms = (time.perf_counter() - start_time) * 1000.0
                    result = TaskResult(
                        task_id=resolved_task_id,
                        status="success",
                        result=None,
                        duration_ms=duration_ms,
                    )
                self._tasks[resolved_task_id] = (message, result)
            else:
                initial_result = TaskResult(
                    task_id=resolved_task_id,
                    status="pending",
                    result=None,
                )
                self._tasks[resolved_task_id] = (message, initial_result)
                self._queue.append(message)
                # 按优先级从高到低排序
                self._queue.sort(key=lambda item: item.priority, reverse=True)

        return resolved_task_id

    def process_next(self) -> TaskResult | None:
        """从队列中提取并执行下一个待处理任务（测试辅助函数）。

        Returns:
            TaskResult | None: 执行结果，队列为空返回 None。
        """
        with self._lock:
            if not self._queue:
                return None
            message = self._queue.pop(0)
            running_result = TaskResult(task_id=message.task_id, status="running")
            self._tasks[message.task_id] = (message, running_result)
            handler = self._handlers.get(message.task_name)

        start_time = time.perf_counter()
        if handler is not None:
            try:
                handler_result = handler(message.payload)
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                final_result = TaskResult(
                    task_id=message.task_id,
                    status="success",
                    result=handler_result,
                    duration_ms=duration_ms,
                )
            except Exception as exception:
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                final_result = TaskResult(
                    task_id=message.task_id,
                    status="failed",
                    error=str(exception),
                    duration_ms=duration_ms,
                )
        else:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            final_result = TaskResult(
                task_id=message.task_id,
                status="success",
                result=None,
                duration_ms=duration_ms,
            )

        with self._lock:
            self._tasks[message.task_id] = (message, final_result)

        return final_result

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
        self._check_hooks("get_status")

        with self._lock:
            entry = self._tasks.get(task_id)
            if entry is None:
                return None
            message, result = entry
            if message.user_id != user_id:
                raise PermissionDeniedError(
                    f"无权访问任务 {task_id}",
                    details={"task_id": task_id, "user_id": user_id},
                )
            return result

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
        self._check_hooks("cancel")

        with self._lock:
            entry = self._tasks.get(task_id)
            if entry is None:
                return False
            message, current_result = entry
            if message.user_id != user_id:
                raise PermissionDeniedError(
                    f"无权取消任务 {task_id}",
                    details={"task_id": task_id, "user_id": user_id},
                )

            if current_result.status != "pending":
                return False

            self._queue = [item for item in self._queue if item.task_id != task_id]
            cancelled_result = TaskResult(
                task_id=task_id,
                status="cancelled",
                duration_ms=current_result.duration_ms,
            )
            self._tasks[task_id] = (message, cancelled_result)
            return True

    def __repr__(self) -> str:
        """安全脱敏的字符串表示。"""
        with self._lock:
            count = len(self._tasks)
            pending_count = len(self._queue)
        return (
            f"<MemoryQueueAdapter total_tasks={count} "
            f"pending={pending_count} immediate_mode={self._immediate_mode}>"
        )


__all__ = ["MemoryQueueAdapter"]
