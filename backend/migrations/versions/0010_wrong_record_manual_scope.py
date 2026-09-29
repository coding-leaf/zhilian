"""Allow manually marked wrong records without a practice/attempt provenance.

``wrong_records.practice_id`` / ``attempt_item_id`` become nullable so a question
the user marks by hand (no practice session, no attempt item) can be stored at
all. ``practice_id IS NULL`` is the definition of a manual record — no separate
``source`` column is introduced, because two fields expressing the same fact
drift apart.

The downgrade needs an explicit decision for manual rows: their existence is a
capability this revision introduces, so they have no representable shape in the
pre-0010 schema. They are deleted rather than left to fail the NOT NULL
constraint. Judged records (real provenance) are untouched.

Revision ID: 0010_wrong_record_manual_scope
(kept <= 32 chars: alembic_version.version_num is varchar(32))
Revises: 0009_avatar_object_key
Create Date: 2026-09-29 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_wrong_record_manual_scope"
down_revision: str | None = "0009_avatar_object_key"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Relax practice/attempt provenance to nullable (SQLite batch compatible)."""
    with op.batch_alter_table("wrong_records") as batch_op:
        batch_op.alter_column(
            "practice_id",
            existing_type=postgresql.UUID(as_uuid=True),
            nullable=True,
        )
        batch_op.alter_column(
            "attempt_item_id",
            existing_type=postgresql.UUID(as_uuid=True),
            nullable=True,
        )


def downgrade() -> None:
    """Restore NOT NULL provenance, dropping manual rows that cannot satisfy it."""
    op.execute("DELETE FROM wrong_records WHERE practice_id IS NULL OR attempt_item_id IS NULL")
    with op.batch_alter_table("wrong_records") as batch_op:
        batch_op.alter_column(
            "practice_id",
            existing_type=postgresql.UUID(as_uuid=True),
            nullable=False,
        )
        batch_op.alter_column(
            "attempt_item_id",
            existing_type=postgresql.UUID(as_uuid=True),
            nullable=False,
        )
