"""智练 Headless CLI 顶层入口与参数装配。

用法（工作目录 backend/）：

    python -m app.cli <command> [subcommand] [options]

全局参数：
- `--json`：结构化 JSON 输出（供 AI 解析）；
- `--db-url <url>`：覆盖数据库连接串（默认取 AppSettings）；
- `--allow-fake`：仅离线测试使用，允许 fake/memory Provider；
- `--log-level <level>`：日志级别，默认 INFO。

统一异常处理：
- `CliError`：按携带的 `exit_code` 退出，并打印 `message` + `remediation`；
- 其余未预期异常：记录日志并返回 `EXIT_RUNTIME(1)`。
"""

import argparse
import logging
from collections.abc import Sequence
from typing import Any

from app.cli import smoke as smoke_commands
from app.cli.commands import CommandHandler
from app.cli.commands import auth as auth_commands
from app.cli.commands import db as db_commands
from app.cli.commands import doctor as doctor_commands
from app.cli.commands import grading as grading_commands
from app.cli.commands import material as material_commands
from app.cli.commands import practice as practice_commands
from app.cli.commands import question as question_commands
from app.cli.context import CliContext
from app.cli.errors import EXIT_RUNTIME, CliError
from app.cli.report import Reporter

LOGGER = logging.getLogger("app.cli")


def build_parser() -> argparse.ArgumentParser:
    """构建顶层参数解析器并注册全部子命令。

    Returns:
        argparse.ArgumentParser: 已装配全局参数与子命令的解析器。
    """
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="智练 Headless CLI：真实链路闭环验证与配置体检。",
    )
    parser.add_argument("--json", action="store_true", help="以结构化 JSON 输出结果。")
    parser.add_argument("--db-url", default=None, help="覆盖数据库连接串（默认取配置）。")
    parser.add_argument(
        "--allow-fake",
        action="store_true",
        help="允许 fake/memory Provider（仅离线自测，真实链路模式下勿用）。",
    )
    parser.add_argument("--log-level", default="INFO", help="日志级别（默认 INFO）。")

    subparsers = parser.add_subparsers(dest="command", required=True)
    doctor_commands.register(subparsers)
    db_commands.register(subparsers)
    auth_commands.register(subparsers)
    material_commands.register(subparsers)
    question_commands.register(subparsers)
    practice_commands.register(subparsers)
    grading_commands.register(subparsers)
    smoke_commands.register(subparsers)
    return parser


def _configure_logging(level: str) -> None:
    """配置根日志器级别与格式。

    Args:
        level: 日志级别名称（如 INFO / DEBUG）。

    Raises:
        ValueError: 级别名称非法。
    """
    logging.basicConfig(
        level=level.upper(),
        format="%(levelname)s %(name)s: %(message)s",
        force=True,
    )


def _report_cli_error(error: CliError, reporter: Reporter) -> int:
    """输出可预期 CLI 错误并返回其退出码。

    Args:
        error: 携带退出码与修复指引的 CLI 错误。
        reporter: 输出器。

    Returns:
        int: `error.exit_code`。
    """
    payload: dict[str, Any] = {"error": error.message, "exit_code": error.exit_code}
    if error.remediation:
        payload["remediation"] = error.remediation
    if error.details:
        payload["details"] = error.details

    if reporter.json_mode:
        reporter.emit(payload)
    else:
        print(f"错误: {error.message}")
        if error.remediation:
            print(f"修复建议: {error.remediation}")
    return error.exit_code


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 入口：解析参数、装配上下文并分发至子命令处理器。

    Args:
        argv: 参数序列；缺省读取 `sys.argv[1:]`。

    Returns:
        int: 进程退出码。
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    reporter = Reporter(json_mode=bool(getattr(args, "json", False)))

    try:
        _configure_logging(str(args.log_level))
        context = CliContext.create(
            db_url=args.db_url,
            allow_fake=bool(getattr(args, "allow_fake", False)),
        )
        handler: CommandHandler = args.handler
        return handler(args, context, reporter)
    except CliError as error:
        return _report_cli_error(error, reporter)
    except KeyboardInterrupt:
        LOGGER.warning("CLI 被用户中断。")
        return EXIT_RUNTIME
    except Exception as error:
        LOGGER.exception("CLI 执行未预期异常。")
        if reporter.json_mode:
            reporter.emit({"error": str(error), "exit_code": EXIT_RUNTIME})
        else:
            print(f"未预期错误: {error}")
        return EXIT_RUNTIME


__all__ = ["build_parser", "main"]
