"""`queue` 子命令：后台任务滞留只读巡检（AC-9 / design.md 第 19 条）。

子命令：
- `queue stalled [--older-than-minutes N] [--limit N]`：只读列出长期停留在
  「判题中」(`practices.status='submitted'`) 与解析中间态 (`material_versions`)
  的业务记录，用于定位 RQ worker 未消费、进程重启或任务悬挂导致的滞留。

设计约束：
- **只读**：本命令绝不回写业务状态，避免绕过用户可见的恢复入口；
- 恢复仍由用户可操作入口完成：`POST /practices/{id}/regrade`（判题重试）与
  `POST /materials/{id}/retry`（解析重试）；
- 不探测 Redis / worker 存活：那需要绕过 `QueueProtocol` 边界直接读 RQ 注册表，
  留待后续单独设计。

退出码契约：无滞留 `0`；存在滞留记录 `2`；数据库不可达 `4`。
"""

import argparse
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import bindparam, text

from app.cli.commands import GLOBAL_OPTIONS_PARENT
from app.cli.context import CliContext
from app.cli.errors import EXIT_ASSERTION, EXIT_INFRA, EXIT_OK
from app.cli.report import Reporter
from app.models.material import ParseStatus
from app.models.practice import PracticeStatus

DEFAULT_OLDER_THAN_MINUTES = 15
"""默认滞留判定阈值（分钟），与 RQ 任务超时/退避量级对齐。"""

DEFAULT_LIMIT = 20
"""单类滞留记录默认返回条数上限。"""

STALLED_PARSE_STATUSES: tuple[str, ...] = (
    ParseStatus.QUEUED.value,
    ParseStatus.PARSING_DOC.value,
    ParseStatus.OCR_PROCESSING.value,
    ParseStatus.EXTRACTING_KNOWLEDGE.value,
    ParseStatus.AUDITING_KNOWLEDGE.value,
    ParseStatus.EMBEDDING_GENERATION.value,
)
"""判定为「解析处理中」的版本细分状态集合（与 MaterialService 状态机一致）。"""


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """注册 `queue` 子命令及其动作。

    Args:
        subparsers: 顶层子命令解析器集合。
    """
    parser = subparsers.add_parser(
        "queue",
        parents=[GLOBAL_OPTIONS_PARENT],
        help="后台任务巡检（stalled）",
        description="只读巡检长期滞留的判题/解析业务记录，用于定位悬挂的后台任务。",
    )
    actions = parser.add_subparsers(dest="queue_action", required=True)

    stalled = actions.add_parser(
        "stalled",
        parents=[GLOBAL_OPTIONS_PARENT],
        help="列出长期未推进的判题与解析记录",
    )
    stalled.add_argument(
        "--older-than-minutes",
        type=int,
        default=DEFAULT_OLDER_THAN_MINUTES,
        help=f"滞留阈值（分钟），默认 {DEFAULT_OLDER_THAN_MINUTES}。",
    )
    stalled.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"每类记录返回条数上限，默认 {DEFAULT_LIMIT}。",
    )
    stalled.set_defaults(handler=handle_stalled)


def _format_timestamp(value: Any) -> str | None:
    """把数据库返回的时间戳统一格式化为 ISO 字符串。

    原生 ``text()`` 查询在 SQLite 上返回裸字符串、在 PostgreSQL 上返回 ``datetime``，
    因此在边界处统一归一化，避免对返回值做隐式格式假设。

    Args:
        value: 数据库返回的时间戳原始值。

    Returns:
        str | None: ISO 字符串；空值返回 None。
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _query_stalled_practices(session: Any, cutoff: datetime, limit: int) -> list[dict[str, Any]]:
    """查询超过阈值仍停留在「判题中」的练习（只读）。"""
    rows = session.execute(
        text(
            "SELECT id, user_id, submitted_at FROM practices "
            "WHERE status = :status AND submitted_at IS NOT NULL AND submitted_at < :cutoff "
            "ORDER BY submitted_at ASC LIMIT :limit"
        ),
        {"status": PracticeStatus.SUBMITTED.value, "cutoff": cutoff, "limit": limit},
    ).all()
    return [
        {
            "practice_id": str(row[0]),
            "user_ref": str(row[1])[:8],
            "submitted_at": _format_timestamp(row[2]),
            "action": "POST /practices/{id}/regrade",
        }
        for row in rows
    ]


def _query_stalled_versions(session: Any, cutoff: datetime, limit: int) -> list[dict[str, Any]]:
    """查询超过阈值仍停留在解析中间态的资料版本（只读）。"""
    rows = session.execute(
        text(
            "SELECT id, material_id, user_id, parse_status, updated_at FROM material_versions "
            "WHERE parse_status IN :statuses AND updated_at < :cutoff "
            "ORDER BY updated_at ASC LIMIT :limit"
        ).bindparams(bindparam("statuses", expanding=True)),
        {
            "statuses": list(STALLED_PARSE_STATUSES),
            "cutoff": cutoff,
            "limit": limit,
        },
    ).all()
    return [
        {
            "version_id": str(row[0]),
            "material_id": str(row[1]),
            "user_ref": str(row[2])[:8],
            "parse_status": row[3],
            "updated_at": _format_timestamp(row[4]),
            "action": "POST /materials/{id}/retry",
        }
        for row in rows
    ]


def handle_stalled(args: argparse.Namespace, context: CliContext, reporter: Reporter) -> int:
    """执行滞留只读巡检并按退出码契约返回。

    Args:
        args: 解析后的命令参数（含 `older_than_minutes` / `limit`）。
        context: CLI 执行上下文。
        reporter: 结构化/人类可读输出器。

    Returns:
        int: 退出码；存在滞留记录时为 2，数据库不可达时为 4。
    """
    older_than_minutes = max(
        1, int(getattr(args, "older_than_minutes", DEFAULT_OLDER_THAN_MINUTES))
    )
    limit = max(1, int(getattr(args, "limit", DEFAULT_LIMIT)))
    cutoff = datetime.now(UTC) - timedelta(minutes=older_than_minutes)

    try:
        with context.container.get_session() as session:
            stalled_practices = _query_stalled_practices(session, cutoff, limit)
            stalled_versions = _query_stalled_versions(session, cutoff, limit)
    except Exception as exc:
        reporter.emit(
            {
                "command": "queue.stalled",
                "status": "infra_unreachable",
                "detail": str(exc)[:200],
            }
        )
        reporter.info("数据库不可达，无法巡检后台任务滞留记录。")
        return EXIT_INFRA

    total = len(stalled_practices) + len(stalled_versions)
    payload: dict[str, Any] = {
        "command": "queue.stalled",
        "older_than_minutes": older_than_minutes,
        "cutoff": cutoff.isoformat(),
        "limit": limit,
        "stalled_practices": stalled_practices,
        "stalled_versions": stalled_versions,
        "total": total,
        "status": "ok" if total == 0 else "stalled",
    }
    reporter.emit(payload)

    if total == 0:
        return EXIT_OK

    reporter.info(
        f"检出 {total} 条滞留记录（判题 {len(stalled_practices)} / 解析 {len(stalled_versions)}）；"
        "请确认 RQ worker 存活，并按每条记录的 action 引导用户重试。"
    )
    return EXIT_ASSERTION


__all__ = ["handle_stalled", "register"]
