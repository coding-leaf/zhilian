"""Unit tests for 0003 practice tables Alembic migration.

Tests the two-way symmetry of upgrade() -> downgrade() -> upgrade() across SQLite.
"""

import importlib

from sqlalchemy import create_engine, inspect

from app.models.base import Base


class TestPracticeMigration:
    """Test suite for 0003 Alembic migration upgrade and downgrade symmetry."""

    def test_migration_0003_upgrade_and_downgrade_symmetry(self) -> None:
        """Verify migration 0003 can cleanly upgrade, downgrade, and re-upgrade."""
        migration_0001 = importlib.import_module(
            "migrations.versions.0001_create_material_tables_and_vector"
        )
        migration_0002 = importlib.import_module(
            "migrations.versions.0002_create_knowledge_and_question_tables"
        )
        migration_0003 = importlib.import_module("migrations.versions.0003_create_practice_tables")

        engine = create_engine("sqlite:///:memory:")
        try:
            with engine.begin() as connection:
                # 1. Prerequisite: create users table
                Base.metadata.tables["users"].create(connection)

                from alembic.operations import Operations
                from alembic.runtime.migration import MigrationContext

                context = MigrationContext.configure(connection)
                op = Operations(context)

                import alembic.op as alembic_op

                alembic_op._proxy = op  # type: ignore[attr-defined]

                # 2. Run prerequisites 0001 and 0002
                migration_0001.upgrade()
                migration_0002.upgrade()

                # 3. Test migration 0003 upgrade
                migration_0003.upgrade()

                inspector = inspect(connection)
                table_names = set(inspector.get_table_names())
                assert "practices" in table_names
                assert "attempt_items" in table_names
                assert "grading_records" in table_names
                assert "mastery_records" in table_names
                assert "diagnosis_reports" in table_names
                assert "wrong_records" in table_names

                # 4. Test migration 0003 downgrade
                migration_0003.downgrade()
                inspector.clear_cache()
                tables_after_downgrade = set(inspector.get_table_names())

                assert "wrong_records" not in tables_after_downgrade
                assert "diagnosis_reports" not in tables_after_downgrade
                assert "mastery_records" not in tables_after_downgrade
                assert "grading_records" not in tables_after_downgrade
                assert "attempt_items" not in tables_after_downgrade
                assert "practices" not in tables_after_downgrade

                # Verify 0001 and 0002 tables remain intact
                assert "questions" in tables_after_downgrade
                assert "knowledge_points" in tables_after_downgrade
                assert "materials" in tables_after_downgrade
                assert "users" in tables_after_downgrade

                # 5. Re-run migration 0003 upgrade to verify symmetry
                migration_0003.upgrade()
                inspector.clear_cache()
                tables_re_upgraded = set(inspector.get_table_names())
                assert "practices" in tables_re_upgraded
                assert "attempt_items" in tables_re_upgraded
                assert "grading_records" in tables_re_upgraded
                assert "mastery_records" in tables_re_upgraded
                assert "diagnosis_reports" in tables_re_upgraded
                assert "wrong_records" in tables_re_upgraded
        finally:
            engine.dispose()
