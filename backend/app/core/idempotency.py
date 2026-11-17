"""Idempotency key validation helpers shared across API and integration layers."""

import re

from app.core.errors import IdempotencyKeyInvalidError

_MAX_KEY_LENGTH: int = 128
_KEY_PATTERN: re.Pattern[str] = re.compile(r"^[a-zA-Z0-9_\-:\.]+$")


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


__all__ = ["validate_idempotency_key"]
