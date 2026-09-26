"""`practice` 子命令：建练习、逐题作答与交卷。

子命令：
- `practice create --user-id <uuid> --question-ids <csv> [--material-id <uuid>]`：
  依据题目集合反推知识点与资料，创建练习会话；
- `practice answer --practice-id <uuid> --question-id <uuid> --answer <text> [--user-id]`：
  暂存作答；
- `practice submit --practice-id <uuid> [--answers <json>] [--user-id]`：交卷（可选批量作答）。

退出码契约：成功 `0`；断言/校验 `2`；非真实 Provider `3`。
"""

import argparse
import json
import uuid
from typing import Any

from app.cli.commands import (
    GLOBAL_OPTIONS_PARENT,
    ensure_real_or_allowed,
    parse_uuid,
)
from app.cli.context import CliContext
from app.cli.errors import EXIT_ASSERTION, EXIT_OK, CliError
from app.cli.report import Reporter
from app.services.practice import (
    CreatePracticeOptions,
    PracticeAssemblyMode,
)


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """注册 `practice` 子命令及其动作。

    Args:
        subparsers: 顶层子命令解析器集合。
    """
    parser = subparsers.add_parser(
        "practice",
        parents=[GLOBAL_OPTIONS_PARENT],
        help="练习会话（create / answer / submit）",
        description="创建练习、暂存作答并交卷。",
    )
    actions = parser.add_subparsers(dest="practice_action", required=True)

    create = actions.add_parser("create", parents=[GLOBAL_OPTIONS_PARENT], help="创建练习")
    create.add_argument("--user-id", required=True, help="用户主键 UUID。")
    create.add_argument("--question-ids", required=True, help="题目 UUID CSV。")
    create.add_argument("--material-id", default=None, help="可选资料主键 UUID。")
    create.add_argument("--title", default=None, help="可选练习标题。")
    create.set_defaults(handler=handle_create)

    answer = actions.add_parser("answer", parents=[GLOBAL_OPTIONS_PARENT], help="暂存单题作答")
    answer.add_argument("--practice-id", required=True, help="练习主键 UUID。")
    answer.add_argument("--question-id", required=True, help="题目主键 UUID。")
    answer.add_argument("--answer", required=True, help="作答文本或选项标识。")
    answer.add_argument("--user-id", required=True, help="用户主键 UUID。")
    answer.set_defaults(handler=handle_answer)

    submit = actions.add_parser("submit", parents=[GLOBAL_OPTIONS_PARENT], help="交卷")
    submit.add_argument("--practice-id", required=True, help="练习主键 UUID。")
    submit.add_argument(
        "--answers", default=None, help="可选批量作答 JSON（question_id -> answer）。"
    )
    submit.add_argument("--user-id", required=True, help="用户主键 UUID。")
    submit.set_defaults(handler=handle_submit)


def _parse_question_ids(raw: str) -> list[uuid.UUID]:
    ids: list[uuid.UUID] = []
    for item in raw.split(","):
        token = item.strip()
        if token:
            ids.append(parse_uuid(token, "--question-ids"))
    if not ids:
        raise CliError(
            "--question-ids 不能为空。",
            exit_code=EXIT_ASSERTION,
            remediation="请传入逗号分隔的题目 UUID 列表。",
        )
    return ids


def handle_create(args: argparse.Namespace, context: CliContext, reporter: Reporter) -> int:
    """执行 `practice create`。

    通过题目集合反推知识点集合与资料归属，再按顺序模式组卷。

    Args:
        args: 解析后的命令参数（须含 `user_id` / `question_ids`）。
        context: CLI 执行上下文。
        reporter: 输出器。

    Returns:
        int: 成功返回 `EXIT_OK`。
    """
    ensure_real_or_allowed(context)
    user_id = parse_uuid(args.user_id, "--user-id")
    question_ids = _parse_question_ids(str(args.question_ids))

    with context.container.get_session() as session:
        question_service = context.container.create_question_service(session)
        questions = [
            question_service.get_question(question_id=question_id, user_id=user_id)
            for question_id in question_ids
        ]
        knowledge_point_ids: list[uuid.UUID] = []
        for question in questions:
            if question.knowledge_point_id not in knowledge_point_ids:
                knowledge_point_ids.append(question.knowledge_point_id)

        material_id = (
            parse_uuid(args.material_id, "--material-id")
            if args.material_id
            else questions[0].material_id
        )
        question_types = tuple(dict.fromkeys(question.question_type for question in questions))

        practice_service = context.container.create_practice_service(session)
        practice = practice_service.create_practice(
            user_id,
            CreatePracticeOptions(
                title=args.title or "CLI 练习",
                material_id=material_id,
                knowledge_point_ids=knowledge_point_ids,
                question_count=len(question_ids),
                question_types=question_types,
                mode=PracticeAssemblyMode.SEQUENTIAL,
            ),
            request_id=uuid.uuid4().hex,
        )
        payload: dict[str, Any] = {
            "command": "practice create",
            "status": "ok",
            "practice_id": str(practice.id),
            "material_id": str(practice.material_id),
            "practice_status": practice.status,
            "question_count": practice.question_count,
            "ordered_question_ids": list(practice.ordered_question_ids or []),
        }
    reporter.emit(payload)
    return EXIT_OK


def handle_answer(args: argparse.Namespace, context: CliContext, reporter: Reporter) -> int:
    """执行 `practice answer`。

    Args:
        args: 解析后的命令参数（须含 `practice_id` / `question_id` / `answer`）。
        context: CLI 执行上下文。
        reporter: 输出器。

    Returns:
        int: 成功返回 `EXIT_OK`。
    """
    ensure_real_or_allowed(context)
    user_id = parse_uuid(args.user_id, "--user-id")
    practice_id = parse_uuid(args.practice_id, "--practice-id")
    question_id = parse_uuid(args.question_id, "--question-id")

    with context.container.get_session() as session:
        practice_service = context.container.create_practice_service(session)
        item = practice_service.save_answer(
            user_id,
            practice_id=practice_id,
            question_id=question_id,
            user_answer=str(args.answer),
        )
        payload: dict[str, Any] = {
            "command": "practice answer",
            "status": "ok",
            "practice_id": str(practice_id),
            "question_id": str(question_id),
            "attempt_item_id": str(item.id),
            "is_answered": item.is_answered,
        }
    reporter.emit(payload)
    return EXIT_OK


def _load_answers(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CliError(
            "--answers 不是合法 JSON。",
            exit_code=EXIT_ASSERTION,
            details={"error": str(exc)},
            remediation='示例：--answers \'{"<question_id>": "A"}\'。',
        ) from exc
    if not isinstance(parsed, dict):
        raise CliError(
            "--answers 必须为 JSON 对象（question_id -> answer）。",
            exit_code=EXIT_ASSERTION,
        )
    return {str(key): str(value) for key, value in parsed.items()}


def handle_submit(args: argparse.Namespace, context: CliContext, reporter: Reporter) -> int:
    """执行 `practice submit`。

    Args:
        args: 解析后的命令参数（须含 `practice_id`）。
        context: CLI 执行上下文。
        reporter: 输出器。

    Returns:
        int: 成功返回 `EXIT_OK`。
    """
    ensure_real_or_allowed(context)
    user_id = parse_uuid(args.user_id, "--user-id")
    practice_id = parse_uuid(args.practice_id, "--practice-id")
    answers = _load_answers(getattr(args, "answers", None))

    with context.container.get_session() as session:
        practice_service = context.container.create_practice_service(session)
        for question_id, answer in answers.items():
            practice_service.save_answer(
                user_id,
                practice_id=practice_id,
                question_id=parse_uuid(question_id, "--answers.key"),
                user_answer=answer,
            )
        result = practice_service.submit_practice(
            user_id,
            practice_id=practice_id,
            idempotency_key=f"cli-{uuid.uuid4().hex}",
            confirm_unanswered=True,
        )
        payload: dict[str, Any] = {
            "command": "practice submit",
            "status": "ok",
            "practice_id": str(result.practice_id),
            "task_id": result.task_id,
            "practice_status": result.status,
            "total_questions": result.total_questions,
            "answered_questions": result.answered_questions,
            "unanswered_count": result.unanswered_count,
            "submitted_at": result.submitted_at,
        }
    reporter.emit(payload)
    return EXIT_OK


__all__ = ["handle_answer", "handle_create", "handle_submit", "register"]
