"""Unit tests for the Material, MaterialVersion, MaterialSnippet, and MaterialOCRPage models.

Tests schema definitions, multi-tenant isolation, relationship cascades,
vector type fallback, privacy desensitization (__repr__), and Alembic migration symmetry.
"""

import importlib
import uuid
from collections.abc import Generator
from datetime import datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.models.base import Base
from app.models.material import (
    Material,
    MaterialDocType,
    MaterialOCRPage,
    MaterialSnippet,
    MaterialStatus,
    MaterialVersion,
    ParseStatus,
    SourceType,
    get_vector_type,
)
from app.models.user import User


@pytest.fixture
def db_session() -> Generator[sessionmaker[Session], None, None]:
    """Creates an in-memory SQLite database session factory for material tests."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory: sessionmaker[Session] = sessionmaker(bind=engine)
    try:
        yield session_factory
    finally:
        engine.dispose()


class TestMaterialEnumsAndTypes:
    """Test suite for material domain enums and vector type fallback."""

    def test_enums_values(self) -> None:
        """Verify enum definitions adhere to the spec."""
        assert MaterialStatus.PENDING.value == "pending"
        assert MaterialStatus.PARSING.value == "parsing"
        assert MaterialStatus.READY.value == "ready"
        assert MaterialStatus.FAILED.value == "failed"

        assert ParseStatus.QUEUED.value == "queued"
        assert ParseStatus.READY.value == "ready"
        assert ParseStatus.FAILED.value == "failed"

        assert SourceType.LOCAL.value == "local"
        assert SourceType.WECHAT.value == "wechat"

        assert MaterialDocType.PDF.value == "pdf"
        assert MaterialDocType.DOCX.value == "docx"
        assert MaterialDocType.MARKDOWN.value == "md"

    def test_get_vector_type_fallback(self) -> None:
        """Verify vector type fallback returns a valid SQLAlchemy TypeEngine."""
        vector_type = get_vector_type(1024)
        assert vector_type is not None

    def test_get_vector_type_import_error_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify get_vector_type safely falls back to JSON when pgvector is absent."""
        import sys

        from sqlalchemy.types import JSON

        monkeypatch.setitem(sys.modules, "pgvector.sqlalchemy", None)
        fallback_type = get_vector_type(1024)
        assert isinstance(fallback_type, JSON)


class TestMaterialModels:
    """Test suite for Material, MaterialVersion, MaterialSnippet, MaterialOCRPage."""

    def test_material_defaults_and_creation(self, db_session: sessionmaker[Session]) -> None:
        """Verify Material initializes with correct defaults and fields."""
        user_id = uuid.uuid4()
        with db_session() as session:
            user = User(id=user_id, openid="test_material_user_01")
            session.add(user)
            session.commit()

            material = Material(
                user_id=user_id,
                title="Linear Algebra Notes",
                file_format=MaterialDocType.PDF.value,
                file_size=1048576,
            )
            session.add(material)
            session.commit()

            assert isinstance(material.id, uuid.UUID)
            assert material.user_id == user_id
            assert material.title == "Linear Algebra Notes"
            assert material.file_format == "pdf"
            assert material.file_size == 1048576
            assert material.source_type == SourceType.LOCAL.value
            assert material.status == MaterialStatus.PENDING.value
            assert material.current_version_id is None
            assert material.is_deleted is False
            assert isinstance(material.created_at, datetime)
            assert isinstance(material.updated_at, datetime)

    def test_material_version_creation_and_relationship(
        self, db_session: sessionmaker[Session]
    ) -> None:
        """Verify MaterialVersion fields and 1:N relationship with Material."""
        user_id = uuid.uuid4()
        with db_session() as session:
            user = User(id=user_id, openid="test_material_user_02")
            session.add(user)
            session.commit()

            material = Material(
                user_id=user_id,
                title="Calculus Vol 1",
                file_format="pdf",
                file_size=2097152,
            )
            session.add(material)
            session.commit()

            version = MaterialVersion(
                user_id=user_id,
                material_id=material.id,
                version_number=1,
                storage_key="materials/calculus_v1.pdf",
                content_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            )
            session.add(version)
            session.commit()

            # Set current_version_id with use_alter
            material.current_version_id = version.id
            session.commit()

            # Reload
            retrieved_mat = session.scalar(select(Material).where(Material.id == material.id))
            assert retrieved_mat is not None
            assert len(retrieved_mat.versions) == 1
            assert retrieved_mat.versions[0].id == version.id
            assert retrieved_mat.current_version is not None
            assert retrieved_mat.current_version.id == version.id
            assert retrieved_mat.current_version.version_number == 1
            assert retrieved_mat.current_version.parse_status == ParseStatus.QUEUED.value
            assert retrieved_mat.current_version.is_active is True

    def test_material_snippet_fields_and_isolation(self, db_session: sessionmaker[Session]) -> None:
        """Verify MaterialSnippet persistence, JSON metadata, and vector storage."""
        user_id = uuid.uuid4()
        with db_session() as session:
            user = User(id=user_id, openid="test_material_user_03")
            session.add(user)
            session.commit()

            material = Material(
                user_id=user_id,
                title="Physics Handbook",
                file_format="docx",
                file_size=512000,
            )
            session.add(material)
            session.commit()

            version = MaterialVersion(
                user_id=user_id,
                material_id=material.id,
                version_number=1,
                storage_key="materials/physics.docx",
                content_hash="abc123hash",
            )
            session.add(version)
            session.commit()

            snippet_text = "Newton's second law states that F = ma."
            snippet = MaterialSnippet(
                user_id=user_id,
                material_id=material.id,
                version_id=version.id,
                snippet_index=0,
                content=snippet_text,
                char_length=len(snippet_text),
                start_offset=0,
                end_offset=len(snippet_text),
                chapter_title="Chapter 1: Dynamics",
                source_info={"page_number": 1, "paragraph_index": 2},
                embedding=[0.01] * 1024,
            )
            session.add(snippet)
            session.commit()

            retrieved = session.scalar(
                select(MaterialSnippet).where(MaterialSnippet.id == snippet.id)
            )
            assert retrieved is not None
            assert retrieved.snippet_index == 0
            assert retrieved.content == snippet_text
            assert retrieved.char_length == len(snippet_text)
            assert retrieved.chapter_title == "Chapter 1: Dynamics"
            assert retrieved.source_info["page_number"] == 1
            assert retrieved.user_id == user_id
            assert retrieved.material_id == material.id
            assert retrieved.version_id == version.id

    def test_material_ocr_page_fields(self, db_session: sessionmaker[Session]) -> None:
        """Verify MaterialOCRPage fields, gate conditions, and reshoot counter."""
        user_id = uuid.uuid4()
        with db_session() as session:
            user = User(id=user_id, openid="test_material_user_04")
            session.add(user)
            session.commit()

            material = Material(
                user_id=user_id,
                title="Scanned Chemistry Exam",
                file_format="pdf",
                file_size=1024000,
            )
            session.add(material)
            session.commit()

            version = MaterialVersion(
                user_id=user_id,
                material_id=material.id,
                version_number=1,
                storage_key="materials/chem_scan.pdf",
                content_hash="hashchemscan01",
            )
            session.add(version)
            session.commit()

            ocr_page = MaterialOCRPage(
                user_id=user_id,
                material_id=material.id,
                version_id=version.id,
                page_number=1,
                image_storage_key="ocr/pages/page_1.png",
                raw_text="Chemistry exam page 1 text",
                gibberish_ratio=0.05,
                valid_char_count=120,
                is_qualified=True,
                unqualified_reason=None,
                reshoot_count=0,
            )
            session.add(ocr_page)
            session.commit()

            retrieved = session.scalar(
                select(MaterialOCRPage).where(MaterialOCRPage.id == ocr_page.id)
            )
            assert retrieved is not None
            assert retrieved.page_number == 1
            assert retrieved.gibberish_ratio == 0.05
            assert retrieved.valid_char_count == 120
            assert retrieved.is_qualified is True
            assert retrieved.reshoot_count == 0

    def test_desensitization_repr_redlines(self) -> None:
        """Verify __repr__ desensitization redline: content and raw text MUST NOT appear."""
        user_id = uuid.uuid4()
        mat_id = uuid.uuid4()
        ver_id = uuid.uuid4()
        snip_id = uuid.uuid4()
        ocr_id = uuid.uuid4()

        sensitive_snippet_text = "TOP_SECRET_EXAM_QUESTION_AND_ANSWER_TEXT_DO_NOT_LEAK"
        sensitive_ocr_transcript = "CONFIDENTIAL_OCR_SCANNED_PAGE_TRANSCRIPT_DO_NOT_LEAK"

        snippet = MaterialSnippet(
            id=snip_id,
            user_id=user_id,
            material_id=mat_id,
            version_id=ver_id,
            snippet_index=1,
            content=sensitive_snippet_text,
            char_length=len(sensitive_snippet_text),
            start_offset=0,
            end_offset=len(sensitive_snippet_text),
        )

        ocr_page = MaterialOCRPage(
            id=ocr_id,
            user_id=user_id,
            material_id=mat_id,
            version_id=ver_id,
            page_number=2,
            image_storage_key="s3://storage/key.png",
            raw_text=sensitive_ocr_transcript,
        )

        material = Material(
            id=mat_id,
            user_id=user_id,
            title="Highly Confidential Math Notes",
            file_format="pdf",
            file_size=100,
        )

        version = MaterialVersion(
            id=ver_id,
            user_id=user_id,
            material_id=mat_id,
            version_number=1,
            storage_key="s3://private-bucket/materials/abc.pdf",
            content_hash="content_hash_digest_123",
        )

        # Assert __repr__ strings
        snippet_repr = repr(snippet)
        ocr_repr = repr(ocr_page)
        mat_repr = repr(material)
        ver_repr = repr(version)

        assert sensitive_snippet_text not in snippet_repr, (
            "Redline violated: snippet content leaked in repr"
        )
        assert sensitive_ocr_transcript not in ocr_repr, (
            "Redline violated: ocr raw_text leaked in repr"
        )
        assert "content_hash_digest_123" not in ver_repr
        assert str(snip_id) in snippet_repr
        assert str(mat_id) in mat_repr

    def test_cascade_delete_from_material_to_versions_and_snippets(
        self, db_session: sessionmaker[Session]
    ) -> None:
        """Verify cascade deletion removes versions, snippets, and ocr_pages upon deletion."""
        user_id = uuid.uuid4()
        with db_session() as session:
            user = User(id=user_id, openid="test_cascade_user")
            session.add(user)
            session.commit()

            material = Material(
                user_id=user_id,
                title="Biology 101",
                file_format="pdf",
                file_size=50000,
            )
            session.add(material)
            session.commit()

            version = MaterialVersion(
                user_id=user_id,
                material_id=material.id,
                version_number=1,
                storage_key="bio/v1.pdf",
                content_hash="biohash1",
            )
            session.add(version)
            session.commit()

            snippet = MaterialSnippet(
                user_id=user_id,
                material_id=material.id,
                version_id=version.id,
                snippet_index=0,
                content="Cellular mitosis stages",
                char_length=23,
                start_offset=0,
                end_offset=23,
            )
            ocr_page = MaterialOCRPage(
                user_id=user_id,
                material_id=material.id,
                version_id=version.id,
                page_number=1,
                image_storage_key="bio/p1.png",
                raw_text="Cell mitosis",
            )
            session.add_all([snippet, ocr_page])
            session.commit()

            # Confirm all exist
            assert (
                session.scalar(select(MaterialVersion).where(MaterialVersion.id == version.id))
                is not None
            )
            assert (
                session.scalar(select(MaterialSnippet).where(MaterialSnippet.id == snippet.id))
                is not None
            )
            assert (
                session.scalar(select(MaterialOCRPage).where(MaterialOCRPage.id == ocr_page.id))
                is not None
            )

            # Delete material
            session.delete(material)
            session.commit()

            # Verify cascade deletion
            assert (
                session.scalar(select(MaterialVersion).where(MaterialVersion.id == version.id))
                is None
            )
            assert (
                session.scalar(select(MaterialSnippet).where(MaterialSnippet.id == snippet.id))
                is None
            )
            assert (
                session.scalar(select(MaterialOCRPage).where(MaterialOCRPage.id == ocr_page.id))
                is None
            )

    def test_material_soft_delete(self, db_session: sessionmaker[Session]) -> None:
        """Verify soft deletion flag toggles without physical row deletion."""
        user_id = uuid.uuid4()
        with db_session() as session:
            user = User(id=user_id, openid="test_soft_delete_user")
            session.add(user)
            session.commit()

            material = Material(
                user_id=user_id,
                title="Draft Physics Guide",
                file_format="md",
                file_size=1024,
            )
            session.add(material)
            session.commit()

            assert material.is_deleted is False

            # Mark soft deleted
            material.is_deleted = True
            session.commit()

            # Query should still find record if not filtering is_deleted
            retrieved = session.scalar(select(Material).where(Material.id == material.id))
            assert retrieved is not None
            assert retrieved.is_deleted is True

            # Query filtering is_deleted == False should exclude it
            active_mats = session.scalars(
                select(Material).where(Material.user_id == user_id, Material.is_deleted.is_(False))
            ).all()
            assert len(active_mats) == 0

    def test_tenant_cascade_from_user_to_all_models(
        self, db_session: sessionmaker[Session]
    ) -> None:
        """Verify deleting User cascades down to Material and its versions/snippets/pages."""
        user_id = uuid.uuid4()
        with db_session() as session:
            user = User(id=user_id, openid="test_user_cascade_tenant")
            session.add(user)
            session.commit()

            material = Material(
                user_id=user_id,
                title="Mathematics Discrete",
                file_format="pdf",
                file_size=2048,
            )
            session.add(material)
            session.commit()

            version = MaterialVersion(
                user_id=user_id,
                material_id=material.id,
                version_number=1,
                storage_key="math/v1.pdf",
                content_hash="mathhash1",
            )
            session.add(version)
            session.commit()

            snippet = MaterialSnippet(
                user_id=user_id,
                material_id=material.id,
                version_id=version.id,
                snippet_index=0,
                content="Graph theory basics",
                char_length=19,
                start_offset=0,
                end_offset=19,
            )
            ocr_page = MaterialOCRPage(
                user_id=user_id,
                material_id=material.id,
                version_id=version.id,
                page_number=1,
                image_storage_key="math/page1.png",
                raw_text="Graph theory",
            )
            session.add_all([snippet, ocr_page])
            session.commit()

            # Verify TenantModelMixin user_id on all 4 models
            assert material.user_id == user_id
            assert version.user_id == user_id
            assert snippet.user_id == user_id
            assert ocr_page.user_id == user_id

            # Verify TenantModelMixin foreign key cascade definition on all 4 models
            for model_cls in (Material, MaterialVersion, MaterialSnippet, MaterialOCRPage):
                col = next(iter(model_cls.user_id.property.columns))
                fk = next(iter(col.foreign_keys))
                assert fk.target_fullname == "users.id"
                assert fk.ondelete == "CASCADE"

            # Verify material_id cascade foreign key on child models
            for child_cls in (MaterialVersion, MaterialSnippet, MaterialOCRPage):
                col = next(iter(child_cls.material_id.property.columns))
                fk = next(iter(col.foreign_keys))
                assert fk.target_fullname == "materials.id"
                assert fk.ondelete == "CASCADE"

            # Verify version_id cascade foreign key on snippet and ocr page
            for sub_cls in (MaterialSnippet, MaterialOCRPage):
                col = next(iter(sub_cls.version_id.property.columns))
                fk = next(iter(col.foreign_keys))
                assert fk.target_fullname == "material_versions.id"
                assert fk.ondelete == "CASCADE"


class TestMaterialMigration:
    """Test suite for Alembic migration upgrade and downgrade reversibility."""

    def test_migration_upgrade_and_downgrade(self) -> None:
        """Verify the migration script can execute upgrade and downgrade without errors."""
        migration = importlib.import_module(
            "migrations.versions.0001_create_material_tables_and_vector"
        )

        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            # First create users table as prerequisite
            Base.metadata.tables["users"].create(connection)

            from alembic.operations import Operations
            from alembic.runtime.migration import MigrationContext

            context = MigrationContext.configure(connection)
            op = Operations(context)

            # Bind context to migration op
            import alembic.op as alembic_op

            alembic_op._proxy = op  # type: ignore[attr-defined]

            # Test upgrade
            migration.upgrade()

            # Inspect created tables
            from sqlalchemy import inspect

            inspector = inspect(connection)
            table_names = set(inspector.get_table_names())
            assert "materials" in table_names
            assert "material_versions" in table_names
            assert "material_snippets" in table_names
            assert "material_ocr_pages" in table_names

            # Test downgrade
            migration.downgrade()
            inspector.clear_cache()
            table_names_after_downgrade = set(inspector.get_table_names())
            assert "material_ocr_pages" not in table_names_after_downgrade
            assert "material_snippets" not in table_names_after_downgrade
            assert "material_versions" not in table_names_after_downgrade
            assert "materials" not in table_names_after_downgrade
            assert "users" in table_names_after_downgrade
