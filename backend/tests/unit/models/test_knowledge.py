"""Unit tests for KnowledgePoint and KnowledgePointSnippet persistence models.

Covers tree topology self-referencing, multi-tenant cascade isolation,
snippet bidirectional tracing, cascade deletion, and desensitized __repr__.
"""

import uuid
from collections.abc import Generator
from datetime import datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models.base import Base
from app.models.knowledge import KnowledgePoint, KnowledgePointSnippet
from app.models.material import Material, MaterialDocType, MaterialSnippet, MaterialVersion
from app.models.user import User


@pytest.fixture
def db_session() -> Generator[sessionmaker[Session], None, None]:
    """Creates an in-memory SQLite database session factory for knowledge tests."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory: sessionmaker[Session] = sessionmaker(bind=engine)
    try:
        yield session_factory
    finally:
        engine.dispose()


@pytest.fixture
def setup_material_and_version(
    db_session: sessionmaker[Session],
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Fixture providing user_id, material_id, and version_id for test cases."""
    user_id = uuid.uuid4()
    material_id = uuid.uuid4()
    version_id = uuid.uuid4()

    with db_session() as session:
        user = User(id=user_id, openid=f"test_kp_user_{user_id.hex[:8]}")
        session.add(user)
        session.commit()

        material = Material(
            id=material_id,
            user_id=user_id,
            title="Operating Systems Principles",
            file_format=MaterialDocType.PDF.value,
            file_size=1024000,
        )
        session.add(material)
        session.commit()

        version = MaterialVersion(
            id=version_id,
            user_id=user_id,
            material_id=material_id,
            version_number=1,
            storage_key="materials/os_v1.pdf",
            content_hash="content_hash_os_01",
        )
        session.add(version)
        session.commit()

    return user_id, material_id, version_id


class TestKnowledgePointTree:
    """Test suite for KnowledgePoint self-referencing hierarchy and tree topology."""

    def test_knowledge_point_tree_hierarchy(
        self,
        db_session: sessionmaker[Session],
        setup_material_and_version: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
    ) -> None:
        """Verify root and child knowledge points can form a valid tree with level 1~5."""
        user_id, material_id, version_id = setup_material_and_version

        with db_session() as session:
            # 1. Root knowledge point (level 1, parent_id is None)
            root_kp = KnowledgePoint(
                user_id=user_id,
                material_id=material_id,
                version_id=version_id,
                parent_id=None,
                name="Memory Management",
                description="Overview of virtual memory and physical memory mechanisms.",
                level=1,
                batch_id="batch_kp_001",
                is_low_confidence=False,
            )
            session.add(root_kp)
            session.commit()

            assert root_kp.parent_id is None
            assert root_kp.level == 1
            assert isinstance(root_kp.id, uuid.UUID)
            assert isinstance(root_kp.created_at, datetime)
            assert isinstance(root_kp.updated_at, datetime)

            # 2. Child knowledge point (level 2, parent_id = root.id)
            child_kp = KnowledgePoint(
                user_id=user_id,
                material_id=material_id,
                version_id=version_id,
                parent_id=root_kp.id,
                name="Paging Mechanism",
                description="Logical to physical address translation with page tables.",
                level=2,
                batch_id="batch_kp_001",
                is_low_confidence=False,
            )
            session.add(child_kp)
            session.commit()

            # 3. Grandchild knowledge point (level 3, parent_id = child.id)
            grandchild_kp = KnowledgePoint(
                user_id=user_id,
                material_id=material_id,
                version_id=version_id,
                parent_id=child_kp.id,
                name="TLB Speedup",
                description="Translation Lookaside Buffer caching page translations.",
                level=3,
                batch_id="batch_kp_001",
                is_low_confidence=True,
            )
            session.add(grandchild_kp)
            session.commit()

            # Reload root and test bidirectional relationship
            session.expire_all()
            reloaded_root = session.scalar(
                select(KnowledgePoint).where(KnowledgePoint.id == root_kp.id)
            )
            assert reloaded_root is not None
            assert len(reloaded_root.children) == 1
            assert reloaded_root.children[0].id == child_kp.id
            assert len(reloaded_root.children[0].children) == 1
            assert reloaded_root.children[0].children[0].id == grandchild_kp.id
            assert reloaded_root.children[0].children[0].is_low_confidence is True

            # Verify parent navigation
            reloaded_child = session.scalar(
                select(KnowledgePoint).where(KnowledgePoint.id == child_kp.id)
            )
            assert reloaded_child is not None
            assert reloaded_child.parent is not None
            assert reloaded_child.parent.id == root_kp.id

    def test_knowledge_point_cascade_deletion(
        self,
        db_session: sessionmaker[Session],
        setup_material_and_version: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
    ) -> None:
        """Verify deleting a parent knowledge point cascades and deletes its children."""
        user_id, material_id, version_id = setup_material_and_version

        with db_session() as session:
            root_kp = KnowledgePoint(
                user_id=user_id,
                material_id=material_id,
                version_id=version_id,
                parent_id=None,
                name="Concurrency Control",
                description="Locks, semaphores, and deadlocks.",
                level=1,
                batch_id="batch_cascade_01",
            )
            session.add(root_kp)
            session.commit()

            child_kp = KnowledgePoint(
                user_id=user_id,
                material_id=material_id,
                version_id=version_id,
                parent_id=root_kp.id,
                name="Mutex Locks",
                description="Mutual exclusion primitives.",
                level=2,
                batch_id="batch_cascade_01",
            )
            session.add(child_kp)
            session.commit()

            child_id = child_kp.id

            # Delete root knowledge point
            session.delete(root_kp)
            session.commit()

            # Verify child is deleted
            assert (
                session.scalar(select(KnowledgePoint).where(KnowledgePoint.id == child_id)) is None
            )


class TestKnowledgePointSnippetMapping:
    """Test suite for KnowledgePointSnippet bidirectional tracing and constraints."""

    def test_snippet_mapping_creation_and_uniqueness(
        self,
        db_session: sessionmaker[Session],
        setup_material_and_version: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
    ) -> None:
        """Verify KnowledgePointSnippet links knowledge point and snippet with uniqueness."""
        user_id, material_id, version_id = setup_material_and_version

        with db_session() as session:
            kp = KnowledgePoint(
                user_id=user_id,
                material_id=material_id,
                version_id=version_id,
                parent_id=None,
                name="CPU Scheduling",
                level=1,
                batch_id="batch_mapping_01",
            )
            session.add(kp)
            session.commit()

            snippet = MaterialSnippet(
                user_id=user_id,
                material_id=material_id,
                version_id=version_id,
                snippet_index=0,
                content="Round Robin scheduling with time slice quantum.",
                char_length=47,
                start_offset=0,
                end_offset=47,
            )
            session.add(snippet)
            session.commit()

            mapping = KnowledgePointSnippet(
                user_id=user_id,
                knowledge_point_id=kp.id,
                snippet_id=snippet.id,
            )
            session.add(mapping)
            session.commit()

            assert isinstance(mapping.id, uuid.UUID)
            assert mapping.user_id == user_id
            assert mapping.knowledge_point_id == kp.id
            assert mapping.snippet_id == snippet.id

            # Test bidirectional navigation
            session.expire_all()
            reloaded_kp = session.scalar(select(KnowledgePoint).where(KnowledgePoint.id == kp.id))
            assert reloaded_kp is not None
            assert len(reloaded_kp.snippet_mappings) == 1
            assert reloaded_kp.snippet_mappings[0].snippet.content == snippet.content

            # Test unique constraint on (knowledge_point_id, snippet_id)
            duplicate_mapping = KnowledgePointSnippet(
                user_id=user_id,
                knowledge_point_id=kp.id,
                snippet_id=snippet.id,
            )
            session.add(duplicate_mapping)
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()

    def test_cascade_deletion_on_snippet_or_kp(
        self,
        db_session: sessionmaker[Session],
        setup_material_and_version: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
    ) -> None:
        """Verify deleting a knowledge point cascades and removes its snippet mappings."""
        user_id, material_id, version_id = setup_material_and_version

        with db_session() as session:
            kp = KnowledgePoint(
                user_id=user_id,
                material_id=material_id,
                version_id=version_id,
                parent_id=None,
                name="Deadlock Detection",
                level=1,
                batch_id="batch_mapping_02",
            )
            snippet = MaterialSnippet(
                user_id=user_id,
                material_id=material_id,
                version_id=version_id,
                snippet_index=1,
                content="Resource allocation graph cycle detection.",
                char_length=42,
                start_offset=48,
                end_offset=90,
            )
            session.add_all([kp, snippet])
            session.commit()

            mapping = KnowledgePointSnippet(
                user_id=user_id,
                knowledge_point_id=kp.id,
                snippet_id=snippet.id,
            )
            session.add(mapping)
            session.commit()
            mapping_id = mapping.id

            # Delete knowledge point
            session.delete(kp)
            session.commit()

            assert (
                session.scalar(
                    select(KnowledgePointSnippet).where(KnowledgePointSnippet.id == mapping_id)
                )
                is None
            )


class TestKnowledgeDesensitizationAndTenant:
    """Test suite for privacy desensitization and tenant isolation."""

    def test_knowledge_repr_redaction(self) -> None:
        """Verify KnowledgePoint and KnowledgePointSnippet __repr__ does not leak descriptions."""
        kp_id = uuid.uuid4()
        user_id = uuid.uuid4()
        snippet_id = uuid.uuid4()
        confidential_desc = "TOP_SECRET_CONFIDENTIAL_KNOWLEDGE_DESCRIPTION_DO_NOT_PRINT"

        kp = KnowledgePoint(
            id=kp_id,
            user_id=user_id,
            material_id=uuid.uuid4(),
            version_id=uuid.uuid4(),
            parent_id=None,
            name="Confidential Algorithm",
            description=confidential_desc,
            level=2,
            batch_id="batch_repr_01",
            is_low_confidence=True,
        )

        mapping = KnowledgePointSnippet(
            id=uuid.uuid4(),
            user_id=user_id,
            knowledge_point_id=kp_id,
            snippet_id=snippet_id,
        )

        kp_repr = repr(kp)
        mapping_repr = repr(mapping)

        assert confidential_desc not in kp_repr, (
            "Redline violated: KnowledgePoint description leaked"
        )
        assert str(kp_id) in kp_repr
        assert str(user_id) in kp_repr
        assert "low_conf=True" in kp_repr

        assert str(kp_id) in mapping_repr
        assert str(snippet_id) in mapping_repr

    def test_tenant_foreign_key_definition(self) -> None:
        """Verify knowledge models properly inherit TenantModelMixin."""
        for model_cls in (KnowledgePoint, KnowledgePointSnippet):
            col = next(iter(model_cls.user_id.property.columns))
            fk = next(iter(col.foreign_keys))
            assert fk.target_fullname == "users.id"
            assert fk.ondelete == "CASCADE"
