"""分布式幂等拦截器协议与数据契约定义模块。

严格遵循 AGENTS.md 规范：
- 适配层通过 Protocol 抽象接口与外部实现解耦；
- 纯协议与值对象定义，提供纯函数式 Key 格式与租户存储前缀校验；
- 支持运行时类型检查与多态注入。
"""

import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.core.errors import IdempotencyKeyInvalidError

_MAX_KEY_LENGTH: int = 128
_KEY_PATTERN: re.Pattern[str] = re.compile(r"^[a-zA-Z0-9_\-:\.]+$")


@dataclass(frozen=True)
class IdempotencyRecord:
    """幂等执行记录值对象契约。"""

    key: str
    user_id: str
    status: str  # "LOCKED", "COMPLETED"
    result: dict[str, Any] | None = None
    locked_at: float = field(default_factory=time.time)
    expire_at: float = 0.0

    def __post_init__(self) -> None:
        if not self.key or not self.key.strip():
            raise ValueError("key 不能为空")
        if not self.user_id or not self.user_id.strip():
            raise ValueError("user_id 不能为空")
        normalized_status = self.status.upper()
        if normalized_status not in ("LOCKED", "COMPLETED"):
            raise ValueError(f"status '{self.status}' 不合法，可选值: 'LOCKED', 'COMPLETED'")


@runtime_checkable
class IdempotencyProtocol(Protocol):
    """分布式幂等拦截器抽象协议。"""

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
            key: 幂等键（客户端上报的 UUIDv4 或业务唯一定位标识）。
            user_id: 关联租户用户 ID。
            ttl_seconds: 锁最大持有租期（秒），防止死锁，默认 60s。
            raise_on_conflict: 冲突时是否直接抛出 IdempotencyConflictError，默认 True。

        Returns:
            bool: 抢占成功返回 True；已被占用且 raise_on_conflict=False 时返回 False。

        Raises:
            IdempotencyConflictError: 当已被抢占且 raise_on_conflict=True 时抛出。
            IdempotencyKeyInvalidError: 当 key 格式非法或为空时抛出。
        """
        ...

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
            response_data: 待缓存的结构化响应体数据。
            ttl_seconds: 快照保留时长（秒），默认 86400 (24 小时)。

        Raises:
            IdempotencyKeyInvalidError: key 非法。
        """
        ...

    def get_result(self, key: str, user_id: str) -> dict[str, Any] | None:
        """获取已成功完成的幂等请求响应快照（回放）。

        Args:
            key: 幂等键。
            user_id: 租户用户 ID。

        Returns:
            dict[str, Any] | None: 命中的历史响应快照，未完成或不存在时返回 None。

        Raises:
            IdempotencyKeyInvalidError: key 非法。
        """
        ...

    def release_lock(self, key: str, user_id: str) -> None:
        """业务执行失败或异常退出时，主动释放正在处理中的幂等锁，允许后续重试。

        Args:
            key: 幂等键。
            user_id: 租户用户 ID。

        Raises:
            IdempotencyKeyInvalidError: key 非法。
        """
        ...


def validate_idempotency_key(key: str) -> str:
    """校验幂等键格式合法性并返回去除首尾空格后的规范键。

    Args:
        key: 待校验的幂等键。

    Returns:
        str: 校验合规的幂等键。

    Raises:
        IdempotencyKeyInvalidError: 格式不合法、超长或为空。
    """
    if not isinstance(key, str):
        raise IdempotencyKeyInvalidError("幂等键必须为字符串")

    trimmed_key = key.strip()
    if not trimmed_key:
        raise IdempotencyKeyInvalidError("幂等键不能为空")

    if len(trimmed_key) > _MAX_KEY_LENGTH:
        raise IdempotencyKeyInvalidError(
            f"幂等键长度不能超过 {_MAX_KEY_LENGTH} 字符，当前长度: {len(trimmed_key)}",
            details={"length": len(trimmed_key)},
        )

    if not _KEY_PATTERN.match(trimmed_key):
        raise IdempotencyKeyInvalidError(
            "幂等键包含非法字符，仅允许字母、数字、连字符、下划线、冒号与点号",
            details={"key": trimmed_key},
        )

    return trimmed_key


def build_idempotency_storage_key(user_id: str, key: str) -> str:
    """构建带多租户隔离前缀的幂等存储键。

    Args:
        user_id: 用户/租户 ID。
        key: 幂等键。

    Returns:
        str: 带租户前缀的组合存储键。
    """
    return f"user:{user_id}:idempotency:{key}"


__all__ = [
    "IdempotencyProtocol",
    "IdempotencyRecord",
    "build_idempotency_storage_key",
    "validate_idempotency_key",
]
