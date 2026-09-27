"""Unit tests for 0007 folder active-name unique migration.

Verifies that the full ``(user_id, name)`` unique constraint is swapped for a
partial unique index scoped to active folders, that archived rows no longer
occupy a name, and that ``upgrade -> downgrade -> upgrade`` is symmetric on
SQLite.
"""

import importlib
import uuid

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

MIGRATION_ORDER = (
    "0001_create_material_tables_and_vector",
    "0002_create_knowledge_and_question_tables",
    "0003_create_practice_tables",
    "0004_add_practice_mode",
    "0005_create_material_folders",
    "0006_practice_folder_scope",
)

REVISION = "0007_folder_active_name_unique"

_INSERT = text(
    "INSERT INTO material_folders (id, user_id, name, sort_order, archived_at, "
    "created_at, updated_at) VALUES (:id, :uid, :name, 0, :archived, "
    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
)


def _apply_prerequisites(connection) -> None:  # type: ignore[no-untyped-def]
    """Replay every migration that precedes 0007."""
    import alembic.op as alembic_op
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    context = MigrationContext.configure(connection)
    alembic_op._proxy = Operations(context)  # type: ignore[attr-defined]
    for name in MIGRATION_ORDER:
        module = importlib.import_module(f"migrations.versions.{name}")
        module.upgrade()


class TestFolderActiveNameMigration:
    """Test suite for 0007 Alembic migration symmetry and semantics."""

    def test_upgrade_downgrade_symmetry(self) -> None:
        """Verify partial index replace/restore round-trips cleanly on SQLite."""
        migration = importlib.import_module(f"migrations.versions.{REVISION}")
        engine = create_engine("sqlite:///:memory:")
        try:
            with engine.begin() as connection:
                _apply_prerequisites(connection)
                inspector = inspect(connection)

                before_indexes = {idx["name"] for idx in inspector.get_indexes("material_folders")}
                assert "uq_material_folders_user_name_active" not in before_indexes

                migration.upgrade()
                inspector.clear_cache()
                indexes = {idx["name"] for idx in inspector.get_indexes("material_folders")}
                assert "uq_material_folders_user_name_active" in indexes
                unique_names = {
                    uc["name"] for uc in inspector.get_unique_constraints("material_folders")
                }
                assert "uq_material_folders_user_name" not in unique_names

                migration.downgrade()
                inspector.clear_cache()
                downgraded = {idx["name"] for idx in inspector.get_indexes("material_folders")}
                assert "uq_material_folders_user_name_active" not in downgraded
                downgraded_unique = {
                    uc["name"] for uc in inspector.get_unique_constraints("material_folders")
                }
                assert "uq_material_folders_user_name" in downgraded_unique

                migration.upgrade()
                inspector.clear_cache()
                re_indexes = {idx["name"] for idx in inspector.get_indexes("material_folders")}
                assert "uq_material_folders_user_name_active" in re_indexes
        finally:
            engine.dispose()

    def test_archived_names_are_reusable(self) -> None:
        """Verify two archived rows may share a name but two active rows may not."""
        migration = importlib.import_module(f"migrations.versions.{REVISION}")
        engine = create_engine("sqlite:///:memory:")
        try:
            with engine.begin() as connection:
                _apply_prerequisites(connection)
                migration.upgrade()

                user_id = uuid.uuid4()

                def insert(name: str, archived: str | None) -> None:
                    connection.execute(
                        _INSERT,
                        {
                            "id": str(uuid.uuid4()),
                            "uid": str(user_id),
                            "name": name,
                            "archived": archived,
                        },
                    )

                # An archived row occupies a name.
                insert("复用课程", "2026-09-27 00:00:00")
                # An active row may reuse the archived name.
                insert("复用课程", None)
                # A second active row with the same name must conflict.
                with pytest.raises(IntegrityError):
                    insert("复用课程", None)
        finally:
            engine.dispose()
