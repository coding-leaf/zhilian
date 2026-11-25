"""Soft-delete legacy pending_review questions to enforce zero student-facing review queue.

Revision ID: 0013_retire_pending_review
Revises: 0012_job_practice_grading_uq
Create Date: 2026-11-24 22:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_retire_pending_review"
down_revision: str | None = "0012_job_practice_grading_uq"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_PENDING_REVIEW_STATUS = "pending_review"


def _questions_table() -> sa.Table:
    """Return lightweight Table clause for reversible pending_review soft-delete updates."""
    return sa.table(
        "questions",
        sa.column("status", sa.String(32)),
        sa.column("is_deleted", sa.Boolean()),
    )


def upgrade() -> None:
    """Soft-delete all legacy pending_review questions while preserving audit/check history."""
    conn = op.get_bind()
    questions = _questions_table()
    conn.execute(
        questions.update()
        .where(
            questions.c.status == _PENDING_REVIEW_STATUS,
            questions.c.is_deleted.is_(False),
        )
        .values(is_deleted=True)
    )


def downgrade() -> None:
    """Restore soft-deleted legacy pending_review questions."""
    conn = op.get_bind()
    questions = _questions_table()
    conn.execute(
        questions.update()
        .where(
            questions.c.status == _PENDING_REVIEW_STATUS,
            questions.c.is_deleted.is_(True),
        )
        .values(is_deleted=False)
    )
