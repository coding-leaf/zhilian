"""Create question_collections and question_collection_items tables.

Revision ID: 0014_question_collections
Revises: 0013_retire_pending_review
Create Date: 2026-11-25 00:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014_question_collections"
down_revision: str | None = "0013_retire_pending_review"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Create question_collections and question_collection_items tables with indexes."""
    op.create_table(
        "question_collections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("description", sa.String(255), nullable=False, server_default=""),
        sa.Column(
            "folder_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("material_folders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("color_token", sa.String(32), nullable=True),
        sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
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
        sa.UniqueConstraint("user_id", "name", name="uq_question_collections_user_name"),
    )
    op.create_index(
        "ix_question_collections_user_id",
        "question_collections",
        ["user_id"],
    )
    op.create_index(
        "ix_question_collections_user_folder",
        "question_collections",
        ["user_id", "folder_id"],
    )
    op.create_index(
        "ix_question_collections_user_pinned_updated",
        "question_collections",
        ["user_id", "is_pinned", "updated_at"],
    )

    op.create_table(
        "question_collection_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "collection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("question_collections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "question_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("questions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
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
        sa.UniqueConstraint(
            "collection_id",
            "question_id",
            name="uq_collection_items_collection_question",
        ),
    )
    op.create_index(
        "ix_question_collection_items_user_id",
        "question_collection_items",
        ["user_id"],
    )
    op.create_index(
        "ix_collection_items_user_collection",
        "question_collection_items",
        ["user_id", "collection_id"],
    )
    op.create_index(
        "ix_collection_items_user_question",
        "question_collection_items",
        ["user_id", "question_id"],
    )


def downgrade() -> None:
    """Drop question_collection_items and question_collections symmetrically."""
    op.drop_index("ix_collection_items_user_question", table_name="question_collection_items")
    op.drop_index("ix_collection_items_user_collection", table_name="question_collection_items")
    op.drop_index("ix_question_collection_items_user_id", table_name="question_collection_items")
    op.drop_table("question_collection_items")

    op.drop_index(
        "ix_question_collections_user_pinned_updated",
        table_name="question_collections",
    )
    op.drop_index("ix_question_collections_user_folder", table_name="question_collections")
    op.drop_index("ix_question_collections_user_id", table_name="question_collections")
    op.drop_table("question_collections")
