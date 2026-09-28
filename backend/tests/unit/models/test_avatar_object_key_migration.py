"""Migration coverage for managed user avatar object keys."""

import importlib

from sqlalchemy import create_engine, inspect, text

MIGRATION_ORDER = (
    "0001_create_material_tables_and_vector",
    "0002_create_knowledge_and_question_tables",
    "0003_create_practice_tables",
    "0004_add_practice_mode",
    "0005_create_material_folders",
    "0006_practice_folder_scope",
    "0007_folder_active_name_unique",
    "0008_question_batch_id",
)


def _apply_prerequisites(connection) -> None:  # type: ignore[no-untyped-def]
    """Replay every migration preceding 0009."""
    import alembic.op as alembic_op
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    alembic_op._proxy = Operations(MigrationContext.configure(connection))  # type: ignore[attr-defined]
    for name in MIGRATION_ORDER:
        importlib.import_module(f"migrations.versions.{name}").upgrade()


def test_avatar_key_migration_preserves_legacy_urls() -> None:
    migration = importlib.import_module("migrations.versions.0009_avatar_object_key")
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as connection:
            _apply_prerequisites(connection)
            connection.execute(
                text(
                    "INSERT INTO users (id, openid, nickname, avatar_url, token_version, "
                    "is_active, is_deleted, created_at, updated_at) VALUES "
                    "('u1', 'openid-1', '', 'https://old.example/a.jpg', 1, 1, 0, "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            migration.upgrade()
            inspector = inspect(connection)
            columns = {column["name"] for column in inspector.get_columns("users")}
            assert "avatar_object_key" in columns
            assert (
                connection.execute(
                    text("SELECT avatar_url FROM users WHERE openid='openid-1'")
                ).scalar_one()
                == "https://old.example/a.jpg"
            )

            migration.downgrade()
            inspector.clear_cache()
            columns = {column["name"] for column in inspector.get_columns("users")}
            assert "avatar_object_key" not in columns
            migration.upgrade()
            inspector.clear_cache()
            assert "avatar_object_key" in {
                column["name"] for column in inspector.get_columns("users")
            }
    finally:
        engine.dispose()
