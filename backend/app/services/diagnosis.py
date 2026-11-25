"""学情诊断、掌握度衰减聚合与错题联动领域服务。

负责协调 DiagnosisRepository、PracticeRepository、KnowledgeRepository 与 GradingRepository，
调用纯函数计算核 aggregate_mastery_scores 与 synthesize_diagnosis_report，
完成单/多知识点掌握度 30 天半衰期衰减加权聚合、学情诊断报告原子生成、状态机阻断校验与错题本联动。
严格遵循 AGENTS.md 规范：
- app/services 是全系统唯一允许开启数据库事务的层；
- 缩写白名单仅限 8 个 (api, id, url, ocr, llm, db, config, env)；
- 8 要素结构化脱敏日志输出，绝密脱敏红线：严禁向日志记录题干、选项、答案与用户作答原文；
- 纯函数计算核隔离调度。
"""

import logging
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.algorithms.diagnosis import synthesize_diagnosis_report
from app.core.algorithms.mastery import (
    AttemptRecord,
    GradingSourceType,
    aggregate_mastery_scores,
)
from app.core.errors import (
    AppError,
    DiagnosisReportNotFoundError,
    MasteryRecordNotFoundError,
    PracticeNotFoundError,
    PracticeNotGradedError,
    QuestionNotFoundError,
    WrongRecordNotFoundError,
)
from app.core.logging import log_structured_metric
from app.models.practice import (
    DiagnosisReport,
    ErrorType,
    GradingStatus,
    MasteryLevel,
    MasteryRecord,
    PracticeStatus,
    WrongRecord,
    build_question_snapshot,
    validate_question_snapshot,
)
from app.repositories.diagnosis import DiagnosisRepository
from app.repositories.grading import GradingRepository
from app.repositories.knowledge import KnowledgeRepository
from app.repositories.practice import PracticeRepository
from app.repositories.question import QuestionRepository
from app.services._diagnosis_report import (
    MasteryBaselineSnapshot,
    apply_diagnosis_report_updates,
    build_diagnosis_report_entity,
    build_evaluation_inputs_and_mistakes,
    collect_involved_point_ids,
    ensure_utc,
    evaluate_graded_items_partial,
    evaluate_practice_items,
    sync_wrong_records_from_evaluations,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class KnowledgeMasterySummaryDTO:
    """单知识点掌握度汇总数据传输实体。"""

    knowledge_point_id: uuid.UUID
    knowledge_name: str
    mastery_score: float
    level: str
    practice_count: int
    correct_count: int
    last_practiced_at: datetime | None


@dataclass(frozen=True)
class UserMasteryOverviewDTO:
    """用户在指定学习资料下的掌握度宏观全景数据传输实体。"""

    material_id: uuid.UUID | None
    overall_mastery_score: float
    total_knowledge_points: int
    unlearned_count: int
    weak_count: int
    basic_count: int
    proficient_count: int
    weak_knowledge_points: list[KnowledgeMasterySummaryDTO]


def resolve_channel_to_source(channel: str | None) -> GradingSourceType:
    """将判题渠道映射为算法计算核来源枚举。

    Args:
        channel: 判题渠道字符串 (offline / ai / user_self)。

    Returns:
        GradingSourceType: 算法识别的置信度来源类型枚举。
    """
    if not channel:
        return GradingSourceType.OFFLINE_RULE
    normalized_channel = channel.strip().lower()
    if normalized_channel in ("offline", "offline_rule"):
        return GradingSourceType.OFFLINE_RULE
    if normalized_channel in ("ai", "llm", "llm_grading", "ai_grading"):
        return GradingSourceType.AI_GRADING
    if normalized_channel in ("user_self", "self_assessment", "user_appeal", "appeal_regrade"):
        return GradingSourceType.SELF_ASSESSMENT
    return GradingSourceType.UNKNOWN


def normalize_error_type(error_type: str | None) -> str | None:
    """标准化错题错误类型入参，兼容前端历史简写枚举。

    BUG-DIAG-010: 前端历史筛选项使用 `incomplete` / `deviation`，而后端
    `ErrorType` 权威枚举为 `incomplete_expression` / `question_misreading`。
    此处统一映射为权威枚举值；未识别值原样透传，由 SQL 等值条件自然返回空，
    杜绝静默回退为「全量」。

    Args:
        error_type: 原始错误类型字符串。

    Returns:
        str | None: 标准化后的错误类型；空值返回 None。
    """
    if error_type is None:
        return None
    normalized = error_type.strip().lower()
    if not normalized:
        return None
    legacy_aliases = {
        "incomplete": ErrorType.INCOMPLETE_EXPRESSION.value,
        "deviation": ErrorType.QUESTION_MISREADING.value,
    }
    return legacy_aliases.get(normalized, normalized)


def map_mastery_level_to_db(level: Any) -> str:
    """将纯函数算法层四档掌握度等级映射至数据库模型字符串。

    Args:
        level: 算法层掌握度等级枚举或字符串。

    Returns:
        str: 数据库 MasteryLevel 枚举值字符串。
    """
    level_string = str(level).upper()
    if "UNLEARNED" in level_string:
        return MasteryLevel.UNLEARNED.value
    if "WEAK" in level_string:
        return MasteryLevel.WEAK.value
    if "DEVELOPING" in level_string or "BASIC" in level_string:
        return MasteryLevel.BASIC.value
    if "MASTERED" in level_string or "PROFICIENT" in level_string:
        return MasteryLevel.PROFICIENT.value
    return str(level).lower()


class DiagnosisService:
    """学情诊断、掌握度沉淀与错题流转核心领域服务。"""

    def __init__(
        self,
        session: Session,
        diagnosis_repo: DiagnosisRepository | None = None,
        practice_repo: PracticeRepository | None = None,
        grading_repo: GradingRepository | None = None,
        knowledge_repo: KnowledgeRepository | None = None,
        question_repo: QuestionRepository | None = None,
    ) -> None:
        """初始化诊断服务实例。

        Args:
            session: SQLAlchemy 数据库会话。
            diagnosis_repo: 学情诊断与掌握度仓储实例。
            practice_repo: 练习与答卷仓储实例。
            grading_repo: 判题记录仓储实例。
            knowledge_repo: 知识点仓储实例。
            question_repo: 题目标仓储实例 (手动标记错题需按题解析知识点归属)。
        """
        # 防御性兼容参数位置顺序
        if isinstance(grading_repo, KnowledgeRepository) and knowledge_repo is None:
            knowledge_repo = grading_repo
            grading_repo = None
        elif isinstance(knowledge_repo, GradingRepository) and grading_repo is None:
            grading_repo = knowledge_repo
            knowledge_repo = None

        self.session = session
        self.diagnosis_repo = diagnosis_repo or DiagnosisRepository(session)
        self.practice_repo = practice_repo or PracticeRepository(session)
        self.grading_repo = grading_repo or GradingRepository(session)
        self.knowledge_repo = knowledge_repo or KnowledgeRepository(session)
        self.question_repo = question_repo or QuestionRepository(session)

    # --------------------------------------------------------------------------
    # 结构化脱敏日志 8 要素工具方法
    # --------------------------------------------------------------------------

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
        """输出遵循规范的 8 要素结构化脱敏日志。

        绝密脱敏红线：严禁记录题干、选项、标准答案及用户作答原文。
        """
        log_structured_metric(
            logger,
            action=action,
            request_id=request_id,
            user_id=user_id,
            target_id=target_id,
            duration_ms=duration_ms,
            error_code=error_code,
            extra=extra,
            service_label="DiagnosisService",
        )

    # --------------------------------------------------------------------------
    # 核心业务方法
    # --------------------------------------------------------------------------

    def calculate_and_update_mastery(
        self,
        user_id: uuid.UUID,
        knowledge_point_ids: Sequence[uuid.UUID],
        current_time: datetime | None = None,
        request_id: str | None = None,
    ) -> list[MasteryRecord]:
        """针对指定知识点批量计算艾宾浩斯时间衰减掌握度并持久化。

        流水线逻辑：
        1. 获取知识点历史至多 200 条作答快照与生效判题记录；
        2. 转换数据为 AttemptRecord 不可变实体序列；
        3. 调用纯函数 aggregate_mastery_scores 计算 30 天半衰期衰减聚合得分；
        4. 映射四档掌握度等级 (UNLEARNED, WEAK, BASIC, PROFICIENT)；
        5. Upsert 持久化至 MasteryRecord 数据表并输出审计日志。

        Args:
            user_id: 租户用户主键。
            knowledge_point_ids: 待计算的知识点主键序列。
            current_time: 可选的评估基准时间戳（测试与仿真支持）。
            request_id: 请求追踪标识。

        Returns:
            list[MasteryRecord]: 持久化更新后的掌握度记录列表（支持双模索引）。
        """
        start_time = time.perf_counter()
        request_id = request_id or str(uuid.uuid4())
        evaluation_time = ensure_utc(current_time) or datetime.now(UTC)
        evaluation_timestamp = evaluation_time.timestamp()

        updated_records: list[MasteryRecord] = []

        for point_id in knowledge_point_ids:
            history = self.diagnosis_repo.get_attempt_history_for_knowledge_point(
                knowledge_point_id=point_id,
                user_id=user_id,
                limit=200,
            )

            records_input: list[AttemptRecord] = []
            correct_count = 0
            last_practiced_at: datetime | None = None
            recent_snapshots: list[dict[str, Any]] = []

            for item, grading in history:
                if grading is not None and grading.score is not None:
                    max_score_value = grading.max_score if grading.max_score > 0.0 else 1.0
                    item_score = max(0.0, min(1.0, float(grading.score) / max_score_value))
                    channel = grading.channel
                    record_created_at = grading.created_at
                elif item.score is not None:
                    max_score_value = item.max_score if item.max_score > 0.0 else 1.0
                    item_score = max(0.0, min(1.0, float(item.score) / max_score_value))
                    channel = "offline"
                    record_created_at = item.created_at
                else:
                    item_score = 0.0
                    channel = "offline"
                    record_created_at = item.created_at

                normalized_created_at = ensure_utc(record_created_at)
                source = resolve_channel_to_source(channel)
                answered_timestamp = (
                    normalized_created_at.timestamp()
                    if normalized_created_at is not None
                    else evaluation_timestamp
                )

                if last_practiced_at is None or (
                    normalized_created_at is not None and normalized_created_at > last_practiced_at
                ):
                    last_practiced_at = normalized_created_at

                if item_score >= 1.0:
                    correct_count += 1

                records_input.append(
                    AttemptRecord(
                        record_id=str(item.id),
                        knowledge_id=str(point_id),
                        score=item_score,
                        source=source,
                        answered_at_timestamp=answered_timestamp,
                    )
                )
                recent_snapshots.append(
                    {
                        "attempt_item_id": str(item.id),
                        "score": round(item_score, 4),
                        "source": str(source),
                        "answered_at": (
                            normalized_created_at.isoformat() if normalized_created_at else None
                        ),
                    }
                )

            aggregation_result = aggregate_mastery_scores(
                records=records_input,
                evaluated_at_timestamp=evaluation_timestamp,
                knowledge_ids=[str(point_id)],
            )
            aggregation_item = aggregation_result.items.get(str(point_id))

            if aggregation_item is not None:
                final_score = aggregation_item.mastery_score
                level_str = map_mastery_level_to_db(aggregation_item.mastery_level)
            else:
                final_score = 0.0
                level_str = MasteryLevel.UNLEARNED.value

            mastery_record = self.diagnosis_repo.upsert_mastery_record(
                user_id=user_id,
                knowledge_point_id=point_id,
                mastery_score=final_score,
                level=level_str,
                practice_count=len(history),
                correct_count=correct_count,
                last_practiced_at=last_practiced_at,
                decayed_at=evaluation_time,
                recent_records_snapshot=recent_snapshots[:200],
            )
            updated_records.append(mastery_record)

        self.session.flush()

        duration_ms = (time.perf_counter() - start_time) * 1000.0
        self._log_metric(
            action="CALCULATE_MASTERY",
            request_id=request_id,
            user_id=user_id,
            target_id=str(knowledge_point_ids[0]) if knowledge_point_ids else "empty",
            duration_ms=duration_ms,
            error_code=0,
            extra={
                "points_count": len(knowledge_point_ids),
                "updated_records_count": len(updated_records),
            },
        )
        return updated_records

    def sync_practice_learning_state(
        self,
        *,
        user_id: uuid.UUID,
        practice_id: uuid.UUID,
        partial_ok: bool = True,
        current_time: datetime | None = None,
        commit: bool = True,
    ) -> None:
        """同步练习已判分作答项至错题本 (WrongRecord) 与知识点掌握度 (MasteryRecord)。"""
        evaluation_time = current_time if current_time is not None else datetime.now(UTC)
        practice = self.practice_repo.get_practice_by_id(
            practice_id=practice_id,
            user_id=user_id,
            include_items=False,
        )
        if practice is None:
            return

        items = self.practice_repo.list_attempt_items(practice_id=practice_id, user_id=user_id)
        grading_records = self.grading_repo.list_final_records_by_practice(
            practice_id=practice_id,
            user_id=user_id,
        )
        if partial_ok:
            item_evaluations, *_ = evaluate_graded_items_partial(
                items=items,
                grading_records=grading_records,
            )
            if not item_evaluations:
                return
            sorted_point_ids = collect_involved_point_ids(None, item_evaluations)
        else:
            item_evaluations, *_ = evaluate_practice_items(
                practice_id=practice_id,
                items=items,
                grading_records=grading_records,
            )
            sorted_point_ids = collect_involved_point_ids(
                practice.knowledge_point_ids, item_evaluations
            )

        if sorted_point_ids:
            self.calculate_and_update_mastery(
                user_id=user_id,
                knowledge_point_ids=sorted_point_ids,
                current_time=evaluation_time,
            )

        fallback_point_id = sorted_point_ids[0] if sorted_point_ids else None
        sync_wrong_records_from_evaluations(
            diagnosis_repo=self.diagnosis_repo,
            user_id=user_id,
            practice_id=practice_id,
            item_evaluations=item_evaluations,
            fallback_point_id=fallback_point_id,
        )
        if commit:
            self.session.commit()
        else:
            self.session.flush()

    def ensure_diagnosis_report(
        self,
        *,
        user_id: uuid.UUID,
        practice_id: uuid.UUID,
    ) -> DiagnosisReport | None:
        """若练习已达成 COMPLETED、全部作答项已有终态成功判分且尚无报告，则幂等预生成。"""
        practice = self.practice_repo.get_practice_by_id(
            practice_id=practice_id,
            user_id=user_id,
            include_items=False,
        )
        if (
            practice is None
            or practice.status != PracticeStatus.COMPLETED.value
            or practice.completed_at is None
        ):
            return None
        existing = self.diagnosis_repo.get_diagnosis_report_by_practice_id(
            practice_id=practice_id,
            user_id=user_id,
        )
        if existing is not None:
            return existing
        items = self.practice_repo.list_attempt_items(practice_id=practice_id, user_id=user_id)
        grading_records = self.grading_repo.list_final_records_by_practice(
            practice_id=practice_id,
            user_id=user_id,
        )
        grading_map = {record.attempt_item_id: record for record in grading_records}
        if not items or any(
            item.id not in grading_map
            or grading_map[item.id].status != GradingStatus.SUCCESS.value
            or grading_map[item.id].score is None
            for item in items
        ):
            return None
        return self.generate_diagnosis_report(user_id=user_id, practice_id=practice_id)

    def refresh_diagnosis_report(
        self,
        *,
        user_id: uuid.UUID,
        practice_id: uuid.UUID,
        current_time: datetime | None = None,
        request_id: str | None = None,
    ) -> DiagnosisReport | None:
        """在自评覆盖或 AI 重判改动最终得分后，原地刷新（或首次生成）诊断报告。"""
        practice = self.practice_repo.get_practice_by_id(
            practice_id=practice_id,
            user_id=user_id,
            include_items=False,
        )
        if (
            practice is None
            or practice.status != PracticeStatus.COMPLETED.value
            or practice.completed_at is None
        ):
            return None
        items = self.practice_repo.list_attempt_items(practice_id=practice_id, user_id=user_id)
        grading_records = self.grading_repo.list_final_records_by_practice(
            practice_id=practice_id,
            user_id=user_id,
        )
        grading_map = {record.attempt_item_id: record for record in grading_records}
        if not items or any(
            item.id not in grading_map
            or grading_map[item.id].status != GradingStatus.SUCCESS.value
            or grading_map[item.id].score is None
            for item in items
        ):
            return None
        return self.generate_diagnosis_report(
            user_id=user_id,
            practice_id=practice_id,
            current_time=current_time,
            request_id=request_id,
            force_refresh=True,
        )

    def _persist_or_update_report(
        self,
        *,
        existing_report: DiagnosisReport | None,
        report_id: uuid.UUID,
        practice_id: uuid.UUID,
        user_id: uuid.UUID,
        synthesis_result: Any,
        total_questions: int,
        unanswered_count: int,
        wrong_count: int,
        score_rate: float,
        is_structure_degraded: bool,
        start_time: float,
        request_id: str,
    ) -> DiagnosisReport:
        """原子写入新建报告或原地刷新既有诊断报告，处理并发唯一约束竞争。"""
        if existing_report is not None:
            apply_diagnosis_report_updates(
                existing_report,
                synthesis_result=synthesis_result,
                total_questions=total_questions,
                unanswered_count=unanswered_count,
                wrong_count=wrong_count,
                score_rate=score_rate,
                is_structure_degraded=is_structure_degraded,
            )
            self.session.flush()
            self.session.commit()
            return existing_report

        report = build_diagnosis_report_entity(
            report_id=report_id,
            practice_id=practice_id,
            user_id=user_id,
            synthesis_result=synthesis_result,
            total_questions=total_questions,
            unanswered_count=unanswered_count,
            wrong_count=wrong_count,
            score_rate=score_rate,
            is_structure_degraded=is_structure_degraded,
        )
        try:
            created_report = self.diagnosis_repo.create_diagnosis_report(report, user_id=user_id)
            self.session.commit()
            return created_report
        except IntegrityError:
            self.session.rollback()
            raced_report = self.diagnosis_repo.get_diagnosis_report_by_practice_id(
                practice_id=practice_id,
                user_id=user_id,
            )
            if raced_report is not None:
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                self._log_metric(
                    action="GENERATE_DIAGNOSIS_REPORT_IDEMPOTENT",
                    request_id=request_id,
                    user_id=user_id,
                    target_id=practice_id,
                    duration_ms=duration_ms,
                    error_code=0,
                    extra={"report_id": str(raced_report.id)},
                )
                return raced_report
            raise

    def generate_diagnosis_report(
        self,
        user_id: uuid.UUID,
        practice_id: uuid.UUID,
        current_time: datetime | None = None,
        request_id: str | None = None,
        *,
        force_refresh: bool = False,
    ) -> DiagnosisReport:
        """全卷判题终态触发生成学情诊断报告与错题联动持久化。

        流水线逻辑：
        1. 检索 Practice，严格校验租户 user_id 与存在性；
        2. 状态机防错校验：若练习状态处于 PARTIALLY_GRADED 或非 COMPLETED，
           坚决抛出 PracticeNotGradedError (40016)；
        3. 幂等校验：若练习已生成诊断报告，直接幂等返回已存在的 DiagnosisReport；
        4. 聚合作答项与最终判题记录，统计未作答、答错与整卷得分率；
        5. 调用 calculate_and_update_mastery 刷新本次练习关联知识点的掌握度；
        6. 组装 KnowledgeEvaluationInput 与 MistakeEvidence，
           检查知识点低可信度标记 (is_low_confidence -> is_structure_degraded)；
        7. 调用纯函数 synthesize_diagnosis_report 识别薄弱/退步知识点并归因；
        8. 联动同步错题本：答错题目累加 error_count，答对题目攻克标记 is_mastered=True；
        9. 原子落库 DiagnosisReport 实体并提交数据库事务。

        Args:
            user_id: 租户用户主键。
            practice_id: 练习主键。
            current_time: 可选的评估时间戳（用于测试时间模拟）。
            request_id: 请求追踪标识。

        Returns:
            DiagnosisReport: 持久化并提交事务的学情诊断报告实体。

        Raises:
            PracticeNotFoundError: 练习不存在或越权访问。
            PracticeNotGradedError: 练习尚未全量判题终态。
        """
        start_time = time.perf_counter()
        request_id = request_id or str(uuid.uuid4())
        evaluation_time = current_time if current_time is not None else datetime.now(UTC)

        # 1. 检索 Practice 并校验归属
        practice = self.practice_repo.get_practice_by_id(
            practice_id=practice_id,
            user_id=user_id,
            include_items=False,
        )
        if practice is None:
            self._log_metric(
                action="GENERATE_DIAGNOSIS_REPORT",
                request_id=request_id,
                user_id=user_id,
                target_id=practice_id,
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
                error_code=40010,
            )
            raise PracticeNotFoundError(
                "请求的练习记录不存在或无权访问",
                details={"practice_id": str(practice_id)},
            )

        # 2. 状态机防错：非 COMPLETED 或 PARTIALLY_GRADED 严禁生成报告
        if practice.status != PracticeStatus.COMPLETED.value or practice.completed_at is None:
            self._log_metric(
                action="GENERATE_DIAGNOSIS_REPORT",
                request_id=request_id,
                user_id=user_id,
                target_id=practice_id,
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
                error_code=40016,
            )
            raise PracticeNotGradedError(
                "练习尚未完成全量判题，无法生成学情诊断报告",
                details={
                    "practice_id": str(practice_id),
                    "status": practice.status,
                },
            )

        # 3. 幂等校验（force_refresh=True 时允许原地重算并刷新既有报告）
        existing_report = self.diagnosis_repo.get_diagnosis_report_by_practice_id(
            practice_id=practice_id,
            user_id=user_id,
        )
        if existing_report is not None and not force_refresh:
            self._log_metric(
                action="GENERATE_DIAGNOSIS_REPORT_IDEMPOTENT",
                request_id=request_id,
                user_id=user_id,
                target_id=practice_id,
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
                error_code=0,
                extra={"report_id": str(existing_report.id)},
            )
            return existing_report

        # 4. 聚合作答项与最终判题记录
        items = self.practice_repo.list_attempt_items(practice_id=practice_id, user_id=user_id)
        grading_records = self.grading_repo.list_final_records_by_practice(
            practice_id=practice_id,
            user_id=user_id,
        )
        (
            item_evaluations,
            unanswered_count,
            wrong_count,
            total_scored,
            total_maximum,
        ) = evaluate_practice_items(
            practice_id=practice_id,
            items=items,
            grading_records=grading_records,
        )

        # 5. 汇集知识点并先冻结练习前基线快照，再计算并落库最新掌握度
        sorted_point_ids = collect_involved_point_ids(
            practice.knowledge_point_ids, item_evaluations
        )
        previous_records = self.diagnosis_repo.list_mastery_records_by_knowledge_point_ids(
            knowledge_point_ids=sorted_point_ids,
            user_id=user_id,
        )
        previous_record_map: dict[uuid.UUID, MasteryBaselineSnapshot] = {
            record.knowledge_point_id: MasteryBaselineSnapshot(
                mastery_score=float(record.mastery_score),
                last_practiced_at=record.last_practiced_at,
            )
            for record in previous_records
        }

        updated_mastery_list = self.calculate_and_update_mastery(
            user_id=user_id,
            knowledge_point_ids=sorted_point_ids,
            current_time=evaluation_time,
            request_id=request_id,
        )
        current_record_map = {record.knowledge_point_id: record for record in updated_mastery_list}

        # 6. 组装纯函数输入、错题证据并合成诊断内容
        (
            evaluation_inputs,
            mistake_evidences,
            is_structure_degraded,
            fallback_point_id,
        ) = build_evaluation_inputs_and_mistakes(
            knowledge_repo=self.knowledge_repo,
            user_id=user_id,
            sorted_point_ids=sorted_point_ids,
            previous_record_map=previous_record_map,
            current_record_map=current_record_map,
            item_evaluations=item_evaluations,
            evaluation_time=evaluation_time,
        )
        report_id = existing_report.id if existing_report is not None else uuid.uuid4()
        synthesis_result = synthesize_diagnosis_report(
            report_id=str(report_id),
            evaluated_knowledge_items=evaluation_inputs,
            mistakes=mistake_evidences,
        )

        # 7. 联动同步错题本并新建或原地刷新 DiagnosisReport 实体
        sync_wrong_records_from_evaluations(
            diagnosis_repo=self.diagnosis_repo,
            user_id=user_id,
            practice_id=practice_id,
            item_evaluations=item_evaluations,
            fallback_point_id=fallback_point_id,
        )
        score_rate = round(total_scored / total_maximum, 4) if total_maximum > 0.0 else 0.0
        persisted_report = self._persist_or_update_report(
            existing_report=existing_report if force_refresh else None,
            report_id=report_id,
            practice_id=practice_id,
            user_id=user_id,
            synthesis_result=synthesis_result,
            total_questions=len(items),
            unanswered_count=unanswered_count,
            wrong_count=wrong_count,
            score_rate=score_rate,
            is_structure_degraded=is_structure_degraded,
            start_time=start_time,
            request_id=request_id,
        )

        duration_ms = (time.perf_counter() - start_time) * 1000.0
        self._log_metric(
            action="REFRESH_DIAGNOSIS_REPORT" if force_refresh else "GENERATE_DIAGNOSIS_REPORT",
            request_id=request_id,
            user_id=user_id,
            target_id=practice_id,
            duration_ms=duration_ms,
            error_code=0,
            extra={
                "report_id": str(persisted_report.id),
                "total_questions": len(items),
                "wrong_count": wrong_count,
                "score_rate": score_rate,
                "is_structure_degraded": is_structure_degraded,
                "force_refresh": force_refresh,
            },
        )
        return persisted_report

    def get_diagnosis_report(
        self,
        user_id: uuid.UUID,
        report_id: uuid.UUID,
        request_id: str | None = None,
    ) -> DiagnosisReport:
        """根据报告主键获取诊断报告详情，强制验证租户隔离。

        Args:
            user_id: 租户用户主键。
            report_id: 诊断报告主键。
            request_id: 请求追踪标识。

        Returns:
            DiagnosisReport: 命中的诊断报告实体。

        Raises:
            DiagnosisReportNotFoundError: 报告不存在或无权访问。
        """
        start_time = time.perf_counter()
        request_id = request_id or str(uuid.uuid4())

        report = self.diagnosis_repo.get_diagnosis_report_by_id(
            report_id=report_id,
            user_id=user_id,
        )
        if report is None:
            self._log_metric(
                action="GET_DIAGNOSIS_REPORT",
                request_id=request_id,
                user_id=user_id,
                target_id=report_id,
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
                error_code=40017,
            )
            raise DiagnosisReportNotFoundError(
                "学情诊断报告不存在或无权访问",
                details={"report_id": str(report_id)},
            )

        self._log_metric(
            action="GET_DIAGNOSIS_REPORT",
            request_id=request_id,
            user_id=user_id,
            target_id=report_id,
            duration_ms=(time.perf_counter() - start_time) * 1000.0,
            error_code=0,
        )
        return report

    def get_diagnosis_report_by_practice(
        self,
        user_id: uuid.UUID,
        practice_id: uuid.UUID,
        request_id: str | None = None,
    ) -> DiagnosisReport:
        """根据练习标识获取关联的诊断报告实体。

        Args:
            user_id: 租户用户主键。
            practice_id: 练习主键。
            request_id: 请求追踪标识。

        Returns:
            DiagnosisReport: 命中的诊断报告实体。

        Raises:
            DiagnosisReportNotFoundError: 报告不存在或无权访问。
        """
        start_time = time.perf_counter()
        request_id = request_id or str(uuid.uuid4())

        report = self.diagnosis_repo.get_diagnosis_report_by_practice_id(
            practice_id=practice_id,
            user_id=user_id,
        )
        if report is None:
            self._log_metric(
                action="GET_DIAGNOSIS_REPORT_BY_PRACTICE",
                request_id=request_id,
                user_id=user_id,
                target_id=practice_id,
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
                error_code=40017,
            )
            raise DiagnosisReportNotFoundError(
                "未找到该练习对应的学情诊断报告",
                details={"practice_id": str(practice_id)},
            )

        self._log_metric(
            action="GET_DIAGNOSIS_REPORT_BY_PRACTICE",
            request_id=request_id,
            user_id=user_id,
            target_id=practice_id,
            duration_ms=(time.perf_counter() - start_time) * 1000.0,
            error_code=0,
        )
        return report

    def list_diagnosis_reports(
        self,
        user_id: uuid.UUID,
        page: int = 1,
        page_size: int = 20,
        limit: int | None = None,
        offset: int | None = None,
        request_id: str | None = None,
    ) -> list[DiagnosisReport]:
        """分页获取当前租户用户的学情诊断报告列表。

        Args:
            user_id: 租户用户主键。
            page: 页码 (从 1 起始)。
            page_size: 每页数量，默认 20。
            limit: 可选的直接 limit 覆盖。
            offset: 可选的直接 offset 覆盖。
            request_id: 请求追踪标识。

        Returns:
            list[DiagnosisReport]: 诊断报告实体列表。
        """
        effective_limit = limit if limit is not None else page_size
        effective_offset = offset if offset is not None else max(0, (page - 1) * page_size)

        reports = self.diagnosis_repo.list_diagnosis_reports_by_user(
            user_id=user_id,
            limit=effective_limit,
            offset=effective_offset,
        )
        return reports

    def get_user_mastery_overview(
        self,
        user_id: uuid.UUID,
        material_id: uuid.UUID | None = None,
        request_id: str | None = None,
        *,
        folder_id: uuid.UUID | None = None,
        unclassified: bool = False,
    ) -> UserMasteryOverviewDTO:
        """获取用户的知识点掌握度宏观全景。

        当 ``material_id`` 缺省为 None 时，支持按 ``folder_id`` 或未分类过滤，
        否则聚合该用户全部知识点与其掌握度记录（跨资料）。

        Args:
            user_id: 租户用户主键。
            material_id: 可选资料主键；None 表示聚合课程范围或全部资料知识点。
            request_id: 请求追踪标识。
            folder_id: 可选课程文件夹主键过滤。
            unclassified: 为 True 时仅统计未归类（``folder_id IS NULL``）资料下的知识点。

        Returns:
            UserMasteryOverviewDTO: 包含薄弱点清单与四档统计的总览实体。
        """
        start_time = time.perf_counter()
        request_id = request_id or str(uuid.uuid4())

        if material_id is not None:
            knowledge_points = self.knowledge_repo.list_by_material_id(
                material_id=material_id,
                user_id=user_id,
            )
            mastery_records = self.diagnosis_repo.list_mastery_records_by_material(
                material_id=material_id,
                user_id=user_id,
            )
        elif folder_id is not None or unclassified:
            knowledge_points = self.knowledge_repo.list_by_folder_scope(
                user_id=user_id,
                folder_id=folder_id,
                unclassified=unclassified,
            )
            mastery_records = self.diagnosis_repo.list_mastery_records_by_knowledge_point_ids(
                [kp.id for kp in knowledge_points],
                user_id=user_id,
            )
        else:
            knowledge_points = self.knowledge_repo.list_all_by_user_id(user_id=user_id)
            mastery_records = self.diagnosis_repo.list_mastery_records_by_user(user_id=user_id)
        record_map = {record.knowledge_point_id: record for record in mastery_records}

        unlearned_count = 0
        weak_count = 0
        basic_count = 0
        proficient_count = 0
        weak_points_summary: list[KnowledgeMasterySummaryDTO] = []
        total_score_sum = 0.0

        for point in knowledge_points:
            record = record_map.get(point.id)
            if record is not None:
                score = record.mastery_score
                level = record.level
                practice_count = record.practice_count
                correct_count = record.correct_count
                last_practiced = record.last_practiced_at
            else:
                score = 0.0
                level = MasteryLevel.UNLEARNED.value
                practice_count = 0
                correct_count = 0
                last_practiced = None

            summary_dto = KnowledgeMasterySummaryDTO(
                knowledge_point_id=point.id,
                knowledge_name=point.name,
                mastery_score=score,
                level=level,
                practice_count=practice_count,
                correct_count=correct_count,
                last_practiced_at=last_practiced,
            )
            total_score_sum += score

            level_normalized = level.lower()
            if level_normalized == MasteryLevel.UNLEARNED.value:
                unlearned_count += 1
            elif level_normalized == MasteryLevel.WEAK.value:
                weak_count += 1
                weak_points_summary.append(summary_dto)
            elif level_normalized in (MasteryLevel.BASIC.value, "developing"):
                basic_count += 1
            elif level_normalized in (MasteryLevel.PROFICIENT.value, "mastered"):
                proficient_count += 1
            else:
                if score < 0.40:
                    weak_count += 1
                    weak_points_summary.append(summary_dto)
                elif score < 0.70:
                    basic_count += 1
                else:
                    proficient_count += 1

        overall_score = (
            round(total_score_sum / len(knowledge_points), 4) if knowledge_points else 0.0
        )

        # 薄弱点最弱优先：与算法层约定一致，按掌握度升序排列（得分最低排在最前），
        # 次级以知识点主键稳定排序 (BUG-DIAG-020)。
        weak_points_summary.sort(
            key=lambda item: (item.mastery_score, str(item.knowledge_point_id))
        )

        overview_dto = UserMasteryOverviewDTO(
            material_id=material_id,
            overall_mastery_score=overall_score,
            total_knowledge_points=len(knowledge_points),
            unlearned_count=unlearned_count,
            weak_count=weak_count,
            basic_count=basic_count,
            proficient_count=proficient_count,
            weak_knowledge_points=weak_points_summary,
        )

        duration_ms = (time.perf_counter() - start_time) * 1000.0
        self._log_metric(
            action="GET_MASTERY_OVERVIEW",
            request_id=request_id,
            user_id=user_id,
            target_id=material_id if material_id is not None else "all",
            duration_ms=duration_ms,
            error_code=0,
            extra={
                "total_points": len(knowledge_points),
                "weak_count": weak_count,
                "overall_score": overall_score,
            },
        )
        return overview_dto

    def get_knowledge_mastery(
        self,
        user_id: uuid.UUID,
        knowledge_point_id: uuid.UUID,
        request_id: str | None = None,
    ) -> KnowledgeMasterySummaryDTO:
        """获取单个知识点的当前掌握度衰减聚合数据。

        Args:
            user_id: 租户用户主键。
            knowledge_point_id: 知识点主键。
            request_id: 请求追踪标识。

        Returns:
            KnowledgeMasterySummaryDTO: 单知识点掌握度汇总数据传输实体。

        Raises:
            MasteryRecordNotFoundError: 知识点掌握度记录不存在或无权访问。
        """
        start_time = time.perf_counter()
        request_id = request_id or str(uuid.uuid4())

        record = self.diagnosis_repo.get_mastery_record(
            knowledge_point_id=knowledge_point_id,
            user_id=user_id,
        )
        if record is None:
            self._log_metric(
                action="GET_KNOWLEDGE_MASTERY",
                request_id=request_id,
                user_id=user_id,
                target_id=knowledge_point_id,
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
                error_code=40018,
            )
            raise MasteryRecordNotFoundError(
                message="该知识点尚未产生掌握度评估记录",
                details={"knowledge_point_id": str(knowledge_point_id)},
                knowledge_point_id=knowledge_point_id,
            )

        knowledge_name = getattr(record, "knowledge_name", None)
        if not knowledge_name:
            knowledge_point = self.knowledge_repo.get_by_id(knowledge_point_id, user_id=user_id)
            knowledge_name = (
                knowledge_point.name if knowledge_point else f"知识点-{str(knowledge_point_id)[:8]}"
            )

        summary_dto = KnowledgeMasterySummaryDTO(
            knowledge_point_id=record.knowledge_point_id,
            knowledge_name=knowledge_name,
            mastery_score=record.mastery_score,
            level=record.level,
            practice_count=record.practice_count,
            correct_count=record.correct_count,
            last_practiced_at=record.last_practiced_at,
        )

        self._log_metric(
            action="GET_KNOWLEDGE_MASTERY",
            request_id=request_id,
            user_id=user_id,
            target_id=knowledge_point_id,
            duration_ms=(time.perf_counter() - start_time) * 1000.0,
            error_code=0,
            extra={
                "mastery_score": record.mastery_score,
                "level": record.level,
            },
        )
        return summary_dto

    def list_wrong_records(
        self,
        user_id: uuid.UUID,
        material_id: uuid.UUID | None = None,
        folder_id: uuid.UUID | None = None,
        unclassified: bool = False,
        status: str | None = None,
        is_mastered: bool | None = None,
        knowledge_point_id: uuid.UUID | None = None,
        error_type: str | None = None,
        question_type: str | None = None,
        page: int = 1,
        page_size: int = 50,
        limit: int | None = None,
        offset: int | None = None,
    ) -> tuple[list[WrongRecord], int]:
        """多维分页查询当前租户用户的错题列表及真实总数。

        Args:
            user_id: 租户用户主键。
            material_id: 可选的学习资料标识过滤。
            status: 可选的错题状态过滤 ("mastered" / "active" / "unmastered")。
            is_mastered: 可选的攻克掌握布尔状态过滤。
            knowledge_point_id: 可选的知识点主键过滤。
            error_type: 可选的错误类型过滤 (兼容 incomplete/deviation 简写)。
            question_type: 可选的题目快照题型过滤。
            page: 分页页码，默认 1。
            page_size: 每页条数，默认 50。
            limit: 可选的直接 limit。
            offset: 可选的直接 offset。

        Returns:
            tuple[list[WrongRecord], int]: 当前页错题实体列表与符合过滤条件的真实总数。
        """
        effective_limit = limit if limit is not None else page_size
        effective_offset = offset if offset is not None else max(0, (page - 1) * page_size)

        effective_is_mastered = is_mastered
        if effective_is_mastered is None and status is not None:
            normalized_status = status.strip().lower()
            if normalized_status in ("mastered", "true", "1"):
                effective_is_mastered = True
            elif normalized_status in ("active", "unmastered", "false", "0"):
                effective_is_mastered = False

        # BUG-DIAG-010/011/012: material_id / error_type / question_type 全量下推仓储，
        # 由数据库统一完成过滤、分页与真实计数，彻底移除 limit=1000 内存截断。
        normalized_error_type = normalize_error_type(error_type)
        scope_filters: dict[str, Any] = {}
        if folder_id is not None:
            scope_filters["folder_id"] = folder_id
        if unclassified:
            scope_filters["unclassified"] = True
        records = self.diagnosis_repo.list_wrong_records(
            user_id=user_id,
            is_mastered=effective_is_mastered,
            knowledge_point_id=knowledge_point_id,
            material_id=material_id,
            error_type=normalized_error_type,
            question_type=question_type,
            limit=effective_limit,
            offset=effective_offset,
            **scope_filters,
        )
        total = int(
            self.diagnosis_repo.count_wrong_records(
                user_id=user_id,
                is_mastered=effective_is_mastered,
                knowledge_point_id=knowledge_point_id,
                material_id=material_id,
                error_type=normalized_error_type,
                question_type=question_type,
                **scope_filters,
            )
        )
        return records, total

    def get_wrong_record_scopes(
        self, user_id: uuid.UUID, knowledge_point_ids: set[uuid.UUID]
    ) -> dict[uuid.UUID, tuple[uuid.UUID, uuid.UUID | None]]:
        """Resolve material and course for a page of wrong records."""
        return self.diagnosis_repo.get_wrong_record_scopes(user_id, knowledge_point_ids)

    def get_wrong_record_display_meta(
        self, user_id: uuid.UUID, knowledge_point_ids: set[uuid.UUID]
    ) -> dict[uuid.UUID, tuple[uuid.UUID, uuid.UUID | None, str, str]]:
        """Resolve material, course, knowledge point name, and material title for wrong records."""
        return self.diagnosis_repo.get_wrong_record_display_meta(user_id, knowledge_point_ids)

    def list_wrong_record_groups(
        self,
        user_id: uuid.UUID,
        is_mastered: bool | None = None,
        *,
        folder_id: uuid.UUID | None = None,
        unclassified: bool = False,
    ) -> list[dict[str, Any]]:
        """Group the wrong-record collection by course and source, honoring folder filter."""
        repo_kwargs: dict[str, Any] = {}
        if folder_id is not None:
            repo_kwargs["folder_id"] = folder_id
        if unclassified:
            repo_kwargs["unclassified"] = True
        groups: dict[tuple[uuid.UUID | None, uuid.UUID | None], dict[str, Any]] = {}
        for (
            group_folder_id,
            folder_name,
            material_id,
            material_title,
            count,
        ) in self.diagnosis_repo.list_wrong_record_groups(user_id, is_mastered, **repo_kwargs):
            key = (group_folder_id, None if group_folder_id is not None else material_id)
            if key not in groups:
                groups[key] = {
                    "folder_id": group_folder_id,
                    "folder_name": folder_name,
                    "material_id": key[1],
                    "material_title": material_title if group_folder_id is None else None,
                    "count": 0,
                }
            groups[key]["count"] += count
        return sorted(
            groups.values(),
            key=lambda group: (
                group["folder_id"] is None,
                group["folder_name"] or group["material_title"] or "",
            ),
        )

    def mark_question_as_wrong(
        self,
        user_id: uuid.UUID,
        question_id: uuid.UUID,
        request_id: str | None = None,
    ) -> WrongRecord:
        """把题库里已有的一道题手动记入错题本 (无需先在 App 内做过这道题)。

        快照构造与判题路径共用 `build_question_snapshot`：前端错题卡片**只**读
        `question_snapshot` 渲染，两份形状就意味着手工错题与判题错题在界面上长得不一样。
        构造后经 `validate_question_snapshot` 校验，不通过即失败且**不写库**——
        写入一条渲染不出来的错题比拒绝标记糟得多。

        手工记录没有练习归属：`practice_id` / `attempt_item_id` 均为 NULL
        (该 NULL 本身就是「手工创建」的定义，不另设 source 列)，`error_type` 为
        `ErrorType.MANUAL` (来源标记，不是错因归因)。对已有错题记录的题目重复标记是
        幂等更新 (累加 `error_count`、重置 `is_mastered`)，且**不会**抹掉判题路径写下的
        练习归属，见 `DiagnosisRepository.upsert_wrong_record` 的练习归属契约。

        Args:
            user_id: 租户用户主键。
            question_id: 要标记为错题的题目主键。
            request_id: 请求追踪标识。

        Returns:
            WrongRecord: 新建或累加更新后的错题记录实体。

        Raises:
            QuestionNotFoundError: 题目不存在、已软删除或跨租户非法访问 (404 / 40009)。
            AppError: 题目快照不合法 (400 / 40008)，此时数据库无新增记录。
        """
        start_time = time.perf_counter()
        request_id = request_id or str(uuid.uuid4())

        question = self.question_repo.get_question_by_id(question_id, user_id)
        if question is None:
            self._log_metric(
                action="MARK_QUESTION_AS_WRONG",
                request_id=request_id,
                user_id=user_id,
                target_id=question_id,
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
                error_code=40009,
            )
            raise QuestionNotFoundError(
                message="请求的题目不存在或无权访问",
                details={"question_id": str(question_id)},
            )

        snapshot = build_question_snapshot(question)
        is_valid, err_msg = validate_question_snapshot(snapshot)
        if not is_valid:
            self._log_metric(
                action="MARK_QUESTION_AS_WRONG",
                request_id=request_id,
                user_id=user_id,
                target_id=question_id,
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
                error_code=40008,
                extra={"reason": err_msg},
            )
            raise AppError(
                error_code=40008,
                message=f"题目快照质检未通过: {err_msg}",
                details={"question_id": str(question_id), "reason": err_msg},
            )

        record = self.diagnosis_repo.upsert_wrong_record(
            user_id=user_id,
            question_id=question_id,
            knowledge_point_id=question.knowledge_point_id,
            practice_id=None,
            attempt_item_id=None,
            error_type=ErrorType.MANUAL.value,
            question_snapshot=snapshot,
        )
        self.session.commit()
        self._log_metric(
            action="MARK_QUESTION_AS_WRONG",
            request_id=request_id,
            user_id=user_id,
            target_id=question_id,
            duration_ms=(time.perf_counter() - start_time) * 1000.0,
            error_code=0,
            extra={"wrong_record_id": str(record.id), "error_count": record.error_count},
        )
        return record

    def mark_wrong_record_mastered(
        self,
        user_id: uuid.UUID,
        record_id: uuid.UUID,
        is_mastered: bool = True,
        request_id: str | None = None,
    ) -> WrongRecord:
        """标记或取消指定错题记录的攻克掌握状态。

        Args:
            user_id: 租户用户主键。
            record_id: 错题记录主键。
            is_mastered: 目标攻克状态，默认 True (向后兼容)。
            request_id: 请求追踪标识。

        Returns:
            WrongRecord: 更新后的错题实体。

        Raises:
            WrongRecordNotFoundError: 错题记录不存在或无权访问。
        """
        start_time = time.perf_counter()
        request_id = request_id or str(uuid.uuid4())

        record = self.diagnosis_repo.mark_wrong_record_mastered(
            wrong_record_id=record_id,
            user_id=user_id,
            is_mastered=is_mastered,
        )
        if record is None:
            self._log_metric(
                action="MARK_WRONG_RECORD_MASTERED",
                request_id=request_id,
                user_id=user_id,
                target_id=record_id,
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
                error_code=40019,
            )
            raise WrongRecordNotFoundError(
                message="错题记录不存在或无权访问",
                details={"record_id": str(record_id)},
                record_id=record_id,
            )

        self.session.commit()
        self._log_metric(
            action="MARK_WRONG_RECORD_MASTERED",
            request_id=request_id,
            user_id=user_id,
            target_id=record_id,
            duration_ms=(time.perf_counter() - start_time) * 1000.0,
            error_code=0,
            extra={
                "is_mastered": record.is_mastered,
                "mastered_at": record.mastered_at.isoformat() if record.mastered_at else None,
            },
        )
        return record

    def remove_wrong_record(
        self,
        user_id: uuid.UUID,
        wrong_record_id: uuid.UUID | None = None,
        record_id: uuid.UUID | None = None,
        request_id: str | None = None,
    ) -> bool:
        """删除指定错题记录。

        Args:
            user_id: 租户用户主键。
            wrong_record_id: 错题记录主键。
            record_id: 错题记录主键别名。
            request_id: 请求追踪标识。

        Returns:
            bool: 成功删除返回 True。

        Raises:
            WrongRecordNotFoundError: 错题记录不存在或无权访问。
        """
        target_id = record_id if record_id is not None else wrong_record_id
        if target_id is None:
            return False

        start_time = time.perf_counter()
        request_id = request_id or str(uuid.uuid4())

        deleted = self.diagnosis_repo.delete_wrong_record(
            record_id=target_id,
            user_id=user_id,
        )
        if not deleted:
            self._log_metric(
                action="REMOVE_WRONG_RECORD",
                request_id=request_id,
                user_id=user_id,
                target_id=target_id,
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
                error_code=40019,
            )
            raise WrongRecordNotFoundError(
                message="错题记录不存在或无权访问",
                details={"record_id": str(target_id)},
                record_id=target_id,
            )

        self.session.commit()
        self._log_metric(
            action="REMOVE_WRONG_RECORD",
            request_id=request_id,
            user_id=user_id,
            target_id=target_id,
            duration_ms=(time.perf_counter() - start_time) * 1000.0,
            error_code=0,
        )
        return True


ReportService = DiagnosisService
"""对齐系统 ROADMAP 与领域服务命名的别名导出。"""

__all__ = [
    "DiagnosisService",
    "KnowledgeMasterySummaryDTO",
    "ReportService",
    "UserMasteryOverviewDTO",
]
