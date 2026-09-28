"""判题编排、异步分流与自评/重判核心领域服务。

负责整卷判题流水线编排、客观题秒判、主观题双阈值分流与大模型结构化评分、
LLM 20s 超时降级至 pending_regrade (严禁判错)、用户自主评分覆盖与异步重新判题。
严格遵循 AGENTS.md 规范：
- app/services 是全系统唯一允许开启数据库事务的层；
- 缩写白名单仅限 8 个 (api, id, url, ocr, llm, db, config, env)；
- 8 要素结构化脱敏日志输出，严禁向日志记录题干、选项、答案与用户作答原文；
- 纯函数计算核隔离调度。
"""

import json
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.algorithms.grading import (
    OBJECTIVE_QUESTION_TYPES,
    SCORE_ROUNDING_UNIT,
    GradingRubricItem,
    match_and_grade_answer,
    round_half_up,
)
from app.core.errors import (
    AttemptItemNotFoundError,
    GradingExecutionError,
    GradingNotAllowedError,
    PracticeNotFoundError,
)
from app.core.security import generate_user_ref
from app.integrations.llm.protocol import (
    LLMMessage,
    LLMOptions,
    LLMProtocol,
)
from app.models.practice import (
    AttemptItem,
    GradingChannel,
    GradingRecord,
    GradingStatus,
    Practice,
    PracticeStatus,
)
from app.repositories.grading import GradingRepository
from app.repositories.practice import PracticeRepository

logger = logging.getLogger(__name__)


# ==============================================================================
# 数据契约与传输对象 (DTOs)
# ==============================================================================


@dataclass(frozen=True)
class SelfEvaluateDTO:
    """用户自主评分请求对象。"""

    attempt_item_id: uuid.UUID
    score: float
    feedback: str | None = None
    is_correct: bool | None = None


@dataclass(frozen=True)
class RegradeAttemptDTO:
    """单题重新判题请求对象。"""

    attempt_item_id: uuid.UUID
    reason: str | None = None


@dataclass(frozen=True)
class AttemptGradingDetailDTO:
    """作答题目判题明细与历史传输对象。"""

    attempt_item_id: uuid.UUID
    latest_grading: GradingRecord | None
    records: list[GradingRecord]
    practice_id: uuid.UUID | None = None
    question_id: uuid.UUID | None = None
    current_record: GradingRecord | None = None
    history: list[GradingRecord] | None = None


@dataclass(frozen=True)
class PracticeGradingSummary:
    """整卷判题结果汇总。"""

    practice_id: uuid.UUID
    status: str
    total_score: float
    max_score: float
    total_items: int
    graded_items: int
    pending_regrade_count: int
    records: list[GradingRecord]


class LLMGradingRubricEvaluation(BaseModel):
    """LLM 结构化判题采分点响应 Schema。"""

    point_id: str
    score: float
    reason: str


class LLMGradingOutput(BaseModel):
    """LLM 结构化判题响应 Schema。"""

    score: float
    confidence: float = 0.9
    feedback: str = ""
    hit_keywords: list[str] = Field(default_factory=list)
    missing_keywords: list[str] = Field(default_factory=list)
    evaluations: list[LLMGradingRubricEvaluation] = Field(default_factory=list)


# ==============================================================================
# 判题领域编排服务 (GradingService)
# ==============================================================================


class GradingService:
    """判题编排与结果分流领域服务。

    负责协调 GradingRepository 与 PracticeRepository，
    调用纯函数算法核与大模型结构化适配器执行判题编排。
    """

    def __init__(
        self,
        session: Session,
        practice_repo: PracticeRepository | None = None,
        grading_repo: GradingRepository | None = None,
        llm_adapter: LLMProtocol | None = None,
    ) -> None:
        """初始化判题服务实例。

        Args:
            session: 数据库会话。
            practice_repo: 练习仓储，缺省自动构建。
            grading_repo: 判题记录仓储，缺省自动构建。
            llm_adapter: 大模型适配网关。
        """
        self.session = session
        self.practice_repo = practice_repo or PracticeRepository(session)
        self.grading_repo = grading_repo or GradingRepository(session)
        self.llm_adapter = llm_adapter

    # --------------------------------------------------------------------------
    # 结构化脱敏日志 8 要素工具方法
    # --------------------------------------------------------------------------

    def _log_metric(
        self,
        action: str,
        request_id: str,
        user_id: uuid.UUID,
        target_id: str | uuid.UUID,
        duration_ms: float,
        error_code: int = 0,
        level: int = logging.INFO,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """输出严格符合 AGENTS.md 规范的 8 要素结构化脱敏日志。

        绝密脱敏红线：严禁打印题干、选项、标准答案、用户答案原文及密钥。
        """
        user_ref = generate_user_ref(user_id)
        log_payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": logging.getLevelName(level),
            "logger_name": logger.name,
            "request_id": request_id or "-",
            "user_ref": user_ref,
            "target_id": str(target_id),
            "duration_ms": round(duration_ms, 2),
            "error_code": error_code,
            "action": action,
        }
        if extra:
            log_payload["details"] = extra
        logger.log(level, "METRIC %s", json.dumps(log_payload, ensure_ascii=False))

    # --------------------------------------------------------------------------
    # 1. 整卷判题主流水线 (grade_practice / grade_practice_submission)
    # --------------------------------------------------------------------------

    def grade_practice(
        self,
        user_id: uuid.UUID,
        practice_id: uuid.UUID,
        request_id: str = "",
    ) -> PracticeGradingSummary:
        """整卷判题流水线。

        对练习的每个作答项执行分流判定：未答零分、客观题离线秒判、主观题双阈值分流与
        大模型结构化评分；大模型超时/故障降级为 pending_regrade。

        Args:
            user_id: 租户用户标识。
            practice_id: 关联练习标识。
            request_id: 请求跟踪标识。

        Returns:
            PracticeGradingSummary: 整卷判题结果汇总。

        Raises:
            PracticeNotFoundError: 练习不存在或无权访问。
            GradingNotAllowedError: 练习状态不允许判题。
        """
        start_time = time.perf_counter()

        practice = self.practice_repo.get_practice_by_id(practice_id, user_id, include_items=True)
        if practice is None:
            raise PracticeNotFoundError(
                "请求的练习不存在或无权访问",
                details={"practice_id": str(practice_id)},
            )

        if practice.status not in (
            PracticeStatus.SUBMITTED.value,
            PracticeStatus.COMPLETED.value,
            PracticeStatus.PARTIALLY_GRADED.value,
        ):
            raise GradingNotAllowedError(
                f"练习当前状态不允许判题: {practice.status}",
                details={"status": practice.status, "practice_id": str(practice_id)},
            )

        items = practice.items
        saved_records: list[GradingRecord] = []
        has_pending_regrade = False

        existing_records = {
            record.attempt_item_id: record
            for record in self.grading_repo.list_final_records_by_practice(practice_id, user_id)
        }

        for item in items:
            existing = existing_records.get(item.id)
            # 幂等重放: 已由系统判成功的题不重复判题 (避免队列重投重复消耗 LLM 与分数漂移);
            # 用户自评记录除外, 整卷判题须重新推演并保留旧记录为历史 (GRADE-016 / FR-44)
            if (
                existing is not None
                and existing.status == GradingStatus.SUCCESS.value
                and existing.channel != GradingChannel.USER_SELF.value
                and (
                    practice.status
                    in (
                        PracticeStatus.SUBMITTED.value,
                        PracticeStatus.PARTIALLY_GRADED.value,
                    )
                    or practice.completed_at is not None
                )
            ):
                record, item_has_pending = existing, False
            else:
                record, item_has_pending = self._grade_attempt_item(
                    item=item,
                    practice=practice,
                    user_id=user_id,
                )
            saved_records.append(record)
            if item_has_pending:
                has_pending_regrade = True

        # 汇总得分与推演状态机
        total_score = round(sum(it.score or 0.0 for it in items), 2)
        max_score = round(sum(it.max_score for it in items), 2)
        practice.total_score = total_score
        practice.max_score = max_score

        # 状态机决策: 存在待重判必须置为 PARTIALLY_GRADED (FR-42 阻断报告); 全判完置为 COMPLETED
        all_graded = bool(items) and all(
            r.status == GradingStatus.SUCCESS.value for r in saved_records
        )
        if has_pending_regrade:
            practice.status = PracticeStatus.PARTIALLY_GRADED.value
            practice.completed_at = None
        elif all_graded:
            practice.status = PracticeStatus.COMPLETED.value
            if not practice.completed_at:
                practice.completed_at = datetime.now(UTC)

        self.session.flush()

        duration_ms = (time.perf_counter() - start_time) * 1000
        self._log_metric(
            action="grade_practice",
            request_id=request_id,
            user_id=user_id,
            target_id=practice_id,
            duration_ms=duration_ms,
            extra={
                "total_items": len(items),
                "total_score": total_score,
                "has_pending_regrade": has_pending_regrade,
                "final_status": practice.status,
            },
        )

        return PracticeGradingSummary(
            practice_id=practice_id,
            status=practice.status,
            total_score=total_score,
            max_score=max_score,
            total_items=len(items),
            graded_items=sum(1 for r in saved_records if r.status == GradingStatus.SUCCESS.value),
            pending_regrade_count=sum(
                1 for r in saved_records if r.status == GradingStatus.PENDING_REGRADE.value
            ),
            records=saved_records,
        )

    def grade_practice_submission(
        self,
        practice_id: uuid.UUID,
        user_id: uuid.UUID,
        request_id: str = "",
    ) -> PracticeGradingSummary:
        """整卷判题流水线别名接口，兼容不同入参次序。"""
        return self.grade_practice(user_id=user_id, practice_id=practice_id, request_id=request_id)

    def _grade_attempt_item(
        self,
        item: AttemptItem,
        practice: Practice,
        user_id: uuid.UUID,
    ) -> tuple[GradingRecord, bool]:
        """单题判题处理内部函数。

        判题事务安全 (GRADE-016)：先完成算法计算，仅在即将持久化新生效记录前
        才将旧记录置为非最终；算法异常时安全降级为待重判记录，绝不中断整卷判题。

        Returns:
            tuple[GradingRecord, bool]: (生效的判题记录, 是否触发待重判)
        """
        user_ans = item.user_answer
        is_actually_answered = bool(item.is_answered and user_ans and user_ans.strip())

        # 1. 未作答分支短路
        if not is_actually_answered:
            item.score = 0.0
            item.is_answered = False

            self.grading_repo.set_records_non_final_by_attempt_id(item.id, user_id=user_id)
            record = GradingRecord(
                id=uuid.uuid4(),
                practice_id=practice.id,
                attempt_item_id=item.id,
                question_id=item.question_id,
                channel=GradingChannel.OFFLINE.value,
                status=GradingStatus.SUCCESS.value,
                is_final=True,
                score=0.0,
                max_score=item.max_score,
                confidence=1.0,
                feedback="未作答",
                hit_keywords=[],
                missing_keywords=[],
                grading_metadata={"unanswered": True, "is_correct": False},
            )
            self.grading_repo.create_record(record, user_id=user_id)
            return record, False

        # 2. 提取题目快照参数并调用算法核（防御性兜底，脏快照不拖垮整卷）
        snapshot = item.question_snapshot or {}
        try:
            q_type = snapshot.get("question_type", "")
            ref_answer = snapshot.get("answer", "")
            options = snapshot.get("options", [])
            rubric_data = snapshot.get("grading_rubric")
            parsed_rubric: list[GradingRubricItem] = []
            if isinstance(rubric_data, dict):
                pts = rubric_data.get("points") or rubric_data.get("dimensions") or []
                if isinstance(pts, list):
                    for p in pts:
                        if isinstance(p, dict):
                            raw_weight = (
                                p.get("weight")
                                if p.get("weight") is not None
                                else p.get("score", 1.0)
                            )
                            parsed_rubric.append(
                                GradingRubricItem(
                                    point_id=str(p.get("point_id", "")),
                                    description=str(p.get("description", "")),
                                    weight=float(raw_weight) if raw_weight is not None else 1.0,
                                    keywords=tuple(p.get("keywords", ())),
                                    negation_words=tuple(p.get("negation_words", ())),
                                )
                            )

            result = match_and_grade_answer(
                question_type=q_type,
                user_answer=user_ans or "",
                reference_answer=ref_answer,
                max_score=item.max_score,
                options=options,
                grading_rubric=parsed_rubric,
            )
        except Exception as exc:
            # 快照格式或未知题型导致算法异常：安全降级为待重判，不中断整卷且不丢原记录
            logger.warning("单题判分算法异常，安全降级为待重判: %s", str(exc)[:200])
            return self._build_pending_regrade_record(
                item=item,
                practice_id=practice.id,
                user_id=user_id,
                error_msg=str(exc)[:200],
            )

        # 3. 离线判分分支 (客观题或主观题高置信度离线判分)
        if not result.requires_llm:
            item.score = result.score

            self.grading_repo.set_records_non_final_by_attempt_id(item.id, user_id=user_id)
            record = GradingRecord(
                id=uuid.uuid4(),
                practice_id=practice.id,
                attempt_item_id=item.id,
                question_id=item.question_id,
                channel=GradingChannel.OFFLINE.value,
                status=GradingStatus.SUCCESS.value,
                is_final=True,
                score=result.score,
                max_score=item.max_score,
                confidence=result.confidence,
                similarity_score=result.match_score,
                hit_keywords=list(result.hit_keywords),
                missing_keywords=list(result.missing_keywords),
                feedback=result.reasoning,
                grading_metadata={
                    "method": result.grading_method.value,
                    "is_correct": result.is_correct,
                },
            )
            self.grading_repo.create_record(record, user_id=user_id)
            return record, False

        # 4. 转大模型主观题打分分支
        return self._grade_with_llm(
            item=item,
            practice_id=practice.id,
            user_id=user_id,
            snapshot=snapshot,
            user_ans=user_ans or "",
        )

    def _grade_with_llm(
        self,
        item: AttemptItem,
        practice_id: uuid.UUID,
        user_id: uuid.UUID,
        snapshot: dict[str, Any],
        user_ans: str,
    ) -> tuple[GradingRecord, bool]:
        """调用大模型网关执行主观题评分，支持 20s 超时降级至 pending_regrade。"""
        if self.llm_adapter is None:
            # 无适配器配置直接降级
            return self._build_pending_regrade_record(
                item=item,
                practice_id=practice_id,
                user_id=user_id,
                error_msg="未配置大模型适配器",
            )

        system_prompt = (
            "你是一位严格公正的专业判题阅卷专家。请依据题干、标准参考答案与评分细则对考生的主观题作答进行打分。"
            f"本题满分基准为 {item.max_score} 分。请严格输出结构化 JSON 格式数据，"
            "包含 score, confidence, feedback, hit_keywords, missing_keywords, evaluations 字段。"
        )
        user_prompt = (
            f"【题型】: {snapshot.get('question_type', '')}\n"
            f"【题干】: {snapshot.get('stem', '')}\n"
            f"【参考答案】: {snapshot.get('answer', '')}\n"
            f"【评分细则】: {json.dumps(snapshot.get('grading_rubric', {}), ensure_ascii=False)}\n"
            f"【考生作答】: {user_ans}\n"
            f"【本题满分】: {item.max_score}"
        )
        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=user_prompt),
        ]
        options = LLMOptions(timeout=20.0, temperature=0.2)

        try:
            output, resp = self.llm_adapter.generate_structured(
                messages=messages,
                response_model=LLMGradingOutput,
                options=options,
            )

            clamped_score = min(item.max_score, max(0.0, float(output.score)))
            final_score = round_half_up(clamped_score, SCORE_ROUNDING_UNIT)
            is_correct = bool(final_score >= item.max_score * 0.6)

            item.score = final_score

            self.grading_repo.set_records_non_final_by_attempt_id(item.id, user_id=user_id)
            record = GradingRecord(
                id=uuid.uuid4(),
                practice_id=practice_id,
                attempt_item_id=item.id,
                question_id=item.question_id,
                channel=GradingChannel.AI.value,
                status=GradingStatus.SUCCESS.value,
                is_final=True,
                score=final_score,
                max_score=item.max_score,
                confidence=min(1.0, max(0.0, float(output.confidence))),
                feedback=output.feedback,
                hit_keywords=list(output.hit_keywords),
                missing_keywords=list(output.missing_keywords),
                grading_metadata={
                    "is_correct": is_correct,
                    "evaluations": [e.model_dump() for e in output.evaluations],
                    "duration_ms": resp.duration_ms,
                    "model": resp.model,
                },
            )
            self.grading_repo.create_record(record, user_id=user_id)
            return record, False

        except Exception as exc:
            # 绝密脱敏：日志绝不记录作答原文，仅记录异常与耗时
            logger.warning("LLM判题异常或超时降级为待重判: %s", str(exc)[:200])
            return self._build_pending_regrade_record(
                item=item,
                practice_id=practice_id,
                user_id=user_id,
                error_msg=str(exc)[:200],
            )

    def _build_pending_regrade_record(
        self,
        item: AttemptItem,
        practice_id: uuid.UUID,
        user_id: uuid.UUID,
        error_msg: str,
    ) -> tuple[GradingRecord, bool]:
        """构建待重新判题降级记录 (FR-42 严禁判错)。"""
        # 待重判时作答项得分为“未定分”(None)，与真实 0 分区分，供前端判定为待重新判题
        item.score = None

        # 仅在即将生成新生效记录前失效旧记录，保证任何异常前旧生效记录仍完整
        self.grading_repo.set_records_non_final_by_attempt_id(item.id, user_id=user_id)
        record = GradingRecord(
            id=uuid.uuid4(),
            practice_id=practice_id,
            attempt_item_id=item.id,
            question_id=item.question_id,
            channel=GradingChannel.AI.value,
            status=GradingStatus.PENDING_REGRADE.value,
            is_final=True,
            score=0.0,
            max_score=item.max_score,
            confidence=None,
            feedback="AI判题超时，已加入待重判队列",
            hit_keywords=[],
            missing_keywords=[],
            grading_metadata={"fallback_reason": error_msg, "is_correct": False},
        )
        self.grading_repo.create_record(record, user_id=user_id)
        return record, True

    # --------------------------------------------------------------------------
    # 2. 用户主观题自主评分 (self_evaluate_attempt)
    # --------------------------------------------------------------------------

    def self_evaluate_attempt(
        self,
        *args: Any,
        user_id: uuid.UUID | None = None,
        dto: SelfEvaluateDTO | None = None,
        attempt_item_id: uuid.UUID | None = None,
        score: float | None = None,
        is_correct: bool | None = None,
        user_feedback: str | None = None,
        request_id: str = "",
    ) -> GradingRecord:
        """用户主观题自主评分覆盖。

        支持多种调用签名：
        - self_evaluate_attempt(user_id, dto)
        - self_evaluate_attempt(user_id=user_id, dto=dto)
        - self_evaluate_attempt(attempt_item_id, user_id, score, is_correct, user_feedback)

        Args:
            *args: 位置入参。
            user_id: 租户用户标识。
            dto: 自评传输对象。
            attempt_item_id: 作答项标识。
            score: 分数。
            is_correct: 是否判定为正确。
            user_feedback: 用户自评反馈。
            request_id: 请求跟踪标识。

        Returns:
            GradingRecord: 生成并生效的自评记录。

        Raises:
            AttemptItemNotFoundError: 作答项不存在或无权访问。
            GradingNotAllowedError: 客观题自评或分值超出上限。
        """
        start_time = time.perf_counter()

        # 解析灵活入参
        resolved_user_id = user_id
        resolved_item_id = attempt_item_id
        resolved_score = score
        resolved_feedback = user_feedback
        resolved_is_correct = is_correct

        if len(args) == 2:
            if isinstance(args[1], SelfEvaluateDTO):
                resolved_user_id = args[0]
                dto = args[1]
            elif isinstance(args[0], SelfEvaluateDTO):
                dto = args[0]
                resolved_user_id = args[1]
        elif len(args) >= 3:
            resolved_item_id = args[0]
            resolved_user_id = args[1]
            resolved_score = float(args[2])
            if len(args) >= 4:
                resolved_is_correct = bool(args[3])
            if len(args) >= 5:
                resolved_feedback = args[4]
        elif len(args) == 1:
            if isinstance(args[0], SelfEvaluateDTO):
                dto = args[0]
            elif isinstance(args[0], uuid.UUID):
                resolved_user_id = args[0]

        if dto is not None:
            resolved_item_id = dto.attempt_item_id
            resolved_score = float(dto.score)
            resolved_feedback = dto.feedback
            if resolved_is_correct is None:
                # 优先采纳用户显式指定的对错；为空时留待 score > 0 回退判定
                resolved_is_correct = dto.is_correct

        if resolved_user_id is None or resolved_item_id is None or resolved_score is None:
            raise GradingNotAllowedError("自评必须提供 user_id, attempt_item_id 及 score 参数")

        eval_score = float(resolved_score)
        eval_is_correct = (
            resolved_is_correct if resolved_is_correct is not None else (eval_score > 0)
        )

        # 1. 检索作答项并校验归属
        stmt = select(AttemptItem).where(
            AttemptItem.id == resolved_item_id,
            AttemptItem.user_id == resolved_user_id,
        )
        item = self.session.execute(stmt).scalars().first()
        if item is None:
            raise AttemptItemNotFoundError(
                "请求的作答题目明细不存在或无权访问",
                details={"attempt_item_id": str(resolved_item_id)},
            )

        # 2. 客观题校验：客观题严禁自评 (FR-44)
        snapshot = item.question_snapshot or {}
        q_type = snapshot.get("question_type", "")
        if q_type in OBJECTIVE_QUESTION_TYPES:
            raise GradingNotAllowedError(
                "客观选择与判断题由系统客观判分，不允许用户自主评分",
                details={"question_type": q_type, "attempt_item_id": str(resolved_item_id)},
            )

        # 3. 分值边界校验 [0.0, item.max_score]
        if eval_score < 0.0 or eval_score > item.max_score:
            raise GradingNotAllowedError(
                f"自主评分分值 ({eval_score}) 超出合法范围 [0.0, {item.max_score}]",
                details={"score": eval_score, "max_score": item.max_score},
            )

        # 4. 原子切换原生效记录为失效
        self.grading_repo.set_records_non_final_by_attempt_id(item.id, user_id=resolved_user_id)

        # 5. 持久化新生效的自评记录
        record = GradingRecord(
            id=uuid.uuid4(),
            practice_id=item.practice_id,
            attempt_item_id=item.id,
            question_id=item.question_id,
            channel=GradingChannel.USER_SELF.value,
            status=GradingStatus.SUCCESS.value,
            is_final=True,
            score=eval_score,
            max_score=item.max_score,
            confidence=1.0,
            feedback=resolved_feedback or "用户自主评分",
            hit_keywords=[],
            missing_keywords=[],
            grading_metadata={"user_self_eval": True, "is_correct": eval_is_correct},
        )
        self.grading_repo.create_record(record, user_id=resolved_user_id)

        # 6. 更新 AttemptItem
        item.score = eval_score

        # 7. 重新汇总整卷总分与状态
        practice = self.practice_repo.get_practice_by_id(
            item.practice_id, resolved_user_id, include_items=True
        )
        if practice is not None:
            practice.total_score = round(sum(it.score or 0.0 for it in practice.items), 2)
            pending_count = self.grading_repo.count_pending_regrade(
                practice.id, user_id=resolved_user_id
            )
            if pending_count == 0:
                practice.status = PracticeStatus.COMPLETED.value
                if not practice.completed_at:
                    practice.completed_at = datetime.now(UTC)
            else:
                practice.status = PracticeStatus.PARTIALLY_GRADED.value

        self.session.flush()

        duration_ms = (time.perf_counter() - start_time) * 1000
        self._log_metric(
            action="self_evaluate_attempt",
            request_id=request_id,
            user_id=resolved_user_id,
            target_id=resolved_item_id,
            duration_ms=duration_ms,
            extra={"score": eval_score, "is_correct": eval_is_correct},
        )

        return record

    # --------------------------------------------------------------------------
    # 3. 主观题重新判题 (regrade_attempt)
    # --------------------------------------------------------------------------

    def regrade_attempt(
        self,
        *args: Any,
        user_id: uuid.UUID | None = None,
        dto: RegradeAttemptDTO | None = None,
        attempt_item_id: uuid.UUID | None = None,
        request_id: str = "",
    ) -> GradingRecord:
        """主观题重新判题流程。

        支持多种调用签名：
        - regrade_attempt(user_id, dto)
        - regrade_attempt(user_id=user_id, dto=dto)
        - regrade_attempt(attempt_item_id, user_id)

        Args:
            *args: 位置入参。
            user_id: 租户用户标识。
            dto: 重判传输对象。
            attempt_item_id: 作答项标识。
            request_id: 请求跟踪标识。

        Returns:
            GradingRecord: 重判生成的生效记录。

        Raises:
            AttemptItemNotFoundError: 作答项不存在或无权访问。
            GradingNotAllowedError: 客观题或未作答题目不允许重判。
            GradingExecutionError: 大模型重判调用失败。
        """
        start_time = time.perf_counter()

        resolved_user_id = user_id
        resolved_item_id = attempt_item_id

        if len(args) == 2:
            if isinstance(args[1], RegradeAttemptDTO):
                resolved_user_id = args[0]
                dto = args[1]
            elif isinstance(args[0], RegradeAttemptDTO):
                dto = args[0]
                resolved_user_id = args[1]
            elif isinstance(args[0], uuid.UUID) and isinstance(args[1], uuid.UUID):
                resolved_item_id = args[0]
                resolved_user_id = args[1]
        elif len(args) == 1:
            if isinstance(args[0], RegradeAttemptDTO):
                dto = args[0]
            elif isinstance(args[0], uuid.UUID):
                resolved_user_id = args[0]

        if dto is not None:
            resolved_item_id = dto.attempt_item_id

        if resolved_user_id is None or resolved_item_id is None:
            raise GradingNotAllowedError("重判必须提供 user_id 与 attempt_item_id 参数")

        # 1. 检索作答项并校验归属
        stmt = select(AttemptItem).where(
            AttemptItem.id == resolved_item_id,
            AttemptItem.user_id == resolved_user_id,
        )
        item = self.session.execute(stmt).scalars().first()
        if item is None:
            raise AttemptItemNotFoundError(
                "请求的作答题目明细不存在或无权访问",
                details={"attempt_item_id": str(resolved_item_id)},
            )

        # 2. 题型校验：仅主观题支持重判
        snapshot = item.question_snapshot or {}
        q_type = snapshot.get("question_type", "")
        if q_type in OBJECTIVE_QUESTION_TYPES:
            raise GradingNotAllowedError(
                "客观题目不支持重新判题",
                details={"question_type": q_type, "attempt_item_id": str(resolved_item_id)},
            )

        if not item.is_answered or not item.user_answer:
            raise GradingNotAllowedError(
                "未作答题目不允许重判",
                details={"attempt_item_id": str(resolved_item_id)},
            )

        # 3. 调用大模型评分
        if self.llm_adapter is None:
            raise GradingExecutionError(
                "未配置大模型适配器，无法执行重新判题",
                details={"attempt_item_id": str(resolved_item_id)},
            )

        system_prompt = (
            "你是一位严格公正的专业阅卷专家。请依据题干、标准参考答案与评分细则对考生主观题作答重新打分。"
            f"本题满分为 {item.max_score} 分。"
            "输出严格 JSON 格式：score, confidence, feedback, evaluations。"
        )
        user_prompt = (
            f"【题型】: {q_type}\n"
            f"【题干】: {snapshot.get('stem', '')}\n"
            f"【参考答案】: {snapshot.get('answer', '')}\n"
            f"【评分细则】: {json.dumps(snapshot.get('grading_rubric', {}), ensure_ascii=False)}\n"
            f"【考生作答】: {item.user_answer}\n"
            f"【本题满分】: {item.max_score}"
        )
        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=user_prompt),
        ]
        options = LLMOptions(timeout=20.0, temperature=0.2)

        try:
            output, resp = self.llm_adapter.generate_structured(
                messages=messages,
                response_model=LLMGradingOutput,
                options=options,
            )
        except Exception as exc:
            logger.warning("大模型重判异常失败: %s", str(exc)[:200])
            raise GradingExecutionError(
                f"大模型重判执行失败: {exc}",
                details={"attempt_item_id": str(resolved_item_id)},
            ) from exc

        clamped_score = min(item.max_score, max(0.0, float(output.score)))
        final_score = round_half_up(clamped_score, SCORE_ROUNDING_UNIT)
        is_correct = bool(final_score >= item.max_score * 0.6)

        # 4. 原记录置为失效
        self.grading_repo.set_records_non_final_by_attempt_id(item.id, user_id=resolved_user_id)

        # 5. 持久化新 AI 重判记录
        record = GradingRecord(
            id=uuid.uuid4(),
            practice_id=item.practice_id,
            attempt_item_id=item.id,
            question_id=item.question_id,
            channel=GradingChannel.AI.value,
            status=GradingStatus.SUCCESS.value,
            is_final=True,
            score=final_score,
            max_score=item.max_score,
            confidence=min(1.0, max(0.0, float(output.confidence))),
            feedback=output.feedback,
            hit_keywords=list(output.hit_keywords),
            missing_keywords=list(output.missing_keywords),
            grading_metadata={
                "regrade": True,
                "is_correct": is_correct,
                "evaluations": [e.model_dump() for e in output.evaluations],
                "duration_ms": resp.duration_ms,
                "model": resp.model,
            },
        )
        self.grading_repo.create_record(record, user_id=resolved_user_id)

        # 6. 更新 AttemptItem 与练习状态
        item.score = final_score

        practice = self.practice_repo.get_practice_by_id(
            item.practice_id, resolved_user_id, include_items=True
        )
        if practice is not None:
            practice.total_score = round(sum(it.score or 0.0 for it in practice.items), 2)
            pending_count = self.grading_repo.count_pending_regrade(
                practice.id, user_id=resolved_user_id
            )
            if pending_count == 0:
                practice.status = PracticeStatus.COMPLETED.value
                if not practice.completed_at:
                    practice.completed_at = datetime.now(UTC)
            else:
                practice.status = PracticeStatus.PARTIALLY_GRADED.value

        self.session.flush()

        duration_ms = (time.perf_counter() - start_time) * 1000
        self._log_metric(
            action="regrade_attempt",
            request_id=request_id,
            user_id=resolved_user_id,
            target_id=resolved_item_id,
            duration_ms=duration_ms,
            extra={"score": final_score, "is_correct": is_correct},
        )

        return record

    # --------------------------------------------------------------------------
    # 4. 作答判题记录与历史明细只读查询 (get_attempt_grading_detail)
    # --------------------------------------------------------------------------

    def get_attempt_grading_detail(
        self,
        user_id: uuid.UUID,
        attempt_item_id: uuid.UUID,
        request_id: str = "",
    ) -> AttemptGradingDetailDTO:
        """获取指定作答项的最新生效判题记录与全部历史记录。

        为只读查询方法，严格遵循租户隔离与单向分层。

        Args:
            user_id: 租户用户标识。
            attempt_item_id: 作答项主键标识。
            request_id: 请求跟踪标识。

        Returns:
            AttemptGradingDetailDTO: 包含最新生效记录与历史记录明细的传输对象。

        Raises:
            AttemptItemNotFoundError: 作答项不存在或跨租户越权访问 (40013)。
        """
        start_time = time.perf_counter()

        # 1. 验证作答项是否存在且属于该 user_id
        if hasattr(self.practice_repo, "get_attempt_item_by_id"):
            item = self.practice_repo.get_attempt_item_by_id(attempt_item_id, user_id=user_id)
        else:
            stmt = select(AttemptItem).where(
                AttemptItem.id == attempt_item_id,
                AttemptItem.user_id == user_id,
            )
            item = self.session.execute(stmt).scalars().first()

        if item is None:
            raise AttemptItemNotFoundError(attempt_item_id=attempt_item_id)

        # 2. 查询最新生效记录与全部历史判题记录
        if hasattr(self.grading_repo, "get_latest_record_by_attempt_id"):
            latest_grading = self.grading_repo.get_latest_record_by_attempt_id(
                attempt_item_id,
                user_id=user_id,
            )
        else:
            latest_grading = self.grading_repo.get_final_record_for_attempt(
                attempt_item_id,
                user_id=user_id,
            )

        if hasattr(self.grading_repo, "list_records_by_attempt_id"):
            records = self.grading_repo.list_records_by_attempt_id(
                attempt_item_id,
                user_id=user_id,
            )
        else:
            records = self.grading_repo.list_records_by_attempt_item(
                attempt_item_id,
                user_id=user_id,
            )

        # 3. 输出结构化脱敏日志 8 要素 (严禁记录题干、标准答案与考生作答)
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        self._log_metric(
            action="get_attempt_grading_detail",
            request_id=request_id,
            user_id=user_id,
            target_id=attempt_item_id,
            duration_ms=duration_ms,
            error_code=0,
            extra={
                "records_count": len(records),
                "has_latest": latest_grading is not None,
            },
        )

        return AttemptGradingDetailDTO(
            attempt_item_id=attempt_item_id,
            practice_id=item.practice_id,
            question_id=item.question_id,
            latest_grading=latest_grading,
            current_record=latest_grading,
            records=records,
            history=records,
        )


__all__ = [
    "AttemptGradingDetailDTO",
    "GradingService",
    "LLMGradingOutput",
    "LLMGradingRubricEvaluation",
    "PracticeGradingSummary",
    "RegradeAttemptDTO",
    "SelfEvaluateDTO",
]
