"""练习、答卷、掌握度与诊断报告持久化模型定义。

包含多维度练习主表、解耦型作答项快照表、混合判题记录表、
遗忘衰减掌握度表、错题归因诊断报告表以及防重累加错题本表。
"""

import enum
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.models.base import Base, TenantModelMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.knowledge import KnowledgePoint
    from app.models.material import Material  # noqa: F401
    from app.models.question import Question  # noqa: F401


class PracticeStatus(enum.StrEnum):
    """练习生命周期状态枚举。

    遵循技术决策 1 两阶段状态机模型：
    NOT_STARTED: 已创建，尚未打开或作答
    IN_PROGRESS: 作答进行中
    PARTIALLY_GRADED: 部分判分/未决态 (存在 pending_regrade 主观题，阻断掌握度与报告)
    COMPLETED: 全卷终态判完 (已生成掌握度快照与正式诊断报告)
    """

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    PARTIALLY_GRADED = "partially_graded"
    COMPLETED = "completed"


class PracticeSourceType(enum.StrEnum):
    """练习来源类型枚举。

    NORMAL: 常规创建练习 (选定资料与知识点范围)
    WEAKNESS: 薄弱知识点强化 / 诊断报告末尾一键继续练习 (FR-58)
    WRONG_RECORD: 错题本一键巩固练习 (错题来源)
    """

    NORMAL = "normal"
    WEAKNESS = "weakness"
    WRONG_RECORD = "wrong_record"


class GradingChannel(enum.StrEnum):
    """判题渠道枚举 (覆盖需求 FR-43 规定的三类判题来源)。"""

    OFFLINE = "offline"  # 离线确定性判分 (客观题秒判 / 主观题高置信度双阈值匹配)
    AI = "ai"  # 大模型判题 (主观题兜底)
    USER_SELF = "user_self"  # 用户自评覆盖 (FR-44)


class GradingStatus(enum.StrEnum):
    """判题处理状态枚举。"""

    PENDING = "pending"  # 待判题 (进入队列)
    SUCCESS = "success"  # 判定成功并已计算分值
    PENDING_REGRADE = "pending_regrade"  # 待重新判题 (LLM 20s 超时或限流降级，严禁判错)
    FAILED = "failed"  # 判定异常失败


class MasteryLevel(enum.StrEnum):
    """知识点掌握度四档评级枚举 (覆盖需求 FR-48)。

    UNLEARNED: 未学 (mastery_score == 0.0 或无作答记录)
    WEAK: 薄弱 (0.0 < mastery_score < 0.40)
    BASIC: 基本掌握 (0.40 <= mastery_score < 0.70)
    PROFICIENT: 熟练 (0.70 <= mastery_score <= 1.0)
    """

    UNLEARNED = "unlearned"
    WEAK = "weak"
    BASIC = "basic"
    PROFICIENT = "proficient"


class ErrorType(enum.StrEnum):
    """错题错误归因类型枚举 (覆盖需求 FR-55 四类一票否决归因)。"""

    CONCEPTUAL = "conceptual"  # 概念性错误 (核心知识点理解偏差)
    INCOMPLETE_EXPRESSION = "incomplete_expression"  # 表述不全 (要点遗漏)
    QUESTION_MISREADING = "question_misreading"  # 审题偏差 (误解题干限定条件)
    UNANSWERED = "unanswered"  # 未作答 (FR-36 独立分类统计)


def validate_question_snapshot(snapshot: dict[str, Any]) -> tuple[bool, str | None]:
    """题目 6 要素快照完整性与自洽性纯函数校验。

    Args:
        snapshot: 待校验的题目快照字典数据

    Returns:
        tuple[bool, str | None]: (是否校验通过, 错误原因说明)
    """
    if not isinstance(snapshot, dict):
        return False, "snapshot must be a dictionary"

    stem = snapshot.get("stem")
    if not stem or not isinstance(stem, str) or not stem.strip():
        return False, "stem is required and cannot be empty"

    question_type = snapshot.get("question_type")
    if not question_type or not isinstance(question_type, str):
        return False, "question_type is required"

    answer = snapshot.get("answer")
    if answer is None or (isinstance(answer, str) and not answer.strip()):
        return False, "answer is required and cannot be empty"

    # 客观选择题 (单选、多选) options 校验
    if question_type in ("single_choice", "multiple_choice"):
        options = snapshot.get("options")
        if not options or not isinstance(options, list) or len(options) < 2:
            return False, "options must be a list with at least 2 items for choice questions"
        for opt in options:
            if not isinstance(opt, dict) or "key" not in opt or "content" not in opt:
                return False, "each option must contain 'key' and 'content'"

    # 主观题评分细则分值核算校验
    grading_rubric = snapshot.get("grading_rubric")
    if grading_rubric and isinstance(grading_rubric, dict):
        total_score = grading_rubric.get("total_score")
        dimensions = grading_rubric.get("dimensions") or grading_rubric.get("points")
        if total_score is not None and dimensions and isinstance(dimensions, list):
            points_sum = 0.0
            for d in dimensions:
                if isinstance(d, dict):
                    pt = d.get("points", d.get("score", 0.0))
                    if isinstance(pt, (int, float)):
                        points_sum += float(pt)
            if abs(points_sum - float(total_score)) > 1e-4:
                return False, (
                    f"Sum of rubric points ({points_sum}) "
                    f"does not match total_score ({total_score})"
                )

    return True, None


def validate_practice_transition(
    current_status: PracticeStatus | str,
    has_pending_regrade: bool,
    all_items_graded: bool,
) -> tuple[bool, str | None, PracticeStatus | None]:
    """两阶段答卷状态机跃迁决策纯函数。

    依据技术决策 1：
    1. 答卷存在待重新判题 (pending_regrade) 时跃迁为 PARTIALLY_GRADED；
    2. 全卷所有题目判分完成且无待重判时，跃迁为 COMPLETED；
    3. COMPLETED 状态不可逆。

    Args:
        current_status: 当前练习状态
        has_pending_regrade: 是否存在待重新判题题目
        all_items_graded: 是否所有作答项均已判分

    Returns:
        tuple[bool, str | None, PracticeStatus | None]:
            (是否允许跃迁, 拒绝原因, 目标状态)
    """
    status_str = (
        current_status.value if isinstance(current_status, PracticeStatus) else current_status
    )

    if status_str == PracticeStatus.NOT_STARTED.value:
        return True, None, PracticeStatus.IN_PROGRESS

    if status_str == PracticeStatus.IN_PROGRESS.value:
        if has_pending_regrade:
            return True, None, PracticeStatus.PARTIALLY_GRADED
        if all_items_graded:
            return True, None, PracticeStatus.COMPLETED
        return True, None, PracticeStatus.IN_PROGRESS

    if status_str == PracticeStatus.PARTIALLY_GRADED.value:
        if has_pending_regrade:
            return False, "Cannot complete practice with pending_regrade items", None
        if all_items_graded:
            return True, None, PracticeStatus.COMPLETED
        return True, None, PracticeStatus.PARTIALLY_GRADED

    if status_str == PracticeStatus.COMPLETED.value:
        return False, "Practice already completed and is immutable", None

    return False, f"Unknown practice status: {status_str}", None


class Practice(Base, TimestampMixin, TenantModelMixin):
    """练习主实体模型。

    承载自主练习生命周期、出题打散配置、交卷强幂等与学情报告归属。
    """

    __tablename__ = "practices"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="练习主键 UUIDv4",
    )
    material_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("materials.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联学习资料标识",
    )
    title: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="练习标题 (如: 计算机网络第3章-专项练习)",
    )
    knowledge_point_ids: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=list,
        comment="练习覆盖的知识点 UUID 列表",
    )
    question_types: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=list,
        comment="包含的题型范围列表",
    )
    difficulty: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        default=None,
        comment="期望难度偏好 (1~5，空为混合)",
    )
    question_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="练习题目总数 (1~50)",
    )
    ordered_question_ids: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=list,
        comment="固化打散后的题目 ID 有序列表 (同知识点不相邻)",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=PracticeStatus.NOT_STARTED.value,
        index=True,
        comment="练习生命周期状态 (PracticeStatus)",
    )
    source_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=PracticeSourceType.NORMAL.value,
        comment="练习来源类型 (PracticeSourceType: normal/weakness)",
    )
    source_report_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "diagnosis_reports.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_practices_source_report_id",
        ),
        nullable=True,
        index=True,
        comment="来源诊断报告标识 (用于继续练习防重合并)",
    )
    submit_idempotency_key: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="交卷强幂等键 (客户端 UUIDv4 标识)",
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment="客户端答卷提交时间戳 (UTC)",
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment="全卷所有题目判分完成时间戳 (UTC)",
    )
    total_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        default=None,
        comment="卷面最终累计得分",
    )
    max_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        default=None,
        comment="卷面总满分分值",
    )

    # 关系映射
    items: Mapped[list["AttemptItem"]] = relationship(
        "AttemptItem",
        back_populates="practice",
        cascade="all, delete-orphan",
        order_by="AttemptItem.order_index",
    )
    grading_records: Mapped[list["GradingRecord"]] = relationship(
        "GradingRecord",
        back_populates="practice",
        cascade="all, delete-orphan",
    )
    diagnosis_report: Mapped["DiagnosisReport | None"] = relationship(
        "DiagnosisReport",
        back_populates="practice",
        uselist=False,
        cascade="all, delete-orphan",
        foreign_keys="DiagnosisReport.practice_id",
    )

    __table_args__ = (
        # 继续练习防重合并索引 (快速检索同来源未开始练习, FR-58)
        Index("ix_practices_user_source_status", "user_id", "source_report_id", "status"),
        # 资料维度练习列表索引
        Index("ix_practices_user_mat_status", "user_id", "material_id", "status"),
        # 用户练习状态索引
        Index("ix_practices_user_status", "user_id", "status"),
        # 交卷强幂等联合唯一索引 (阻断24小时内重复交卷, FR-35)
        Index(
            "uq_practices_user_submit_key",
            "user_id",
            "submit_idempotency_key",
            unique=True,
            postgresql_where=text("submit_idempotency_key IS NOT NULL"),
        ),
    )

    def __repr__(self) -> str:
        """绝密脱敏日志展示，严禁泄漏题目、答案及细则全文。"""
        return (
            f"<Practice id={self.id} user_id={self.user_id} status={self.status} "
            f"count={self.question_count} score={self.total_score}/{self.max_score}>"
        )


class AttemptItem(Base, TimestampMixin, TenantModelMixin):
    """答卷作答项与题目快照实体模型。

    落实技术决策 2：question_id 为可空弱外键，强制存储 question_snapshot (JSONB)
    实现原题软删除/更新与历史答卷的物理彻底解耦。
    """

    __tablename__ = "attempt_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="作答项主键 UUIDv4",
    )
    practice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("practices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联练习主键",
    )
    question_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("questions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="关联题目弱外键 (SET NULL, 物理彻底解耦)",
    )
    order_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="卷面题目序号 (从 1 起始)",
    )
    question_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        comment="题目完整 6 要素快照 (题干/选项/答案/解析/细则/切片)",
    )
    user_answer: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
        comment="用户作答文本或选项标识 (严禁写入日志)",
    )
    is_answered: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="是否实际作答 (未作答题目独立标记按零分计, FR-36)",
    )
    duration_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="单题作答耗时 (秒)",
    )
    score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        default=None,
        comment="本题最终判定得分",
    )
    max_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=1.0,
        comment="本题满分基准分值",
    )

    # 关系映射
    practice: Mapped["Practice"] = relationship(
        "Practice",
        back_populates="items",
    )
    grading_records: Mapped[list["GradingRecord"]] = relationship(
        "GradingRecord",
        back_populates="attempt_item",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        # 逐题保存强幂等键 (支持断网恢复与逐题保存, FR-34)
        UniqueConstraint("practice_id", "question_id", name="uq_attempt_items_practice_question"),
        Index("ix_attempt_items_practice_order", "practice_id", "order_index"),
        Index("ix_attempt_items_user_practice", "user_id", "practice_id"),
    )

    def __repr__(self) -> str:
        """绝密脱敏日志展示，严禁泄漏 user_answer 与 question_snapshot 全文。"""
        ans_len = len(self.user_answer) if self.user_answer else 0
        return (
            f"<AttemptItem id={self.id} practice_id={self.practice_id} "
            f"q_id={self.question_id} order={self.order_index} "
            f"answered={self.is_answered} ans_len={ans_len} score={self.score}>"
        )


class GradingRecord(Base, TimestampMixin, TenantModelMixin):
    """混合判题记录与审计追踪实体模型。

    支持离线规则判题、AI 判题与用户自评历史并存，通过 is_final 标记当前生效判定。
    """

    __tablename__ = "grading_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="判题记录主键 UUIDv4",
    )
    practice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("practices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联练习主键",
    )
    attempt_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attempt_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联作答项主键",
    )
    question_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("questions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="弱关联题目标识",
    )
    channel: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="判题渠道 (GradingChannel: offline/ai/user_self)",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="判题状态 (GradingStatus: pending/success/pending_regrade/failed)",
    )
    is_final: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="是否为最终生效判分结果",
    )
    score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        default=None,
        comment="本次判定得分",
    )
    max_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=1.0,
        comment="满分基准分值",
    )
    similarity_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        default=None,
        comment="主观题离线双阈值比对相似度/向量余弦分",
    )
    hit_keywords: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=list,
        comment="命中要点关键词列表",
    )
    missing_keywords: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=list,
        comment="遗漏核心要点列表",
    )
    confidence: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        default=None,
        comment="判题置信度评分 (0.0~1.0)",
    )
    feedback: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
        comment="判题评语与得分反馈说明 (严禁直接记录日志)",
    )
    grading_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
        comment="过程元数据 (LLM token/耗时/Prompt版本/离线特征等)",
    )

    # 关系映射
    practice: Mapped["Practice"] = relationship(
        "Practice",
        back_populates="grading_records",
    )
    attempt_item: Mapped["AttemptItem"] = relationship(
        "AttemptItem",
        back_populates="grading_records",
    )

    __table_args__ = (
        Index("ix_grading_records_item_final", "attempt_item_id", "is_final"),
        Index("ix_grading_records_practice_status", "practice_id", "status"),
        Index("ix_grading_records_user_practice", "user_id", "practice_id"),
    )

    def __repr__(self) -> str:
        """绝密脱敏日志展示，严禁泄漏 feedback, hit_keywords, missing_keywords。"""
        return (
            f"<GradingRecord id={self.id} item_id={self.attempt_item_id} channel={self.channel} "
            f"status={self.status} final={self.is_final} score={self.score}/{self.max_score}>"
        )


class MasteryRecord(Base, TimestampMixin, TenantModelMixin):
    """知识点掌握度持久化实体模型。

    按 (user_id, knowledge_point_id) 唯一聚合，结合 30 天半衰期时间衰减算法。
    """

    __tablename__ = "mastery_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="掌握度记录主键 UUIDv4",
    )
    knowledge_point_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_points.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联知识点主键",
    )
    mastery_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        comment="连续掌握度数值 (0.0~1.0)",
    )
    level: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=MasteryLevel.UNLEARNED.value,
        comment="掌握度档次 (MasteryLevel)",
    )
    practice_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="累计有效作答题目数",
    )
    correct_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="累计正确/达标次数",
    )
    last_practiced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment="最后有效作答时间 (30天半衰期衰减基准)",
    )
    decayed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment="上次衰减计算时间戳 (UTC)",
    )
    recent_records_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=list,
        comment="参与计算的最近200条有效答题记录简要元数据快照",
    )

    # 关系映射
    knowledge_point: Mapped["KnowledgePoint"] = relationship(
        "KnowledgePoint",
    )

    __table_args__ = (
        UniqueConstraint("user_id", "knowledge_point_id", name="uq_mastery_records_user_kp"),
        Index("ix_mastery_records_user_level", "user_id", "level"),
    )

    def __repr__(self) -> str:
        """绝密脱敏日志展示。"""
        return (
            f"<MasteryRecord id={self.id} user_id={self.user_id} kp_id={self.knowledge_point_id} "
            f"score={self.mastery_score:.2f} level={self.level} count={self.practice_count}>"
        )


class DiagnosisReport(Base, TimestampMixin, TenantModelMixin):
    """诊断报告实体模型。

    与练习严格 1:1 强一致关联，落实 FR-50 薄弱知识点必须关联错题的数据驱动要求。
    """

    __tablename__ = "diagnosis_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="诊断报告主键 UUIDv4",
    )
    practice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("practices.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        comment="关联练习主键 (1:1 强一致)",
    )
    weak_knowledge_points: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=list,
        comment="主要薄弱知识点列表 (强关联本次错题ID，无错题必须为空)",
    )
    regressed_knowledge_points: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=list,
        comment="退步知识点列表 (与上次快照相比退步量 Delta >= 0.05)",
    )
    analysis_causes: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=list,
        comment="结构化作答归因列表",
    )
    actionable_suggestions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=list,
        comment="行动建议与一键继续练习入口数据",
    )
    unanswered_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="未作答题目数 (FR-36 独立统计)",
    )
    wrong_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="答错题目数",
    )
    pending_regrade_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="待重新判题题目数 (正式报告应为0)",
    )
    total_questions: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="卷面题目总数",
    )
    score_rate: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        comment="卷面整体得分率 (0.0~1.0)",
    )
    is_structure_degraded: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="知识结构降级标记 (低可信度黄色标签)",
    )

    # 关系映射
    practice: Mapped["Practice"] = relationship(
        "Practice",
        back_populates="diagnosis_report",
        foreign_keys=[practice_id],
    )

    __table_args__ = (
        UniqueConstraint("practice_id", name="uq_diagnosis_reports_practice_id"),
        Index("ix_diagnosis_reports_user_created", "user_id", "created_at"),
    )

    def __repr__(self) -> str:
        """绝密脱敏日志展示。"""
        return (
            f"<DiagnosisReport id={self.id} practice_id={self.practice_id} "
            f"score_rate={self.score_rate:.2f} wrong={self.wrong_count} "
            f"unanswered={self.unanswered_count} degraded={self.is_structure_degraded}>"
        )


class WrongRecord(Base, TimestampMixin, TenantModelMixin):
    """防重累加错题本实体模型。

    建立 (user_id, question_id) 联合唯一键，支持连续答错 error_count 累加，
    支持攻克掌握 is_mastered 软状态流转，独立固化题目快照。
    """

    __tablename__ = "wrong_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="错题记录主键 UUIDv4",
    )
    question_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("questions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="关联题目弱外键 (SET NULL, 题目删除不破坏错题)",
    )
    knowledge_point_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_points.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联知识点标识",
    )
    practice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("practices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="最近答错练习标识",
    )
    attempt_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attempt_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="最近答错作答项标识",
    )
    error_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="错误类型 (ErrorType: 4类一票否决归因)",
    )
    error_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="连续答错累计次数 (重做答错累加)",
    )
    is_mastered: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="是否已攻克掌握 (重做正确后置为True，保留历史记录可查)",
    )
    last_wrong_answer: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
        comment="最近一次错误作答内容 (严禁打印入日志)",
    )
    question_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        comment="冗余备份题目快照 (题干/选项/解析，保证原题被删除时错题本仍可独立完整渲染)",
    )
    first_wrong_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(UTC),
        nullable=False,
        comment="首次答错时间戳 (UTC)",
    )
    mastered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment="攻克掌握时间戳 (UTC)",
    )

    # 关系映射
    knowledge_point: Mapped["KnowledgePoint"] = relationship(
        "KnowledgePoint",
    )
    practice: Mapped["Practice"] = relationship(
        "Practice",
    )
    attempt_item: Mapped["AttemptItem"] = relationship(
        "AttemptItem",
    )

    __table_args__ = (
        # 同一用户同一题目错题记录唯一 (FR-54)
        UniqueConstraint("user_id", "question_id", name="uq_wrong_records_user_question"),
        Index("ix_wrong_records_user_mastered_type", "user_id", "is_mastered", "error_type"),
        Index("ix_wrong_records_user_kp_mastered", "user_id", "knowledge_point_id", "is_mastered"),
    )

    def __repr__(self) -> str:
        """绝密脱敏日志展示，严禁泄漏 last_wrong_answer 与 question_snapshot 全文。"""
        ans_len = len(self.last_wrong_answer) if self.last_wrong_answer else 0
        return (
            f"<WrongRecord id={self.id} user_id={self.user_id} q_id={self.question_id} "
            f"type={self.error_type} count={self.error_count} "
            f"mastered={self.is_mastered} ans_len={ans_len}>"
        )
