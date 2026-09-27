"""Unit tests for KnowledgeRepository in app/repositories/knowledge.py.

Verifies:
1. KnowledgePoint CRUD operations: create, batch create, read by id, list by material,
   list by user, get by version (ordered by level), update, soft delete by material,
   delete by id, and delete by version.
2. Dual traceability mappings: create mappings, get snippets for point, get points for snippet.
3. Strict multi-tenant isolation (Anti-horizontal privilege escalation) preventing
   any cross-user data leakage, modification, or deletion.
"""

import uuid
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.base import Base
from app.models.knowledge import KnowledgePoint, KnowledgePointSnippet
from app.models.material import Material, MaterialSnippet, MaterialVersion
from app.repositories.knowledge import KnowledgeRepository


@pytest.fixture
def session() -> Generator[Session, None, None]:
    """Provides an isolated in-memory SQLite database session."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as sess:
        yield sess
    engine.dispose()


@pytest.fixture
def helper_setup(session: Session) -> dict[str, uuid.UUID]:
    """Sets up a material and version for relationship testing."""
    user_id = uuid.uuid4()
    material_id = uuid.uuid4()
    version_id = uuid.uuid4()

    material = Material(
        id=material_id,
        user_id=user_id,
        title="测试教材.pdf",
        file_format="pdf",
        file_size=1024,
    )
    session.add(material)

    version = MaterialVersion(
        id=version_id,
        user_id=user_id,
        material_id=material_id,
        version_number=1,
        storage_key="materials/v1.pdf",
        content_hash="abc123hash",
    )
    session.add(version)
    session.commit()

    return {
        "user_id": user_id,
        "material_id": material_id,
        "version_id": version_id,
    }


class TestKnowledgeRepositoryCRUD:
    """Test suite for KnowledgeRepository CRUD operations."""

    def test_create_and_get_knowledge_point(
        self, session: Session, helper_setup: dict[str, uuid.UUID]
    ) -> None:
        """Verify creating and retrieving a single knowledge point."""
        repo = KnowledgeRepository(session)
        user_id = helper_setup["user_id"]
        material_id = helper_setup["material_id"]
        version_id = helper_setup["version_id"]

        point = repo.create_knowledge_point(
            user_id=user_id,
            material_id=material_id,
            version_id=version_id,
            name="极限的定义",
            description="微积分极限基本概念与数学定义",
            level=1,
            batch_id="batch_001",
            is_low_confidence=False,
        )
        session.commit()

        assert point.id is not None
        assert point.user_id == user_id
        assert point.name == "极限的定义"
        assert point.level == 1
        assert point.is_low_confidence is False

        # Query using get_by_id and get_knowledge_point_by_id
        fetched = repo.get_by_id(point.id, user_id)
        assert fetched is not None
        assert fetched.id == point.id
        assert fetched.name == "极限的定义"

        fetched_alias = repo.get_knowledge_point_by_id(point.id, user_id)
        assert fetched_alias is not None
        assert fetched_alias.id == point.id

    def test_batch_create_knowledge_points(
        self, session: Session, helper_setup: dict[str, uuid.UUID]
    ) -> None:
        """Verify batch creation of knowledge points via models and dicts."""
        repo = KnowledgeRepository(session)
        user_id = helper_setup["user_id"]
        material_id = helper_setup["material_id"]
        version_id = helper_setup["version_id"]

        root = KnowledgePoint(
            user_id=user_id,
            material_id=material_id,
            version_id=version_id,
            name="函数与极限",
            level=1,
            batch_id="b1",
        )
        child_dict = {
            "material_id": material_id,
            "version_id": version_id,
            "name": "数列极限",
            "level": 2,
            "batch_id": "b1",
        }

        created = repo.batch_create_knowledge_points([root, child_dict], user_id)
        session.commit()

        assert len(created) == 2
        assert created[0].name == "函数与极限"
        assert created[1].name == "数列极限"
        assert created[1].user_id == user_id

        # Also test create_knowledge_points alias
        alias_points = [
            KnowledgePoint(
                user_id=user_id,
                material_id=material_id,
                version_id=version_id,
                name="函数的连续性",
                level=2,
                batch_id="b1",
            )
        ]
        created_alias = repo.create_knowledge_points(alias_points, user_id)
        session.commit()
        assert len(created_alias) == 1

    def test_list_and_get_by_version(
        self, session: Session, helper_setup: dict[str, uuid.UUID]
    ) -> None:
        """Verify listing knowledge points by material, user, and version."""
        repo = KnowledgeRepository(session)
        user_id = helper_setup["user_id"]
        material_id = helper_setup["material_id"]
        version_id = helper_setup["version_id"]

        # Insert points at level 2 then level 1
        p2 = repo.create_knowledge_point(
            user_id=user_id,
            material_id=material_id,
            version_id=version_id,
            name="导数的几何意义",
            level=2,
            batch_id="b1",
        )
        p1 = repo.create_knowledge_point(
            user_id=user_id,
            material_id=material_id,
            version_id=version_id,
            name="导数与微分",
            level=1,
            batch_id="b1",
        )
        session.commit()

        by_mat = repo.list_by_material_id(material_id, user_id)
        assert len(by_mat) == 2
        assert by_mat[0].level == 1
        assert by_mat[1].level == 2

        by_ver = repo.get_knowledge_points_by_version(material_id, version_id, user_id)
        assert len(by_ver) == 2
        assert by_ver[0].id == p1.id
        assert by_ver[1].id == p2.id

        by_usr = repo.list_by_user_id(user_id, limit=10)
        assert len(by_usr) == 2

    def test_list_all_by_user_id_aggregates_across_materials(
        self, session: Session, helper_setup: dict[str, uuid.UUID]
    ) -> None:
        """Verify list_all_by_user_id aggregates every user point across materials (DIAG-007)."""
        repo = KnowledgeRepository(session)
        user_id = helper_setup["user_id"]
        material_id = helper_setup["material_id"]
        version_id = helper_setup["version_id"]

        # Second material owned by the same user
        material_b = Material(
            id=uuid.uuid4(),
            user_id=user_id,
            title="第二教材.pdf",
            file_format="pdf",
            file_size=512,
        )
        version_b = MaterialVersion(
            id=uuid.uuid4(),
            user_id=user_id,
            material_id=material_b.id,
            version_number=1,
            storage_key="materials/b.pdf",
            content_hash="hash-b",
        )
        session.add_all([material_b, version_b])

        # Material owned by a different tenant (must never leak)
        other_user_id = uuid.uuid4()
        other_material = Material(
            id=uuid.uuid4(),
            user_id=other_user_id,
            title="他人教材.pdf",
            file_format="pdf",
            file_size=1,
        )
        other_version = MaterialVersion(
            id=uuid.uuid4(),
            user_id=other_user_id,
            material_id=other_material.id,
            version_number=1,
            storage_key="materials/o.pdf",
            content_hash="hash-o",
        )
        session.add_all([other_material, other_version])
        session.commit()

        repo.create_knowledge_point(
            user_id=user_id,
            material_id=material_id,
            version_id=version_id,
            name="A-1",
            level=2,
            batch_id="b",
        )
        repo.create_knowledge_point(
            user_id=user_id,
            material_id=material_id,
            version_id=version_id,
            name="A-2",
            level=1,
            batch_id="b",
        )
        repo.create_knowledge_point(
            user_id=user_id,
            material_id=material_b.id,
            version_id=version_b.id,
            name="B-1",
            level=1,
            batch_id="b",
        )
        repo.create_knowledge_point(
            user_id=other_user_id,
            material_id=other_material.id,
            version_id=other_version.id,
            name="OTHER",
            level=1,
            batch_id="b",
        )
        session.commit()

        points = repo.list_all_by_user_id(user_id)

        assert len(points) == 3
        assert {point.name for point in points} == {"A-1", "A-2", "B-1"}
        # Ordered by level asc, then created_at asc
        assert points[0].level == 1
        assert points[-1].level == 2

    def test_update_knowledge_point(
        self, session: Session, helper_setup: dict[str, uuid.UUID]
    ) -> None:
        """Verify updating attributes of a knowledge point."""
        repo = KnowledgeRepository(session)
        user_id = helper_setup["user_id"]
        material_id = helper_setup["material_id"]
        version_id = helper_setup["version_id"]

        point = repo.create_knowledge_point(
            user_id=user_id,
            material_id=material_id,
            version_id=version_id,
            name="原始名称",
            description="原始描述",
            level=1,
            batch_id="b1",
        )
        session.commit()

        updated = repo.update_knowledge_point(
            point.id,
            user_id,
            name="更新名称",
            description="更新描述",
            is_low_confidence=True,
        )
        session.commit()

        assert updated is not None
        assert updated.name == "更新名称"
        assert updated.description == "更新描述"
        assert updated.is_low_confidence is True

    def test_delete_operations(self, session: Session, helper_setup: dict[str, uuid.UUID]) -> None:
        """Verify delete_by_id, delete by version, and soft_delete_by_material_id."""
        repo = KnowledgeRepository(session)
        user_id = helper_setup["user_id"]
        material_id = helper_setup["material_id"]
        version_id = helper_setup["version_id"]

        p1 = repo.create_knowledge_point(
            user_id=user_id,
            material_id=material_id,
            version_id=version_id,
            name="待删除点1",
            level=1,
            batch_id="b1",
        )
        p2 = repo.create_knowledge_point(
            user_id=user_id,
            material_id=material_id,
            version_id=version_id,
            name="待删除点2",
            level=1,
            batch_id="b1",
        )
        session.commit()

        p1_id = p1.id
        p2_id = p2.id

        # Delete single point
        assert repo.delete_by_id(p1_id, user_id) is True
        assert repo.get_by_id(p1_id, user_id) is None
        assert repo.delete_by_id(p1_id, user_id) is False

        # Delete by version
        deleted_count = repo.delete_knowledge_points_by_version(material_id, version_id, user_id)
        assert deleted_count == 1
        assert repo.get_by_id(p2_id, user_id) is None

        # Re-create and test soft_delete_by_material_id
        p3 = repo.create_knowledge_point(
            user_id=user_id,
            material_id=material_id,
            version_id=version_id,
            name="待删除点3",
            level=1,
            batch_id="b1",
        )
        session.commit()
        p3_id = p3.id
        soft_deleted = repo.soft_delete_by_material_id(material_id, user_id)
        assert soft_deleted == 1
        assert repo.get_by_id(p3_id, user_id) is None


class TestKnowledgeRepositoryTraceability:
    """Test suite for dual-traceability between KnowledgePoint and MaterialSnippet."""

    def test_snippet_and_point_bidirectional_query(
        self, session: Session, helper_setup: dict[str, uuid.UUID]
    ) -> None:
        """Verify querying snippets by point and points by snippet."""
        repo = KnowledgeRepository(session)
        user_id = helper_setup["user_id"]
        material_id = helper_setup["material_id"]
        version_id = helper_setup["version_id"]

        # Create snippets
        s1 = MaterialSnippet(
            id=uuid.uuid4(),
            user_id=user_id,
            material_id=material_id,
            version_id=version_id,
            snippet_index=0,
            content="切片1内容",
            char_length=6,
            start_offset=0,
            end_offset=6,
        )
        s2 = MaterialSnippet(
            id=uuid.uuid4(),
            user_id=user_id,
            material_id=material_id,
            version_id=version_id,
            snippet_index=1,
            content="切片2内容",
            char_length=6,
            start_offset=7,
            end_offset=13,
        )
        session.add_all([s1, s2])

        # Create knowledge point
        kp = repo.create_knowledge_point(
            user_id=user_id,
            material_id=material_id,
            version_id=version_id,
            name="核心概念",
            level=1,
            batch_id="b1",
        )
        session.commit()

        # Create relations
        relations = [
            {"knowledge_point_id": kp.id, "snippet_id": s1.id},
            KnowledgePointSnippet(knowledge_point_id=kp.id, snippet_id=s2.id, user_id=user_id),
        ]
        repo.create_material_relations(relations, user_id)
        session.commit()

        # Test alias create_knowledge_point_snippets
        repo.create_knowledge_point_snippets([], user_id)
        session.commit()

        # Query snippets for point
        snippets = repo.get_snippets_for_point(kp.id, user_id)
        assert len(snippets) == 2
        assert snippets[0].id == s1.id
        assert snippets[1].id == s2.id

        # Alias query
        alias_snippets = repo.get_snippets_by_knowledge_point(kp.id, user_id)
        assert len(alias_snippets) == 2

        # Query points for snippet
        points_for_s1 = repo.get_points_for_snippet(s1.id, user_id)
        assert len(points_for_s1) == 1
        assert points_for_s1[0].id == kp.id

        alias_points_for_s2 = repo.get_knowledge_points_by_snippet(s2.id, user_id)
        assert len(alias_points_for_s2) == 1
        assert alias_points_for_s2[0].id == kp.id


class TestKnowledgeRepositoryMultiTenantIsolation:
    """Test suite ensuring strict cross-user tenant isolation."""

    def test_tenant_isolation_on_all_methods(
        self, session: Session, helper_setup: dict[str, uuid.UUID]
    ) -> None:
        """Verify that another user cannot access, modify, or delete tenant data."""
        repo = KnowledgeRepository(session)
        owner_id = helper_setup["user_id"]
        attacker_id = uuid.uuid4()
        material_id = helper_setup["material_id"]
        version_id = helper_setup["version_id"]

        # Owner creates point
        point = repo.create_knowledge_point(
            user_id=owner_id,
            material_id=material_id,
            version_id=version_id,
            name="私有考点",
            level=1,
            batch_id="b1",
        )
        snippet = MaterialSnippet(
            id=uuid.uuid4(),
            user_id=owner_id,
            material_id=material_id,
            version_id=version_id,
            snippet_index=0,
            content="私有切片内容",
            char_length=7,
            start_offset=0,
            end_offset=7,
        )
        session.add(snippet)
        session.commit()

        repo.create_material_relations(
            [{"knowledge_point_id": point.id, "snippet_id": snippet.id}], owner_id
        )
        session.commit()

        # Attacker cannot get_by_id
        assert repo.get_by_id(point.id, attacker_id) is None
        assert repo.get_knowledge_point_by_id(point.id, attacker_id) is None

        # Attacker cannot list
        assert repo.list_by_material_id(material_id, attacker_id) == []
        assert repo.list_by_user_id(attacker_id) == []
        assert repo.get_knowledge_points_by_version(material_id, version_id, attacker_id) == []

        # Attacker cannot update
        assert repo.update_knowledge_point(point.id, attacker_id, name="越权篡改") is None
        refreshed = repo.get_by_id(point.id, owner_id)
        assert refreshed is not None
        assert refreshed.name == "私有考点"

        # Attacker cannot query relations
        assert repo.get_snippets_for_point(point.id, attacker_id) == []
        assert repo.get_snippets_by_knowledge_point(point.id, attacker_id) == []
        assert repo.get_points_for_snippet(snippet.id, attacker_id) == []
        assert repo.get_knowledge_points_by_snippet(snippet.id, attacker_id) == []

        # Attacker cannot delete
        assert repo.delete_by_id(point.id, attacker_id) is False
        assert repo.delete_knowledge_points_by_version(material_id, version_id, attacker_id) == 0
        assert repo.soft_delete_by_material_id(material_id, attacker_id) == 0

        # Point still exists for owner
        assert repo.get_by_id(point.id, owner_id) is not None
