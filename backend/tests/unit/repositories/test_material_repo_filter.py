"""单元测试补充：app/repositories/material.py 中 folder_id 聚合与状态过滤路径。

补测目标：覆盖 P1-4「个人页学习足迹统计口径漏算」修复路径与状态过滤未覆盖行。

P1-4 关键路径：
- `_apply_folder_filter(unclassified=True)` → `Material.folder_id IS NULL`
- `_apply_folder_filter(folder_id=<uuid>)` → `Material.folder_id == folder_id`
- `_visible_folder_condition()` → `folder_id IS NULL OR folder.archived_at IS NULL`

未覆盖行（实测 6/207）：
- L157: status 单值过滤（vs statuses 多状态聚合）
- L198: `_apply_folder_filter(unclassified=True)` 分支
- L200: `_apply_folder_filter(folder_id=<uuid>)` 分支
- L268: count_stmt 单值 status 过滤
- L306: `move_folder` 主路径
"""

import uuid
from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.base import Base
from app.models.material import (
    Material,
    MaterialFolder,
    MaterialStatus,
)
from app.repositories.material import MaterialRepository


@pytest.fixture
def session() -> Generator[Session, None, None]:
    """Provide isolated SQLite in-memory session for each test."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as sess:
        yield sess
    engine.dispose()


class _TestDataFactory:
    """Test data factory creating folders and materials with explicit relationship."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = MaterialRepository(session)

    def create_folder(
        self,
        user_id: uuid.UUID,
        name: str,
        archived: bool = False,
    ) -> MaterialFolder:
        folder = MaterialFolder(
            user_id=user_id,
            name=name,
            archived_at=datetime.now(UTC) if archived else None,
        )
        self.session.add(folder)
        self.session.flush()
        return folder

    def create_material(
        self,
        user_id: uuid.UUID,
        title: str,
        folder_id: uuid.UUID | None = None,
        status: str = MaterialStatus.READY.value,
    ) -> Material:
        mat = self.repo.create_material(
            user_id=user_id,
            title=title,
            file_format="pdf",
            file_size=1024,
            folder_id=folder_id,
            status=status,
        )
        self.session.commit()
        return mat


class TestApplyFolderFilter:
    """_apply_folder_filter three-branch coverage: unclassified / folder_id / default."""

    def test_unclassified_only_returns_materials_with_null_folder(self, session: Session) -> None:
        factory = _TestDataFactory(session)
        user_id = uuid.uuid4()

        folder = factory.create_folder(user_id=user_id, name="高等数学")
        mat_in_folder = factory.create_material(
            user_id=user_id, title="题库A.pdf", folder_id=folder.id
        )
        mat_unclassified = factory.create_material(
            user_id=user_id, title="未分类.pdf", folder_id=None
        )

        items, total = factory.repo.list_materials_by_user(user_id=user_id, unclassified=True)

        item_ids = {item.id for item in items}
        assert mat_unclassified.id in item_ids
        assert mat_in_folder.id not in item_ids
        assert total == 1
        assert mat_unclassified.folder_id is None

    def test_folder_id_filters_materials_to_specific_folder(self, session: Session) -> None:
        factory = _TestDataFactory(session)
        user_id = uuid.uuid4()

        folder_a = factory.create_folder(user_id=user_id, name="课程A")
        folder_b = factory.create_folder(user_id=user_id, name="课程B")
        mat_a = factory.create_material(user_id=user_id, title="A1.pdf", folder_id=folder_a.id)
        mat_b = factory.create_material(user_id=user_id, title="B1.pdf", folder_id=folder_b.id)
        mat_none = factory.create_material(user_id=user_id, title="None.pdf", folder_id=None)

        items = factory.repo.list_materials(user_id=user_id, folder_id=folder_a.id)

        item_ids = {item.id for item in items}
        assert item_ids == {mat_a.id}
        assert mat_b.id not in item_ids
        assert mat_none.id not in item_ids

    def test_archived_folder_materials_are_excluded_by_default(self, session: Session) -> None:
        factory = _TestDataFactory(session)
        user_id = uuid.uuid4()

        active_folder = factory.create_folder(user_id=user_id, name="活跃课程")
        archived_folder = factory.create_folder(user_id=user_id, name="归档课程", archived=True)
        mat_active = factory.create_material(
            user_id=user_id, title="活跃.pdf", folder_id=active_folder.id
        )
        mat_archived = factory.create_material(
            user_id=user_id, title="已归档.pdf", folder_id=archived_folder.id
        )

        items = factory.repo.list_materials(user_id=user_id)

        item_ids = {item.id for item in items}
        assert mat_active.id in item_ids
        assert mat_archived.id not in item_ids

    def test_archived_folder_excluded_via_exclude_archived_folder_flag(
        self, session: Session
    ) -> None:
        factory = _TestDataFactory(session)
        user_id = uuid.uuid4()

        archived_folder = factory.create_folder(user_id=user_id, name="归档课", archived=True)
        mat = factory.create_material(
            user_id=user_id, title="已归档.pdf", folder_id=archived_folder.id
        )

        assert (
            factory.repo.get_material_by_id(mat.id, user_id, exclude_archived_folder=True) is None
        )
        assert (
            factory.repo.get_material_by_id(mat.id, user_id, exclude_archived_folder=False)
            is not None
        )


class TestStatusAggregationFilter:
    """statuses multi-value aggregation vs status single-value filter paths."""

    def test_status_single_value_filter(self, session: Session) -> None:
        factory = _TestDataFactory(session)
        user_id = uuid.uuid4()

        mat_ready = factory.create_material(
            user_id=user_id, title="就绪.pdf", status=MaterialStatus.READY.value
        )
        mat_pending = factory.create_material(
            user_id=user_id, title="等待.pdf", status=MaterialStatus.PENDING.value
        )

        items = factory.repo.list_materials(user_id=user_id, status=MaterialStatus.READY.value)

        item_ids = {item.id for item in items}
        assert item_ids == {mat_ready.id}
        assert mat_pending.id not in item_ids

    def test_statuses_multi_status_aggregation(self, session: Session) -> None:
        factory = _TestDataFactory(session)
        user_id = uuid.uuid4()

        mat_ready = factory.create_material(
            user_id=user_id, title="就绪.pdf", status=MaterialStatus.READY.value
        )
        mat_pending = factory.create_material(
            user_id=user_id, title="等待.pdf", status=MaterialStatus.PENDING.value
        )
        mat_failed = factory.create_material(
            user_id=user_id, title="失败.pdf", status=MaterialStatus.FAILED.value
        )

        items, total = factory.repo.list_materials_by_user(
            user_id=user_id,
            statuses=[MaterialStatus.READY.value, MaterialStatus.PENDING.value],
        )

        item_ids = {item.id for item in items}
        assert mat_ready.id in item_ids
        assert mat_pending.id in item_ids
        assert mat_failed.id not in item_ids
        assert total == 2

    def test_statuses_takes_priority_over_single_status(self, session: Session) -> None:
        factory = _TestDataFactory(session)
        user_id = uuid.uuid4()

        mat_ready = factory.create_material(
            user_id=user_id, title="就绪.pdf", status=MaterialStatus.READY.value
        )
        mat_pending = factory.create_material(
            user_id=user_id, title="等待.pdf", status=MaterialStatus.PENDING.value
        )

        items = factory.repo.list_materials(
            user_id=user_id,
            status=MaterialStatus.READY.value,
            statuses=[MaterialStatus.READY.value, MaterialStatus.PENDING.value],
        )

        item_ids = {item.id for item in items}
        assert mat_ready.id in item_ids
        assert mat_pending.id in item_ids


class TestMoveFolder:
    """move_folder main path: relocate material between courses."""

    def test_move_material_into_folder(self, session: Session) -> None:
        factory = _TestDataFactory(session)
        user_id = uuid.uuid4()

        folder = factory.create_folder(user_id=user_id, name="目标课程")
        mat = factory.create_material(user_id=user_id, title="待移动.pdf", folder_id=None)

        result = factory.repo.move_folder(mat.id, user_id, folder.id)
        assert result is not None
        assert result.folder_id == folder.id

        fetched = factory.repo.get_material_by_id(mat.id, user_id)
        assert fetched is not None
        assert fetched.folder_id == folder.id

    def test_move_material_back_to_unclassified(self, session: Session) -> None:
        factory = _TestDataFactory(session)
        user_id = uuid.uuid4()

        folder = factory.create_folder(user_id=user_id, name="源课程")
        mat = factory.create_material(user_id=user_id, title="已归属.pdf", folder_id=folder.id)

        result = factory.repo.move_folder(mat.id, user_id, None)
        assert result is not None
        assert result.folder_id is None

    def test_move_folder_returns_none_when_material_missing(self, session: Session) -> None:
        repo = MaterialRepository(session)
        user_id = uuid.uuid4()

        result = repo.move_folder(material_id=uuid.uuid4(), user_id=user_id, folder_id=None)
        assert result is None

    def test_move_folder_returns_none_for_other_user_material(self, session: Session) -> None:
        factory = _TestDataFactory(session)
        user_a = uuid.uuid4()
        user_b = uuid.uuid4()

        mat = factory.create_material(user_id=user_a, title="A的资料.pdf")
        folder = factory.create_folder(user_id=user_b, name="B的课程")

        result = factory.repo.move_folder(mat.id, user_b, folder.id)
        assert result is None

        fetched = factory.repo.get_material_by_id(mat.id, user_a)
        assert fetched is not None
        assert fetched.folder_id is None


class TestP1BugRegression:
    """P1-4 regression: unclassified aggregate must match by NULL predicate exactly."""

    def test_p1_4_regression_unclassified_aggregate_must_not_miss_null_folder(
        self, session: Session
    ) -> None:
        factory = _TestDataFactory(session)
        user_id = uuid.uuid4()

        folder = factory.create_folder(user_id=user_id, name="高数")
        unclassified_mats = [
            factory.create_material(user_id=user_id, title=f"未分类{i}.pdf", folder_id=None)
            for i in range(6)
        ]
        classified_mats = [
            factory.create_material(user_id=user_id, title=f"已归属{i}.pdf", folder_id=folder.id)
            for i in range(4)
        ]

        items, total = factory.repo.list_materials_by_user(user_id=user_id, unclassified=True)

        item_ids = {item.id for item in items}
        assert len(items) == 6
        assert all(m.id in item_ids for m in unclassified_mats)
        assert all(m.id not in item_ids for m in classified_mats)
        assert total == 6

    def test_p1_4_regression_total_includes_all_user_materials(self, session: Session) -> None:
        factory = _TestDataFactory(session)
        user_id = uuid.uuid4()

        folder = factory.create_folder(user_id=user_id, name="课程X")

        for i in range(3):
            factory.create_material(user_id=user_id, title=f"未分类{i}.pdf", folder_id=None)
        for i in range(2):
            factory.create_material(user_id=user_id, title=f"已归属{i}.pdf", folder_id=folder.id)

        items, total = factory.repo.list_materials_by_user(user_id=user_id)

        assert total == 5
        assert len(items) == 5


class TestSingleStatusCounting:
    """list_materials_by_user single-status count_stmt path (L268)."""

    def test_single_status_count_total_matches_filtered_items(self, session: Session) -> None:
        factory = _TestDataFactory(session)
        user_id = uuid.uuid4()

        for i in range(3):
            factory.create_material(
                user_id=user_id, title=f"就绪{i}.pdf", status=MaterialStatus.READY.value
            )
        for i in range(2):
            factory.create_material(
                user_id=user_id, title=f"等待{i}.pdf", status=MaterialStatus.PENDING.value
            )

        items, total = factory.repo.list_materials_by_user(
            user_id=user_id, status=MaterialStatus.READY.value
        )

        assert total == 3
        assert len(items) == 3
        assert all(item.status == MaterialStatus.READY.value for item in items)

    def test_single_status_with_unclassified_combined(self, session: Session) -> None:
        factory = _TestDataFactory(session)
        user_id = uuid.uuid4()

        folder = factory.create_folder(user_id=user_id, name="课程")

        for i in range(2):
            factory.create_material(
                user_id=user_id,
                title=f"就绪未分类{i}.pdf",
                folder_id=None,
                status=MaterialStatus.READY.value,
            )
        factory.create_material(
            user_id=user_id,
            title="就绪已归属.pdf",
            folder_id=folder.id,
            status=MaterialStatus.READY.value,
        )
        factory.create_material(
            user_id=user_id,
            title="等待未分类.pdf",
            folder_id=None,
            status=MaterialStatus.PENDING.value,
        )

        items, total = factory.repo.list_materials_by_user(
            user_id=user_id,
            status=MaterialStatus.READY.value,
            unclassified=True,
        )

        assert total == 2
        assert len(items) == 2
        assert all(item.folder_id is None for item in items)
        assert all(item.status == MaterialStatus.READY.value for item in items)


class TestListSnippetsByIds:
    """list_snippets_by_ids empty-collection early return (L721)."""

    def test_list_snippets_by_ids_with_empty_collection_returns_empty(
        self, session: Session
    ) -> None:
        """传入空 snippet_ids 集合时：list_snippets_by_ids 必须立刻返回空列表（L721 早返回）。"""
        factory = _TestDataFactory(session)
        user_id = uuid.uuid4()

        result = factory.repo.list_snippets_by_ids(snippet_ids=[], user_id=user_id)
        assert result == []

    def test_list_snippets_by_ids_with_empty_tuple_returns_empty(self, session: Session) -> None:
        """空 tuple 输入同样走早返回路径。"""
        factory = _TestDataFactory(session)
        user_id = uuid.uuid4()

        result = factory.repo.list_snippets_by_ids(snippet_ids=(), user_id=user_id)
        assert result == []
