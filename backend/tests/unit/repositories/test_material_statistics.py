"""学习足迹的真实 SQL 聚合回归，不依赖资料列表分页或课程分组。"""

import uuid
from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.base import Base
from app.models.knowledge import KnowledgePoint
from app.models.material import Material, MaterialFolder, MaterialStatus
from app.repositories.material import MaterialRepository


@pytest.fixture
def session() -> Generator[Session, None, None]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def create_material(
    session: Session,
    user_id: uuid.UUID,
    *,
    folder_id: uuid.UUID | None = None,
    status: MaterialStatus = MaterialStatus.READY,
    deleted: bool = False,
    knowledge_count: int = 1,
) -> Material:
    repo = MaterialRepository(session)
    material = repo.create_material(
        user_id=user_id,
        title="学习讲义",
        file_format="txt",
        file_size=1,
        status=status.value,
        folder_id=folder_id,
    )
    material.is_deleted = deleted
    version = repo.create_version(
        material_id=material.id,
        user_id=user_id,
        version_number=1,
        storage_key=f"{material.id}/v1.txt",
        content_hash=str(material.id),
    )
    material.current_version_id = version.id
    for index in range(knowledge_count):
        session.add(
            KnowledgePoint(
                user_id=user_id,
                material_id=material.id,
                version_id=version.id,
                name=f"考点 {index}",
                batch_id="statistics-test",
            )
        )
    session.flush()
    return material


def test_empty_statistics(session: Session) -> None:
    assert MaterialRepository(session).get_statistics(user_id=uuid.uuid4()) == (0, 0)


def test_course_materials_without_unclassified_and_without_join_multiplication(
    session: Session,
) -> None:
    user_id = uuid.uuid4()
    folder = MaterialFolder(user_id=user_id, name="课程")
    session.add(folder)
    session.flush()
    create_material(session, user_id, folder_id=folder.id, knowledge_count=3)
    create_material(session, user_id, folder_id=folder.id, knowledge_count=0)

    assert MaterialRepository(session).get_statistics(user_id=user_id) == (2, 3)


def test_unclassified_and_archived_course_materials_are_included(session: Session) -> None:
    user_id = uuid.uuid4()
    active = MaterialFolder(user_id=user_id, name="当前课程")
    archived = MaterialFolder(user_id=user_id, name="归档课程", archived_at=datetime.now(UTC))
    session.add_all([active, archived])
    session.flush()
    create_material(session, user_id, folder_id=active.id, knowledge_count=2)
    create_material(session, user_id, folder_id=archived.id, knowledge_count=3)
    create_material(session, user_id, knowledge_count=4)

    assert MaterialRepository(session).get_statistics(user_id=user_id) == (3, 9)


@pytest.mark.parametrize(
    "status", [status for status in MaterialStatus if status != MaterialStatus.READY]
)
def test_deleted_and_non_ready_materials_exclude_their_knowledge_points(
    session: Session,
    status: MaterialStatus,
) -> None:
    user_id = uuid.uuid4()
    create_material(session, user_id, knowledge_count=2)
    create_material(session, user_id, deleted=True, knowledge_count=3)
    create_material(session, user_id, status=status, knowledge_count=4)

    assert MaterialRepository(session).get_statistics(user_id=user_id) == (1, 2)


def test_material_and_knowledge_tenants_are_both_filtered(session: Session) -> None:
    user_id, other_user_id = uuid.uuid4(), uuid.uuid4()
    own = create_material(session, user_id, knowledge_count=2)
    other = create_material(session, other_user_id, knowledge_count=3)
    # 即使历史数据中的考点租户与资料租户不一致，两侧都必须检查。
    for material, point_user in [(own, other_user_id), (other, user_id)]:
        session.add(
            KnowledgePoint(
                user_id=point_user,
                material_id=material.id,
                version_id=material.current_version_id,
                name="错配考点",
                batch_id="mismatched-tenant",
            )
        )
    session.flush()

    repo = MaterialRepository(session)
    assert repo.get_statistics(user_id=user_id) == (1, 2)
    assert repo.get_statistics(user_id=other_user_id) == (1, 3)


def test_knowledge_points_count_entities_across_versions(session: Session) -> None:
    user_id = uuid.uuid4()
    material = create_material(session, user_id, knowledge_count=2)
    repo = MaterialRepository(session)
    current = repo.create_version(
        material_id=material.id,
        user_id=user_id,
        version_number=2,
        storage_key=f"{material.id}/v2.txt",
        content_hash="second-version",
    )
    material.current_version_id = current.id
    session.add(
        KnowledgePoint(
            user_id=user_id,
            material_id=material.id,
            version_id=current.id,
            name="新版本考点",
            batch_id="second-version",
        )
    )
    session.flush()

    assert repo.get_statistics(user_id=user_id) == (1, 3)


def test_statistics_are_not_limited_to_a_material_list_page(session: Session) -> None:
    user_id = uuid.uuid4()
    for _ in range(25):
        create_material(session, user_id)

    assert MaterialRepository(session).get_statistics(user_id=user_id) == (25, 25)
