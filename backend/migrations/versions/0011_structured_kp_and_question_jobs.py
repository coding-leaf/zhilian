"""Add structured_content/sort_order on knowledge_points and question_generation_jobs table.

Revision ID: 0011_kp_struct_and_q_jobs
Revises: 0010_wrong_record_manual_scope
Create Date: 2026-11-17 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_kp_struct_and_q_jobs"
down_revision: str | None = "0010_wrong_record_manual_scope"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def _json_type() -> sa.JSON:
    """Return dialect-aware JSON type using JSONB on PostgreSQL and JSON on SQLite."""
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    """Add structured KP columns and create question_generation_jobs table."""
    with op.batch_alter_table("knowledge_points") as batch_op:
        batch_op.add_column(
            sa.Column(
                "structured_content",
                _json_type(),
                nullable=True,
                comment="知识点结构化内容 (core_summary/key_takeaways/key_formulas/boundary_notes)",
            )
        )
        batch_op.add_column(
            sa.Column(
                "sort_order",
                sa.Integer(),
                nullable=False,
                server_default="0",
                comment="同层或资料内排序序号",
            )
        )

    op.create_table(
        "question_generation_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("material_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("folder_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("request_payload", _json_type(), nullable=False),
        sa.Column("total_kps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_kps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("generated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("batch_id", sa.String(64), nullable=True),
        sa.Column("question_ids", _json_type(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_question_generation_jobs_user_id",
        "question_generation_jobs",
        ["user_id"],
    )
    op.create_index(
        "ix_question_generation_jobs_material_id",
        "question_generation_jobs",
        ["material_id"],
    )
    op.create_index(
        "ix_question_generation_jobs_folder_id",
        "question_generation_jobs",
        ["folder_id"],
    )
    op.create_index(
        "ix_question_generation_jobs_status",
        "question_generation_jobs",
        ["status"],
    )
    op.create_index(
        "ix_question_generation_jobs_user_status",
        "question_generation_jobs",
        ["user_id", "status"],
    )
    op.create_index(
        "ix_question_generation_jobs_user_created",
        "question_generation_jobs",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    """Drop question_generation_jobs table and remove KP structured columns."""
    op.drop_index(
        "ix_question_generation_jobs_user_created",
        table_name="question_generation_jobs",
    )
    op.drop_index(
        "ix_question_generation_jobs_user_status",
        table_name="question_generation_jobs",
    )
    op.drop_index(
        "ix_question_generation_jobs_status",
        table_name="question_generation_jobs",
    )
    op.drop_index(
        "ix_question_generation_jobs_folder_id",
        table_name="question_generation_jobs",
    )
    op.drop_index(
        "ix_question_generation_jobs_material_id",
        table_name="question_generation_jobs",
    )
    op.drop_index(
        "ix_question_generation_jobs_user_id",
        table_name="question_generation_jobs",
    )
    op.drop_table("question_generation_jobs")

    with op.batch_alter_table("knowledge_points") as batch_op:
        batch_op.drop_column("sort_order")
        batch_op.drop_column("structured_content")
