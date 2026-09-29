"""Unit tests for 0010 wrong_record optional practice scope migration.

Verifies the ``upgrade -> downgrade -> upgrade`` round trip on SQLite, that
``practice_id`` / ``attempt_item_id`` become nullable, and that the downgrade
deletes only manual rows (those without provenance), keeping judged records.
"""

import importlib
import uuid
from collections.abc import Generator
from typing import Any

import pytest
from sqlalchemy import Connection, create_engine, inspect, text

MIGRATION_ORDER = (
    "0001_create_material_tables_and_vector",
    "0002_create_knowledge_and_question_tables",
    "0003_create_practice_tables",
    "0004_add_practice_mode",
    "0005_create_material_folders",
    "0006_practice_folder_scope",
    "0007_folder_active_name_unique",
    "0008_question_batch_id",
    "0009_avatar_object_key",
)

REVISION = "0010_wrong_record_manual_scope"

_INSERT_RECORD = text(
    "INSERT INTO wrong_records ("
    "id, user_id, question_id, knowledge_point_id, practice_id, attempt_item_id, "
    "error_type, error_count, is_mastered, question_snapshot, first_wrong_at, "
    "created_at, updated_at"
    ") VALUES ("
    ":id, :user_id, NULL, :knowledge_point_id, :practice_id, :attempt_item_id, "
    "'conceptual', 1, 0, '{}', '2026-09-29 00:00:00', "
    "'2026-09-29 00:00:00', '2026-09-29 00:00:00'"
    ")"
)


def _insert_record(
    connection: Connection,
    *,
    practice_id: str | None,
    attempt_item_id: str | None,
) -> str:
    """Insert a wrong record row, optionally without practice provenance."""
    record_id = str(uuid.uuid4())
    connection.execute(
        _INSERT_RECORD,
        {
            "id": record_id,
            "user_id": str(uuid.uuid4()),
            "knowledge_point_id": str(uuid.uuid4()),
            "practice_id": practice_id,
            "attempt_item_id": attempt_item_id,
        },
    )
    return record_id


def _columns(connection: Connection) -> dict[str, Any]:
    inspector = inspect(connection)
    return {col["name"]: col for col in inspector.get_columns("wrong_records")}


@pytest.fixture
def connection() -> Generator[Connection, None, None]:
    """Replay migrations 0001..0009 on an in-memory SQLite database."""
    import alembic.op as alembic_op
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        context = MigrationContext.configure(conn)
        alembic_op._proxy = Operations(context)  # type: ignore[attr-defined]
        for name in MIGRATION_ORDER:
            importlib.import_module(f"migrations.versions.{name}").upgrade()
        yield conn
    engine.dispose()


class TestWrongRecordScopeMigration:
    """Test suite for 0010 Alembic migration upgrade/downgrade symmetry."""

    def test_upgrade_and_downgrade_symmetry(self, connection: Connection) -> None:
        """Manual rows are insertable after upgrade and removed by downgrade."""
        migration = importlib.import_module(f"migrations.versions.{REVISION}")

        before = _columns(connection)
        assert before["practice_id"]["nullable"] is False
        assert before["attempt_item_id"]["nullable"] is False

        # 1. Upgrade: provenance becomes optional.
        migration.upgrade()
        after_upgrade = _columns(connection)
        assert after_upgrade["practice_id"]["nullable"] is True
        assert after_upgrade["attempt_item_id"]["nullable"] is True

        # 2. A manual record (no provenance) is now representable.
        judged_id = _insert_record(
            connection,
            practice_id=str(uuid.uuid4()),
            attempt_item_id=str(uuid.uuid4()),
        )
        manual_id = _insert_record(connection, practice_id=None, attempt_item_id=None)

        # 3. Downgrade drops manual rows only, keeping judged provenance intact.
        migration.downgrade()
        after_downgrade = _columns(connection)
        assert after_downgrade["practice_id"]["nullable"] is False
        assert after_downgrade["attempt_item_id"]["nullable"] is False
        remaining = {
            str(row[0])
            for row in connection.execute(text("SELECT id FROM wrong_records")).fetchall()
        }
        assert judged_id in remaining
        assert manual_id not in remaining

        # 4. Re-upgrade proves symmetry: the constraint relaxes again.
        migration.upgrade()
        re_upgraded = _columns(connection)
        assert re_upgraded["practice_id"]["nullable"] is True
        assert re_upgraded["attempt_item_id"]["nullable"] is True
        _insert_record(connection, practice_id=None, attempt_item_id=None)
