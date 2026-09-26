"""`grading` 子命令：整卷判题与学情诊断报告。

子命令：
- `grading grade --practice-id <uuid> [--user-id]`：执行整卷判题；
- `diagnosis report --practice-id <uuid> [--user-id]`：生成/获取学情诊断报告。

退出码契约：成功 `0`；断言/校验 `2`；非真实 Provider `3`。
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
    """注册 `grading` 与 `diagnosis` 子命令。

    Args:
        subparsers: 顶层子命令解析器集合。
    """
    grading = subparsers.add_parser(
        "grading",
        parents=[GLOBAL_OPTIONS_PARENT],
        help="整卷判题（grade）",
        description="对已完成交卷的练习执行整卷判题。",
    )
    actions = grading.add_subparsers(dest="grading_action", required=True)

    grade = actions.add_parser("grade", parents=[GLOBAL_OPTIONS_PARENT], help="整卷判题")
    grade.add_argument("--practice-id", required=True, help="练习主键 UUID。")
    grade.add_argument("--user-id", required=True, help="用户主键 UUID。")
    grade.set_defaults(handler=handle_grade)

    diagnosis = subparsers.add_parser(
        "diagnosis",
        parents=[GLOBAL_OPTIONS_PARENT],
        help="学情诊断（report）",
        description="生成并返回学情诊断报告。",
    )
    diagnosis_actions = diagnosis.add_subparsers(dest="diagnosis_action", required=True)

    report = diagnosis_actions.add_parser(
        "report",
        parents=[GLOBAL_OPTIONS_PARENT],
        help="生成学情诊断报告",
    )
    report.add_argument("--practice-id", required=True, help="练习主键 UUID。")
    report.add_argument("--user-id", required=True, help="用户主键 UUID。")
    report.set_defaults(handler=handle_diagnosis_report)


def handle_grade(args: argparse.Namespace, context: CliContext, reporter: Reporter) -> int:
    """执行 `grading grade`。

    Args:
        args: 解析后的命令参数（须含 `practice_id` / `user_id`）。
        context: CLI 执行上下文。
        reporter: 输出器。

    Returns:
        int: 成功返回 `EXIT_OK`。
    """
    ensure_real_or_allowed(context)
    user_id = parse_uuid(args.user_id, "--user-id")
    practice_id = parse_uuid(args.practice_id, "--practice-id")
    with context.container.get_session() as session:
        grading_service = context.container.create_grading_service(session)
        summary = grading_service.grade_practice_submission(practice_id, user_id)
        payload: dict[str, Any] = {
            "command": "grading grade",
            "status": "ok",
            "practice_id": str(summary.practice_id),
            "practice_status": summary.status,
            "total_score": summary.total_score,
            "max_score": summary.max_score,
            "total_items": summary.total_items,
            "graded_items": summary.graded_items,
            "pending_regrade_count": summary.pending_regrade_count,
        }
    reporter.emit(payload)
    return EXIT_OK


def handle_diagnosis_report(
    args: argparse.Namespace, context: CliContext, reporter: Reporter
) -> int:
    """执行 `diagnosis report`。

    Args:
        args: 解析后的命令参数（须含 `practice_id` / `user_id`）。
        context: CLI 执行上下文。
        reporter: 输出器。

    Returns:
        int: 成功返回 `EXIT_OK`。
    """
    ensure_real_or_allowed(context)
    user_id = parse_uuid(args.user_id, "--user-id")
    practice_id = parse_uuid(args.practice_id, "--practice-id")
    with context.container.get_session() as session:
        diagnosis_service = context.container.create_diagnosis_service(session)
        report = diagnosis_service.generate_diagnosis_report(user_id, practice_id)
        payload: dict[str, Any] = {
            "command": "diagnosis report",
            "status": "ok",
            "report_id": str(report.id),
            "practice_id": str(report.practice_id),
            "score_rate": report.score_rate,
            "total_questions": report.total_questions,
            "unanswered_count": report.unanswered_count,
            "wrong_count": report.wrong_count,
            "pending_regrade_count": report.pending_regrade_count,
            "weak_knowledge_point_count": len(report.weak_knowledge_points or []),
            "regressed_knowledge_point_count": len(report.regressed_knowledge_points or []),
            "suggestion_count": len(report.actionable_suggestions or []),
        }
    reporter.emit(payload)
    return EXIT_OK


__all__ = ["handle_diagnosis_report", "handle_grade", "register"]
