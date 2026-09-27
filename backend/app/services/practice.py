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
import random
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.algorithms.practice import scatter_adjacent_knowledge_questions
from app.core.errors import (
    AppError,
    PracticeEmptyQuestionsError,
    PracticeNotFoundError,
    PracticeStatusError,
)
from app.core.security import generate_user_ref
from app.integrations.idempotency.factory import create_idempotency_adapter
from app.integrations.idempotency.protocol import (
    IdempotencyProtocol,
    validate_idempotency_key,
)
from app.integrations.queue.factory import create_queue_adapter
from app.integrations.queue.protocol import QueueProtocol
from app.models.practice import (
    AttemptItem,
    MasteryRecord,
    Practice,
    PracticeSourceType,
    PracticeStatus,
    WrongRecord,
    validate_question_snapshot,
)
from app.models.question import Question, QuestionStatus
from app.repositories.practice import PracticeRepository
from app.repositories.question import QuestionRepository

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
        idempotency: IdempotencyProtocol | None = None,
        queue: QueueProtocol | None = None,
    ) -> None:
        """初始化练习服务实例。

        Args:
            session: SQLAlchemy 数据库会话。
            practice_repo: 可选注入的练习仓储实例。
            question_repo: 可选注入的题目仓储实例。
            idempotency: 可选注入的幂等适配器实例。
            queue: 可选注入的任务队列适配器实例。
        """
        self.session = session
        self.practice_repo = practice_repo or PracticeRepository(session)
        self.question_repo = question_repo or QuestionRepository(session)
        self.idempotency = idempotency or create_idempotency_adapter("memory")
        self.queue = queue or create_queue_adapter("memory")

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
        log_payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": "INFO" if error_code == 0 else "ERROR",
            "logger_name": __name__,
            "request_id": request_id,
            "user_ref": generate_user_ref(user_id),
            "target_id": str(target_id),
            "duration_ms": round(duration_ms, 2),
            "error_code": error_code,
            "action": action,
        }
        if extra:
            log_payload.update(extra)

        if error_code == 0:
            logger.info("PracticeService execution completed: %s", log_payload)
        else:
            logger.error("PracticeService execution error: %s", log_payload)

    def _release_lock_quietly(self, clean_key: str, user_id: uuid.UUID) -> None:
        """尽力释放幂等锁，失败仅记录告警，绝不阻断主流程。"""
        try:
            self.idempotency.release_lock(clean_key, str(user_id))
        except Exception:
            logger.warning("Idempotency lock release degraded for user_ref=%s", user_id)

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
            status=PracticeStatus.COMPLETED.value,
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
    ) -> Practice:
        """创建练习会话并执行组卷与题目打散。

        Args:
            user_id: 租户用户标识。
            options: 组卷配置选项。
            request_id: 请求跟踪标识。

        Returns:
            Practice: 已创建的练习实体。

        Raises:
            PracticeEmptyQuestionsError: 可用题目不足以满足题量要求。
            AppError: 快照校验失败或系统异常。
        """
        start_time = time.perf_counter()

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

        # Step 2: 检索候选可用题目 (按知识点轮转交织，保证各知识点均衡覆盖)
        kp_questions_map: dict[uuid.UUID, list[Question]] = {}
        total_available = 0
        for kp_id in options.knowledge_point_ids:
            kp_questions = self.question_repo.list_questions_by_knowledge_point(
                knowledge_point_id=kp_id,
                user_id=user_id,
                status=QuestionStatus.AVAILABLE.value,
                include_deleted=False,
            )
            if options.question_types:
                type_set = set(options.question_types)
                kp_questions = [q for q in kp_questions if q.question_type in type_set]
            if options.difficulty is not None:
                kp_questions = [q for q in kp_questions if q.difficulty == options.difficulty]
            kp_questions_map[kp_id] = kp_questions
            total_available += len(kp_questions)

        # 题量门禁校验
        if total_available < options.question_count:
            duration_ms = (time.perf_counter() - start_time) * 1000
            self._log_metric(
                action="create_practice_failed",
                request_id=request_id,
                user_id=user_id,
                target_id="empty_questions",
                duration_ms=duration_ms,
                error_code=40012,
                extra={"required": options.question_count, "available": total_available},
            )
            raise PracticeEmptyQuestionsError(
                "题库可用题目不足，无法满足当前出题配置要求",
                details={
                    "required": options.question_count,
                    "available": total_available,
                },
            )

        # 轮转交织候选题目
        interleaved_candidates: list[Question] = []
        max_kp_len = max((len(qs) for qs in kp_questions_map.values()), default=0)
        for idx in range(max_kp_len):
            for kp_id in options.knowledge_point_ids:
                qs = kp_questions_map[kp_id]
                if idx < len(qs):
                    interleaved_candidates.append(qs[idx])

        # 去重保持唯一
        seen_ids: set[uuid.UUID] = set()
        filtered_candidates: list[Question] = []
        for q in interleaved_candidates:
            if q.id not in seen_ids:
                seen_ids.add(q.id)
                filtered_candidates.append(q)

        # Step 3: 根据模式排序抽题
        selected_questions: list[Question]
        if options.mode == PracticeAssemblyMode.WEAK_POINTS:
            # 查询未攻克错题与低掌握度知识点
            wrong_q_stmt = select(WrongRecord.question_id).where(
                WrongRecord.user_id == user_id,
                WrongRecord.is_mastered.is_(False),
            )
            unmastered_wrong_ids = set(self.session.execute(wrong_q_stmt).scalars().all())

            weak_kp_stmt = select(MasteryRecord.knowledge_point_id).where(
                MasteryRecord.user_id == user_id,
                MasteryRecord.mastery_score < 0.40,
            )
            weak_kp_ids = set(self.session.execute(weak_kp_stmt).scalars().all())

            def _weakness_priority(q: Question) -> tuple[int, int]:
                is_wrong = 1 if q.id in unmastered_wrong_ids else 0
                is_weak = 1 if q.knowledge_point_id in weak_kp_ids else 0
                return (is_wrong, is_weak)

            filtered_candidates.sort(key=_weakness_priority, reverse=True)
            selected_questions = filtered_candidates[: options.question_count]
        elif options.mode == PracticeAssemblyMode.RANDOM:
            shuffled = list(filtered_candidates)
            random.shuffle(shuffled)
            selected_questions = shuffled[: options.question_count]
        else:  # SEQUENTIAL
            selected_questions = filtered_candidates[: options.question_count]

        # Step 4: 纯函数同知识点不相邻打散 (FR-31)
        scattered_questions = scatter_adjacent_knowledge_questions(
            selected_questions,
            knowledge_id_getter=lambda q: q.knowledge_point_id,
        )

        # Step 5: 题目 6 要素快照完整性校验与持久化
        snapshots: list[dict[str, Any]] = []
        for q in scattered_questions:
            snapshot = {
                "stem": q.stem,
                "question_type": q.question_type,
                "options": q.options or [],
                "answer": q.answer,
                "analysis": q.analysis or "",
                "explanation": q.analysis or "",
                "difficulty": q.difficulty,
                "source_snippet_id": str(q.source_snippet_id) if q.source_snippet_id else None,
                "grading_rubric": q.grading_rubric or {},
            }
            is_valid, err_msg = validate_question_snapshot(snapshot)
            if not is_valid:
                raise AppError(
                    error_code=40008,
                    message=f"题目快照质检未通过: {err_msg}",
                    details={"question_id": str(q.id), "reason": err_msg},
                )
            snapshots.append(snapshot)

        # Step 4.5: 解析归属资料 (缺省时由选中题目回填，支持错题本等无资料上下文来源)
        resolved_material_id = options.material_id
        if resolved_material_id is None:
            resolved_material_id = scattered_questions[0].material_id

        try:
            practice = Practice(
                material_id=resolved_material_id,
                title=options.title,
                knowledge_point_ids=[str(kp) for kp in options.knowledge_point_ids],
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
            self.session.rollback()
            raise

    def get_practice(
        self,
        user_id: uuid.UUID,
        practice_id: uuid.UUID,
    ) -> Practice:
        """获取练习详情及其题目作答项。

        Args:
            user_id: 租户用户标识。
            practice_id: 练习主键。

        Returns:
            Practice: 练习实体。

        Raises:
            PracticeNotFoundError: 练习不存在或无权访问。
        """
        practice = self.practice_repo.get_practice_by_id(practice_id, user_id, include_items=True)
        if practice is None:
            raise PracticeNotFoundError(
                "请求的练习不存在或无权访问",
                details={"practice_id": str(practice_id)},
            )
        return practice

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

    def timeout_practice(
        self,
        user_id: uuid.UUID,
        practice_id: uuid.UUID,
        request_id: str = "",
    ) -> Practice:
        """练习作答超时归档。"""
        practice = self.practice_repo.get_practice_by_id(practice_id, user_id, include_items=False)
        if practice is None:
            raise PracticeNotFoundError(
                "请求的练习不存在或无权访问",
                details={"practice_id": str(practice_id)},
            )
        if practice.status == PracticeStatus.COMPLETED.value:
            raise PracticeStatusError(
                "练习已完成，禁止标记超时",
                details={"status": practice.status},
            )

        try:
            self.practice_repo.update_practice_status(
                practice_id, user_id, PracticeStatus.TIMEOUT.value
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

            if practice.status == PracticeStatus.COMPLETED.value:
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

            # 4. 事务原子更新练习状态与交卷时间
            now = datetime.now(UTC)
            self.practice_repo.update_practice_status(
                dto.practice_id,
                user_id,
                PracticeStatus.COMPLETED.value,
                submit_idempotency_key=clean_key,
                submitted_at=now,
            )

            # 5. 异步派发判题任务
            task_id = self.queue.enqueue(
                task_name="grading_jobs",
                payload={
                    "practice_id": str(dto.practice_id),
                    "user_id": str(user_id),
                },
                user_id=str(user_id),
            )

            self.session.commit()

            answered_count = total_questions - unanswered_count
            result = PracticeSubmissionResult(
                practice_id=dto.practice_id,
                task_id=task_id,
                status=PracticeStatus.COMPLETED.value,
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
                    user_id,
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
            self.idempotency.release_lock(clean_key, str(user_id))
            raise


__all__ = [
    "CreatePracticeOptions",
    "PracticeAssemblyMode",
    "PracticeService",
    "PracticeSubmissionResult",
    "SaveAnswerDTO",
    "SubmitPracticeDTO",
]
