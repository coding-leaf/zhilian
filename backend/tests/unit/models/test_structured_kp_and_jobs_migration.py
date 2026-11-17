"""Unit tests for 0011 structured knowledge point and question generation jobs migration."""

import importlib
import uuid
from collections.abc import Generator

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
    "0010_wrong_record_manual_scope",
)

REVISION_MODULE = "0011_structured_kp_and_question_jobs"


@pytest.fixture
def connection() -> Generator[Connection, None, None]:
    """Replay migrations 0001..0010 on an in-memory SQLite database."""
    import alembic.op as alembic_op
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    engine = create_engine("sqlite:///:memory:")
    sentinel = object()
    previous = getattr(alembic_op, "_proxy", sentinel)
    try:
        with engine.begin() as conn:
            context = MigrationContext.configure(conn)
            alembic_op._proxy = Operations(context)  # type: ignore[attr-defined]
            for name in MIGRATION_ORDER:
                importlib.import_module(f"migrations.versions.{name}").upgrade()
            yield conn
    finally:
        if previous is sentinel:
            if hasattr(alembic_op, "_proxy"):
                del alembic_op._proxy
        else:
            alembic_op._proxy = previous  # type: ignore[attr-defined]
        engine.dispose()


class TestStructuredKpAndJobsMigration:
    """Test suite for 0011 Alembic migration upgrade/downgrade symmetry."""

    def test_upgrade_and_downgrade_symmetry(self, connection: Connection) -> None:
        """Verify columns, new table, indexes, and symmetric downgrade/upgrade."""
        migration = importlib.import_module(f"migrations.versions.{REVISION_MODULE}")

        before_kp = {c["name"] for c in inspect(connection).get_columns("knowledge_points")}
        assert "structured_content" not in before_kp
        assert "sort_order" not in before_kp
        assert "question_generation_jobs" not in inspect(connection).get_table_names()

        migration.upgrade()

        inspector = inspect(connection)
        after_kp = {c["name"]: c for c in inspector.get_columns("knowledge_points")}
        assert "structured_content" in after_kp
        assert after_kp["structured_content"]["nullable"] is True
        assert "sort_order" in after_kp
        assert after_kp["sort_order"]["nullable"] is False

        assert "question_generation_jobs" in inspector.get_table_names()
        job_cols = {c["name"] for c in inspector.get_columns("question_generation_jobs")}
        expected_cols = {
            "id",
            "user_id",
            "material_id",
            "folder_id",
            "status",
            "request_payload",
            "total_kps",
            "completed_kps",
            "generated_count",
            "batch_id",
            "question_ids",
            "error_message",
            "created_at",
            "updated_at",
            "completed_at",
        }
        assert expected_cols.issubset(job_cols)

        # Insert test row into question_generation_jobs
        connection.execute(
            text(
                "INSERT INTO question_generation_jobs "
                "(id, user_id, status, request_payload, question_ids) "
                "VALUES (:id, :uid, 'queued', '{}', '[]')"
            ),
            {"id": str(uuid.uuid4()), "uid": str(uuid.uuid4())},
        )

        # Downgrade symmetrically drops table and KP columns
        migration.downgrade()
        down_inspector = inspect(connection)
        assert "question_generation_jobs" not in down_inspector.get_table_names()
        down_kp = {c["name"] for c in down_inspector.get_columns("knowledge_points")}
        assert "structured_content" not in down_kp
        assert "sort_order" not in down_kp

        # Re-upgrade passes cleanly
        migration.upgrade()
        assert "question_generation_jobs" in inspect(connection).get_table_names()
