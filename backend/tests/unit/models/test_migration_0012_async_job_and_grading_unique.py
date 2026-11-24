"""Alembic 0012 migration tests: question_generation_jobs columns, dedup & partial unique index."""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import alembic.op as alembic_op
import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError

BACKEND_DIR = Path(__file__).resolve().parents[3]
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
TARGET_REVISION = "0012_job_practice_grading_uq"


def _load_revisions():
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    script_dir = ScriptDirectory.from_config(config)
    return list(reversed(list(script_dir.walk_revisions())))


def test_migration_0012_upgrade_dedup_unique_and_downgrade_symmetry() -> None:
    """Verify 0012 deduplicates legacy final records, enforces partial unique, and downgrades."""
    revisions = _load_revisions()
    pre_revisions = [rev for rev in revisions if rev.revision != TARGET_REVISION]
    target_rev = next(rev for rev in revisions if rev.revision == TARGET_REVISION)

    engine = create_engine("sqlite:///:memory:")
    sentinel = object()
    previous_proxy = getattr(alembic_op, "_proxy", sentinel)
    try:
        with engine.begin() as conn:
            alembic_op._proxy = Operations(MigrationContext.configure(conn))
            for rev in pre_revisions:
                assert rev.module is not None
                rev.module.upgrade()

            # Seed legacy duplicate is_final=True grading_records for one attempt_item
            user_id = uuid.uuid4().hex
            material_id = uuid.uuid4().hex
            practice_id = uuid.uuid4().hex
            item_id = uuid.uuid4().hex
            older_record_id = uuid.uuid4().hex
            newer_record_id = uuid.uuid4().hex
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
                    "INSERT INTO practices (id, user_id, material_id, title, "
                    "knowledge_point_ids, question_types, question_count, ordered_question_ids, "
                    "status, source_type, mode, created_at, updated_at) "
                    "VALUES (:id, :uid, :mid, 'p', '[]', '[]', 1, '[]', "
                    "'completed', 'normal', 'sequential', :t, :t)"
                ),
                {"id": practice_id, "uid": user_id, "mid": material_id, "t": now},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO attempt_items (id, user_id, practice_id, order_index, "
                    "question_snapshot, is_answered, duration_seconds, max_score, "
                    "created_at, updated_at) "
                    "VALUES (:id, :uid, :pid, 1, '{}', 1, 0, 5.0, :t, :t)"
                ),
                {"id": item_id, "uid": user_id, "pid": practice_id, "t": now},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO grading_records (id, user_id, practice_id, attempt_item_id, "
                    "channel, status, is_final, score, max_score, hit_keywords, "
                    "missing_keywords, grading_metadata, created_at, updated_at) "
                    "VALUES (:id, :uid, :pid, :iid, 'ai', 'success', 1, 2.0, 5.0, "
                    "'[]', '[]', '{}', :t, :t)"
                ),
                {
                    "id": older_record_id,
                    "uid": user_id,
                    "pid": practice_id,
                    "iid": item_id,
                    "t": now - timedelta(minutes=5),
                },
            )
            conn.execute(
                sa.text(
                    "INSERT INTO grading_records (id, user_id, practice_id, attempt_item_id, "
                    "channel, status, is_final, score, max_score, hit_keywords, "
                    "missing_keywords, grading_metadata, created_at, updated_at) "
                    "VALUES (:id, :uid, :pid, :iid, 'ai', 'success', 1, 4.5, 5.0, "
                    "'[]', '[]', '{}', :t, :t)"
                ),
                {
                    "id": newer_record_id,
                    "uid": user_id,
                    "pid": practice_id,
                    "iid": item_id,
                    "t": now,
                },
            )

            # Run 0012 upgrade
            assert target_rev.module is not None
            target_rev.module.upgrade()

            # 1. Verify question_generation_jobs columns exist
            job_cols = {c["name"] for c in inspect(conn).get_columns("question_generation_jobs")}
            assert {
                "result_practice_id",
                "source_type",
                "source_practice_id",
                "idempotency_key",
            }.issubset(job_cols)

            # 2. Verify legacy duplicate final records were deduplicated (latest kept)
            rows = conn.execute(
                sa.text("SELECT id, is_final FROM grading_records WHERE attempt_item_id = :iid"),
                {"iid": item_id},
            ).fetchall()
            final_by_id = {row[0]: bool(row[1]) for row in rows}
            assert final_by_id[newer_record_id] is True
            assert final_by_id[older_record_id] is False

            # 3. Verify partial unique index blocks a second is_final=1 row
            with pytest.raises(IntegrityError), conn.begin_nested():
                conn.execute(
                    sa.text(
                        "INSERT INTO grading_records (id, user_id, practice_id, "
                        "attempt_item_id, channel, status, is_final, score, max_score, "
                        "hit_keywords, missing_keywords, grading_metadata, "
                        "created_at, updated_at) "
                        "VALUES (:id, :uid, :pid, :iid, 'ai', 'success', 1, 5.0, 5.0, "
                        "'[]', '[]', '{}', :t, :t)"
                    ),
                    {
                        "id": uuid.uuid4().hex,
                        "uid": user_id,
                        "pid": practice_id,
                        "iid": item_id,
                        "t": now,
                    },
                )

            # 4. Multiple historical is_final=0 rows remain allowed
            conn.execute(
                sa.text(
                    "INSERT INTO grading_records (id, user_id, practice_id, attempt_item_id, "
                    "channel, status, is_final, score, max_score, hit_keywords, "
                    "missing_keywords, grading_metadata, created_at, updated_at) "
                    "VALUES (:id, :uid, :pid, :iid, 'ai', 'success', 0, 1.0, 5.0, "
                    "'[]', '[]', '{}', :t, :t)"
                ),
                {
                    "id": uuid.uuid4().hex,
                    "uid": user_id,
                    "pid": practice_id,
                    "iid": item_id,
                    "t": now,
                },
            )

            # 5. Downgrade -> Upgrade symmetry
            target_rev.module.downgrade()
            job_cols_after_down = {
                c["name"] for c in inspect(conn).get_columns("question_generation_jobs")
            }
            assert "result_practice_id" not in job_cols_after_down
            assert "idempotency_key" not in job_cols_after_down
            grading_indexes = {idx["name"] for idx in inspect(conn).get_indexes("grading_records")}
            assert "uq_grading_records_item_final" not in grading_indexes

            target_rev.module.upgrade()
            grading_indexes_re = {
                idx["name"] for idx in inspect(conn).get_indexes("grading_records")
            }
            assert "uq_grading_records_item_final" in grading_indexes_re
    finally:
        if previous_proxy is sentinel:
            if hasattr(alembic_op, "_proxy"):
                del alembic_op._proxy
        else:
            alembic_op._proxy = previous_proxy
        engine.dispose()
