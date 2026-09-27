"""Unit tests for MaterialFolder model and migration 0005.

Verifies fields/defaults, unique (user_id, name) constraint, Material.folder
relationship attribution, SET NULL foreign key metadata, privacy-safe __repr__,
and the 0005 Alembic migration upgrade/downgrade symmetry.
"""

import importlib
import uuid
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models.base import Base
from app.models.material import Material, MaterialFolder
from app.models.user import User


@pytest.fixture
def db_session() -> Generator[sessionmaker[Session], None, None]:
    """Creates an in-memory SQLite database session factory."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory: sessionmaker[Session] = sessionmaker(bind=engine)
    try:
        yield session_factory
    finally:
        engine.dispose()


class TestMaterialFolderModel:
    """Test suite for the MaterialFolder entity."""

    def test_folder_defaults_and_creation(self, db_session: sessionmaker[Session]) -> None:
        """Verify defaults: archived_at None, sort_order 0, parent_id None."""
        user_id = uuid.uuid4()
        with db_session() as session:
            session.add(User(id=user_id, openid="folder_model_user_01"))
            session.commit()

            folder = MaterialFolder(user_id=user_id, name="线性代数")
            session.add(folder)
            session.commit()

            assert isinstance(folder.id, uuid.UUID)
            assert folder.user_id == user_id
            assert folder.name == "线性代数"
            assert folder.parent_id is None
            assert folder.sort_order == 0
            assert folder.archived_at is None

    def test_unique_user_name_constraint(self, db_session: sessionmaker[Session]) -> None:
        """Verify the unique (user_id, name) constraint is enforced."""
        user_id = uuid.uuid4()
        with db_session() as session:
            session.add(User(id=user_id, openid="folder_model_user_02"))
            session.commit()
            session.add(MaterialFolder(user_id=user_id, name="高等数学"))
            session.commit()

            session.add(MaterialFolder(user_id=user_id, name="高等数学"))
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()

    def test_material_folder_attribution_and_relationship(
        self, db_session: sessionmaker[Session]
    ) -> None:
        """Verify Material.folder_id attribution and folder.materials backref."""
        user_id = uuid.uuid4()
        with db_session() as session:
            session.add(User(id=user_id, openid="folder_model_user_03"))
            session.commit()

            folder = MaterialFolder(user_id=user_id, name="概率论")
            session.add(folder)
            session.commit()

            material = Material(
                user_id=user_id,
                title="概率论讲义.pdf",
                file_format="pdf",
                file_size=1000,
                folder_id=folder.id,
            )
            session.add(material)
            session.commit()

            assert material.folder_id == folder.id
            assert material.folder is not None
            assert material.folder.id == folder.id

            reloaded = session.scalar(select(MaterialFolder).where(MaterialFolder.id == folder.id))
            assert reloaded is not None
            assert len(reloaded.materials) == 1
            assert reloaded.materials[0].id == material.id

    def test_folder_id_foreign_key_is_set_null(self) -> None:
        """Verify materials.folder_id FK targets material_folders.id with SET NULL."""
        col = next(iter(Material.folder_id.property.columns))
        fk = next(iter(col.foreign_keys))
        assert fk.target_fullname == "material_folders.id"
        assert fk.ondelete == "SET NULL"
        assert col.nullable is True

    def test_repr_desensitization(self) -> None:
        """Verify __repr__ never leaks full sensitive content."""
        folder = MaterialFolder(id=uuid.uuid4(), user_id=uuid.uuid4(), name="A" * 60)
        text = repr(folder)
        assert "A" * 60 not in text
        assert str(folder.id) in text


class TestMaterialFolderMigration0005:
    """Test suite for migration 0005 upgrade/downgrade symmetry."""

    def test_migration_0005_upgrade_and_downgrade(self) -> None:
        """Verify 0005 creates material_folders + materials.folder_id and rolls back."""
        migration_0001 = importlib.import_module(
            "migrations.versions.0001_create_material_tables_and_vector"
        )
        migration_0005 = importlib.import_module("migrations.versions.0005_create_material_folders")

        engine = create_engine("sqlite:///:memory:")
        try:
            with engine.begin() as connection:
                import alembic.op as alembic_op
                from alembic.operations import Operations
                from alembic.runtime.migration import MigrationContext

                context = MigrationContext.configure(connection)
                alembic_op._proxy = Operations(context)  # type: ignore[attr-defined]

                migration_0001.upgrade()
                migration_0005.upgrade()

                inspector = inspect(connection)
                table_names = set(inspector.get_table_names())
                assert "material_folders" in table_names
                material_columns = {c["name"] for c in inspector.get_columns("materials")}
                assert "folder_id" in material_columns
                folder_columns = {c["name"] for c in inspector.get_columns("material_folders")}
                assert {"id", "user_id", "name", "parent_id", "sort_order", "archived_at"} <= (
                    folder_columns
                )

                migration_0005.downgrade()
                inspector.clear_cache()
                tables_after = set(inspector.get_table_names())
                assert "material_folders" not in tables_after
                columns_after = {c["name"] for c in inspector.get_columns("materials")}
                assert "folder_id" not in columns_after

                migration_0005.upgrade()
                inspector.clear_cache()
                assert "material_folders" in set(inspector.get_table_names())
                assert "folder_id" in {c["name"] for c in inspector.get_columns("materials")}
        finally:
            engine.dispose()
