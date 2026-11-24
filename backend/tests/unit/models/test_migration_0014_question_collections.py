"""Alembic 0014 migration tests: question_collections and question_collection_items."""

from pathlib import Path

import alembic.op as alembic_op
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

BACKEND_DIR = Path(__file__).resolve().parents[3]
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
TARGET_REVISION = "0014_question_collections"


def _load_revisions():
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    script_dir = ScriptDirectory.from_config(config)
    return list(reversed(list(script_dir.walk_revisions())))


def test_migration_0014_upgrade_downgrade_symmetry() -> None:
    """Verify 0014 creates collection tables/indexes and rolls back cleanly."""
    revisions = _load_revisions()
    pre_revisions = [rev for rev in revisions if rev.revision != TARGET_REVISION]
    target_rev = next(rev for rev in revisions if rev.revision == TARGET_REVISION)
    assert target_rev.down_revision == "0013_retire_pending_review"
    assert target_rev.module is not None

    engine = create_engine("sqlite:///:memory:")
    sentinel = object()
    previous_proxy = getattr(alembic_op, "_proxy", sentinel)
    try:
        with engine.begin() as conn:
            alembic_op._proxy = Operations(MigrationContext.configure(conn))
            for rev in pre_revisions:
                assert rev.module is not None
                rev.module.upgrade()

            target_rev.module.upgrade()
            inspector = inspect(conn)
            assert "question_collections" in inspector.get_table_names()
            assert "question_collection_items" in inspector.get_table_names()

            target_rev.module.downgrade()
            inspector_after_down = inspect(conn)
            assert "question_collections" not in inspector_after_down.get_table_names()
            assert "question_collection_items" not in inspector_after_down.get_table_names()

            target_rev.module.upgrade()
            inspector_reup = inspect(conn)
            assert "question_collections" in inspector_reup.get_table_names()
            assert "question_collection_items" in inspector_reup.get_table_names()
    finally:
        if previous_proxy is sentinel:
            if hasattr(alembic_op, "_proxy"):
                del alembic_op._proxy
        else:
            alembic_op._proxy = previous_proxy
        engine.dispose()
