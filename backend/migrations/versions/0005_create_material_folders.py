"""Create material_folders table and add materials.folder_id.

Adds the single-level course folder container plus material attribution.
Archive is soft (archived_at) with 7-day lazy physical purge.

Revision ID: 0005_create_material_folders
Revises: 0004_add_practice_mode
Create Date: 2026-09-27 21:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_create_material_folders"
down_revision: str | None = "0004_add_practice_mode"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Create material_folders and bind materials.folder_id (nullable, SET NULL)."""
    conn = op.get_bind()

    op.create_table(
        "material_folders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column(
            "parent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("material_folders.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint("user_id", "name", name="uq_material_folders_user_name"),
    )
    op.create_index(
        "ix_material_folders_archived_at",
        "material_folders",
        ["archived_at"],
    )
    op.create_index(
        "ix_material_folders_user_archived",
        "material_folders",
        ["user_id", "archived_at"],
    )

    with op.batch_alter_table("materials") as batch_op:
        batch_op.add_column(
            sa.Column(
                "folder_id",
                postgresql.UUID(as_uuid=True),
                nullable=True,
                comment="所属课程文件夹 (NULL=未分类)",
            )
        )
        if conn.dialect.name != "sqlite":
            batch_op.create_foreign_key(
                "fk_materials_folder_id",
                "material_folders",
                ["folder_id"],
                ["id"],
                ondelete="SET NULL",
            )
        batch_op.create_index("ix_materials_folder_id", ["folder_id"])
        batch_op.create_index(
            "ix_materials_user_folder_deleted",
            ["user_id", "folder_id", "is_deleted"],
        )


def downgrade() -> None:
    """Drop materials.folder_id and the material_folders table symmetrically."""
    with op.batch_alter_table("materials") as batch_op:
        batch_op.drop_index("ix_materials_user_folder_deleted")
        batch_op.drop_index("ix_materials_folder_id")
        batch_op.drop_column("folder_id")

    op.drop_index("ix_material_folders_user_archived", table_name="material_folders")
    op.drop_index("ix_material_folders_archived_at", table_name="material_folders")
    op.drop_table("material_folders")
