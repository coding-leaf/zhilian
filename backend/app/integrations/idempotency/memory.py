"""内存虚拟分布式幂等拦截适配器实现模块。

严格遵循 AGENTS.md 规范：
- 专为单元测试与本地开发环境提供高性能内存 Fake 实现；
- 单元测试运行在网络绝对阻断环境下，零套接字连接；
- 并发安全（采用 threading.Lock 保护内部记录映射）；
- 严格进行 user_id 租户隔离校验，防止越权；
- 绝密脱敏保护：__repr__ 禁止打印响应体或键名细节。
"""

import threading
import time
from collections.abc import Callable
from typing import Any

from app.core.errors import IdempotencyConflictError, PermissionDeniedError
from app.integrations.idempotency.protocol import (
    IdempotencyProtocol,
    IdempotencyRecord,
    build_idempotency_storage_key,
    validate_idempotency_key,
)


class MemoryIdempotencyAdapter(IdempotencyProtocol):
    """基于内存的线程安全分布式幂等拦截器适配器。"""

    def __init__(self) -> None:
        """初始化内存幂等拦截器。"""
        self._lock = threading.Lock()
        self._records: dict[str, IdempotencyRecord] = {}
        self._clock: Callable[[], float] = time.time
        self._fault_injections: dict[str, Exception] = {}

    def set_clock(self, clock_fn: Callable[[], float]) -> None:
        """配置模拟时钟提供者（用于 TTL 过期测试）。

        Args:
            clock_fn: 返回当前 Unix 时间戳浮点数的可调用对象。
        """
        with self._lock:
            self._clock = clock_fn

    def set_fault_injection(self, operation: str, exception: Exception | None) -> None:
        """配置模拟故障注入。

        Args:
            operation: 操作标识（如 "acquire_lock", "set_result"）。
            exception: 待抛出的异常，传 None 表示清除。
        """
        with self._lock:
            if exception is None:
                self._fault_injections.pop(operation, None)
            else:
                self._fault_injections[operation] = exception

    def _check_hooks(self, operation: str) -> None:
        """检查并触发注入的故障。

        Args:
            operation: 当前操作名称。
        """
        if operation in self._fault_injections:
            raise self._fault_injections[operation]

    def reset(self) -> None:
        """重置适配器内部所有状态。"""
        with self._lock:
            self._records.clear()
            self._fault_injections.clear()
            self._clock = time.time

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
            raise_on_conflict: 冲突时是否抛出异常。

        Returns:
            bool: 抢占成功返回 True；已被占用且 raise_on_conflict=False 返回 False。

        Raises:
            IdempotencyConflictError: 发生并发抢占冲突。
            PermissionDeniedError: 跨租户越权。
            IdempotencyKeyInvalidError: 幂等键格式不合法。
        """
        self._check_hooks("acquire_lock")
        clean_key = validate_idempotency_key(key)
        if not user_id or not user_id.strip():
            raise ValueError("user_id 不能为空")

        storage_key = build_idempotency_storage_key(user_id, clean_key)

        with self._lock:
            current_time = self._clock()
            existing_record = self._records.get(storage_key)

            if existing_record is not None:
                if current_time >= existing_record.expire_at:
                    self._records.pop(storage_key, None)
                else:
                    if existing_record.user_id != user_id:
                        raise PermissionDeniedError(
                            f"无权操作幂等键: {clean_key}",
                            details={"key": clean_key, "user_id": user_id},
                        )
                    if raise_on_conflict:
                        raise IdempotencyConflictError(
                            f"请求正在并发处理中，请勿重复提交: {clean_key}",
                            details={"key": clean_key, "user_id": user_id},
                        )
                    return False

            record = IdempotencyRecord(
                key=clean_key,
                user_id=user_id,
                status="LOCKED",
                result=None,
                locked_at=current_time,
                expire_at=current_time + ttl_seconds,
            )
            self._records[storage_key] = record
            return True

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
            PermissionDeniedError: 跨租户越权。
            IdempotencyKeyInvalidError: 幂等键非法。
        """
        self._check_hooks("set_result")
        clean_key = validate_idempotency_key(key)
        if not user_id or not user_id.strip():
            raise ValueError("user_id 不能为空")

        storage_key = build_idempotency_storage_key(user_id, clean_key)

        with self._lock:
            current_time = self._clock()
            existing_record = self._records.get(storage_key)
            if existing_record is not None and existing_record.user_id != user_id:
                raise PermissionDeniedError(
                    f"无权操作幂等键: {clean_key}",
                    details={"key": clean_key, "user_id": user_id},
                )

            locked_at = existing_record.locked_at if existing_record is not None else current_time
            completed_record = IdempotencyRecord(
                key=clean_key,
                user_id=user_id,
                status="COMPLETED",
                result=response_data,
                locked_at=locked_at,
                expire_at=current_time + ttl_seconds,
            )
            self._records[storage_key] = completed_record

    def get_result(self, key: str, user_id: str) -> dict[str, Any] | None:
        """获取已成功完成的幂等请求响应快照。

        Args:
            key: 幂等键。
            user_id: 租户用户 ID。

        Returns:
            dict[str, Any] | None: 历史响应快照，未完成或不存在返回 None。

        Raises:
            PermissionDeniedError: 跨租户越权。
            IdempotencyKeyInvalidError: 幂等键非法。
        """
        self._check_hooks("get_result")
        clean_key = validate_idempotency_key(key)
        if not user_id or not user_id.strip():
            raise ValueError("user_id 不能为空")

        storage_key = build_idempotency_storage_key(user_id, clean_key)

        with self._lock:
            current_time = self._clock()
            existing_record = self._records.get(storage_key)
            if existing_record is None:
                return None

            if current_time >= existing_record.expire_at:
                self._records.pop(storage_key, None)
                return None

            if existing_record.user_id != user_id:
                raise PermissionDeniedError(
                    f"无权访问幂等键: {clean_key}",
                    details={"key": clean_key, "user_id": user_id},
                )

            if existing_record.status == "COMPLETED":
                return existing_record.result

            return None

    def release_lock(self, key: str, user_id: str) -> None:
        """业务执行失败或异常退出时，主动释放正在处理中的幂等锁。

        Args:
            key: 幂等键。
            user_id: 租户用户 ID。

        Raises:
            PermissionDeniedError: 跨租户越权。
            IdempotencyKeyInvalidError: 幂等键非法。
        """
        self._check_hooks("release_lock")
        clean_key = validate_idempotency_key(key)
        if not user_id or not user_id.strip():
            raise ValueError("user_id 不能为空")

        storage_key = build_idempotency_storage_key(user_id, clean_key)

        with self._lock:
            existing_record = self._records.get(storage_key)
            if existing_record is not None:
                if existing_record.user_id != user_id:
                    raise PermissionDeniedError(
                        f"无权释放幂等键: {clean_key}",
                        details={"key": clean_key, "user_id": user_id},
                    )
                if existing_record.status == "LOCKED":
                    self._records.pop(storage_key, None)

    def __repr__(self) -> str:
        """安全脱敏的字符串表示。"""
        with self._lock:
            active_count = len(self._records)
        return f"<MemoryIdempotencyAdapter active_records={active_count}>"


__all__ = ["MemoryIdempotencyAdapter"]
