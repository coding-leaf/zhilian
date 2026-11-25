"""Add study_guide cache columns on knowledge_points table.

Revision ID: 0015_kp_study_guide
Revises: 0014_question_collections
Create Date: 2026-11-25 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_kp_study_guide"
down_revision: str | None = "0014_question_collections"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def _json_type() -> sa.JSON:
    """Return dialect-aware JSON type using JSONB on PostgreSQL and JSON on SQLite."""
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    """Add study_guide cache columns to knowledge_points."""
    with op.batch_alter_table("knowledge_points") as batch_op:
        batch_op.add_column(
            sa.Column(
                "study_guide",
                _json_type(),
                nullable=True,
                comment="考前精讲笔记永久缓存 JSON (StudyGuideContent v1)",
            )
        )
        batch_op.add_column(
            sa.Column(
                "study_guide_generated_at",
                sa.DateTime(timezone=True),
                nullable=True,
                comment="考前精讲笔记生成时间 (UTC)",
            )
        )
        batch_op.add_column(
            sa.Column(
                "study_guide_version",
                sa.Integer(),
                nullable=False,
                server_default="0",
                comment="考前精讲笔记 Schema 版本号 (0=未生成, 1=v1)",
            )
        )


def downgrade() -> None:
    """Remove study_guide cache columns from knowledge_points."""
    with op.batch_alter_table("knowledge_points") as batch_op:
        batch_op.drop_column("study_guide_version")
        batch_op.drop_column("study_guide_generated_at")
        batch_op.drop_column("study_guide")
