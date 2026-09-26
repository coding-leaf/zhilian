"""`db` 子命令：Alembic 迁移升级与受保护的破坏性重置。

子命令：
- `db upgrade`：将数据库迁移至 `head`；
- `db reset --yes`：先 `downgrade base` 再 `upgrade head`，彻底重建结构（破坏性，需显式确认）。

实现复用 Alembic 编程 API（`alembic.config.Config` + `alembic.command`），
`script_location` 固定指向 backend/migrations，并通过环境变量将当前生效的连接串
透传给 `migrations/env.py`（该文件优先读取 AppSettings）。
"""

import argparse
import os
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.cli.commands import GLOBAL_OPTIONS_PARENT
from app.cli.context import CliContext
from app.cli.errors import EXIT_OK, EXIT_RUNTIME, CliError
from app.cli.report import Reporter, redact_url
from app.core.config import get_settings

BACKEND_ROOT = Path(__file__).resolve().parents[3]
"""backend/ 根目录（app/cli/commands/db.py -> 上溯 3 层）。"""

ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"
"""Alembic 配置文件绝对路径。"""

MIGRATIONS_DIR = BACKEND_ROOT / "migrations"
"""Alembic 迁移脚本目录绝对路径。"""


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """注册 `db` 子命令及其 upgrade/reset 动作。

    Args:
        subparsers: 顶层子命令解析器集合。
    """
    parser = subparsers.add_parser(
        "db",
        parents=[GLOBAL_OPTIONS_PARENT],
        help="数据库迁移管理（upgrade / reset）",
        description="执行 Alembic 迁移升级，或受保护的破坏性结构重建。",
    )
    actions = parser.add_subparsers(dest="db_action", required=True)

    upgrade = actions.add_parser(
        "upgrade",
        parents=[GLOBAL_OPTIONS_PARENT],
        help="迁移至最新版本 (head)",
    )
    upgrade.set_defaults(handler=handle_upgrade)

    reset = actions.add_parser(
        "reset",
        parents=[GLOBAL_OPTIONS_PARENT],
        help="破坏性：清空并重建数据库结构",
    )
    reset.add_argument(
        "--yes",
        action="store_true",
        help="显式确认执行破坏性重置（缺失时命令拒绝执行）。",
    )
    reset.set_defaults(handler=handle_reset)


def _configure_alembic(db_url: str) -> Config:
    """构造指向当前数据库连接的 Alembic 配置。

    `migrations/env.py` 优先读取 `AppSettings.db.db_url`，因此这里通过设置
    `ZHILIAN_DB__DB_URL` 环境变量并清空配置缓存，确保 `--db-url` 覆盖生效。

    Args:
        db_url: 当前生效的数据库连接串。

    Returns:
        Config: 已定位 `script_location` 的 Alembic 配置对象。
    """
    os.environ["ZHILIAN_DB__DB_URL"] = db_url
    get_settings.cache_clear()

    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", db_url)
    return config


def handle_upgrade(args: argparse.Namespace, context: CliContext, reporter: Reporter) -> int:
    """执行 `db upgrade`：迁移至 head。

    Args:
        args: 解析后的命令参数（未使用）。
        context: CLI 执行上下文。
        reporter: 输出器。

    Returns:
        int: 成功返回 `EXIT_OK`。
    """
    del args
    config = _configure_alembic(context.db_url)
    command.upgrade(config, "head")
    reporter.emit(
        {
            "command": "db upgrade",
            "status": "ok",
            "database_url": redact_url(context.db_url),
            "revision": context.db_revision(),
        }
    )
    return EXIT_OK


def handle_reset(args: argparse.Namespace, context: CliContext, reporter: Reporter) -> int:
    """执行 `db reset`：破坏性重建数据库结构。

    Args:
        args: 解析后的命令参数（须含 `yes`）。
        context: CLI 执行上下文。
        reporter: 输出器。

    Returns:
        int: 成功返回 `EXIT_OK`。

    Raises:
        CliError: 未传入 `--yes` 时拒绝执行。
    """
    if not bool(getattr(args, "yes", False)):
        raise CliError(
            "db reset 为破坏性操作，将清空并重建全部表结构，必须显式传入 --yes 确认。",
            exit_code=EXIT_RUNTIME,
            remediation="如确认执行，请重新运行：python -m app.cli db reset --yes",
        )

    reporter.info("警告：正在执行破坏性重置（downgrade base -> upgrade head）。")
    config = _configure_alembic(context.db_url)
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    reporter.emit(
        {
            "command": "db reset",
            "status": "ok",
            "database_url": redact_url(context.db_url),
            "revision": context.db_revision(),
        }
    )
    return EXIT_OK


__all__ = ["handle_reset", "handle_upgrade", "register"]
