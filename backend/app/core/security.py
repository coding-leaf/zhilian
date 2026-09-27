"""安全计算核心模块。

提供 JWT 双令牌签发、解码验签、令牌版本对比及结构化日志脱敏摘要计算纯函数。
严格遵循 AGENTS.md 规范：
- 纯函数计算核无状态，绝密脱敏红线严禁向日志或载荷中暴露业务与敏感明文；
- 常量具备明确依据注释；
- 行覆盖率门槛 >= 95%。
"""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from app.core.config import get_settings
from app.core.errors import AuthenticationError

# 依据：轻量级高频 HMAC-SHA256 签名，兼具计算能效与移动端传输开销，对齐工业通用基线
ALGORITHM: str = "HS256"

# 依据：软件需求规格说明书 NFR-13，2 小时有效窗口覆盖单次深度自主学习周期
ACCESS_TOKEN_EXPIRE_MINUTES: int = 120

# 依据：微信小程序移动端免登录无感刷新体验的最佳实践推荐窗口 (30 天)
REFRESH_TOKEN_EXPIRE_DAYS: int = 30


def get_secret_key(*, secret_key: str | None = None) -> str:
    """获取系统用于 JWT 签名的密钥。

    唯一真相源为强类型 Settings (`ZHILIAN_SECRET_KEY`)；显式入参仅用于测试注入，
    严禁绕过 Settings 读取裸环境变量，避免生产注入被静默忽略。

    Args:
        secret_key: 可选的显式密钥，优先级最高 (供测试注入)。

    Returns:
        str: 签名密钥。
    """
    if secret_key is not None:
        return secret_key
    return get_settings().secret_key.get_secret_value()


def create_access_token(
    user_id: uuid.UUID | str,
    token_version: int,
    expires_delta: timedelta | None = None,
    secret_key: str | None = None,
) -> str:
    """签发短效 Access Token。

    载荷严格限制为 6 个必要字段，严格禁止注入任何敏感业务数据：
    sub, type, token_version, exp, iat, jti。

    Args:
        user_id: 归属用户标识。
        token_version: 用户当前令牌版本号。
        expires_delta: 自定义过期时间间隔，为 None 时采用默认 2 小时。
        secret_key: 自定义签名密钥，为 None 时读取系统配置密钥。

    Returns:
        str: 编码后的 JWT 字符串。
    """
    now = datetime.now(UTC)
    if expires_delta is not None:
        expire_time = now + expires_delta
    else:
        expire_time = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    payload: dict[str, Any] = {
        "sub": str(user_id),
        "type": "access",
        "token_version": token_version,
        "iat": int(now.timestamp()),
        "exp": int(expire_time.timestamp()),
        "jti": str(uuid.uuid4()),
    }

    key = secret_key if secret_key is not None else get_secret_key()
    return jwt.encode(payload, key, algorithm=ALGORITHM)


def create_refresh_token(
    user_id: uuid.UUID | str,
    token_version: int,
    expires_delta: timedelta | None = None,
    secret_key: str | None = None,
) -> str:
    """签发长效 Refresh Token。

    用于客户端向刷新端点置换全新的 Access Token 和 Refresh Token。

    Args:
        user_id: 归属用户标识。
        token_version: 用户当前令牌版本号。
        expires_delta: 自定义过期时间间隔，为 None 时采用默认 30 天。
        secret_key: 自定义签名密钥，为 None 时读取系统配置密钥。

    Returns:
        str: 编码后的 JWT 字符串。
    """
    now = datetime.now(UTC)
    if expires_delta is not None:
        expire_time = now + expires_delta
    else:
        expire_time = now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    payload: dict[str, Any] = {
        "sub": str(user_id),
        "type": "refresh",
        "token_version": token_version,
        "iat": int(now.timestamp()),
        "exp": int(expire_time.timestamp()),
        "jti": str(uuid.uuid4()),
    }

    key = secret_key if secret_key is not None else get_secret_key()
    return jwt.encode(payload, key, algorithm=ALGORITHM)


def decode_token(
    token: str,
    expected_type: str | None = None,
    secret_key: str | None = None,
) -> dict[str, Any]:
    """解码并校验 JWT 令牌有效性。

    校验签名、过期时间、必填载荷字段以及令牌类型匹配性。

    Args:
        token: 待解码的 JWT 字符串。
        expected_type: 期望的令牌类型 ("access" 或 "refresh")。
        secret_key: 解码所用密钥，为 None 时使用系统配置密钥。

    Returns:
        dict[str, Any]: 解码后的有效载荷字典。

    Raises:
        AuthenticationError: 当令牌格式错误、签名损坏、过期、缺失字段或类型不符时。
    """
    key = secret_key if secret_key is not None else get_secret_key()

    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            key,
            algorithms=[ALGORITHM],
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError(
            message="身份认证失败: 访问凭证已过期，请重新登录",
            details={"reason": "token_expired"},
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError(
            message="身份认证失败: 凭证签名无效或格式损坏",
            details={"reason": "token_invalid"},
        ) from exc

    token_type = payload.get("type")
    if expected_type is not None and token_type != expected_type:
        raise AuthenticationError(
            message=f"令牌类型错误: 期望 {expected_type} 令牌，实际为 {token_type}",
            details={"expected_type": expected_type, "actual_type": token_type},
        )

    if not payload.get("sub"):
        raise AuthenticationError(
            message="令牌载荷不完整: 缺失用户标识 (sub)",
            details={"reason": "missing_sub"},
        )

    if payload.get("token_version") is None:
        raise AuthenticationError(
            message="令牌载荷不完整: 缺失令牌版本号 (token_version)",
            details={"reason": "missing_token_version"},
        )

    return payload


def verify_token_version(payload_version: int, current_version: int) -> bool:
    """核对令牌中携带的版本号与持久化存储中的当前版本号是否一致。

    用于毫秒级即时吊销用户历史所有已签发令牌。

    Args:
        payload_version: 令牌 Payload 中解析出的版本号。
        current_version: 用户实体在数据库中的当前最新版本号。

    Returns:
        bool: 若两者一致返回 True，否则返回 False。
    """
    return payload_version == current_version


def generate_user_ref(user_id: uuid.UUID | str) -> str:
    """计算结构化日志 8 要素专用的不可逆用户标识脱敏摘要。

    采用 SHA-256 计算用户 ID 字符串后截取前 8 位十六进制字符。
    绝密脱敏红线要求：日志中绝对严禁打印明文 user_id、OpenID 或手机号。

    Args:
        user_id: 用户唯一标识 UUID 或合法字符串。

    Returns:
        str: 恰好 8 位的十六进制不可逆脱敏摘要。
    """
    clean_user_id = str(user_id).strip()
    return hashlib.sha256(clean_user_id.encode("utf-8")).hexdigest()[:8]
