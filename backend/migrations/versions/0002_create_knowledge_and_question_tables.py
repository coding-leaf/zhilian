"""Create knowledge, questions, quality checks, and audit logs tables.

Revision ID: 0002_create_knowledge_and_question_tables
Revises: 0001_create_material_tables_and_vector
Create Date: 2026-09-23 21:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_knowledge_question"
down_revision: str | None = "0001_material_vector"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()

    # 类型方言判断
    if conn.dialect.name == "postgresql":
        from pgvector.sqlalchemy import Vector

        vector_type: sa.types.TypeEngine = Vector(1024)
        json_type: sa.types.TypeEngine = postgresql.JSONB(astext_type=sa.Text())
    else:
        vector_type = sa.JSON()
        json_type = sa.JSON()

    # 1. 创建 knowledge_points 表
    op.create_table(
        "knowledge_points",
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
        sa.Column(
            "version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("material_versions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "parent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_points.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("level", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("batch_id", sa.String(64), nullable=False, index=True),
        sa.Column(
            "is_low_confidence",
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
    )
    op.create_index(
        "ix_knowledge_points_user_mat_ver",
        "knowledge_points",
        ["user_id", "material_id", "version_id"],
    )
    op.create_index(
        "ix_knowledge_points_user_parent",
        "knowledge_points",
        ["user_id", "parent_id"],
    )

    # 2. 创建 knowledge_point_snippets 关联表
    op.create_table(
        "knowledge_point_snippets",
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
            "snippet_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("material_snippets.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
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
        sa.UniqueConstraint(
            "knowledge_point_id",
            "snippet_id",
            name="uq_knowledge_point_snippets_kp_snippet",
        ),
    )
    op.create_index(
        "ix_kp_snippets_user_snippet",
        "knowledge_point_snippets",
        ["user_id", "snippet_id"],
    )
    op.create_index(
        "ix_kp_snippets_user_kp",
        "knowledge_point_snippets",
        ["user_id", "knowledge_point_id"],
    )

    # 3. 创建 questions 题目主表
    op.create_table(
        "questions",
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
        sa.Column(
            "version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("material_versions.id", ondelete="CASCADE"),
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
            "source_snippet_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("material_snippets.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("question_type", sa.String(32), nullable=False, index=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="available", index=True),
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            index=True,
        ),
        sa.Column("stem", sa.Text(), nullable=False),
        sa.Column("options", json_type, nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("analysis", sa.Text(), nullable=False, server_default=""),
        sa.Column("difficulty", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("grading_rubric", json_type, nullable=False),
        sa.Column("source_snippet_ids", json_type, nullable=False),
        sa.Column("embedding", vector_type, nullable=True),
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
        "ix_questions_user_mat_ver_status",
        "questions",
        ["user_id", "material_id", "version_id", "status", "is_deleted"],
    )
    op.create_index(
        "ix_questions_user_kp_deleted",
        "questions",
        ["user_id", "knowledge_point_id", "is_deleted"],
    )

    # 创建 questions.embedding 的 HNSW 向量索引 (PostgreSQL)
    if conn.dialect.name == "postgresql":
        op.create_index(
            "ix_questions_embedding_hnsw",
            "questions",
            ["embedding"],
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 200},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        )

    # 4. 创建 question_quality_checks 质检记录表
    op.create_table(
        "question_quality_checks",
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
            sa.ForeignKey("questions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("batch_id", sa.String(64), nullable=False, index=True),
        sa.Column("check_type", sa.String(32), nullable=False),
        sa.Column("is_passed", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("similarity_score", sa.Float(), nullable=True),
        sa.Column("check_metadata", json_type, nullable=False),
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
        "ix_question_quality_checks_user_batch",
        "question_quality_checks",
        ["user_id", "batch_id"],
    )
    op.create_index(
        "ix_question_quality_checks_question_type",
        "question_quality_checks",
        ["question_id", "check_type"],
    )

    # 5. 创建 question_audit_logs 审计日志表
    op.create_table(
        "question_audit_logs",
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
            sa.ForeignKey("questions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("changed_fields", json_type, nullable=False),
        sa.Column("before_payload", json_type, nullable=False),
        sa.Column("after_payload", json_type, nullable=False),
        sa.Column("reason", sa.String(255), nullable=True),
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
        "ix_question_audit_logs_user_q",
        "question_audit_logs",
        ["user_id", "question_id"],
    )
    op.create_index(
        "ix_question_audit_logs_q_created",
        "question_audit_logs",
        ["question_id", "created_at"],
    )


def downgrade() -> None:
    # 严格对称反向清理
    op.drop_table("question_audit_logs")
    op.drop_table("question_quality_checks")
    op.drop_table("questions")
    op.drop_table("knowledge_point_snippets")
    op.drop_table("knowledge_points")
