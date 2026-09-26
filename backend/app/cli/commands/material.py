"""`material` 子命令：资料上传、同步解析、状态与知识树查询。

子命令：
- `material upload --file <path> [--title] [--user-id|--code]`：导入资料，输出 material/version ID；
- `material parse --material-id <uuid> [--version-id] [--user-id]`：同步执行解析流水线；
  失败时输出 `failed_stage` + `error_message` 并以退出码 2 中止；
- `material status --material-id <uuid> [--user-id]`：输出资料与版本状态；
- `material tree --material-id <uuid> [--version-id] [--user-id]`：输出知识树。

退出码契约：成功 `0`；断言/校验/解析失败 `2`；非真实 Provider `3`。
"""

import argparse
import uuid
from pathlib import Path
from typing import Any

from app.cli.commands import (
    GLOBAL_OPTIONS_PARENT,
    ensure_real_or_allowed,
    parse_uuid,
    resolve_user_id,
)
from app.cli.context import CliContext
from app.cli.errors import EXIT_ASSERTION, EXIT_OK, CliError
from app.cli.report import Reporter
from app.core.errors import AppError
from app.models.material import MaterialVersion, ParseStatus
from app.services.knowledge import KnowledgeService
from app.services.material import MaterialService


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """注册 `material` 子命令及其动作。

    Args:
        subparsers: 顶层子命令解析器集合。
    """
    parser = subparsers.add_parser(
        "material",
        parents=[GLOBAL_OPTIONS_PARENT],
        help="学习资料管理（upload / parse / status / tree）",
        description="上传资料、同步解析、查询状态与知识树。",
    )
    actions = parser.add_subparsers(dest="material_action", required=True)

    upload = actions.add_parser("upload", parents=[GLOBAL_OPTIONS_PARENT], help="上传导入资料")
    upload.add_argument("--file", required=True, help="资料文件路径。")
    upload.add_argument("--title", default=None, help="可选标题（缺省取文件名）。")
    upload.add_argument("--user-id", default=None, help="用户主键 UUID。")
    upload.add_argument("--code", default=None, help="可选微信 code，就地登录。")
    upload.set_defaults(handler=handle_upload)

    parse = actions.add_parser("parse", parents=[GLOBAL_OPTIONS_PARENT], help="同步解析资料")
    parse.add_argument("--material-id", required=True, help="资料主键 UUID。")
    parse.add_argument("--version-id", default=None, help="可选版本主键 UUID。")
    parse.add_argument("--user-id", required=True, help="用户主键 UUID。")
    parse.set_defaults(handler=handle_parse)

    status = actions.add_parser("status", parents=[GLOBAL_OPTIONS_PARENT], help="查询资料状态")
    status.add_argument("--material-id", required=True, help="资料主键 UUID。")
    status.add_argument("--user-id", required=True, help="用户主键 UUID。")
    status.set_defaults(handler=handle_status)

    tree = actions.add_parser("tree", parents=[GLOBAL_OPTIONS_PARENT], help="查询知识树")
    tree.add_argument("--material-id", required=True, help="资料主键 UUID。")
    tree.add_argument("--version-id", default=None, help="可选版本主键 UUID。")
    tree.add_argument("--user-id", required=True, help="用户主键 UUID。")
    tree.set_defaults(handler=handle_tree)


def _read_file(path: str) -> bytes:
    file_path = Path(path)
    if not file_path.is_file():
        raise CliError(
            f"资料文件不存在: {path}",
            exit_code=EXIT_ASSERTION,
            remediation="请传入有效的 --file 路径。",
        )
    try:
        return file_path.read_bytes()
    except OSError as exc:
        raise CliError(
            f"读取资料文件失败: {path}",
            exit_code=EXIT_ASSERTION,
            details={"error": str(exc)},
        ) from exc


def _resolve_target_version(
    service: MaterialService,
    user_id: uuid.UUID,
    material_id: uuid.UUID,
    version_id: uuid.UUID | None,
) -> MaterialVersion:
    versions = service.list_material_versions(user_id, material_id)
    if not versions:
        raise CliError(
            f"资料 {material_id} 不存在可用版本。",
            exit_code=EXIT_ASSERTION,
            remediation="请确认 --material-id 是否正确，或重新上传资料。",
        )
    if version_id is None:
        return versions[0]
    for version in versions:
        if version.id == version_id:
            return version
    raise CliError(
        f"资料 {material_id} 下不存在版本 {version_id}。",
        exit_code=EXIT_ASSERTION,
        remediation="请核对 --version-id。",
    )


def handle_upload(args: argparse.Namespace, context: CliContext, reporter: Reporter) -> int:
    """执行 `material upload`。

    Args:
        args: 解析后的命令参数（须含 `file`）。
        context: CLI 执行上下文。
        reporter: 输出器。

    Returns:
        int: 成功返回 `EXIT_OK`。
    """
    ensure_real_or_allowed(context)
    content = _read_file(str(args.file))
    filename = Path(str(args.file)).name
    with context.container.get_session() as session:
        user_id = resolve_user_id(
            context, session, user_id=args.user_id, code=getattr(args, "code", None)
        )
        service = context.container.create_material_service(session)
        material, version = service.import_material_file(
            user_id=user_id,
            file_content=content,
            filename=filename,
            title=args.title,
            source_type="local",
        )
        payload: dict[str, Any] = {
            "command": "material upload",
            "status": "ok",
            "user_id": str(user_id),
            "material_id": str(material.id),
            "version_id": str(version.id),
            "title": material.title,
            "file_format": material.file_format,
            "file_size": material.file_size,
            "material_status": material.status,
            "parse_status": version.parse_status,
            "version_number": version.version_number,
        }
    reporter.emit(payload)
    return EXIT_OK


def handle_parse(args: argparse.Namespace, context: CliContext, reporter: Reporter) -> int:
    """执行 `material parse`：同步解析并在失败时精确归因。

    Args:
        args: 解析后的命令参数（须含 `material_id` / `user_id`）。
        context: CLI 执行上下文。
        reporter: 输出器。

    Returns:
        int: 解析成功且终态 READY 返回 `EXIT_OK`。

    Raises:
        CliError: 解析失败或终态非 READY（退出码 2），携带 failed_stage/error_message。
    """
    ensure_real_or_allowed(context)
    user_id = parse_uuid(args.user_id, "--user-id")
    material_id = parse_uuid(args.material_id, "--material-id")
    version_id = parse_uuid(args.version_id, "--version-id") if args.version_id else None

    with context.container.get_session() as session:
        service = context.container.create_material_service(session)
        target = _resolve_target_version(service, user_id, material_id, version_id)
        try:
            service.parse_material_pipeline(
                material_id=material_id,
                version_id=target.id,
                user_id=user_id,
            )
        except AppError as exc:
            raise _parse_failure(service, user_id, material_id, target.id, exc) from exc

        refreshed = _resolve_target_version(service, user_id, material_id, target.id)
        if refreshed.parse_status != ParseStatus.READY.value:
            raise CliError(
                "资料解析未达终态 READY。",
                exit_code=EXIT_ASSERTION,
                details={
                    "material_id": str(material_id),
                    "version_id": str(target.id),
                    "parse_status": refreshed.parse_status,
                    "failed_stage": refreshed.failed_stage,
                    "error_message": refreshed.error_message,
                },
                remediation="请检查失败阶段与错误信息，修复后重试。",
            )
        payload: dict[str, Any] = {
            "command": "material parse",
            "status": "ok",
            "material_id": str(material_id),
            "version_id": str(refreshed.id),
            "parse_status": refreshed.parse_status,
            "is_active": refreshed.is_active,
        }
    reporter.emit(payload)
    return EXIT_OK


def _parse_failure(
    service: MaterialService,
    user_id: uuid.UUID,
    material_id: uuid.UUID,
    version_id: uuid.UUID,
    exc: AppError,
) -> CliError:
    """将解析异常与版本失败现场组装为退出码 2 的 CLI 错误。"""
    failed_version = service.repo.get_version_by_id(version_id, user_id)
    details: dict[str, Any] = {
        "material_id": str(material_id),
        "version_id": str(version_id),
        "error_code": exc.error_code,
    }
    if failed_version is not None:
        details["failed_stage"] = failed_version.failed_stage
        details["error_message"] = failed_version.error_message
        details["parse_status"] = failed_version.parse_status
    else:
        details["error_message"] = exc.message
    return CliError(
        f"资料解析失败: {exc.message}",
        exit_code=EXIT_ASSERTION,
        details=details,
        remediation="请依据 failed_stage 定位失败环境（如 DOCX/PDF 内容、Provider 配置）后重试。",
    )


def handle_status(args: argparse.Namespace, context: CliContext, reporter: Reporter) -> int:
    """执行 `material status`。

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
        service = context.container.create_material_service(session)
        material = service.get_material_detail(material_id=material_id, user_id=user_id)
        versions = service.list_material_versions(user_id, material_id)
        payload: dict[str, Any] = {
            "command": "material status",
            "status": "ok",
            "material_id": str(material.id),
            "title": material.title,
            "file_format": material.file_format,
            "material_status": material.status,
            "parse_status": getattr(material, "parse_status", None),
            "progress_percentage": getattr(material, "progress_percentage", None),
            "current_version_id": str(material.current_version_id)
            if material.current_version_id
            else None,
            "versions": [
                {
                    "version_id": str(version.id),
                    "version_number": version.version_number,
                    "parse_status": version.parse_status,
                    "failed_stage": version.failed_stage,
                    "error_message": version.error_message,
                    "is_active": version.is_active,
                }
                for version in versions
            ],
        }
    reporter.emit(payload)
    return EXIT_OK


def _count_and_flatten(nodes: list[dict[str, Any]]) -> tuple[int, list[str]]:
    """递归统计知识树节点数并扁平化节点 ID。"""
    count = 0
    ids: list[str] = []
    for node in nodes:
        count += 1
        node_id = node.get("id")
        if isinstance(node_id, str):
            ids.append(node_id)
        children = node.get("children")
        if isinstance(children, list):
            child_count, child_ids = _count_and_flatten(children)
            count += child_count
            ids.extend(child_ids)
    return count, ids


def handle_tree(args: argparse.Namespace, context: CliContext, reporter: Reporter) -> int:
    """执行 `material tree`。

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
    version_id = parse_uuid(args.version_id, "--version-id") if args.version_id else None
    with context.container.get_session() as session:
        knowledge_service: KnowledgeService = context.container.create_knowledge_service(session)
        roots = knowledge_service.get_knowledge_tree(
            material_id=material_id,
            version_id=version_id,
            user_id=user_id,
        )
        point_count, point_ids = _count_and_flatten(roots)
        payload: dict[str, Any] = {
            "command": "material tree",
            "status": "ok",
            "material_id": str(material_id),
            "point_count": point_count,
            "knowledge_point_ids": point_ids,
            "tree": roots,
        }
    reporter.emit(payload)
    return EXIT_OK


__all__ = [
    "handle_parse",
    "handle_status",
    "handle_tree",
    "handle_upload",
    "register",
]
