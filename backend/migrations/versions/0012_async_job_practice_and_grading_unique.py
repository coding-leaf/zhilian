"""Add auto-practice/idempotency columns on question_generation_jobs and unique final grading index.

Revision ID: 0012_job_practice_grading_uq
Revises: 0011_kp_struct_and_q_jobs
Create Date: 2026-11-24 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_job_practice_grading_uq"
down_revision: str | None = "0011_kp_struct_and_q_jobs"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def _deduplicate_final_grading_records(conn: sa.Connection) -> None:
    """Keep only the latest is_final=True grading record per attempt_item_id."""
    grading_records = sa.table(
        "grading_records",
        sa.column("id"),
        sa.column("attempt_item_id"),
        sa.column("is_final", sa.Boolean),
        sa.column("updated_at"),
        sa.column("created_at"),
    )
    dup_items = (
        conn.execute(
            sa.select(grading_records.c.attempt_item_id)
            .where(grading_records.c.is_final == sa.true())
            .group_by(grading_records.c.attempt_item_id)
            .having(sa.func.count() > 1)
        )
        .scalars()
        .all()
    )
    for item_id in dup_items:
        rows = (
            conn.execute(
                sa.select(grading_records.c.id)
                .where(
                    grading_records.c.attempt_item_id == item_id,
                    grading_records.c.is_final == sa.true(),
                )
                .order_by(
                    grading_records.c.updated_at.desc(),
                    grading_records.c.created_at.desc(),
                    grading_records.c.id.desc(),
                )
            )
            .scalars()
            .all()
        )
        stale_ids = rows[1:]
        if stale_ids:
            conn.execute(
                grading_records.update()
                .where(grading_records.c.id.in_(stale_ids))
                .values(is_final=False)
            )


def upgrade() -> None:
    """Extend question_generation_jobs and enforce unique final grading per attempt item."""
    conn = op.get_bind()
    is_sqlite = conn.dialect.name == "sqlite"

    with op.batch_alter_table("question_generation_jobs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "result_practice_id",
                postgresql.UUID(as_uuid=True),
                nullable=True,
                comment="自动建卷产出的练习主键 UUID (可空)",
            )
        )
        batch_op.add_column(
            sa.Column(
                "source_type",
                sa.String(32),
                nullable=True,
                comment="任务来源意图 (initial_compose|wrong_record|weakness)",
            )
        )
        batch_op.add_column(
            sa.Column(
                "source_practice_id",
                postgresql.UUID(as_uuid=True),
                nullable=True,
                comment="错题再生成溯源原练习主键 UUID (可空)",
            )
        )
        batch_op.add_column(
            sa.Column(
                "idempotency_key",
                sa.String(128),
                nullable=True,
                comment="异步出题任务幂等键 (可空)",
            )
        )
        if not is_sqlite:
            batch_op.create_foreign_key(
                "fk_question_generation_jobs_result_practice_id",
                "practices",
                ["result_practice_id"],
                ["id"],
                ondelete="SET NULL",
            )
        batch_op.create_index(
            "ix_question_generation_jobs_result_practice_id",
            ["result_practice_id"],
        )
        batch_op.create_index(
            "ix_question_generation_jobs_source_practice_id",
            ["source_practice_id"],
        )
        batch_op.create_index(
            "ix_question_generation_jobs_idempotency_key",
            ["idempotency_key"],
        )

    _deduplicate_final_grading_records(conn)
    op.create_index(
        "uq_grading_records_item_final",
        "grading_records",
        ["attempt_item_id"],
        unique=True,
        sqlite_where=sa.text("is_final = 1"),
        postgresql_where=sa.text("is_final IS TRUE"),
    )


def downgrade() -> None:
    """Drop partial unique index and newly added question_generation_jobs columns."""
    conn = op.get_bind()
    is_sqlite = conn.dialect.name == "sqlite"

    op.drop_index(
        "uq_grading_records_item_final",
        table_name="grading_records",
    )

    with op.batch_alter_table("question_generation_jobs") as batch_op:
        batch_op.drop_index("ix_question_generation_jobs_idempotency_key")
        batch_op.drop_index("ix_question_generation_jobs_source_practice_id")
        batch_op.drop_index("ix_question_generation_jobs_result_practice_id")
        if not is_sqlite:
            batch_op.drop_constraint(
                "fk_question_generation_jobs_result_practice_id",
                type_="foreignkey",
            )
        batch_op.drop_column("idempotency_key")
        batch_op.drop_column("source_practice_id")
        batch_op.drop_column("source_type")
        batch_op.drop_column("result_practice_id")
