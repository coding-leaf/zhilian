"""`smoke` 子命令：真实 Provider 下端到端全链路闭环编排与逐阶段断言。

编排 11 个阶段（design.md 第 5 节）：

    preflight -> login -> import -> parse -> snippets -> tree
    -> questions -> practice -> grading -> report -> summary

设计约束：
- 直驱生产同款服务装配（`AppContainer` 工厂 + `get_session`），不绕过业务逻辑；
- 业务执行前完成真实 Provider 校验与基础设施连通性探测；
- 任一步骤失败即停止，输出 `failed_stage` + 原始 `error` + 已完成阶段摘要；
- 确保可重复隔离：每次运行使用独立 `run_id` 命名空间用户。

退出码契约：
- 0 全绿；2 任一阶段断言失败；3 真实 Provider 配置缺口；4 基础设施不可达。
"""

import argparse
import time
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cli import fixtures
from app.cli.commands import GLOBAL_OPTIONS_PARENT
from app.cli.context import CliContext
from app.cli.errors import (
    EXIT_ASSERTION,
    EXIT_CONFIG,
    EXIT_INFRA,
    EXIT_OK,
    CliError,
)
from app.cli.report import STAGE_SKIPPED, Reporter, StageRecorder
from app.core.errors import AppError
from app.models.material import MaterialSnippet, MaterialStatus, ParseStatus
from app.services.practice import CreatePracticeOptions, PracticeAssemblyMode
from app.services.question import GenerateQuestionsOptions

QUESTION_COUNT = 3
"""单次 smoke 生成的题量。"""

INFRA_LABELS: dict[str, str] = {
    "database": "数据库 (PostgreSQL)",
    "redis": "Redis",
    "minio": "对象存储 (MinIO/S3)",
}
"""基础设施组件的中文展示名。"""


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """注册 `smoke` 子命令。

    Args:
        subparsers: 顶层子命令解析器集合。
    """
    parser = subparsers.add_parser(
        "smoke",
        parents=[GLOBAL_OPTIONS_PARENT],
        help="真实 Provider 端到端全链路闭环验证",
        description=("跑通 登录→上传→解析→知识树→出题→作答→交卷→判分→诊断 全链路并逐阶段断言。"),
    )
    parser.add_argument("--file", default=None, help="资料文件路径（缺省用内置中文讲义）。")
    parser.add_argument(
        "--image",
        default=None,
        help="可选真实含字图片（Stage 3 暂不执行 OCR 子链路，仅记录为 skipped）。",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="保留运行数据（默认即保留，重置请用 db reset --yes）。",
    )
    parser.set_defaults(handler=handle)


def _count_nodes(nodes: list[dict[str, Any]]) -> int:
    """递归统计知识树节点总数。"""
    total = 0
    for node in nodes:
        total += 1
        children = node.get("children")
        if isinstance(children, list):
            total += _count_nodes(children)
    return total


def _first_leaf_id(nodes: list[dict[str, Any]]) -> str | None:
    """深度优先返回知识树首个叶子节点 ID（无子节点优先）。"""
    for node in nodes:
        children = node.get("children")
        if isinstance(children, list) and children:
            found = _first_leaf_id(children)
            if found:
                return found
        node_id = node.get("id")
        if isinstance(node_id, str):
            return node_id
    return None


class SmokeRunner:
    """端到端 smoke 全链路编排器（逐阶段断言 + 结构化归因）。"""

    def __init__(
        self,
        args: argparse.Namespace,
        context: CliContext,
        reporter: Reporter,
    ) -> None:
        """初始化编排器并生成隔离运行标识。

        Args:
            args: 解析后的命令参数（file/image/keep）。
            context: CLI 执行上下文（提供容器与真实链路校验）。
            reporter: 输出器（负责阶段记录与最终 JSON 汇总）。
        """
        self.args = args
        self.context = context
        self.reporter = reporter
        self.run_id = uuid.uuid4().hex[:8]
        self.entities: dict[str, Any] = {}
        self.ocr_leg = STAGE_SKIPPED
        self._start = 0.0
        self._user_id: uuid.UUID | None = None
        self._material_id: uuid.UUID | None = None
        self._version_id: uuid.UUID | None = None
        self._knowledge_point_id: uuid.UUID | None = None
        self._question_ids: list[str] = []
        self._practice_id: uuid.UUID | None = None

    def execute(self) -> int:
        """执行全链路并返回契约退出码。

        Returns:
            int: 全绿 0；阶段断言失败 2；配置缺口 3；基础设施不可达 4。
        """
        self._start = time.perf_counter()
        try:
            self._run_stages()
        except Exception as exc:
            return self._emit_failure(exc)
        return self._emit_success()

    def _run_stages(self) -> None:
        """按序执行全部阶段，任一阶段异常即中断上抛。"""
        with self.reporter.stage("preflight") as stage:
            self._preflight(stage)

        with self.context.container.get_session() as session:
            with self.reporter.stage("login") as stage:
                self._login(session, stage)
            with self.reporter.stage("import") as stage:
                self._import(session, stage)
            with self.reporter.stage("parse") as stage:
                self._parse(session, stage)
            with self.reporter.stage("snippets") as stage:
                self._snippets(session, stage)
            with self.reporter.stage("tree") as stage:
                self._tree(session, stage)
            with self.reporter.stage("questions") as stage:
                self._questions(session, stage)
            with self.reporter.stage("practice") as stage:
                self._practice(session, stage)
            with self.reporter.stage("grading") as stage:
                self._grading(session, stage)
            with self.reporter.stage("report") as stage:
                self._diagnosis(session, stage)

        with self.reporter.stage("summary") as stage:
            self._summary(stage)

    # ------------------------------------------------------------------
    # 阶段实现
    # ------------------------------------------------------------------

    def _preflight(self, stage: StageRecorder) -> None:
        """真实链路前置门禁：Provider 校验 + 基础设施连通 + 迁移版本。"""
        context = self.context
        stage.details["allow_fake"] = context.allow_fake
        stage.details["providers"] = context.provider_matrix()

        gaps = context.assert_real_providers(require_ocr=False)
        if gaps:
            raise CliError(
                f"检测到 {len(gaps)} 项非真实 Provider 配置，已在业务执行前中止。",
                exit_code=EXIT_CONFIG,
                details={"gaps": [gap.to_dict() for gap in gaps]},
                remediation="请在 backend/.env 按 gaps[].env_key 补齐真实配置后重试。",
            )

        infra = context.probe_infra()
        stage.details["infrastructure"] = infra
        required = {"database"} if context.allow_fake else {"database", "redis", "minio"}
        unreachable = {
            name: infra.get(name, {}).get("detail", "unknown")
            for name in sorted(required)
            if not infra.get(name, {}).get("reachable")
        }
        if unreachable:
            labels = "、".join(INFRA_LABELS.get(name, name) for name in unreachable)
            raise CliError(
                f"基础设施不可达：{labels}。",
                exit_code=EXIT_INFRA,
                details={"unreachable": unreachable},
                remediation="请检查服务进程、端口与连接配置后重试。",
            )

        revision = context.db_revision()
        stage.details["database_revision"] = revision
        if not context.allow_fake and revision is None:
            raise CliError(
                "数据库未应用 Alembic 迁移（alembic_version 缺失）。",
                exit_code=EXIT_INFRA,
                details={"component": "database_migration"},
                remediation="请先执行 python -m app.cli db upgrade。",
            )

        bucket = context.settings.storage.bucket_name
        try:
            context.container.providers.storage.ensure_bucket_exists(bucket)
        except Exception as exc:
            raise CliError(
                f"对象存储不可用（桶 {bucket} 校验失败）。",
                exit_code=EXIT_INFRA,
                details={"component": "storage", "error": str(exc)},
                remediation="请确认 MinIO/S3 服务与访问凭证配置正确。",
            ) from exc
        stage.details["storage_bucket"] = bucket

    def _login(self, session: Session, stage: StageRecorder) -> None:
        """阶段：确定性开发 OpenID 登录，生成隔离用户命名空间。"""
        auth_service = self.context.container.create_auth_service(session)
        user, _tokens = auth_service.login_with_wechat(f"dev_cli-smoke-{self.run_id}")
        self._user_id = user.id
        self.entities["user_id"] = str(user.id)
        stage.ids["user_id"] = str(user.id)

    def _import(self, session: Session, stage: StageRecorder) -> None:
        """阶段：上传资料并断言进入 pending/parsing。"""
        content, filename = fixtures.resolve_smoke_input(self.args.file)
        service = self.context.container.create_material_service(session)
        material, version = service.import_material_file(
            user_id=self._require_uuid(self._user_id, "user_id"),
            file_content=content,
            filename=filename,
            title=f"CLI Smoke {self.run_id}",
            source_type="local",
        )
        if material.status not in (MaterialStatus.PENDING.value, MaterialStatus.PARSING.value):
            raise CliError(
                f"资料导入后状态异常: {material.status}",
                exit_code=EXIT_ASSERTION,
                details={"material_status": material.status},
            )
        self._material_id = material.id
        self._version_id = version.id
        self.entities["material_id"] = str(material.id)
        self.entities["version_id"] = str(version.id)
        self.entities["file_format"] = material.file_format
        stage.ids.update(
            material_id=str(material.id),
            version_id=str(version.id),
            file_format=material.file_format,
        )

    def _parse(self, session: Session, stage: StageRecorder) -> None:
        """阶段：同步执行解析流水线并断言终态 READY。"""
        service = self.context.container.create_material_service(session)
        material_id = self._require_uuid(self._material_id, "material_id")
        version_id = self._require_uuid(self._version_id, "version_id")
        user_id = self._require_uuid(self._user_id, "user_id")
        try:
            service.parse_material_pipeline(
                material_id=material_id,
                version_id=version_id,
                user_id=user_id,
            )
        except AppError as exc:
            refreshed = service.repo.get_version_by_id(version_id, user_id)
            raise CliError(
                f"资料解析失败: {exc.message}",
                exit_code=EXIT_ASSERTION,
                details={
                    "parse_status": getattr(refreshed, "parse_status", None),
                    "failed_stage": getattr(refreshed, "failed_stage", None),
                    "error_message": getattr(refreshed, "error_message", None),
                    "error_code": exc.error_code,
                },
                remediation="请依据 failed_stage 定位失败环境（文档格式/Provider 配置）后重试。",
            ) from exc

        refreshed = service.repo.get_version_by_id(version_id, user_id)
        if refreshed is None or refreshed.parse_status != ParseStatus.READY.value:
            raise CliError(
                "资料解析未达终态 READY。",
                exit_code=EXIT_ASSERTION,
                details={
                    "parse_status": getattr(refreshed, "parse_status", None),
                    "failed_stage": getattr(refreshed, "failed_stage", None),
                    "error_message": getattr(refreshed, "error_message", None),
                },
            )
        self.entities["parse_status"] = refreshed.parse_status
        stage.ids["parse_status"] = refreshed.parse_status

    def _snippets(self, session: Session, stage: StageRecorder) -> None:
        """阶段：断言切片数 > 0 且至少一条 embedding 非空。"""
        version_id = self._require_uuid(self._version_id, "version_id")
        user_id = self._require_uuid(self._user_id, "user_id")
        statement = select(MaterialSnippet).where(
            MaterialSnippet.version_id == version_id,
            MaterialSnippet.user_id == user_id,
        )
        snippets = list(session.scalars(statement))
        embedded = [
            item for item in snippets if item.embedding is not None and item.embedding != []
        ]
        if not snippets:
            raise CliError(
                "资料未切分出任何有效切片。",
                exit_code=EXIT_ASSERTION,
                details={"version_id": str(version_id)},
            )
        if not embedded:
            raise CliError(
                "切片向量化为空，embedding Provider 可能未生效。",
                exit_code=EXIT_ASSERTION,
                details={"snippet_count": len(snippets), "embedded_count": 0},
            )
        self.entities["snippet_count"] = len(snippets)
        self.entities["embedded_snippet_count"] = len(embedded)
        stage.ids["snippet_count"] = str(len(snippets))
        stage.ids["embedded_snippet_count"] = str(len(embedded))

    def _tree(self, session: Session, stage: StageRecorder) -> None:
        """阶段：断言知识树节点数 > 0 并选取出题知识点。"""
        knowledge_service = self.context.container.create_knowledge_service(session)
        roots = knowledge_service.get_knowledge_tree(
            material_id=self._require_uuid(self._material_id, "material_id"),
            version_id=self._require_uuid(self._version_id, "version_id"),
            user_id=self._require_uuid(self._user_id, "user_id"),
        )
        node_count = _count_nodes(roots)
        leaf_id = _first_leaf_id(roots)
        if node_count == 0 or leaf_id is None:
            raise CliError(
                "知识树为空，无法进入出题阶段。",
                exit_code=EXIT_ASSERTION,
                details={"node_count": node_count},
                remediation="请检查知识点抽取（LLM 结构化输出）是否正常。",
            )
        self._knowledge_point_id = uuid.UUID(leaf_id)
        self.entities["knowledge_point_id"] = leaf_id
        self.entities["knowledge_tree_node_count"] = node_count
        stage.ids["knowledge_point_id"] = leaf_id
        stage.ids["node_count"] = str(node_count)

    def _questions(self, session: Session, stage: StageRecorder) -> None:
        """阶段：生成题目并断言题量 > 0。"""
        question_service = self.context.container.create_question_service(session)
        result = question_service.generate_questions(
            user_id=self._require_uuid(self._user_id, "user_id"),
            material_id=self._require_uuid(self._material_id, "material_id"),
            version_id=self._require_uuid(self._version_id, "version_id"),
            knowledge_point_id=self._require_uuid(self._knowledge_point_id, "knowledge_point_id"),
            options=GenerateQuestionsOptions(count=QUESTION_COUNT),
        )
        self._question_ids = [str(question.id) for question in result.qualified_questions]
        if not self._question_ids:
            raise CliError(
                "题目生成未产出合格题目。",
                exit_code=EXIT_ASSERTION,
                details={
                    "batch_id": result.batch_id,
                    "total_generated": result.total_generated,
                },
                remediation="请检查检索切片相似度门禁或重试。",
            )
        self.entities["question_count"] = len(self._question_ids)
        stage.ids["question_count"] = str(len(self._question_ids))
        stage.details["question_ids"] = self._question_ids

    def _practice(self, session: Session, stage: StageRecorder) -> None:
        """阶段：创建练习、逐题作答并交卷。"""
        service = self.context.container.create_practice_service(session)
        user_id = self._require_uuid(self._user_id, "user_id")
        knowledge_point_id = self._require_uuid(self._knowledge_point_id, "knowledge_point_id")
        practice = service.create_practice(
            user_id,
            CreatePracticeOptions(
                title=f"CLI Smoke {self.run_id}",
                material_id=self._require_uuid(self._material_id, "material_id"),
                knowledge_point_ids=[knowledge_point_id],
                question_count=len(self._question_ids),
                mode=PracticeAssemblyMode.SEQUENTIAL,
            ),
            request_id=uuid.uuid4().hex,
        )
        answered = 0
        for raw_id in list(practice.ordered_question_ids or []):
            service.save_answer(
                user_id,
                practice_id=practice.id,
                question_id=uuid.UUID(raw_id),
                user_answer="A",
            )
            answered += 1
        submission = service.submit_practice(
            user_id,
            practice_id=practice.id,
            idempotency_key=f"cli-smoke-{self.run_id}",
            confirm_unanswered=True,
        )
        self._practice_id = practice.id
        self.entities["practice_id"] = str(practice.id)
        self.entities["answered_count"] = answered
        self.entities["practice_status"] = submission.status
        stage.ids.update(
            practice_id=str(practice.id),
            question_count=str(len(self._question_ids)),
            answered_count=str(answered),
        )

    def _grading(self, session: Session, stage: StageRecorder) -> None:
        """阶段：整卷判题并断言判分结果存在。"""
        service = self.context.container.create_grading_service(session)
        summary = service.grade_practice_submission(
            self._require_uuid(self._practice_id, "practice_id"),
            self._require_uuid(self._user_id, "user_id"),
        )
        if summary is None or summary.total_items <= 0:
            raise CliError(
                "判分结果为空。",
                exit_code=EXIT_ASSERTION,
                details={"practice_id": str(self._practice_id)},
            )
        self.entities["graded_items"] = summary.graded_items
        self.entities["grading_total_score"] = summary.total_score
        stage.ids["graded_items"] = str(summary.graded_items)
        stage.ids["total_items"] = str(summary.total_items)

    def _diagnosis(self, session: Session, stage: StageRecorder) -> None:
        """阶段：生成学情诊断报告并断言报告存在。"""
        service = self.context.container.create_diagnosis_service(session)
        report = service.generate_diagnosis_report(
            self._require_uuid(self._user_id, "user_id"),
            self._require_uuid(self._practice_id, "practice_id"),
        )
        if report is None:
            raise CliError(
                "学情诊断报告生成失败。",
                exit_code=EXIT_ASSERTION,
                details={"practice_id": str(self._practice_id)},
            )
        self.entities["report_id"] = str(report.id)
        stage.ids["report_id"] = str(report.id)
        stage.ids["score_rate"] = str(report.score_rate)

    def _summary(self, stage: StageRecorder) -> None:
        """阶段：汇总关键实体与阶段统计。"""
        stage.details["stage_count"] = len(self.reporter.stages)
        stage.details["question_count"] = len(self._question_ids)

    # ------------------------------------------------------------------
    # 输出与归因
    # ------------------------------------------------------------------

    def _emit_success(self) -> int:
        """输出成功汇总 JSON 并返回 0。"""
        self.reporter.emit(
            {
                "command": "smoke",
                "status": "ok",
                "run_id": self.run_id,
                "exit_code": EXIT_OK,
                "duration_ms": int((time.perf_counter() - self._start) * 1000),
                "ocr_leg": self.ocr_leg,
                "keep": bool(getattr(self.args, "keep", False)),
                "entities": self.entities,
                "stages": self.reporter.stage_payloads(),
            }
        )
        return EXIT_OK

    def _emit_failure(self, exc: Exception) -> int:
        """输出失败归因 JSON，返回契约退出码。"""
        exit_code = self._exit_code_for(exc)
        failed_stage = self.reporter.stages[-1].name if self.reporter.stages else "unknown"
        payload: dict[str, Any] = {
            "command": "smoke",
            "status": "failed",
            "run_id": self.run_id,
            "failed_stage": failed_stage,
            "error": str(exc),
            "exit_code": exit_code,
            "ocr_leg": self.ocr_leg,
            "duration_ms": int((time.perf_counter() - self._start) * 1000),
            "entities": self.entities,
            "stages": self.reporter.stage_payloads(),
        }
        if isinstance(exc, CliError):
            if exc.remediation:
                payload["remediation"] = exc.remediation
            if exc.details:
                payload["details"] = exc.details
        self.reporter.emit(payload)
        return exit_code

    @staticmethod
    def _exit_code_for(exc: Exception) -> int:
        """将异常映射为 smoke 契约退出码。"""
        if isinstance(exc, CliError) and exc.exit_code in (EXIT_CONFIG, EXIT_INFRA):
            return exc.exit_code
        return EXIT_ASSERTION

    @staticmethod
    def _require_uuid(value: uuid.UUID | None, label: str) -> uuid.UUID:
        """断言阶段依赖的前置实体 ID 已就绪。"""
        if value is None:
            raise CliError(
                f"前置阶段缺失实体 {label}，编排中断。",
                exit_code=EXIT_ASSERTION,
            )
        return value


def handle(args: argparse.Namespace, context: CliContext, reporter: Reporter) -> int:
    """执行 `smoke`：编排全链路闭环并返回契约退出码。

    Args:
        args: 解析后的命令参数（file/image/keep）。
        context: CLI 执行上下文。
        reporter: 输出器。

    Returns:
        int: 契约退出码。
    """
    return SmokeRunner(args, context, reporter).execute()


__all__ = ["SmokeRunner", "handle", "register"]
