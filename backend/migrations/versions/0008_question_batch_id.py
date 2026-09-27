"""Persist the question generation batch id on question rows.

Adds ``questions.batch_id`` (nullable, indexed) so every question produced by a
single generation request shares one batch identifier, enabling the question
list to be grouped/filtered by batch. Historical rows keep NULL. Symmetric
downgrade drops the column and its index.

Revision ID: 0008_question_batch_id
Revises: 0007_folder_active_name_unique
Create Date: 2026-09-28 13:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_question_batch_id"
down_revision: str | None = "0007_folder_active_name_unique"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable, indexed batch_id column to questions."""
    with op.batch_alter_table("questions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "batch_id",
                sa.String(64),
                nullable=True,
                comment="出题生成批次标识 (同一次生成共享；历史数据可空)",
            )
        )
        batch_op.create_index("ix_questions_batch_id", ["batch_id"])


def downgrade() -> None:
    """Drop the batch_id index and column symmetrically."""
    with op.batch_alter_table("questions") as batch_op:
        batch_op.drop_index("ix_questions_batch_id")
        batch_op.drop_column("batch_id")
