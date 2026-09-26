"""`doctor` 子命令：配置体检与真实链路前置校验。

输出内容（脱敏后）：
- Provider 矩阵：provider 名 + 密钥是否已配置（布尔），绝不含明文；
- 基础设施连通性：DB / Redis / MinIO 的 `reachable` 与 `detail`；
- 数据库 Alembic 迁移版本号；
- 真实链路配置缺口清单（含建议 `.env` 键名与期望形态）。

退出码契约：
- 非 `--require-real`：始终 `0`，仅报告；
- `--require-real` 且存在 Provider/配置缺口：`EXIT_CONFIG(3)`；
- `--require-real` 且基础设施不可达：`EXIT_INFRA(4)`；
- 全部合规：`0`。
"""

import argparse
from typing import Any

from app.cli.commands import GLOBAL_OPTIONS_PARENT
from app.cli.context import CliContext
from app.cli.errors import EXIT_CONFIG, EXIT_INFRA, EXIT_OK
from app.cli.report import Reporter, redact_url

INFRA_COMPONENT_LABELS: dict[str, str] = {
    "database": "数据库 (PostgreSQL)",
    "redis": "Redis",
    "minio": "对象存储 (MinIO/S3)",
}
"""基础设施组件的中文展示名。"""


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """注册 `doctor` 子命令。

    Args:
        subparsers: 顶层子命令解析器集合。
    """
    parser = subparsers.add_parser(
        "doctor",
        parents=[GLOBAL_OPTIONS_PARENT],
        help="配置体检：Provider 矩阵 + 基础设施连通性 + 迁移版本",
        description="检查真实 Provider 配置、基础设施连通性与数据库迁移版本（输出脱敏）。",
    )
    parser.add_argument(
        "--require-real",
        action="store_true",
        help="强制要求真实 Provider 链路；检测到缺口或基础设施不可达时以 3/4 退出。",
    )
    parser.set_defaults(handler=handle)


def handle(args: argparse.Namespace, context: CliContext, reporter: Reporter) -> int:
    """执行配置体检并按退出码契约返回。

    Args:
        args: 解析后的命令参数（含 `require_real`）。
        context: CLI 执行上下文。
        reporter: 结构化/人类可读输出器。

    Returns:
        int: 退出码。
    """
    require_real = bool(getattr(args, "require_real", False))
    gaps = context.assert_real_providers()
    infra = context.probe_infra()
    unreachable = [name for name, info in infra.items() if not info.get("reachable")]

    payload: dict[str, Any] = {
        "command": "doctor",
        "require_real": require_real,
        "allow_fake": context.allow_fake,
        "settings": {
            "env": context.settings.env,
            "database_url": redact_url(context.db_url),
        },
        "providers": context.provider_matrix(),
        "infrastructure": infra,
        "database_revision": context.db_revision(),
        "gaps": [gap.to_dict() for gap in gaps],
        "status": "ok" if not gaps and not unreachable else "degraded",
    }
    reporter.emit(payload)

    if not require_real:
        return EXIT_OK

    if gaps:
        reporter.info(f"真实链路配置缺口 {len(gaps)} 项，请按 gaps[].env_key 补齐后重试。")
        return EXIT_CONFIG

    if unreachable:
        labels = "、".join(INFRA_COMPONENT_LABELS.get(name, name) for name in unreachable)
        reporter.info(f"基础设施不可达：{labels}，请检查服务与连接配置。")
        return EXIT_INFRA

    return EXIT_OK


__all__ = ["handle", "register"]
