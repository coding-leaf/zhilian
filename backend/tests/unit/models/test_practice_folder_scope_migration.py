"""Unit tests for 0006 practice folder scope Alembic migration.

Verifies the two-way symmetry of upgrade() -> downgrade() -> upgrade() on SQLite,
including nullable material_id, folder_id, and composite indexes.
"""

import importlib

from sqlalchemy import create_engine, inspect

MIGRATION_ORDER = (
    "0001_create_material_tables_and_vector",
    "0002_create_knowledge_and_question_tables",
    "0003_create_practice_tables",
    "0004_add_practice_mode",
    "0005_create_material_folders",
)


class TestPracticeFolderScopeMigration:
    """Test suite for 0006 Alembic migration upgrade/downgrade symmetry."""

    def test_migration_0006_upgrade_and_downgrade_symmetry(self) -> None:
        """Verify migration 0006 rewrites nullable material_id and folder_id cleanly."""
        migration_0006 = importlib.import_module("migrations.versions.0006_practice_folder_scope")

        engine = create_engine("sqlite:///:memory:")
        try:
            with engine.begin() as connection:
                from alembic.operations import Operations
                from alembic.runtime.migration import MigrationContext

                context = MigrationContext.configure(connection)
                op = Operations(context)

                import alembic.op as alembic_op

                alembic_op._proxy = op  # type: ignore[attr-defined]

                # 1. Apply every prerequisite migration up to 0005.
                for name in MIGRATION_ORDER:
                    module = importlib.import_module(f"migrations.versions.{name}")
                    module.upgrade()

                inspector = inspect(connection)
                before = {col["name"]: col for col in inspector.get_columns("practices")}
                assert before["material_id"]["nullable"] is False
                assert "folder_id" not in before

                # 2. Upgrade 0006: material_id nullable, folder_id + indexes added.
                migration_0006.upgrade()
                inspector.clear_cache()
                after_upgrade = {col["name"]: col for col in inspector.get_columns("practices")}
                assert after_upgrade["material_id"]["nullable"] is True
                assert after_upgrade["folder_id"]["nullable"] is True
                upgraded_indexes = {idx["name"] for idx in inspector.get_indexes("practices")}
                assert "ix_practices_folder_id" in upgraded_indexes
                assert "ix_practices_user_folder_status" in upgraded_indexes

                # 3. Downgrade 0006: restore non-null material_id, drop folder_id.
                migration_0006.downgrade()
                inspector.clear_cache()
                after_downgrade = {col["name"]: col for col in inspector.get_columns("practices")}
                assert "folder_id" not in after_downgrade
                assert after_downgrade["material_id"]["nullable"] is False
                downgraded_indexes = {idx["name"] for idx in inspector.get_indexes("practices")}
                assert "ix_practices_folder_id" not in downgraded_indexes
                assert "ix_practices_user_folder_status" not in downgraded_indexes

                # 4. Re-run 0006 to prove upgrade/downgrade symmetry.
                migration_0006.upgrade()
                inspector.clear_cache()
                re_upgraded = {col["name"]: col for col in inspector.get_columns("practices")}
                assert re_upgraded["material_id"]["nullable"] is True
                assert "folder_id" in re_upgraded
        finally:
            engine.dispose()
