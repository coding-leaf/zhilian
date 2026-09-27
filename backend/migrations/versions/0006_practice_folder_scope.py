"""Scope practices to course folders.

Makes ``practices.material_id`` nullable (folder-scope practices have no single
material) and adds ``practices.folder_id`` plus a composite index used by the
course-scoped practice list. Symmetric downgrade restores the prior shape.

Revision ID: 0006_practice_folder_scope
Revises: 0005_create_material_folders
Create Date: 2026-09-28 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_practice_folder_scope"
down_revision: str | None = "0005_create_material_folders"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Allow material-less (folder-scoped) practices and bind folder_id."""
    conn = op.get_bind()
    is_sqlite = conn.dialect.name == "sqlite"

    with op.batch_alter_table("practices") as batch_op:
        batch_op.alter_column(
            "material_id",
            existing_type=postgresql.UUID(as_uuid=True),
            nullable=True,
        )
        batch_op.add_column(
            sa.Column(
                "folder_id",
                postgresql.UUID(as_uuid=True),
                nullable=True,
                comment="归属课程文件夹 (NULL=单资料练习)",
            )
        )
        if not is_sqlite:
            batch_op.create_foreign_key(
                "fk_practices_folder_id",
                "material_folders",
                ["folder_id"],
                ["id"],
                ondelete="SET NULL",
            )
        batch_op.create_index("ix_practices_folder_id", ["folder_id"])
        batch_op.create_index(
            "ix_practices_user_folder_status",
            ["user_id", "folder_id", "status"],
        )


def downgrade() -> None:
    """Drop folder scoping and restore the non-null material binding."""
    conn = op.get_bind()
    is_sqlite = conn.dialect.name == "sqlite"

    with op.batch_alter_table("practices") as batch_op:
        batch_op.drop_index("ix_practices_user_folder_status")
        batch_op.drop_index("ix_practices_folder_id")
        if not is_sqlite:
            batch_op.drop_constraint("fk_practices_folder_id", type_="foreignkey")
        batch_op.drop_column("folder_id")
        batch_op.alter_column(
            "material_id",
            existing_type=postgresql.UUID(as_uuid=True),
            nullable=False,
        )
