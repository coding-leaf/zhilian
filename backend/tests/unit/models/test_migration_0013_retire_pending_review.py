"""Alembic 0013 migration tests: soft-deleting legacy pending_review questions."""

import uuid
from datetime import UTC, datetime
from pathlib import Path

import alembic.op as alembic_op
import sqlalchemy as sa
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

BACKEND_DIR = Path(__file__).resolve().parents[3]
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
TARGET_REVISION = "0013_retire_pending_review"


def _load_revisions():
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    script_dir = ScriptDirectory.from_config(config)
    return list(reversed(list(script_dir.walk_revisions())))


def test_migration_0013_soft_delete_pending_review_and_downgrade_symmetry() -> None:
    """Verify 0013 soft-deletes legacy pending_review rows and reverses symmetrically."""
    revisions = _load_revisions()
    pre_revisions = [rev for rev in revisions if rev.revision != TARGET_REVISION]
    target_rev = next(rev for rev in revisions if rev.revision == TARGET_REVISION)
    assert target_rev.down_revision == "0012_job_practice_grading_uq"

    engine = create_engine("sqlite:///:memory:")
    sentinel = object()
    previous_proxy = getattr(alembic_op, "_proxy", sentinel)
    try:
        with engine.begin() as conn:
            alembic_op._proxy = Operations(MigrationContext.configure(conn))
            for rev in pre_revisions:
                assert rev.module is not None
                rev.module.upgrade()

            user_id = uuid.uuid4().hex
            material_id = uuid.uuid4().hex
            version_id = uuid.uuid4().hex
            kp_id = uuid.uuid4().hex
            q_avail_id = uuid.uuid4().hex
            q_pending_id = uuid.uuid4().hex
            now = datetime.now(UTC)

            conn.execute(
                sa.text(
                    "INSERT INTO users (id, openid, nickname, is_active, token_version, "
                    "created_at, updated_at) "
                    "VALUES (:id, :openid, 'u', 1, 1, :t, :t)"
                ),
                {"id": user_id, "openid": f"wx_{user_id[:8]}", "t": now},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO materials (id, user_id, title, file_format, file_size, "
                    "status, is_deleted, created_at, updated_at) "
                    "VALUES (:id, :uid, 'm.pdf', 'pdf', 100, 'ready', 0, :t, :t)"
                ),
                {"id": material_id, "uid": user_id, "t": now},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO material_versions (id, user_id, material_id, version_number, "
                    "storage_key, content_hash, parse_status, created_at, updated_at) "
                    "VALUES (:id, :uid, :mid, 1, 'raw/m.pdf', 'hash1', 'completed', :t, :t)"
                ),
                {"id": version_id, "uid": user_id, "mid": material_id, "t": now},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO knowledge_points (id, user_id, material_id, version_id, "
                    "name, description, level, batch_id, created_at, updated_at) "
                    "VALUES (:id, :uid, :mid, :vid, 'kp', 'desc', 1, 'kp-b1', :t, :t)"
                ),
                {"id": kp_id, "uid": user_id, "mid": material_id, "vid": version_id, "t": now},
            )
            for q_id, status in ((q_avail_id, "available"), (q_pending_id, "pending_review")):
                conn.execute(
                    sa.text(
                        "INSERT INTO questions (id, user_id, material_id, version_id, "
                        "knowledge_point_id, question_type, status, is_deleted, stem, "
                        "options, answer, analysis, difficulty, grading_rubric, "
                        "source_snippet_ids, created_at, updated_at) "
                        "VALUES (:id, :uid, :mid, :vid, :kid, 'single_choice', :st, 0, "
                        "'测试题干内容足够长', '[]', 'A', '', 3, '{}', '[]', :t, :t)"
                    ),
                    {
                        "id": q_id,
                        "uid": user_id,
                        "mid": material_id,
                        "vid": version_id,
                        "kid": kp_id,
                        "st": status,
                        "t": now,
                    },
                )

            assert target_rev.module is not None
            target_rev.module.upgrade()

            rows = conn.execute(sa.text("SELECT id, status, is_deleted FROM questions")).fetchall()
            deleted_by_id = {row[0]: bool(row[2]) for row in rows}
            assert deleted_by_id[q_avail_id] is False
            assert deleted_by_id[q_pending_id] is True

            target_rev.module.downgrade()
            rows_down = conn.execute(
                sa.text("SELECT id, status, is_deleted FROM questions")
            ).fetchall()
            deleted_after_down = {row[0]: bool(row[2]) for row in rows_down}
            assert deleted_after_down[q_avail_id] is False
            assert deleted_after_down[q_pending_id] is False

            target_rev.module.upgrade()
            rows_reup = conn.execute(
                sa.text("SELECT id, status, is_deleted FROM questions")
            ).fetchall()
            deleted_after_reup = {row[0]: bool(row[2]) for row in rows_reup}
            assert deleted_after_reup[q_avail_id] is False
            assert deleted_after_reup[q_pending_id] is True
    finally:
        if previous_proxy is sentinel:
            if hasattr(alembic_op, "_proxy"):
                del alembic_op._proxy
        else:
            alembic_op._proxy = previous_proxy
        engine.dispose()
