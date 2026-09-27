"""Add mode column to practices table.

Persists the question-assembly mode chosen at creation time so the detail/summary
responses can report the real mode instead of a hardcoded default (BUG-PRAC-011).

Revision ID: 0004_add_practice_mode
Revises: 0003_create_practice_tables
Create Date: 2026-09-27 19:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_add_practice_mode"
down_revision: str | None = "0003_create_practice_tables"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Add the non-null mode column with a backward-compatible server default."""
    with op.batch_alter_table("practices") as batch_op:
        batch_op.add_column(
            sa.Column(
                "mode",
                sa.String(32),
                nullable=False,
                server_default="sequential",
                comment="组卷抽题模式 (PracticeAssemblyMode: sequential/random/weak_points)",
            )
        )


def downgrade() -> None:
    """Drop the mode column to restore the prior schema."""
    with op.batch_alter_table("practices") as batch_op:
        batch_op.drop_column("mode")
