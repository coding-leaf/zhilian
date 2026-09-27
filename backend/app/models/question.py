"""题目主实体、质检记录与审计日志持久化模型定义。

包含 7 大题型题目主表 (支持 1024 维 HNSW 余弦查重向量索引)、
四类一票否决式质检记录表以及不可变修改痕迹审计日志表。
"""

import enum
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.models.base import Base, TenantModelMixin, TimestampMixin
from app.models.material import get_vector_type

if TYPE_CHECKING:
    from app.models.knowledge import KnowledgePoint
    from app.models.material import MaterialSnippet


class QuestionType(enum.StrEnum):
    """题目类型枚举 (覆盖需求 FR-20 规定的七大题型)。"""

    SINGLE_CHOICE = "single_choice"  # 单项选择题
    MULTIPLE_CHOICE = "multiple_choice"  # 多项选择题 (>=3选项, >=2正确项)
    TRUE_FALSE = "true_false"  # 判断题 (二值答案)
    FILL_IN_BLANK = "fill_in_blank"  # 填空题
    TERM_EXPLANATION = "term_explanation"  # 名词解释 (主观题)
    SHORT_ANSWER = "short_answer"  # 简答题 (主观题)
    CASE_ANALYSIS = "case_analysis"  # 案例分析 (主观题)


class QuestionStatus(enum.StrEnum):
    """题目状态生命周期枚举。"""

    AVAILABLE = "available"  # 质检合格，可用状态
    PENDING_REVIEW = "pending_review"  # 待处理区 (质检拦截/生成缺陷)


class QualityCheckType(enum.StrEnum):
    """题目质检检查项类型枚举 (覆盖需求 FR-24 四类一票否决检查)。"""

    NO_SOURCE = "NO_SOURCE"  # 无来源题目 (无片段或实词重合率<0.30)
    DUPLICATE = "DUPLICATE"  # 重复题 (向量相似度>0.90或字符相似度>0.85)
    ANSWER_CONFLICT = "ANSWER_CONFLICT"  # 答案冲突 (题干相似度>0.88但答案不同)
    AMBIGUITY = "AMBIGUITY"  # 明显歧义 (题干过短/选项冲突/答案不合规)


class AuditAction(enum.StrEnum):
    """题目生命周期审计操作动作枚举 (覆盖需求 FR-26 修改痕迹)。"""

    CREATE = "CREATE"  # 初始生成入库
    EDIT = "EDIT"  # 用户编辑修改
    DELETE = "DELETE"  # 用户软删除
    REGENERATE = "REGENERATE"  # 重新生成替换


def validate_question_payload(question_data: dict[str, Any]) -> tuple[bool, str | None]:
    """题目 6 要素完整性与主客观题约束纯函数校验。

    Args:
        question_data: 待校验的题目字典数据

    Returns:
        tuple[bool, str | None]: (是否校验通过, 错误原因说明)
    """
    stem = question_data.get("stem")
    if not stem or not isinstance(stem, str) or not stem.strip():
        return False, "stem is required and cannot be empty"

    question_type = question_data.get("question_type")
    if not question_type or not isinstance(question_type, str):
        return False, "question_type is required"

    answer = question_data.get("answer")
    if answer is None or (isinstance(answer, str) and not answer.strip()):
        return False, "answer is required and cannot be empty"

    # 客观题 (单选、多选) options 校验
    if question_type in (QuestionType.SINGLE_CHOICE.value, QuestionType.MULTIPLE_CHOICE.value):
        options = question_data.get("options")
        if not options or not isinstance(options, list):
            return False, "options must be a non-empty list for objective choice questions"
        for opt in options:
            if not isinstance(opt, dict) or "key" not in opt or "content" not in opt:
                return False, "each option must contain 'key' and 'content'"

    # 主观题评分细则分值核算
    grading_rubric = question_data.get("grading_rubric")
    if grading_rubric and isinstance(grading_rubric, dict):
        total_score = grading_rubric.get("total_score")
        points = grading_rubric.get("points")
        if total_score is not None and points and isinstance(points, list):
            points_sum = sum(p.get("score", 0) for p in points if isinstance(p, dict))
            if points_sum != total_score:
                msg = (
                    f"Sum of rubric points ({points_sum}) "
                    f"does not match total_score ({total_score})"
                )
                return False, msg

    return True, None


class Question(Base, TimestampMixin, TenantModelMixin):
    """题目主实体模型。

    覆盖单选、多选、判断、填空、名词解释、简答、案例分析 7 大题型；
    严格落实题目 6 要素及主观题评分细则；集成 1024 维语义向量与 HNSW 查重索引。
    """

    __tablename__ = "questions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="题目主键 UUIDv4",
    )
    material_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("materials.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="归属学习资料主键",
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("material_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="归属资料版本标识",
    )
    knowledge_point_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_points.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属知识点标识 (要素6)",
    )
    source_snippet_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("material_snippets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="主来源切片标识 (要素5，支持外键追溯)",
    )
    question_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
        comment="题型枚举 (QuestionType)",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=QuestionStatus.AVAILABLE.value,
        index=True,
        comment="题目状态枚举: available(可用) / pending_review(待处理区)",
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        index=True,
        comment="软删除标记 (True表示已删除，与已有答卷解耦)",
    )
    batch_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        comment="出题生成批次标识 (同一次生成共享，用于按批次分类；历史数据可空)",
    )

    # 题目 6 要素与扩展数据
    stem: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="题干全文 (要素1)",
    )
    options: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=list,
        comment="客观题选项列表 (结构: [{'key': 'A', 'content': '...'}])",
    )
    answer: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="参考答案或标准答案 (要素2)",
    )
    analysis: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        comment="题目解析与知识点阐述 (要素3)",
    )
    difficulty: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=3,
        comment="难度系数 (要素4: 1~5 整数，默认3)",
    )
    grading_rubric: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
        comment="主观题评分细则 (JSONB: total_score, points清单及采分关键词)",
    )
    source_snippet_ids: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=list,
        comment="多切片出题上下文列表 (含切片ID与相似度加权元数据)",
    )
    embedding: Mapped[Any] = mapped_column(
        get_vector_type(1024),
        nullable=True,
        comment="题干+选项 1024 维定长语义向量 (HNSW 余弦距离查重)",
    )

    # 关系映射
    knowledge_point: Mapped["KnowledgePoint"] = relationship(
        "KnowledgePoint",
        back_populates="questions",
    )
    source_snippet: Mapped["MaterialSnippet | None"] = relationship(
        "MaterialSnippet",
        foreign_keys=[source_snippet_id],
    )
    quality_checks: Mapped[list["QuestionQualityCheck"]] = relationship(
        "QuestionQualityCheck",
        back_populates="question",
        cascade="all, delete-orphan",
    )
    audit_logs: Mapped[list["QuestionAuditLog"]] = relationship(
        "QuestionAuditLog",
        back_populates="question",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        # 三元组与状态联合索引 (用于组卷与可用题目筛选)
        Index(
            "ix_questions_user_mat_ver_status",
            "user_id",
            "material_id",
            "version_id",
            "status",
            "is_deleted",
        ),
        # 知识点维度题目索引 (按知识点抽题与掌握度统计)
        Index("ix_questions_user_kp_deleted", "user_id", "knowledge_point_id", "is_deleted"),
        # pgvector HNSW 语义查重向量索引 (PostgreSQL)
        Index(
            "ix_questions_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 200},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    def __repr__(self) -> str:
        """安全脱敏日志展示，严禁泄漏 stem, options, answer, analysis 与 grading_rubric。"""
        return (
            f"<Question id={self.id} user_id={self.user_id} type={self.question_type} "
            f"status={self.status} diff={self.difficulty} stem_len={len(self.stem)} "
            f"deleted={self.is_deleted}>"
        )


class QuestionQualityCheck(Base, TimestampMixin, TenantModelMixin):
    """题目质检检查结果记录实体。

    持久化四项一票否决式质检（无来源、重复题、答案冲突、明显歧义）明细。
    """

    __tablename__ = "question_quality_checks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="质检记录主键 UUIDv4",
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联题目标识",
    )
    batch_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="出题生成批次号",
    )
    check_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="质检项类型 (QualityCheckType: NO_SOURCE/DUPLICATE/ANSWER_CONFLICT/AMBIGUITY)",
    )
    is_passed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        comment="该质检项是否通过",
    )
    reason: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        default=None,
        comment="未通过原因说明 (如: 题干与题目[xxx]相似度0.93超限)",
    )
    similarity_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        default=None,
        comment="比对相似度度量值 (重复题或答案冲突比对时保留)",
    )
    check_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
        comment="质检上下文诊断元数据 (如比对候选ID、关键词重合率等)",
    )

    # 关系映射
    question: Mapped["Question"] = relationship(
        "Question",
        back_populates="quality_checks",
    )

    __table_args__ = (
        Index("ix_question_quality_checks_user_batch", "user_id", "batch_id"),
        Index("ix_question_quality_checks_question_type", "question_id", "check_type"),
    )

    def __repr__(self) -> str:
        return (
            f"<QuestionQualityCheck id={self.id} q_id={self.question_id} "
            f"type={self.check_type} passed={self.is_passed}>"
        )


class QuestionAuditLog(Base, TimestampMixin, TenantModelMixin):
    """题目修改痕迹不可变审计日志实体。

    落实需求 FR-26：用户对题目的预览、修改、删除与重新生成全生命周期保留修改痕迹。
    """

    __tablename__ = "question_audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="审计日志主键 UUIDv4",
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联题目标识",
    )
    action: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="操作动作类型 (AuditAction: CREATE/EDIT/DELETE/REGENERATE)",
    )
    changed_fields: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=list,
        comment="本次变更涉及修改的字段名列表 (如: ['stem', 'options'])",
    )
    before_payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
        comment="修改前快照数据 (变更前字段键值摘要)",
    )
    after_payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
        comment="修改后快照数据 (变更后字段键值摘要)",
    )
    reason: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        default=None,
        comment="修改原因或操作备注",
    )

    # 关系映射
    question: Mapped["Question"] = relationship(
        "Question",
        back_populates="audit_logs",
    )

    __table_args__ = (
        Index("ix_question_audit_logs_user_q", "user_id", "question_id"),
        Index("ix_question_audit_logs_q_created", "question_id", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<QuestionAuditLog id={self.id} q_id={self.question_id} "
            f"action={self.action} fields={self.changed_fields}>"
        )
