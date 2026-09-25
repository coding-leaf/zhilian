"""Create material, material_version, material_snippet, and material_ocr_page tables.

Revision ID: 0001_create_material_tables_and_vector
Revises:
Create Date: 2026-09-23 20:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_material_vector"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. 幂等激活 pgvector 扩展 (PostgreSQL 专有)
    if conn.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # 2. 创建 users 用户基础表 (供 materials 及后续业务外键引用)
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("openid", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("unionid", sa.String(64), nullable=True, index=True),
        sa.Column("nickname", sa.String(64), nullable=False, server_default=""),
        sa.Column("avatar_url", sa.String(512), nullable=False, server_default=""),
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    # 3. 创建 materials 主表
    op.create_table(
        "materials",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("file_format", sa.String(32), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False, server_default="local"),
        sa.Column("current_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_materials_user_is_deleted", "materials", ["user_id", "is_deleted"])
    op.create_index("ix_materials_user_status", "materials", ["user_id", "status"])

    # 3. 创建 material_versions 版本表
    op.create_table(
        "material_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "material_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("materials.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False, index=True),
        sa.Column("parse_status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("failed_stage", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("raw_text_storage_key", sa.String(512), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "material_id", "version_number", name="uq_material_versions_material_version"
        ),
    )
    op.create_index(
        "ix_material_versions_user_material", "material_versions", ["user_id", "material_id"]
    )
    op.create_index(
        "ix_material_versions_user_content_hash", "material_versions", ["user_id", "content_hash"]
    )

    # 4. 解决循环外键: 为 materials.current_version_id 绑定外键约束 (use_alter)
    if conn.dialect.name != "sqlite":
        op.create_foreign_key(
            "fk_materials_current_version_id",
            "materials",
            "material_versions",
            ["current_version_id"],
            ["id"],
            ondelete="SET NULL",
            use_alter=True,
        )

    # 5. 创建 material_snippets 知识切片表
    if conn.dialect.name == "postgresql":
        from pgvector.sqlalchemy import Vector

        vector_type: sa.types.TypeEngine = Vector(1024)
        json_type: sa.types.TypeEngine = postgresql.JSONB(astext_type=sa.Text())
    else:
        vector_type = sa.JSON()
        json_type = sa.JSON()

    op.create_table(
        "material_snippets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "material_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("materials.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("material_versions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("snippet_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("char_length", sa.Integer(), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("chapter_title", sa.String(255), nullable=False, server_default=""),
        sa.Column("source_info", json_type, nullable=False),
        sa.Column("embedding", vector_type, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "version_id", "snippet_index", name="uq_material_snippets_version_index"
        ),
    )
    op.create_index(
        "ix_material_snippets_user_mat_ver",
        "material_snippets",
        ["user_id", "material_id", "version_id"],
    )

    # 创建 HNSW 向量索引 (PostgreSQL)
    if conn.dialect.name == "postgresql":
        op.create_index(
            "ix_material_snippets_embedding_hnsw",
            "material_snippets",
            ["embedding"],
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 200},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        )

    # 6. 创建 material_ocr_pages 页面质检表
    op.create_table(
        "material_ocr_pages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "material_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("materials.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("material_versions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("image_storage_key", sa.String(512), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("gibberish_ratio", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("valid_char_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_qualified", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("unqualified_reason", sa.String(255), nullable=True),
        sa.Column("reshoot_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("version_id", "page_number", name="uq_material_ocr_pages_version_page"),
    )
    op.create_index(
        "ix_material_ocr_pages_user_mat_ver",
        "material_ocr_pages",
        ["user_id", "material_id", "version_id"],
    )
    op.create_index(
        "ix_material_ocr_pages_version_qualified",
        "material_ocr_pages",
        ["version_id", "is_qualified"],
    )


def downgrade() -> None:
    conn = op.get_bind()

    # 1. 删除 material_ocr_pages
    op.drop_table("material_ocr_pages")

    # 2. 删除 material_snippets (级联清理 HNSW 索引)
    op.drop_table("material_snippets")

    # 3. 移除 materials 循环外键约束
    if conn.dialect.name != "sqlite":
        op.drop_constraint("fk_materials_current_version_id", "materials", type_="foreignkey")

    # 4. 删除 material_versions
    op.drop_table("material_versions")

    # 5. 删除 materials
    op.drop_table("materials")

    # 6. 删除 users
    op.drop_table("users")
