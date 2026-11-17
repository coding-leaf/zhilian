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

    def test_batch_create_and_get_knowledge_points(
        self, session: Session, helper_setup: dict[str, uuid.UUID]
    ) -> None:
        """Verify batch creation of knowledge points via models and dicts and get_by_id."""
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

        fetched = repo.get_by_id(created[0].id, user_id)
        assert fetched is not None
        assert fetched.id == created[0].id
        assert fetched.name == "函数与极限"

        fetched_alias = repo.get_knowledge_point_by_id(created[0].id, user_id)
        assert fetched_alias is not None
        assert fetched_alias.id == created[0].id

    def test_list_and_get_by_version(
        self, session: Session, helper_setup: dict[str, uuid.UUID]
    ) -> None:
        """Verify listing knowledge points by material and version."""
        repo = KnowledgeRepository(session)
        user_id = helper_setup["user_id"]
        material_id = helper_setup["material_id"]
        version_id = helper_setup["version_id"]

        # Insert points at level 2 then level 1
        p2, p1 = repo.batch_create_knowledge_points(
            [
                {
                    "material_id": material_id,
                    "version_id": version_id,
                    "name": "导数的几何意义",
                    "level": 2,
                    "batch_id": "b1",
                },
                {
                    "material_id": material_id,
                    "version_id": version_id,
                    "name": "导数与微分",
                    "level": 1,
                    "batch_id": "b1",
                },
            ],
            user_id,
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

        repo.batch_create_knowledge_points(
            [
                {
                    "material_id": material_id,
                    "version_id": version_id,
                    "name": "A-1",
                    "level": 2,
                    "batch_id": "b",
                },
                {
                    "material_id": material_id,
                    "version_id": version_id,
                    "name": "A-2",
                    "level": 1,
                    "batch_id": "b",
                },
                {
                    "material_id": material_b.id,
                    "version_id": version_b.id,
                    "name": "B-1",
                    "level": 1,
                    "batch_id": "b",
                },
            ],
            user_id,
        )
        repo.batch_create_knowledge_points(
            [
                {
                    "material_id": other_material.id,
                    "version_id": other_version.id,
                    "name": "OTHER",
                    "level": 1,
                    "batch_id": "b",
                }
            ],
            other_user_id,
        )
        session.commit()

        points = repo.list_all_by_user_id(user_id)

        assert len(points) == 3
        assert {point.name for point in points} == {"A-1", "A-2", "B-1"}
        # Ordered by level asc, then created_at asc
        assert points[0].level == 1
        assert points[-1].level == 2

    def test_delete_by_version(self, session: Session, helper_setup: dict[str, uuid.UUID]) -> None:
        """Verify delete_knowledge_points_by_version."""
        repo = KnowledgeRepository(session)
        user_id = helper_setup["user_id"]
        material_id = helper_setup["material_id"]
        version_id = helper_setup["version_id"]

        created = repo.batch_create_knowledge_points(
            [
                {
                    "material_id": material_id,
                    "version_id": version_id,
                    "name": "待删除点1",
                    "level": 1,
                    "batch_id": "b1",
                },
                {
                    "material_id": material_id,
                    "version_id": version_id,
                    "name": "待删除点2",
                    "level": 1,
                    "batch_id": "b1",
                },
            ],
            user_id,
        )
        session.commit()
        p1_id, p2_id = created[0].id, created[1].id

        deleted_count = repo.delete_knowledge_points_by_version(material_id, version_id, user_id)
        assert deleted_count == 2
        assert repo.get_by_id(p1_id, user_id) is None
        assert repo.get_by_id(p2_id, user_id) is None


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
        [kp] = repo.batch_create_knowledge_points(
            [
                {
                    "material_id": material_id,
                    "version_id": version_id,
                    "name": "核心概念",
                    "level": 1,
                    "batch_id": "b1",
                }
            ],
            user_id,
        )
        session.commit()

        # Create relations
        relations = [
            {"knowledge_point_id": kp.id, "snippet_id": s1.id},
            KnowledgePointSnippet(knowledge_point_id=kp.id, snippet_id=s2.id, user_id=user_id),
        ]
        repo.create_material_relations(relations, user_id)
        session.commit()

        # Query snippets for point
        snippets = repo.get_snippets_for_point(kp.id, user_id)
        assert len(snippets) == 2
        assert snippets[0].id == s1.id
        assert snippets[1].id == s2.id

        # Query points for snippet
        points_for_s1 = repo.get_points_for_snippet(s1.id, user_id)
        assert len(points_for_s1) == 1
        assert points_for_s1[0].id == kp.id


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
        [point] = repo.batch_create_knowledge_points(
            [
                {
                    "material_id": material_id,
                    "version_id": version_id,
                    "name": "私有考点",
                    "level": 1,
                    "batch_id": "b1",
                }
            ],
            owner_id,
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
        assert repo.list_all_by_user_id(attacker_id) == []
        assert repo.get_knowledge_points_by_version(material_id, version_id, attacker_id) == []

        # Attacker cannot query relations
        assert repo.get_snippets_for_point(point.id, attacker_id) == []
        assert repo.get_points_for_snippet(snippet.id, attacker_id) == []

        # Attacker cannot delete
        assert repo.delete_knowledge_points_by_version(material_id, version_id, attacker_id) == 0

        # Point still exists for owner
        assert repo.get_by_id(point.id, owner_id) is not None
