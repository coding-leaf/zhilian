"""`auth` 子命令：微信登录与用户画像查询。

子命令：
- `auth login --code <c> [--nickname <n>]`：登录/自动注册，输出 `user_id`；
  令牌仅输出是否已签发（`has_access_token` / `has_refresh_token`），**绝不输出明文**。
- `auth profile --user-id <uuid>`：输出用户画像。

退出码契约：
- 成功 `0`；
- 入参非法 `2`；
- 非真实 Provider 且未 `--allow-fake` `3`；
- 其余未预期异常由顶层统一处理为 `1`。
"""

import argparse
from typing import Any

from app.cli.commands import (
    GLOBAL_OPTIONS_PARENT,
    ensure_real_or_allowed,
    parse_uuid,
)
from app.cli.context import CliContext
from app.cli.errors import EXIT_OK
from app.cli.report import Reporter


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """注册 `auth` 子命令及其 login/profile 动作。

    Args:
        subparsers: 顶层子命令解析器集合。
    """
    parser = subparsers.add_parser(
        "auth",
        parents=[GLOBAL_OPTIONS_PARENT],
        help="鉴权与用户画像（login / profile）",
        description="通过微信 code 登录或查询用户画像。",
    )
    actions = parser.add_subparsers(dest="auth_action", required=True)

    login = actions.add_parser(
        "login",
        parents=[GLOBAL_OPTIONS_PARENT],
        help="微信登录或自动注册，返回 user_id",
    )
    login.add_argument("--code", required=True, help="微信小程序临时登录凭据 code。")
    login.add_argument("--nickname", default=None, help="可选昵称。")
    login.add_argument("--avatar-url", default=None, help="可选头像 URL。")
    login.set_defaults(handler=handle_login)

    profile = actions.add_parser(
        "profile",
        parents=[GLOBAL_OPTIONS_PARENT],
        help="查询用户画像",
    )
    profile.add_argument("--user-id", required=True, help="用户主键 UUID。")
    profile.set_defaults(handler=handle_profile)


def handle_login(args: argparse.Namespace, context: CliContext, reporter: Reporter) -> int:
    """执行 `auth login`。

    Args:
        args: 解析后的命令参数（须含 `code`）。
        context: CLI 执行上下文。
        reporter: 输出器。

    Returns:
        int: 成功返回 `EXIT_OK`。
    """
    ensure_real_or_allowed(context)
    with context.container.get_session() as session:
        auth_service = context.container.create_auth_service(session)
        user, tokens = auth_service.login_with_wechat(
            str(args.code),
            nickname=args.nickname,
            avatar_url=args.avatar_url,
        )
        payload: dict[str, Any] = {
            "command": "auth login",
            "status": "ok",
            "user_id": str(user.id),
            "nickname": user.nickname,
            "has_access_token": bool(tokens.access_token),
            "has_refresh_token": bool(tokens.refresh_token),
            "token_type": tokens.token_type,
            "expires_in": tokens.expires_in,
        }
    reporter.emit(payload)
    return EXIT_OK


def handle_profile(args: argparse.Namespace, context: CliContext, reporter: Reporter) -> int:
    """执行 `auth profile`。

    Args:
        args: 解析后的命令参数（须含 `user_id`）。
        context: CLI 执行上下文。
        reporter: 输出器。

    Returns:
        int: 成功返回 `EXIT_OK`。
    """
    ensure_real_or_allowed(context)
    user_id = parse_uuid(args.user_id, "--user-id")
    with context.container.get_session() as session:
        auth_service = context.container.create_auth_service(session)
        profile = auth_service.get_user_profile(user_id)
        payload: dict[str, Any] = {
            "command": "auth profile",
            "status": "ok",
            "user_id": str(profile.id),
            "nickname": profile.nickname,
            "avatar_url": profile.avatar_url,
            "created_at": profile.created_at,
        }
    reporter.emit(payload)
    return EXIT_OK


__all__ = ["handle_login", "handle_profile", "register"]
