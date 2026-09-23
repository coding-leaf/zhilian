"""Create practices, attempt items, grading records, mastery, diagnosis, and wrong records tables.

Revision ID: 0003_create_practice_tables
Revises: 0002_create_knowledge_and_question_tables
Create Date: 2026-09-23 21:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_create_practice_tables"
down_revision: str | None = "0002_create_knowledge_and_question_tables"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name
    json_type = postgresql.JSONB(astext_type=sa.Text()) if dialect == "postgresql" else sa.JSON()

    # 1. 创建 practices 主表
    op.create_table(
        "practices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "material_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("materials.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("title", sa.String(128), nullable=False),
        sa.Column("knowledge_point_ids", json_type, nullable=False),
        sa.Column("question_types", json_type, nullable=False),
        sa.Column("difficulty", sa.Integer(), nullable=True),
        sa.Column("question_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ordered_question_ids", json_type, nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="not_started"),
        sa.Column("source_type", sa.String(32), nullable=False, server_default="normal"),
        sa.Column("source_report_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("submit_idempotency_key", sa.String(64), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_score", sa.Float(), nullable=True),
        sa.Column("max_score", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_practices_user_source_status",
        "practices",
        ["user_id", "source_report_id", "status"],
    )
    op.create_index(
        "ix_practices_user_mat_status",
        "practices",
        ["user_id", "material_id", "status"],
    )
    op.create_index("ix_practices_user_status", "practices", ["user_id", "status"])

    if dialect == "postgresql":
        op.create_index(
            "uq_practices_user_submit_key",
            "practices",
            ["user_id", "submit_idempotency_key"],
            unique=True,
            postgresql_where=sa.text("submit_idempotency_key IS NOT NULL"),
        )
    else:
        op.create_index(
            "uq_practices_user_submit_key",
            "practices",
            ["user_id", "submit_idempotency_key"],
            unique=True,
        )

    # 2. 创建 attempt_items 作答项表 (question_id 弱外键 SET NULL)
    op.create_table(
        "attempt_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "practice_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("practices.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "question_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("questions.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("question_snapshot", json_type, nullable=False),
        sa.Column("user_answer", sa.Text(), nullable=True),
        sa.Column(
            "is_answered",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("duration_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("max_score", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "practice_id", "question_id", name="uq_attempt_items_practice_question"
        ),
    )
    op.create_index(
        "ix_attempt_items_practice_order",
        "attempt_items",
        ["practice_id", "order_index"],
    )
    op.create_index(
        "ix_attempt_items_user_practice",
        "attempt_items",
        ["user_id", "practice_id"],
    )

    # 3. 创建 grading_records 混合判题表
    op.create_table(
        "grading_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "practice_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("practices.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "attempt_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("attempt_items.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "question_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("questions.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "is_final",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("max_score", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("similarity_score", sa.Float(), nullable=True),
        sa.Column("hit_keywords", json_type, nullable=False),
        sa.Column("missing_keywords", json_type, nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column("grading_metadata", json_type, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_grading_records_item_final",
        "grading_records",
        ["attempt_item_id", "is_final"],
    )
    op.create_index(
        "ix_grading_records_practice_status",
        "grading_records",
        ["practice_id", "status"],
    )
    op.create_index(
        "ix_grading_records_user_practice",
        "grading_records",
        ["user_id", "practice_id"],
    )

    # 4. 创建 mastery_records 掌握度记录表
    op.create_table(
        "mastery_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "knowledge_point_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_points.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "mastery_score",
            sa.Float(),
            nullable=False,
            server_default="0.0",
        ),
        sa.Column("level", sa.String(32), nullable=False, server_default="unlearned"),
        sa.Column("practice_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("correct_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_practiced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decayed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recent_records_snapshot", json_type, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "knowledge_point_id", name="uq_mastery_records_user_kp"),
    )
    op.create_index(
        "ix_mastery_records_user_level",
        "mastery_records",
        ["user_id", "level"],
    )

    # 5. 创建 diagnosis_reports 诊断报告表
    op.create_table(
        "diagnosis_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "practice_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("practices.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("weak_knowledge_points", json_type, nullable=False),
        sa.Column("regressed_knowledge_points", json_type, nullable=False),
        sa.Column("analysis_causes", json_type, nullable=False),
        sa.Column("actionable_suggestions", json_type, nullable=False),
        sa.Column("unanswered_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("wrong_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pending_regrade_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_questions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("score_rate", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column(
            "is_structure_degraded",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("practice_id", name="uq_diagnosis_reports_practice_id"),
    )
    op.create_index(
        "ix_diagnosis_reports_user_created",
        "diagnosis_reports",
        ["user_id", "created_at"],
    )

    # 6. 创建 wrong_records 错题本表
    op.create_table(
        "wrong_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "question_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("questions.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "knowledge_point_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_points.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "practice_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("practices.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "attempt_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("attempt_items.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("error_type", sa.String(32), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "is_mastered",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("last_wrong_answer", sa.Text(), nullable=True),
        sa.Column("question_snapshot", json_type, nullable=False),
        sa.Column(
            "first_wrong_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("mastered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "question_id", name="uq_wrong_records_user_question"),
    )
    op.create_index(
        "ix_wrong_records_user_mastered_type",
        "wrong_records",
        ["user_id", "is_mastered", "error_type"],
    )
    op.create_index(
        "ix_wrong_records_user_kp_mastered",
        "wrong_records",
        ["user_id", "knowledge_point_id", "is_mastered"],
    )


def downgrade() -> None:
    # 严格逆序删除数据表
    op.drop_table("wrong_records")
    op.drop_table("diagnosis_reports")
    op.drop_table("mastery_records")
    op.drop_table("grading_records")
    op.drop_table("attempt_items")
    op.drop_table("practices")
