"""`question` 子命令：题目生成与列表查询。

子命令：
- `question generate --material-id <uuid> [--knowledge-point-id <uuid>] [--version-id]
  [--count <n>] [--types <csv>] [--user-id]`：生成题目（未给考点时取知识树首个节点）；
- `question list --material-id <uuid> [--user-id]`：列出资料下题目。

退出码契约：成功 `0`；断言/校验 `2`；非真实 Provider `3`。
"""

import argparse
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
from app.models.question import Question
from app.services.question import GenerateQuestionsOptions


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """注册 `question` 子命令及其动作。

    Args:
        subparsers: 顶层子命令解析器集合。
    """
    parser = subparsers.add_parser(
        "question",
        parents=[GLOBAL_OPTIONS_PARENT],
        help="题目生成与查询（generate / list）",
        description="基于知识点生成题目，或列出资料下题目。",
    )
    actions = parser.add_subparsers(dest="question_action", required=True)

    generate = actions.add_parser("generate", parents=[GLOBAL_OPTIONS_PARENT], help="生成题目")
    generate.add_argument("--material-id", required=True, help="资料主键 UUID。")
    generate.add_argument("--version-id", default=None, help="可选版本主键 UUID。")
    generate.add_argument("--knowledge-point-id", default=None, help="可选知识点 UUID。")
    generate.add_argument("--count", type=int, default=5, help="生成题量 (1-20，默认 5)。")
    generate.add_argument(
        "--types", default=None, help="题型 CSV（如 single_choice,multiple_choice）。"
    )
    generate.add_argument("--user-id", required=True, help="用户主键 UUID。")
    generate.set_defaults(handler=handle_generate)

    listing = actions.add_parser("list", parents=[GLOBAL_OPTIONS_PARENT], help="列出题目")
    listing.add_argument("--material-id", required=True, help="资料主键 UUID。")
    listing.add_argument("--user-id", required=True, help="用户主键 UUID。")
    listing.set_defaults(handler=handle_list)


def _first_knowledge_point_id(roots: list[dict[str, Any]]) -> str | None:
    """深度优先取知识树首个节点 ID（优先叶子层级最深处）。"""
    for node in roots:
        children = node.get("children")
        if isinstance(children, list) and children:
            found = _first_knowledge_point_id(children)
            if found:
                return found
        node_id = node.get("id")
        if isinstance(node_id, str):
            return node_id
    return None


def _parse_types(raw: str | None) -> tuple[str, ...] | None:
    if not raw:
        return None
    items = tuple(item.strip() for item in raw.split(",") if item.strip())
    return items or None


def handle_generate(args: argparse.Namespace, context: CliContext, reporter: Reporter) -> int:
    """执行 `question generate`。

    Args:
        args: 解析后的命令参数（须含 `material_id` / `user_id`）。
        context: CLI 执行上下文。
        reporter: 输出器。

    Returns:
        int: 成功返回 `EXIT_OK`。

    Raises:
        CliError: 知识树为空或生成结果为空（退出码 2）。
    """
    ensure_real_or_allowed(context)
    user_id = parse_uuid(args.user_id, "--user-id")
    material_id = parse_uuid(args.material_id, "--material-id")
    version_id = parse_uuid(args.version_id, "--version-id") if args.version_id else None

    with context.container.get_session() as session:
        knowledge_service = context.container.create_knowledge_service(session)
        knowledge_point_raw = getattr(args, "knowledge_point_id", None)
        resolved_version_id = version_id
        if knowledge_point_raw:
            knowledge_point_id = parse_uuid(knowledge_point_raw, "--knowledge-point-id")
        else:
            roots = knowledge_service.get_knowledge_tree(
                material_id=material_id,
                version_id=version_id,
                user_id=user_id,
            )
            first_id = _first_knowledge_point_id(roots)
            if first_id is None:
                raise CliError(
                    "知识树为空，无法确定出题知识点。",
                    exit_code=EXIT_ASSERTION,
                    remediation="请先完成资料解析与知识树抽取，或显式传入 --knowledge-point-id。",
                )
            knowledge_point_id = uuid.UUID(first_id)

        question_service = context.container.create_question_service(session)
        result = question_service.generate_questions(
            user_id=user_id,
            material_id=material_id,
            version_id=resolved_version_id,
            knowledge_point_id=knowledge_point_id,
            options=GenerateQuestionsOptions(
                question_types=_parse_types(args.types)
                or GenerateQuestionsOptions().question_types,
                count=int(args.count),
            ),
        )
        question_ids = [str(q.id) for q in result.qualified_questions]
        if not question_ids:
            raise CliError(
                "题目生成未产出合格题目。",
                exit_code=EXIT_ASSERTION,
                details={"batch_id": result.batch_id, "total_generated": result.total_generated},
                remediation="请检查知识点切片是否充足或重试。",
            )
        payload: dict[str, Any] = {
            "command": "question generate",
            "status": "ok",
            "material_id": str(result.material_id),
            "version_id": str(result.version_id),
            "knowledge_point_id": str(result.knowledge_point_id),
            "batch_id": result.batch_id,
            "total_generated": result.total_generated,
            "qualified_count": len(result.qualified_questions),
            "pending_count": len(result.pending_questions),
            "question_ids": question_ids,
        }
    reporter.emit(payload)
    return EXIT_OK


def _question_summary(question: Question) -> dict[str, Any]:
    return {
        "question_id": str(question.id),
        "knowledge_point_id": str(question.knowledge_point_id),
        "question_type": question.question_type,
        "status": question.status,
        "difficulty": question.difficulty,
        "stem": question.stem,
    }


def handle_list(args: argparse.Namespace, context: CliContext, reporter: Reporter) -> int:
    """执行 `question list`。

    Args:
        args: 解析后的命令参数（须含 `material_id` / `user_id`）。
        context: CLI 执行上下文。
        reporter: 输出器。

    Returns:
        int: 成功返回 `EXIT_OK`。
    """
    ensure_real_or_allowed(context)
    user_id = parse_uuid(args.user_id, "--user-id")
    material_id = parse_uuid(args.material_id, "--material-id")
    with context.container.get_session() as session:
        question_service = context.container.create_question_service(session)
        questions, total = question_service.list_questions(
            user_id,
            material_id=material_id,
            page_size=100,
        )
        payload: dict[str, Any] = {
            "command": "question list",
            "status": "ok",
            "material_id": str(material_id),
            "total": total,
            "questions": [_question_summary(question) for question in questions],
        }
    reporter.emit(payload)
    return EXIT_OK


__all__ = ["handle_generate", "handle_list", "register"]
