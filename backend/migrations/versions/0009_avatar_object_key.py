"""Add persistent object key for app-managed user avatars."""

import sqlalchemy as sa
from alembic import op

revision = "0009_avatar_object_key"
down_revision = "0008_question_batch_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add nullable object key while preserving legacy avatar URLs."""
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("avatar_object_key", sa.String(length=512), nullable=True))


def downgrade() -> None:
    """Remove the managed avatar object key column."""
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("avatar_object_key")
