"""Unit tests for 0008 question batch_id migration.

Verifies that ``questions.batch_id`` (+ index) is added and dropped symmetrically
through ``upgrade -> downgrade -> upgrade`` on SQLite.
"""

import importlib

from sqlalchemy import create_engine, inspect

MIGRATION_ORDER = (
    "0001_create_material_tables_and_vector",
    "0002_create_knowledge_and_question_tables",
    "0003_create_practice_tables",
    "0004_add_practice_mode",
    "0005_create_material_folders",
    "0006_practice_folder_scope",
    "0007_folder_active_name_unique",
)

REVISION = "0008_question_batch_id"


def _apply_prerequisites(connection) -> None:  # type: ignore[no-untyped-def]
    """Replay every migration that precedes 0008."""
    import alembic.op as alembic_op
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    context = MigrationContext.configure(connection)
    alembic_op._proxy = Operations(context)  # type: ignore[attr-defined]
    for name in MIGRATION_ORDER:
        module = importlib.import_module(f"migrations.versions.{name}")
        module.upgrade()


class TestQuestionBatchIdMigration:
    """Test suite for 0008 Alembic migration symmetry."""

    def test_upgrade_downgrade_symmetry(self) -> None:
        """Verify batch_id column + index round-trip cleanly on SQLite."""
        migration = importlib.import_module(f"migrations.versions.{REVISION}")
        engine = create_engine("sqlite:///:memory:")
        try:
            with engine.begin() as connection:
                _apply_prerequisites(connection)
                inspector = inspect(connection)

                before = {col["name"] for col in inspector.get_columns("questions")}
                assert "batch_id" not in before

                migration.upgrade()
                inspector.clear_cache()
                after_upgrade = {col["name"] for col in inspector.get_columns("questions")}
                assert "batch_id" in after_upgrade
                indexes = {idx["name"] for idx in inspector.get_indexes("questions")}
                assert "ix_questions_batch_id" in indexes

                migration.downgrade()
                inspector.clear_cache()
                after_downgrade = {col["name"] for col in inspector.get_columns("questions")}
                assert "batch_id" not in after_downgrade
                downgraded_indexes = {idx["name"] for idx in inspector.get_indexes("questions")}
                assert "ix_questions_batch_id" not in downgraded_indexes

                migration.upgrade()
                inspector.clear_cache()
                re_upgraded = {col["name"] for col in inspector.get_columns("questions")}
                assert "batch_id" in re_upgraded
        finally:
            engine.dispose()
