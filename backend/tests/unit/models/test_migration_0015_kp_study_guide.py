"""Unit tests for 0015 knowledge point study_guide cache columns migration."""

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
    "0011_structured_kp_and_question_jobs",
    "0012_async_job_practice_and_grading_unique",
    "0013_soft_delete_legacy_pending_review_questions",
    "0014_question_collections",
)

REVISION_MODULE = "0015_kp_study_guide"


@pytest.fixture
def connection() -> Generator[Connection, None, None]:
    """Replay migrations 0001..0014 on an in-memory SQLite database."""
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


class TestMigration0015KpStudyGuide:
    """Test suite for 0015 Alembic migration upgrade/downgrade symmetry."""

    def test_upgrade_and_downgrade_symmetry(self, connection: Connection) -> None:
        """Verify study_guide columns, defaults, and symmetric downgrade/upgrade."""
        migration = importlib.import_module(f"migrations.versions.{REVISION_MODULE}")
        assert migration.revision == "0015_kp_study_guide"
        assert migration.down_revision == "0014_question_collections"

        before_cols = {c["name"] for c in inspect(connection).get_columns("knowledge_points")}
        assert "study_guide" not in before_cols
        assert "study_guide_generated_at" not in before_cols
        assert "study_guide_version" not in before_cols

        migration.upgrade()

        after_cols = {c["name"]: c for c in inspect(connection).get_columns("knowledge_points")}
        assert "study_guide" in after_cols
        assert after_cols["study_guide"]["nullable"] is True
        assert "study_guide_generated_at" in after_cols
        assert after_cols["study_guide_generated_at"]["nullable"] is True
        assert "study_guide_version" in after_cols
        assert after_cols["study_guide_version"]["nullable"] is False

        # Insert row using server_default for study_guide_version
        uid = str(uuid.uuid4())
        mat_id = str(uuid.uuid4())
        ver_id = str(uuid.uuid4())
        kp_id = str(uuid.uuid4())
        connection.execute(
            text(
                "INSERT INTO users (id, openid, nickname, is_active, token_version) "
                "VALUES (:uid, :openid, 'test', 1, 1)"
            ),
            {"uid": uid, "openid": f"wx_{uid[:8]}"},
        )
        connection.execute(
            text(
                "INSERT INTO materials "
                "(id, user_id, title, file_format, file_size, source_type, status) "
                "VALUES (:mid, :uid, 't.pdf', 'pdf', 100, 'local', 'ready')"
            ),
            {"mid": mat_id, "uid": uid},
        )
        connection.execute(
            text(
                "INSERT INTO material_versions "
                "(id, user_id, material_id, version_number, storage_key, "
                "content_hash, parse_status, is_active) "
                "VALUES (:vid, :uid, :mid, 1, 'k', 'h', 'ready', 1)"
            ),
            {"vid": ver_id, "uid": uid, "mid": mat_id},
        )
        connection.execute(
            text(
                "INSERT INTO knowledge_points "
                "(id, user_id, material_id, version_id, name, description, "
                "level, batch_id, is_low_confidence) "
                "VALUES (:kpid, :uid, :mid, :vid, '考点一', '描述', 1, 'b1', 0)"
            ),
            {"kpid": kp_id, "uid": uid, "mid": mat_id, "vid": ver_id},
        )
        row = connection.execute(
            text("SELECT study_guide_version FROM knowledge_points WHERE id = :kpid"),
            {"kpid": kp_id},
        ).fetchone()
        assert row is not None and row[0] == 0

        # Downgrade symmetrically drops the 3 columns
        migration.downgrade()
        down_cols = {c["name"] for c in inspect(connection).get_columns("knowledge_points")}
        assert "study_guide" not in down_cols
        assert "study_guide_generated_at" not in down_cols
        assert "study_guide_version" not in down_cols

        # Re-upgrade passes cleanly
        migration.upgrade()
        reup_cols = {c["name"] for c in inspect(connection).get_columns("knowledge_points")}
        assert {"study_guide", "study_guide_generated_at", "study_guide_version"}.issubset(
            reup_cols
        )
