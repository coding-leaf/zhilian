"""Allow reusing the name of an archived course folder.

Replaces the table-level ``(user_id, name)`` unique constraint with a partial
unique index scoped to active folders (``archived_at IS NULL``), so a name only
conflicts with other *active* courses and becomes reusable once a course is
archived. Symmetric downgrade restores the original full unique constraint.

Revision ID: 0007_folder_active_name_unique
Revises: 0006_practice_folder_scope
Create Date: 2026-09-28 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_folder_active_name_unique"
down_revision: str | None = "0006_practice_folder_scope"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Swap the full unique constraint for an active-only partial unique index."""
    conn = op.get_bind()
    is_sqlite = conn.dialect.name == "sqlite"

    if is_sqlite:
        # SQLite cannot drop a named UNIQUE constraint in place; rebuild the table.
        with op.batch_alter_table("material_folders", recreate="always") as batch_op:
            batch_op.drop_constraint("uq_material_folders_user_name", type_="unique")
    else:
        op.drop_constraint(
            "uq_material_folders_user_name",
            "material_folders",
            type_="unique",
        )

    op.create_index(
        "uq_material_folders_user_name_active",
        "material_folders",
        ["user_id", "name"],
        unique=True,
        sqlite_where=sa.text("archived_at IS NULL"),
        postgresql_where=sa.text("archived_at IS NULL"),
    )


def downgrade() -> None:
    """Drop the partial index and restore the original full unique constraint."""
    conn = op.get_bind()
    is_sqlite = conn.dialect.name == "sqlite"

    op.drop_index(
        "uq_material_folders_user_name_active",
        table_name="material_folders",
    )

    if is_sqlite:
        with op.batch_alter_table("material_folders", recreate="always") as batch_op:
            batch_op.create_unique_constraint(
                "uq_material_folders_user_name",
                ["user_id", "name"],
            )
    else:
        op.create_unique_constraint(
            "uq_material_folders_user_name",
            "material_folders",
            ["user_id", "name"],
        )
