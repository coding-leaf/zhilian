"""练习组卷、作答保存与交卷调度核心领域服务。

负责组卷调度 (顺序、随机、薄弱点)、同知识点打散、逐题作答原子保存、
状态机跃迁 (IN_PROGRESS <-> PAUSED, TIMEOUT)、基于强幂等拦截与异步判题队列投递的交卷。
严格遵循 AGENTS.md 规范：
- app/services 是全系统唯一允许开启数据库事务的层；
- 缩写白名单仅限 8 个 (api, id, url, ocr, llm, db, config, env)；
- 8 要素结构化脱敏日志输出，严禁向日志记录题干、选项、答案与用户作答原文。
"""

import enum
import json
import logging
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.algorithms.grading import OBJECTIVE_QUESTION_TYPES
from app.core.algorithms.practice import scatter_adjacent_knowledge_questions
from app.core.errors import (
    FolderNotFoundError,
    KnowledgeNotFoundError,
    PracticeEmptyQuestionsError,
    PracticeNotFoundError,
    PracticeStatusError,
    QueueError,
)
from app.core.idempotency import validate_idempotency_key
from app.core.logging import log_structured_metric
from app.core.security import generate_user_ref
from app.integrations.idempotency.memory import MemoryIdempotencyAdapter
from app.integrations.idempotency.protocol import IdempotencyProtocol
from app.integrations.queue.memory import MemoryQueueAdapter
from app.integrations.queue.protocol import QueueProtocol
from app.models.practice import (
    AttemptItem,
    Practice,
    PracticeSourceType,
    PracticeStatus,
)
from app.repositories.diagnosis import DiagnosisRepository
from app.repositories.folder import FolderRepository
from app.repositories.grading import GradingRepository
from app.repositories.knowledge import KnowledgeRepository
from app.repositories.material import MaterialRepository
from app.repositories.practice import PracticeRepository
from app.repositories.question import QuestionRepository
from app.schemas.material import SourceSnippetDTO
from app.schemas.practice import (
    PracticeDetailResponse,
    PracticeItemDetailResponse,
    QuestionSnapshotDTO,
)
from app.services._grading_llm import grade_offline_attempt_item
from app.services._practice_assembler import (
    PracticeItemView,
    PracticeView,
    build_validated_snapshots,
    collect_interleaved_candidates,
    rank_candidates_by_mode,
    select_explicit_questions,
    wrap_practice_with_source_snippets,
)
from app.services.source_snippets import build_source_snippet_map

logger = logging.getLogger(__name__)


def _serialize_user_answer(user_answer: Any) -> Any:
    """将非字符串作答规范化为可跨语言解析的标准 JSON 字符串。

    多选题前端提交 ``string[]``，若直接 ``str()`` 会落库为 Python repr
    （如 ``"['A', 'B']"``），违背跨端 JSON 契约；此处统一使用
    ``json.dumps`` 序列化，标量与字符串保持原样 (BUG-PRAC-016)。

    Args:
        user_answer: 原始作答内容（字符串、列表、字典或其他标量）。

    Returns:
        Any: 规范化后的作答（字符串、JSON 字符串或 None）。
    """
    if user_answer is None or isinstance(user_answer, str):
        return user_answer
    if isinstance(user_answer, (list, tuple)):
        return json.dumps(sorted(str(item) for item in user_answer), ensure_ascii=False)
    if isinstance(user_answer, dict):
        return json.dumps(user_answer, ensure_ascii=False, sort_keys=True)
    return str(user_answer)


class PracticeAssemblyMode(enum.StrEnum):
    """练习组卷抽题模式枚举。"""

    SEQUENTIAL = "sequential"  # 顺序抽取 (按题库创建次序排列)
    RANDOM = "random"  # 随机打乱抽取
    WEAK_POINTS = "weak_points"  # 薄弱知识点与错题优先模式


@dataclass(frozen=True)
class CreatePracticeOptions:
    """创建练习与组卷高级配置选项。"""

    title: str
    material_id: uuid.UUID | None
    knowledge_point_ids: Sequence[uuid.UUID]
    question_count: int = 10
    question_types: Sequence[str] | None = None
    difficulty: int | None = None
    mode: PracticeAssemblyMode = PracticeAssemblyMode.SEQUENTIAL
    source_type: str = PracticeSourceType.NORMAL.value
    source_report_id: uuid.UUID | None = None
    idempotency_key: str | None = None
    folder_id: uuid.UUID | None = None
    question_ids: Sequence[uuid.UUID] | None = None


@dataclass(frozen=True)
class SaveAnswerDTO:
    """逐题作答暂存请求数据传输对象。"""

    practice_id: uuid.UUID
    question_id: uuid.UUID
    user_answer: str | None
    duration_seconds: int = 0


@dataclass(frozen=True)
class SubmitPracticeDTO:
    """交卷提交请求数据传输对象。"""

    practice_id: uuid.UUID
    idempotency_key: str
    confirm_unanswered: bool = False


@dataclass(frozen=True)
class PracticeSubmissionResult:
    """交卷调度执行结果。"""

    practice_id: uuid.UUID
    task_id: str
    status: str
    unanswered_count: int
    total_questions: int
    submitted_at: datetime
    answered_questions: int = 0
    uncompleted_count: int = 0
    is_idempotent_replay: bool = False


class PracticeService:
    """练习生命周期管理、组卷出题与交卷调度服务。"""

    def __init__(
        self,
        session: Session,
        *,
        practice_repo: PracticeRepository | None = None,
        question_repo: QuestionRepository | None = None,
        material_repo: MaterialRepository | None = None,
        knowledge_repo: KnowledgeRepository | None = None,
        folder_repo: FolderRepository | None = None,
        diagnosis_repo: DiagnosisRepository | None = None,
        idempotency: IdempotencyProtocol | None = None,
        queue: QueueProtocol | None = None,
    ) -> None:
        """初始化练习服务实例。

        Args:
            session: SQLAlchemy 数据库会话。
            practice_repo: 可选注入的练习仓储实例。
            question_repo: 可选注入的题目仓储实例。
            material_repo: 可选注入的资料仓储实例 (用于切片溯源装配)。
            knowledge_repo: 可选注入的知识点仓储实例 (课程范围考点校验)。
            folder_repo: 可选注入的课程文件夹仓储实例。
            diagnosis_repo: 可选注入的学情诊断仓储实例 (用于薄弱点组卷查询)。
            idempotency: 可选注入的幂等适配器实例。
            queue: 可选注入的任务队列适配器实例。
        """
        self.session = session
        self.practice_repo = practice_repo or PracticeRepository(session)
        self.question_repo = question_repo or QuestionRepository(session)
        self.material_repo = material_repo or MaterialRepository(session)
        self.knowledge_repo = knowledge_repo or KnowledgeRepository(session)
        self.folder_repo = folder_repo or FolderRepository(session)
        self.diagnosis_repo = diagnosis_repo or DiagnosisRepository(session)
        self.idempotency = idempotency or MemoryIdempotencyAdapter()
        self.queue = queue or MemoryQueueAdapter()

    def _log_metric(
        self,
        *,
        action: str,
        request_id: str,
        user_id: uuid.UUID,
        target_id: uuid.UUID | str,
        duration_ms: float,
        error_code: int = 0,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """输出遵循规范的 8 要素脱敏结构化日志。"""
        log_structured_metric(
            logger,
            action=action,
            request_id=request_id,
            user_id=user_id,
            target_id=target_id,
            duration_ms=duration_ms,
            error_code=error_code,
            extra=extra,
            service_label="PracticeService",
        )

    def _release_lock_quietly(self, clean_key: str, user_id: uuid.UUID) -> None:
        """尽力释放幂等锁，失败仅记录告警，绝不阻断主流程。"""
        try:
            self.idempotency.release_lock(clean_key, str(user_id))
        except Exception:
            logger.warning(
                "Idempotency lock release degraded for user_ref=%s",
                generate_user_ref(user_id),
            )

    def _compensate_grading_enqueue_failure(
        self,
        practice_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> None:
        """Commit-First 入队失败后的补偿短事务：将 SUBMITTED 回写为 PARTIALLY_GRADED。"""
        try:
            self.practice_repo.try_transition_status(
                practice_id,
                user_id,
                from_status=PracticeStatus.SUBMITTED.value,
                to_status=PracticeStatus.PARTIALLY_GRADED.value,
            )
            self.session.commit()
        except Exception:
            self.session.rollback()
            logger.exception(
                "Compensating status rollback to partially_graded failed for "
                "user_ref=%s target_id=%s",
                generate_user_ref(user_id),
                practice_id,
            )

    def _rebuild_persisted_submission(
        self,
        practice: Practice,
        user_id: uuid.UUID,
    ) -> PracticeSubmissionResult:
        """从已提交的练习实体安全重建交卷结果，用于 DB 级幂等回放。

        当响应快照写入失败但事务已提交（练习已 COMPLETED 且幂等键匹配）时，
        依据数据库中的题目统计重建 ``PracticeSubmissionResult``，避免客户端
        重试撞上 40011 (BUG-PRAC-013)。

        Args:
            practice: 已恢复的练习实体。
            user_id: 租户用户标识。

        Returns:
            PracticeSubmissionResult: 重建的交卷结果（标记为幂等回放）。
        """
        total_questions = self.practice_repo.count_total_items(practice.id, user_id)
        unanswered_count = self.practice_repo.count_unanswered_items(practice.id, user_id)
        submitted_at = practice.submitted_at or datetime.now(UTC)
        return PracticeSubmissionResult(
            practice_id=practice.id,
            task_id="",
            status=practice.status,
            unanswered_count=unanswered_count,
            total_questions=total_questions,
            submitted_at=submitted_at,
            answered_questions=total_questions - unanswered_count,
            uncompleted_count=unanswered_count,
            is_idempotent_replay=True,
        )

    def create_practice(
        self,
        user_id: uuid.UUID,
        options: CreatePracticeOptions,
        request_id: str = "",
        *,
        defer_commit: bool = False,
    ) -> PracticeView:
        """创建练习会话并执行组卷与题目打散。

        当携带 ``idempotency_key`` 时启用幂等保护：命中已完成快照则直接回放既有
        练习；否则抢占处理中锁，拦截并发重复连击创建重复练习，并在成功后写入
        结果快照供后续重试回放。

        Args:
            user_id: 租户用户标识。
            options: 组卷配置选项。
            request_id: 请求跟踪标识。
            defer_commit: 若为 True 仅 flush 而不 commit，由外层事务统一提交。

        Returns:
            PracticeView: 已创建或幂等回放的练习与溯源投影视图。

        Raises:
            PracticeEmptyQuestionsError: 可用题目不足以满足题量要求。
            IdempotencyConflictError: 相同幂等键请求正在并发处理中。
            IdempotencyKeyInvalidError: 幂等键格式非法。
            AppError: 快照校验失败或系统异常。
        """
        start_time = time.perf_counter()

        clean_key: str | None = None
        if options.idempotency_key:
            clean_key = validate_idempotency_key(options.idempotency_key)
            cached_result = self.idempotency.get_result(clean_key, str(user_id))
            if cached_result is not None:
                replayed = self._replay_idempotent_practice(cached_result, user_id)
                if replayed is not None:
                    return self._attach_source_snippets_to_items(replayed, user_id)
            self.idempotency.acquire_lock(clean_key, str(user_id))

        try:
            practice = self._assemble_and_persist_practice(
                user_id=user_id,
                options=options,
                request_id=request_id,
                start_time=start_time,
                defer_commit=defer_commit,
            )
        except Exception:
            if clean_key is not None:
                self._release_lock_quietly(clean_key, user_id)
            raise

        if clean_key is not None:
            # 快照写入容错隔离（与 submit_practice 一致）：练习已提交成功，快照
            # 写入失败不得让请求返回 5xx；释放处理中锁以便同键重试可重新进入。
            try:
                self.idempotency.set_result(
                    clean_key,
                    str(user_id),
                    {"practice_id": str(practice.id)},
                )
            except Exception:
                logger.warning(
                    "Idempotency snapshot persist degraded for create_practice; "
                    "user_ref=%s target_id=%s",
                    generate_user_ref(user_id),
                    practice.id,
                )
                self._release_lock_quietly(clean_key, user_id)
        # 创建响应与详情响应共用同一溯源装配实现，避免「开始作答」后原文抽屉短暂为空
        return self._attach_source_snippets_to_items(practice, user_id)

    def _replay_idempotent_practice(
        self,
        cached_result: dict[str, Any],
        user_id: uuid.UUID,
    ) -> Practice | None:
        """从幂等响应快照回放既有练习实体，快照非法或实体缺失时返回 None。"""
        raw_practice_id = cached_result.get("practice_id")
        if not isinstance(raw_practice_id, str):
            return None
        try:
            practice_id = uuid.UUID(raw_practice_id)
        except (ValueError, TypeError):
            return None
        return self.practice_repo.get_practice_by_id(
            practice_id=practice_id,
            user_id=user_id,
            include_items=True,
        )

    def _resolve_folder_scope_knowledge_points(
        self,
        user_id: uuid.UUID,
        options: CreatePracticeOptions,
    ) -> list[uuid.UUID]:
        """解析练习目标考点集，支持课程文件夹范围。

        未指定 ``folder_id`` 时原样返回请求考点；指定时校验课程归属（不存在/已归档
        抛 ``FolderNotFoundError``），缺省考点取该文件夹全部 ready 资料考点，
        显式考点则逐个校验其归属资料属于该未归档课程。

        Args:
            user_id: 租户用户标识。
            options: 组卷配置选项。

        Returns:
            list[uuid.UUID]: 去重后保序的目标考点标识列表。

        Raises:
            FolderNotFoundError: 课程文件夹不存在、已归档或越权。
            KnowledgeNotFoundError: 显式考点不属于该课程文件夹。
            PracticeEmptyQuestionsError: 课程文件夹下无可用考点。
        """
        if options.folder_id is None:
            return list(dict.fromkeys(options.knowledge_point_ids))

        folder = self.folder_repo.get_by_id(options.folder_id, user_id, include_archived=False)
        if folder is None:
            raise FolderNotFoundError()

        explicit_ids = list(dict.fromkeys(options.knowledge_point_ids))
        if not explicit_ids:
            points = self.question_repo.list_knowledge_points_for_folder(user_id, options.folder_id)
            if not points:
                raise PracticeEmptyQuestionsError(
                    "课程文件夹下没有可用的知识点，无法组卷",
                    details={"folder_id": str(options.folder_id)},
                )
            return [point.id for point in points]

        allowed_material_ids = set(
            self.question_repo.list_material_ids_for_folder(user_id, options.folder_id)
        )
        for kp_id in explicit_ids:
            point = self.knowledge_repo.get_knowledge_point_by_id(kp_id, user_id)
            if point is None or point.material_id not in allowed_material_ids:
                raise KnowledgeNotFoundError(
                    "请求的知识点不存在、越权或不属于该课程文件夹",
                    details={"knowledge_point_id": str(kp_id)},
                )
        return explicit_ids

    def _assemble_and_persist_practice(
        self,
        user_id: uuid.UUID,
        options: CreatePracticeOptions,
        request_id: str,
        start_time: float,
        *,
        defer_commit: bool = False,
    ) -> Practice:
        """执行组卷、快照校验与原子落库 (由 create_practice 幂等外壳调用)。

        Args:
            user_id: 租户用户标识。
            options: 组卷配置选项。
            request_id: 请求跟踪标识。
            start_time: 进入 create_practice 时的高精度计时起点。

        Returns:
            Practice: 已创建的练习实体。
        """
        # Step 1: 检查防重：若来源为诊断报告且存在 NOT_STARTED 练习则直接复用 (FR-58)
        if options.source_report_id is not None:
            existing = self.practice_repo.find_active_by_source_report(
                options.source_report_id, user_id
            )
            if existing is not None:
                duration_ms = (time.perf_counter() - start_time) * 1000
                self._log_metric(
                    action="create_practice_reuse",
                    request_id=request_id,
                    user_id=user_id,
                    target_id=existing.id,
                    duration_ms=duration_ms,
                    extra={"reused": True, "source_report_id": str(options.source_report_id)},
                )
                return existing

        def _log_empty_questions(required_count: int, available_count: int) -> None:
            self._log_metric(
                action="create_practice_failed",
                request_id=request_id,
                user_id=user_id,
                target_id="empty_questions",
                duration_ms=(time.perf_counter() - start_time) * 1000,
                error_code=40012,
                extra={"required": required_count, "available": available_count},
            )

        # Step 2: 检索并抽选候选题目
        if options.question_ids:
            selected_questions, effective_kp_ids = select_explicit_questions(
                self.question_repo,
                user_id=user_id,
                question_ids=options.question_ids,
                question_count=options.question_count,
                is_random=options.mode == PracticeAssemblyMode.RANDOM,
                on_empty_metric=_log_empty_questions,
            )
        else:
            effective_kp_ids = self._resolve_folder_scope_knowledge_points(user_id, options)
            candidates = collect_interleaved_candidates(
                self.question_repo,
                user_id=user_id,
                effective_kp_ids=effective_kp_ids,
                question_types=options.question_types,
                difficulty=options.difficulty,
                required_count=options.question_count,
                on_insufficient_metric=_log_empty_questions,
            )
            selected_questions = rank_candidates_by_mode(
                candidates,
                mode_value=options.mode.value,
                question_count=options.question_count,
                diagnosis_repo=self.diagnosis_repo,
                user_id=user_id,
            )

        # Step 3: 同知识点打散、快照校验与持久化
        scattered_questions = scatter_adjacent_knowledge_questions(
            selected_questions,
            knowledge_id_getter=lambda q: q.knowledge_point_id,
        )
        kp_ids_for_names = {
            q.knowledge_point_id for q in scattered_questions if q.knowledge_point_id is not None
        }
        kp_name_map = (
            {
                kp.id: kp.name
                for kp in self.knowledge_repo.list_by_ids(list(kp_ids_for_names), user_id)
            }
            if kp_ids_for_names and hasattr(self, "knowledge_repo")
            else {}
        )
        snapshots = build_validated_snapshots(scattered_questions, kp_name_map=kp_name_map)

        resolved_material_id = options.material_id
        if resolved_material_id is None and options.folder_id is None:
            resolved_material_id = scattered_questions[0].material_id

        try:
            practice = Practice(
                material_id=resolved_material_id,
                folder_id=options.folder_id,
                title=options.title,
                knowledge_point_ids=[str(kp) for kp in effective_kp_ids],
                question_types=list(options.question_types) if options.question_types else [],
                difficulty=options.difficulty,
                question_count=len(scattered_questions),
                ordered_question_ids=[str(q.id) for q in scattered_questions],
                status=PracticeStatus.NOT_STARTED.value,
                source_type=options.source_type,
                mode=options.mode.value,
                source_report_id=options.source_report_id,
            )
            created_practice = self.practice_repo.create_practice(practice, user_id)

            attempt_items = [
                AttemptItem(
                    practice_id=created_practice.id,
                    question_id=q.id,
                    order_index=idx,
                    question_snapshot=snapshots[idx - 1],
                    is_answered=False,
                    duration_seconds=0,
                )
                for idx, q in enumerate(scattered_questions, start=1)
            ]
            self.practice_repo.create_attempt_items(attempt_items, user_id)
            if defer_commit:
                self.session.flush()
            else:
                self.session.commit()

            duration_ms = (time.perf_counter() - start_time) * 1000
            self._log_metric(
                action="create_practice_success",
                request_id=request_id,
                user_id=user_id,
                target_id=created_practice.id,
                duration_ms=duration_ms,
                extra={
                    "question_count": len(scattered_questions),
                    "mode": options.mode.value,
                },
            )
            return created_practice
        except Exception:
            if not defer_commit:
                self.session.rollback()
            raise

    def get_practice(
        self,
        user_id: uuid.UUID,
        practice_id: uuid.UUID,
    ) -> PracticeDetailResponse:
        """获取练习详情、题目作答项及来源切片溯源信息。

        Args:
            user_id: 租户用户标识。
            practice_id: 练习主键。

        Returns:
            PracticeDetailResponse: 练习详情 DTO (含生效判题要点与来源切片)。

        Raises:
            PracticeNotFoundError: 练习不存在或无权访问。
        """
        practice = self.practice_repo.get_practice_by_id(practice_id, user_id, include_items=True)
        if practice is None:
            raise PracticeNotFoundError(
                "请求的练习不存在或无权访问",
                details={"practice_id": str(practice_id)},
            )
        detail = PracticeDetailResponse.model_validate(practice)
        self._attach_source_snippets(detail, user_id)
        return detail

    @staticmethod
    def _snapshot_source_snippet_id(
        item: PracticeItemDetailResponse | AttemptItem,
    ) -> uuid.UUID | None:
        """安全解析作答项快照中的来源切片主键。

        Args:
            item: 作答项详情 DTO 或 ORM 作答项实体。

        Returns:
            uuid.UUID | None: 合法切片主键；缺失或非法时返回 None。
        """
        snapshot = item.question_snapshot
        raw: Any
        if isinstance(snapshot, QuestionSnapshotDTO):
            raw = snapshot.source_snippet_id
        elif isinstance(snapshot, dict):
            raw = snapshot.get("source_snippet_id")
        else:
            raw = None
        if not raw:
            return None
        try:
            return uuid.UUID(str(raw))
        except (ValueError, TypeError):
            return None

    def _build_source_snippet_map(
        self,
        items: Sequence[PracticeItemDetailResponse | AttemptItem],
        user_id: uuid.UUID,
    ) -> dict[uuid.UUID, SourceSnippetDTO]:
        """按快照 ``source_snippet_id`` 批量装载原文切片投影。

        本方法只负责练习域特有的「从快照提取切片主键」；投影构造与页码回退规则
        委托 ``build_source_snippet_map``（题目侧共用同一实现），保证两侧来源模型不会漂移。
        查询详情路径与创建练习路径都复用本方法。

        Args:
            items: 作答项详情 DTO 或 ORM 作答项实体序列。
            user_id: 租户用户标识。

        Returns:
            dict[uuid.UUID, SourceSnippetDTO]: 切片主键到投影对象的映射。
        """
        snippet_ids: set[uuid.UUID] = set()
        for item in items:
            snippet_id = self._snapshot_source_snippet_id(item)
            if snippet_id is not None:
                snippet_ids.add(snippet_id)

        return build_source_snippet_map(self.material_repo, snippet_ids, user_id)

    @staticmethod
    def _snapshot_missing_kp_id(
        item: PracticeItemDetailResponse | AttemptItem,
    ) -> uuid.UUID | None:
        """提取尚未携带知识点名称的快照中的 knowledge_point_id。"""
        snapshot = item.question_snapshot
        if isinstance(snapshot, QuestionSnapshotDTO):
            if snapshot.knowledge_point_name:
                return None
            raw = snapshot.knowledge_point_id
        elif isinstance(snapshot, dict):
            if snapshot.get("knowledge_point_name"):
                return None
            raw = snapshot.get("knowledge_point_id")
        else:
            raw = None
        if not raw:
            return None
        try:
            return uuid.UUID(str(raw))
        except (ValueError, TypeError):
            return None

    def _build_kp_name_map(
        self,
        items: Sequence[PracticeItemDetailResponse | AttemptItem],
        user_id: uuid.UUID,
    ) -> dict[uuid.UUID, str]:
        """批量装载作答项快照缺失的知识点名称映射。"""
        if not hasattr(self, "knowledge_repo"):
            return {}
        kp_ids: set[uuid.UUID] = set()
        for item in items:
            kp_id = self._snapshot_missing_kp_id(item)
            if kp_id is not None:
                kp_ids.add(kp_id)
        if not kp_ids:
            return {}
        return {kp.id: kp.name for kp in self.knowledge_repo.list_by_ids(list(kp_ids), user_id)}

    def _attach_source_snippets(
        self,
        detail: PracticeDetailResponse,
        user_id: uuid.UUID,
    ) -> None:
        """按 source_snippet_id 批量关联切片摘要，并补齐历史快照缺失的知识点名称。

        Args:
            detail: 已装配的练习详情 DTO (就地补全 source_snippet 与 knowledge_point_name)。
            user_id: 租户用户标识。
        """
        snippet_map = self._build_source_snippet_map(detail.items, user_id)
        kp_name_map = self._build_kp_name_map(detail.items, user_id)
        if not snippet_map and not kp_name_map:
            return

        for item in detail.items:
            snippet_id = self._snapshot_source_snippet_id(item)
            snippet_dto = snippet_map.get(snippet_id) if snippet_id is not None else None
            if snippet_dto is not None:
                item.source_snippet = snippet_dto
                snapshot = item.question_snapshot
                if isinstance(snapshot, QuestionSnapshotDTO):
                    snapshot.source_snippet = snippet_dto
                elif isinstance(snapshot, dict):
                    snapshot["source_snippet"] = snippet_dto

            kp_id = self._snapshot_missing_kp_id(item)
            kp_name = kp_name_map.get(kp_id) if kp_id is not None else None
            if kp_name is not None:
                snapshot = item.question_snapshot
                if isinstance(snapshot, QuestionSnapshotDTO):
                    snapshot.knowledge_point_name = kp_name
                elif isinstance(snapshot, dict):
                    snapshot["knowledge_point_name"] = kp_name

    def _attach_source_snippets_to_items(
        self,
        practice: Practice,
        user_id: uuid.UUID,
    ) -> PracticeView:
        """将练习及作答项包装为携带原文溯源投影的强类型视图，杜绝 ORM 实例动态挂载属性。

        Args:
            practice: 已持久化的练习实体。
            user_id: 租户用户标识。

        Returns:
            PracticeView: 包装后的练习只读兼容视图。
        """
        items = list(practice.items or [])
        snippet_map = self._build_source_snippet_map(items, user_id)
        return wrap_practice_with_source_snippets(
            practice,
            snippet_map,
            self._snapshot_source_snippet_id,
        )

    def list_practices(
        self,
        user_id: uuid.UUID,
        *,
        material_id: uuid.UUID | None = None,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Practice]:
        """多维分页查询用户的练习列表。"""
        return self.practice_repo.list_practices(
            user_id,
            material_id=material_id,
            status=status,
            limit=limit,
            offset=offset,
        )

    def save_answer(
        self,
        user_id: uuid.UUID,
        dto: SaveAnswerDTO | None = None,
        request_id: str = "",
        *,
        practice_id: uuid.UUID | None = None,
        question_id: uuid.UUID | None = None,
        user_answer: Any = None,
        time_spent_seconds: int = 0,
        duration_seconds: int = 0,
    ) -> AttemptItem:
        """逐题保存用户作答并累加耗时。

        Args:
            user_id: 租户用户标识。
            dto: 作答传输对象。
            request_id: 请求跟踪标识。
            practice_id: 练习主键标识。
            question_id: 题目主键标识。
            user_answer: 用户作答文本或选项标识。
            time_spent_seconds: 本次作答耗时（秒）。
            duration_seconds: 作答耗时别名（秒）。

        Returns:
            AttemptItem: 更新后的作答项。

        Raises:
            PracticeNotFoundError: 练习或题目作答项不存在。
            PracticeStatusError: 练习状态不允许修改作答。
        """
        if dto is None:
            if practice_id is None or question_id is None:
                raise ValueError("practice_id 与 question_id 在未提供 dto 时必须传入")
            effective_duration = duration_seconds if duration_seconds > 0 else time_spent_seconds
            dto = SaveAnswerDTO(
                practice_id=practice_id,
                question_id=question_id,
                user_answer=_serialize_user_answer(user_answer),
                duration_seconds=effective_duration,
            )

        start_time = time.perf_counter()

        practice = self.practice_repo.get_practice_by_id(
            dto.practice_id, user_id, include_items=False
        )
        if practice is None:
            raise PracticeNotFoundError(
                "请求的练习不存在或无权访问",
                details={"practice_id": str(dto.practice_id)},
            )

        if practice.status not in (
            PracticeStatus.NOT_STARTED.value,
            PracticeStatus.IN_PROGRESS.value,
        ):
            raise PracticeStatusError(
                "当前练习状态不允许修改作答",
                details={"status": practice.status},
            )

        try:
            # 若状态为未开始，自动跃迁为作答中
            if practice.status == PracticeStatus.NOT_STARTED.value:
                self.practice_repo.update_practice_status(
                    dto.practice_id, user_id, PracticeStatus.IN_PROGRESS.value
                )

            item = self.practice_repo.save_answer(
                practice_id=dto.practice_id,
                question_id=dto.question_id,
                user_id=user_id,
                user_answer=dto.user_answer,
                duration_seconds=dto.duration_seconds,
            )
            self.session.commit()

            duration_ms = (time.perf_counter() - start_time) * 1000
            self._log_metric(
                action="save_answer_success",
                request_id=request_id,
                user_id=user_id,
                target_id=item.id,
                duration_ms=duration_ms,
                extra={"is_answered": item.is_answered, "duration_s": item.duration_seconds},
            )
            return item
        except Exception:
            self.session.rollback()
            raise

    def pause_practice(
        self,
        user_id: uuid.UUID,
        practice_id: uuid.UUID,
        request_id: str = "",
    ) -> Practice:
        """暂停正在进行中的练习会话。"""
        practice = self.practice_repo.get_practice_by_id(practice_id, user_id, include_items=False)
        if practice is None:
            raise PracticeNotFoundError(
                "请求的练习不存在或无权访问",
                details={"practice_id": str(practice_id)},
            )
        if practice.status != PracticeStatus.IN_PROGRESS.value:
            raise PracticeStatusError(
                "当前状态不允许暂停",
                details={"status": practice.status},
            )

        try:
            self.practice_repo.update_practice_status(
                practice_id, user_id, PracticeStatus.PAUSED.value
            )
            self.session.commit()
            refreshed = self.practice_repo.get_practice_by_id(
                practice_id, user_id, include_items=False
            )
            if refreshed is None:
                raise PracticeNotFoundError(
                    "练习实体不存在", details={"practice_id": str(practice_id)}
                )
            return refreshed
        except Exception:
            self.session.rollback()
            raise

    def resume_practice(
        self,
        user_id: uuid.UUID,
        practice_id: uuid.UUID,
        request_id: str = "",
    ) -> Practice:
        """恢复已暂停的练习会话。"""
        practice = self.practice_repo.get_practice_by_id(practice_id, user_id, include_items=False)
        if practice is None:
            raise PracticeNotFoundError(
                "请求的练习不存在或无权访问",
                details={"practice_id": str(practice_id)},
            )
        if practice.status != PracticeStatus.PAUSED.value:
            raise PracticeStatusError(
                "当前状态不允许恢复",
                details={"status": practice.status},
            )

        try:
            self.practice_repo.update_practice_status(
                practice_id, user_id, PracticeStatus.IN_PROGRESS.value
            )
            self.session.commit()
            refreshed = self.practice_repo.get_practice_by_id(
                practice_id, user_id, include_items=False
            )
            if refreshed is None:
                raise PracticeNotFoundError(
                    "练习实体不存在", details={"practice_id": str(practice_id)}
                )
            return refreshed
        except Exception:
            self.session.rollback()
            raise

    def submit_practice(
        self,
        user_id: uuid.UUID,
        dto: SubmitPracticeDTO | None = None,
        request_id: str = "",
        *,
        practice_id: uuid.UUID | None = None,
        idempotency_key: str | None = None,
        confirm_unanswered: bool = False,
    ) -> PracticeSubmissionResult:
        """交卷强幂等调度与判题任务派发。

        Args:
            user_id: 租户用户标识。
            dto: 交卷传输对象。
            request_id: 请求跟踪标识。
            practice_id: 练习主键标识。
            idempotency_key: 客户端强幂等键。
            confirm_unanswered: 是否确认提交未作答题目。

        Returns:
            PracticeSubmissionResult: 交卷执行结果。

        Raises:
            PracticeNotFoundError: 练习不存在。
            PracticeStatusError: 状态非法或未确认未作答题目。
            IdempotencyConflictError: 幂等并发锁抢占失败。
        """
        if dto is None:
            if practice_id is None or idempotency_key is None:
                raise ValueError("practice_id 与 idempotency_key 在未提供 dto 时必须传入")
            dto = SubmitPracticeDTO(
                practice_id=practice_id,
                idempotency_key=idempotency_key,
                confirm_unanswered=confirm_unanswered,
            )

        start_time = time.perf_counter()
        clean_key = validate_idempotency_key(dto.idempotency_key)

        # 1. 强幂等快照命中检查与回放 (FR-35)
        cached_result = self.idempotency.get_result(clean_key, str(user_id))
        if cached_result is not None:
            duration_ms = (time.perf_counter() - start_time) * 1000
            self._log_metric(
                action="submit_practice_replay",
                request_id=request_id,
                user_id=user_id,
                target_id=cached_result["practice_id"],
                duration_ms=duration_ms,
                extra={"replayed": True},
            )
            return PracticeSubmissionResult(
                practice_id=uuid.UUID(cached_result["practice_id"]),
                task_id=cached_result["task_id"],
                status=cached_result["status"],
                unanswered_count=cached_result["unanswered_count"],
                total_questions=cached_result["total_questions"],
                submitted_at=datetime.fromisoformat(cached_result["submitted_at"]),
                answered_questions=cached_result.get(
                    "answered_questions",
                    cached_result["total_questions"] - cached_result["unanswered_count"],
                ),
                uncompleted_count=cached_result.get(
                    "uncompleted_count",
                    cached_result["unanswered_count"],
                ),
                is_idempotent_replay=True,
            )

        # 2. 抢占幂等分布式锁
        self.idempotency.acquire_lock(
            clean_key, str(user_id), ttl_seconds=60, raise_on_conflict=True
        )

        try:
            practice = self.practice_repo.get_practice_by_id(
                dto.practice_id, user_id, include_items=False
            )
            if practice is None:
                raise PracticeNotFoundError(
                    "请求的练习不存在或无权访问",
                    details={"practice_id": str(dto.practice_id)},
                )

            if practice.status in (
                PracticeStatus.SUBMITTED.value,
                PracticeStatus.PARTIALLY_GRADED.value,
                PracticeStatus.COMPLETED.value,
            ):
                # DB 级幂等兜底回放 (BUG-PRAC-013)：快照写入曾失败但事务已提交，
                # 同一幂等键的重试不再抛 40011，而是从已提交实体安全重建结果。
                if practice.submit_idempotency_key == clean_key:
                    replay_result = self._rebuild_persisted_submission(practice, user_id)
                    self._release_lock_quietly(clean_key, user_id)
                    duration_ms = (time.perf_counter() - start_time) * 1000
                    self._log_metric(
                        action="submit_practice_replay_db",
                        request_id=request_id,
                        user_id=user_id,
                        target_id=practice.id,
                        duration_ms=duration_ms,
                        extra={"replayed": True, "source": "persisted_key"},
                    )
                    return replay_result
                raise PracticeStatusError(
                    "练习已完成，禁止重复提交",
                    details={"status": practice.status},
                )

            if practice.status not in (
                PracticeStatus.IN_PROGRESS.value,
                PracticeStatus.NOT_STARTED.value,
                PracticeStatus.PAUSED.value,
            ):
                raise PracticeStatusError(
                    "当前练习状态不允许交卷",
                    details={"status": practice.status},
                )

            # 3. 统计未作答题目 (FR-36)
            unanswered_count = self.practice_repo.count_unanswered_items(dto.practice_id, user_id)
            total_questions = self.practice_repo.count_total_items(dto.practice_id, user_id)

            if unanswered_count > 0 and not dto.confirm_unanswered:
                raise PracticeStatusError(
                    "存在未作答题目，需确认后方可交卷",
                    details={
                        "unanswered_count": unanswered_count,
                        "total_questions": total_questions,
                    },
                )

            # 4. 事务原子 CAS 跃迁交卷状态 + 客观题即时判分 (Commit-First，严禁先入队后提交)
            now = datetime.now(UTC)
            transitioned = self.practice_repo.try_transition_status(
                dto.practice_id,
                user_id,
                from_status=practice.status,
                to_status=PracticeStatus.SUBMITTED.value,
                submit_idempotency_key=clean_key,
                submitted_at=now,
            )
            if not transitioned:
                raise PracticeStatusError(
                    "练习已提交或状态已变更，请勿重复提交",
                    details={"status": practice.status},
                )
            refreshed_practice = (
                self.practice_repo.get_practice_by_id(dto.practice_id, user_id, include_items=False)
                or practice
            )
            final_status, needs_async = self._process_submission_grading(
                practice=refreshed_practice,
                practice_id=dto.practice_id,
                user_id=user_id,
                submitted_at=now,
            )

            self.session.commit()

            task_id = ""
            if needs_async:
                try:
                    task_id = self.queue.enqueue(
                        task_name="grading_jobs",
                        payload={
                            "practice_id": str(dto.practice_id),
                            "user_id": str(user_id),
                        },
                        user_id=str(user_id),
                    )
                except Exception:
                    self._compensate_grading_enqueue_failure(dto.practice_id, user_id)
                    raise
            elif isinstance(self.session, Session):
                from app.services.diagnosis import DiagnosisService

                DiagnosisService(self.session).ensure_diagnosis_report(
                    user_id=user_id,
                    practice_id=dto.practice_id,
                )

            answered_count = total_questions - unanswered_count
            result = PracticeSubmissionResult(
                practice_id=dto.practice_id,
                task_id=task_id,
                status=final_status,
                unanswered_count=unanswered_count,
                total_questions=total_questions,
                submitted_at=now,
                answered_questions=answered_count,
                uncompleted_count=unanswered_count,
            )

            # 6. 持久化幂等响应快照 (容错隔离：快照写入失败不得让已提交请求返回 5xx)
            try:
                self.idempotency.set_result(
                    clean_key,
                    str(user_id),
                    {
                        "practice_id": str(result.practice_id),
                        "task_id": result.task_id,
                        "status": result.status,
                        "unanswered_count": result.unanswered_count,
                        "total_questions": result.total_questions,
                        "submitted_at": result.submitted_at.isoformat(),
                        "answered_questions": result.answered_questions,
                        "uncompleted_count": result.uncompleted_count,
                    },
                    ttl_seconds=86400,
                )
            except Exception:
                logger.warning(
                    "Idempotency snapshot persist degraded; relying on DB key replay "
                    "for user_ref=%s target_id=%s",
                    generate_user_ref(user_id),
                    dto.practice_id,
                )
                # 释放处理中锁，确保同键重试可重新进入并走 DB 级回放。
                self._release_lock_quietly(clean_key, user_id)

            duration_ms = (time.perf_counter() - start_time) * 1000
            self._log_metric(
                action="submit_practice_success",
                request_id=request_id,
                user_id=user_id,
                target_id=dto.practice_id,
                duration_ms=duration_ms,
                extra={
                    "total": total_questions,
                    "unanswered": unanswered_count,
                    "task_id": task_id,
                },
            )
            return result
        except Exception:
            self.session.rollback()
            self._release_lock_quietly(clean_key, user_id)
            raise

    def _process_submission_grading(
        self,
        *,
        practice: Practice,
        practice_id: uuid.UUID,
        user_id: uuid.UUID,
        submitted_at: datetime,
    ) -> tuple[str, bool]:
        """交卷即时客观题判分与状态推进（仅写 DB，不在此处入队以确保 Commit-First）。"""
        items = self.practice_repo.list_attempt_items(practice_id, user_id)
        grading_repo = GradingRepository(self.session)
        needs_async_grading = False
        graded_any = False

        for item in items:
            snapshot = item.question_snapshot or {}
            q_type = str(snapshot.get("question_type") or "").strip().lower()
            if q_type not in OBJECTIVE_QUESTION_TYPES:
                needs_async_grading = True
                continue
            try:
                record, requires_llm = grade_offline_attempt_item(
                    item,
                    practice_id=practice_id,
                    user_id=user_id,
                    grading_repo=grading_repo,
                    allow_high_confidence_subjective=False,
                )
            except Exception:
                logger.warning("交卷同步判客观题降级至异步队列 item_id=%s", item.id)
                needs_async_grading = True
                continue
            if requires_llm or record is None:
                needs_async_grading = True
            else:
                graded_any = True

        if not needs_async_grading:
            practice.total_score = round(sum(it.score or 0.0 for it in items), 2)
            practice.status = PracticeStatus.COMPLETED.value
            practice.completed_at = submitted_at
            self.session.flush()
            # COMPLETED 路径不提前调用 sync_practice_learning_state，避免双写覆盖
            # previous_score 导致退步知识点恒为空；交由提交后的 ensure_diagnosis_report 单次完成。
            return PracticeStatus.COMPLETED.value, False

        if graded_any and isinstance(self.session, Session):
            self.session.flush()
            from app.services.diagnosis import DiagnosisService

            DiagnosisService(self.session).sync_practice_learning_state(
                user_id=user_id,
                practice_id=practice_id,
                partial_ok=True,
                commit=False,
            )

        return PracticeStatus.SUBMITTED.value, True

    # --------------------------------------------------------------------------
    # 判题任务终态失败回写与主动重试 (AC-9 / design.md 第 19 条)
    # --------------------------------------------------------------------------

    def mark_grading_failed(
        self,
        user_id: uuid.UUID,
        practice_id: uuid.UUID,
        *,
        reason: str = "",
        request_id: str = "",
    ) -> Practice | None:
        """把判题任务终态失败的练习回写为「待重判」，供用户可见并可主动恢复。

        仅当练习仍停留在 ``submitted``（即判题任务从未成功跑完）时才回写为
        ``partially_graded``；已是 ``completed`` / ``partially_graded`` /
        ``timeout`` 的记录一律跳过，绝不回退已生效的判分结果，重复回调天然幂等。
        ``completed_at`` 保持为空，因此 ``DiagnosisService`` 的
        「全卷判完才可生成报告」门禁不会被绕过。

        Args:
            user_id: 租户用户标识。
            practice_id: 练习主键。
            reason: 失败原因摘要（仅记录长度与类型，严禁写入用户作答原文）。
            request_id: 请求跟踪标识。

        Returns:
            Practice | None: 回写后的练习实体；练习不存在时返回 None。
        """
        practice = self.practice_repo.get_practice_by_id(practice_id, user_id, include_items=False)
        if practice is None:
            logger.error(
                "判题任务终态失败但练习不存在 target_id=%s user_ref=%s",
                practice_id,
                generate_user_ref(user_id),
            )
            return None

        if practice.status != PracticeStatus.SUBMITTED.value:
            # 已终态或已可恢复：幂等跳过，绝不回退已完成的判分结果
            return practice

        self.practice_repo.update_practice_status(
            practice_id,
            user_id,
            PracticeStatus.PARTIALLY_GRADED.value,
        )
        self.session.commit()
        self._log_metric(
            action="mark_grading_failed",
            request_id=request_id,
            user_id=user_id,
            target_id=practice_id,
            duration_ms=0.0,
            error_code=40015,
            extra={"final_status": practice.status, "reason_len": len(reason)},
        )
        return practice

    def retry_grading(
        self,
        user_id: uuid.UUID,
        practice_id: uuid.UUID,
        request_id: str = "",
    ) -> tuple[str, Practice]:
        """主动重试未完成的整卷判题（用户可操作、幂等、可恢复）。

        允许重试的前置条件是练习处于 ``partially_graded``（判题已跑完但存在待重判项，
        或判题任务终态失败被回写）。判题任务只允许派发一次：状态从 ``partially_graded``
        到 ``submitted`` 的跃迁走数据库条件更新（compare-and-swap），并发触发的第二次
        请求会因未能改到该行而被拒绝，因此不会重复入队。``GradingService.grade_practice``
        对已判定成功的作答项同样幂等跳过，``completed_at`` 只在全部题目真正判完时写入。

        Args:
            user_id: 租户用户标识。
            practice_id: 练习主键。
            request_id: 请求跟踪标识。

        Returns:
            tuple[str, Practice]: (判题任务标识, 回写为 submitted 的练习实体)。

        Raises:
            PracticeNotFoundError: 练习不存在或无权访问。
            PracticeStatusError: 练习已全判完或当前状态不允许重试判题。
            QueueError: 判题任务入队失败（状态回滚为待重判，仍可再次重试）。
        """
        start_time = time.perf_counter()
        practice = self.practice_repo.get_practice_by_id(practice_id, user_id, include_items=False)
        if practice is None:
            raise PracticeNotFoundError(
                "请求的练习不存在或无权访问",
                details={"practice_id": str(practice_id)},
            )

        if practice.status == PracticeStatus.TIMEOUT.value:
            raise PracticeStatusError(
                "练习已超时冻结，无法重试判题",
                details={"status": practice.status},
            )

        if practice.completed_at is not None or practice.status == PracticeStatus.COMPLETED.value:
            raise PracticeStatusError(
                "练习已全部判分完成，无需重试判题",
                details={"status": practice.status},
            )

        if practice.status != PracticeStatus.PARTIALLY_GRADED.value:
            raise PracticeStatusError(
                "练习判题尚未结束，暂无需重试判题",
                details={"status": practice.status},
            )

        try:
            # 状态跃迁必须是数据库条件更新：并发的第二个请求不能从陈旧读到的
            # partially_graded 再次派发判题任务，否则同一批待判项会被判两遍。
            transitioned = self.practice_repo.try_transition_status(
                practice_id,
                user_id,
                from_status=PracticeStatus.PARTIALLY_GRADED.value,
                to_status=PracticeStatus.SUBMITTED.value,
            )
            if not transitioned:
                raise PracticeStatusError(
                    "判题任务已在重试中，请勿重复提交",
                    details={"status": practice.status},
                )
            # Commit-First：必须先提交 SUBMITTED 状态，再投递队列，避免 Worker 抢跑读到旧状态。
            self.session.commit()
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise PracticeStatusError(
                "判题任务状态更新失败，请稍后重试",
                details={"reason": str(exc), "original_type": type(exc).__name__},
            ) from exc
        except PracticeStatusError:
            self.session.rollback()
            raise

        try:
            task_id = self.queue.enqueue(
                task_name="grading_jobs",
                payload={
                    "practice_id": str(practice_id),
                    "user_id": str(user_id),
                },
                user_id=str(user_id),
                priority=1,
            )
        except (QueueError, SQLAlchemyError) as exc:
            # 入队失败时开启补偿短事务将 SUBMITTED 回写为 PARTIALLY_GRADED，避免卡死。
            self._compensate_grading_enqueue_failure(practice_id, user_id)
            raise PracticeStatusError(
                "判题任务入队失败，请稍后重试",
                details={"reason": str(exc), "original_type": type(exc).__name__},
            ) from exc

        # BUG-FIX: get_practice_by_id 检查也必须纳入事务边界，否则并发删除导致实体消失时
        # 状态已跃迁到 SUBMITTED 但抛错无 rollback → 练习永久卡住无法重判。
        # 修复策略：将二次校验纳入 try 块，捕获 NotFoundError 后 rollback + 包装错误。
        try:
            practice = self.practice_repo.get_practice_by_id(
                practice_id, user_id, include_items=False
            )
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise PracticeNotFoundError(
                "请求的练习不存在或无权访问",
                details={"practice_id": str(practice_id), "reason": str(exc)},
            ) from exc
        if practice is None:
            # 实体在状态跃迁 commit 期间消失，包装错误便于诊断
            raise PracticeNotFoundError(
                "请求的练习不存在或无权访问",
                details={"practice_id": str(practice_id)},
            )

        duration_ms = (time.perf_counter() - start_time) * 1000
        self._log_metric(
            action="retry_grading_dispatched",
            request_id=request_id,
            user_id=user_id,
            target_id=practice_id,
            duration_ms=duration_ms,
            extra={"task_id": task_id, "status": practice.status},
        )
        return task_id, practice


__all__ = [
    "CreatePracticeOptions",
    "PracticeAssemblyMode",
    "PracticeItemView",
    "PracticeService",
    "PracticeSubmissionResult",
    "PracticeView",
    "SaveAnswerDTO",
    "SubmitPracticeDTO",
]
