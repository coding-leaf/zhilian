"""Headless CLI 子命令实现包。

集中定义：
- 子命令处理器的统一签名契约 `CommandHandler`；
- 可在子命令任意位置出现的全局选项父解析器 `GLOBAL_OPTIONS_PARENT`；
- 跨子命令复用的入参校验、用户解析与真实 Provider 前置门禁。

关于父解析器：argparse 顶层 optional 无法出现在子命令之后，因此将
`--json` / `--db-url` / `--allow-fake` / `--log-level` 以 `default=SUPPRESS`
的父解析器形式注入每个子命令，保证 `python -m app.cli doctor --json` 可用，
同时不覆盖顶层已解析的取值。
"""

import argparse
import uuid
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.cli.context import CliContext
from app.cli.errors import EXIT_ASSERTION, EXIT_CONFIG, CliError
from app.cli.report import Reporter

CommandHandler = Callable[[argparse.Namespace, CliContext, Reporter], int]
"""子命令处理器签名：接收解析后的参数、执行上下文与输出器，返回退出码。"""


def build_global_options_parent() -> argparse.ArgumentParser:
    """构建承载全局选项的父解析器。

    Returns:
        argparse.ArgumentParser: `add_help=False` 且各选项默认 `SUPPRESS` 的父解析器。
    """
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    parent.add_argument("--db-url", default=argparse.SUPPRESS)
    parent.add_argument("--allow-fake", action="store_true", default=argparse.SUPPRESS)
    parent.add_argument("--log-level", default=argparse.SUPPRESS)
    return parent


GLOBAL_OPTIONS_PARENT = build_global_options_parent()
"""可复用的全局选项父解析器实例。"""


def parse_uuid(value: str | None, label: str) -> uuid.UUID:
    """将字符串解析为 UUID，失败时抛出退出码 2 的 CLI 校验错误。

    Args:
        value: 待解析字符串。
        label: 面向使用者的参数名（用于错误文案）。

    Returns:
        uuid.UUID: 解析结果。

    Raises:
        CliError: 值为空或格式非法（退出码 2）。
    """
    if not value:
        raise CliError(
            f"缺少必填参数 {label}",
            exit_code=EXIT_ASSERTION,
            remediation=f"请传入合法的 UUID，例如：{label} <uuid>。",
        )
    try:
        return uuid.UUID(value)
    except (ValueError, TypeError, AttributeError) as exc:
        raise CliError(
            f"参数 {label} 不是合法 UUID: {value}",
            exit_code=EXIT_ASSERTION,
            details={"value": value},
            remediation=f"请传入标准 UUIDv4 形式的 {label}。",
        ) from exc


def resolve_user_id(
    context: CliContext,
    session: Session,
    *,
    user_id: str | None,
    code: str | None = None,
) -> uuid.UUID:
    """解析租户用户：优先显式 `--user-id`，否则用 `--code` 登录换取。

    Args:
        context: CLI 执行上下文（用于装配 AuthService）。
        session: 当前数据库会话。
        user_id: 显式用户主键字符串。
        code: 可选微信登录 code，用于就地登录并返回其 user_id。

    Returns:
        uuid.UUID: 解析得到的用户主键。

    Raises:
        CliError: 两者均未提供（退出码 2）。
    """
    if user_id:
        return parse_uuid(user_id, "--user-id")
    if code:
        auth_service = context.container.create_auth_service(session)
        user, _ = auth_service.login_with_wechat(code)
        return user.id
    raise CliError(
        "必须提供 --user-id 或 --code 以确定操作主体。",
        exit_code=EXIT_ASSERTION,
        remediation="传入已存在的 --user-id <uuid>，或使用 --code <wechat_code> 就地登录。",
    )


def ensure_real_or_allowed(context: CliContext, *, require_ocr: bool = False) -> None:
    """真实 Provider 前置门禁：检测到 fake/memory/sqlite 回落即中止。

    Args:
        context: CLI 执行上下文。
        require_ocr: 是否强制要求真实 OCR Provider（仅图片链路需要）。

    Raises:
        CliError: 存在配置缺口且未显式 `--allow-fake`（退出码 3）。
    """
    gaps = context.assert_real_providers(require_ocr=require_ocr)
    if not gaps:
        return
    raise CliError(
        f"检测到 {len(gaps)} 项非真实 Provider 配置，已中止以避免伪造成功。",
        exit_code=EXIT_CONFIG,
        details={"gaps": [gap.to_dict() for gap in gaps]},
        remediation=(
            "请在 backend/.env 按 gaps[].env_key 补齐真实配置后重试（离线自测可传 --allow-fake）。"
        ),
    )


__all__ = [
    "GLOBAL_OPTIONS_PARENT",
    "CommandHandler",
    "build_global_options_parent",
    "ensure_real_or_allowed",
    "parse_uuid",
    "resolve_user_id",
]
