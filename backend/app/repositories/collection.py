"""自定义题单与收纳条目数据仓储模块。

全仓储方法强制要求 user_id 参数并下推 SQL 过滤，严格阻断横向越权；
批量计数与关联标题查询采用单次聚合，杜绝 N+1 查询。
"""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.models.collection import QuestionCollection, QuestionCollectionItem
from app.models.knowledge import KnowledgePoint
from app.models.material import Material, MaterialFolder
from app.models.question import Question


class CollectionRepository:
    """自定义题单领域数据仓储。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create_collection(
        self,
        *,
        user_id: uuid.UUID,
        name: str,
        description: str = "",
        folder_id: uuid.UUID | None = None,
        color_token: str | None = None,
        is_pinned: bool = False,
        sort_order: int = 0,
    ) -> QuestionCollection:
        """创建自定义题单并 flush 刷新主键。"""
        collection = QuestionCollection(
            user_id=user_id,
            name=name,
            description=description,
            folder_id=folder_id,
            color_token=color_token,
            is_pinned=is_pinned,
            sort_order=sort_order,
        )
        self.session.add(collection)
        self.session.flush()
        return collection

    def get_collection_by_id(
        self,
        collection_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> QuestionCollection | None:
        """按主键与租户用户查询单个题单。"""
        stmt = select(QuestionCollection).where(
            QuestionCollection.id == collection_id,
            QuestionCollection.user_id == user_id,
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def name_exists(
        self,
        user_id: uuid.UUID,
        name: str,
        *,
        exclude_collection_id: uuid.UUID | None = None,
    ) -> bool:
        """检查当前用户下题单名称是否已存在。"""
        stmt = select(QuestionCollection.id).where(
            QuestionCollection.user_id == user_id,
            QuestionCollection.name == name,
        )
        if exclude_collection_id is not None:
            stmt = stmt.where(QuestionCollection.id != exclude_collection_id)
        return self.session.execute(stmt.limit(1)).scalar_one_or_none() is not None

    def list_collections(
        self,
        user_id: uuid.UUID,
        *,
        folder_id: uuid.UUID | None = None,
        unclassified: bool = False,
    ) -> list[QuestionCollection]:
        """按课程过滤并排序查询当前用户全部题单。"""
        stmt = select(QuestionCollection).where(QuestionCollection.user_id == user_id)
        if folder_id is not None:
            stmt = stmt.where(QuestionCollection.folder_id == folder_id)
        elif unclassified:
            stmt = stmt.where(QuestionCollection.folder_id.is_(None))
        stmt = stmt.order_by(
            QuestionCollection.is_pinned.desc(),
            QuestionCollection.sort_order.asc(),
            QuestionCollection.updated_at.desc(),
        )
        return list(self.session.execute(stmt).scalars().all())

    def count_active_questions_by_collection_ids(
        self,
        user_id: uuid.UUID,
        collection_ids: Sequence[uuid.UUID],
    ) -> dict[uuid.UUID, int]:
        """单次 GROUP BY 批量统计多个题单内的活跃题目数（排除软删除题目）。"""
        if not collection_ids:
            return {}
        stmt = (
            select(
                QuestionCollectionItem.collection_id,
                func.count(QuestionCollectionItem.id),
            )
            .join(Question, QuestionCollectionItem.question_id == Question.id)
            .where(
                QuestionCollectionItem.user_id == user_id,
                QuestionCollectionItem.collection_id.in_(list(collection_ids)),
                Question.user_id == user_id,
                Question.is_deleted.is_(False),
            )
            .group_by(QuestionCollectionItem.collection_id)
        )
        rows = self.session.execute(stmt).all()
        return {collection_id: int(count) for collection_id, count in rows}

    def get_folder_names_by_ids(
        self,
        user_id: uuid.UUID,
        folder_ids: Sequence[uuid.UUID],
    ) -> dict[uuid.UUID, str]:
        """批量查询课程文件夹名称，避免 N+1。"""
        if not folder_ids:
            return {}
        stmt = select(MaterialFolder.id, MaterialFolder.name).where(
            MaterialFolder.user_id == user_id,
            MaterialFolder.id.in_(list(folder_ids)),
        )
        rows = self.session.execute(stmt).all()
        return {folder_id: name for folder_id, name in rows}

    def delete_collection(self, collection: QuestionCollection) -> None:
        """删除题单实体（仅级联删除关联条目，绝不删原题）。"""
        self.session.delete(collection)
        self.session.flush()

    def list_collection_questions(
        self,
        user_id: uuid.UUID,
        collection_id: uuid.UUID,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[tuple[QuestionCollectionItem, Question, str | None, str | None]], int]:
        """分页查询题单内活跃题目及其知识点/讲义名称。"""
        base_filters = (
            QuestionCollectionItem.user_id == user_id,
            QuestionCollectionItem.collection_id == collection_id,
            Question.user_id == user_id,
            Question.is_deleted.is_(False),
        )
        total_stmt = (
            select(func.count(QuestionCollectionItem.id))
            .select_from(QuestionCollectionItem)
            .join(Question, QuestionCollectionItem.question_id == Question.id)
            .where(*base_filters)
        )
        total = int(self.session.execute(total_stmt).scalar_one())

        offset = max(page - 1, 0) * page_size
        stmt = (
            select(
                QuestionCollectionItem,
                Question,
                KnowledgePoint.name,
                Material.title,
            )
            .join(Question, QuestionCollectionItem.question_id == Question.id)
            .outerjoin(
                KnowledgePoint,
                (KnowledgePoint.id == Question.knowledge_point_id)
                & (KnowledgePoint.user_id == user_id),
            )
            .outerjoin(
                Material,
                (Material.id == Question.material_id) & (Material.user_id == user_id),
            )
            .where(*base_filters)
            .order_by(
                QuestionCollectionItem.sort_order.asc(),
                QuestionCollectionItem.created_at.desc(),
            )
            .offset(offset)
            .limit(page_size)
        )
        rows = self.session.execute(stmt).all()
        return [(row[0], row[1], row[2], row[3]) for row in rows], total

    def list_active_question_ids(
        self,
        collection_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        limit: int = 50,
    ) -> list[uuid.UUID]:
        """查询题单内前 ``limit`` 道未软删除题目主键（供整单开练使用）。"""
        stmt = (
            select(Question.id)
            .join(QuestionCollectionItem, QuestionCollectionItem.question_id == Question.id)
            .where(
                QuestionCollectionItem.user_id == user_id,
                QuestionCollectionItem.collection_id == collection_id,
                Question.user_id == user_id,
                Question.is_deleted.is_(False),
            )
            .order_by(
                QuestionCollectionItem.sort_order.asc(),
                QuestionCollectionItem.created_at.desc(),
            )
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars().all())

    def list_valid_user_question_ids(
        self,
        user_id: uuid.UUID,
        question_ids: Sequence[uuid.UUID],
    ) -> set[uuid.UUID]:
        """校验题目归属当前用户且未软删除。"""
        if not question_ids:
            return set()
        stmt = select(Question.id).where(
            Question.user_id == user_id,
            Question.is_deleted.is_(False),
            Question.id.in_(list(question_ids)),
        )
        return set(self.session.execute(stmt).scalars().all())

    def list_existing_question_ids(
        self,
        collection_id: uuid.UUID,
        user_id: uuid.UUID,
        question_ids: Sequence[uuid.UUID],
    ) -> set[uuid.UUID]:
        """查询题单内已收纳的题目主键集合。"""
        if not question_ids:
            return set()
        stmt = select(QuestionCollectionItem.question_id).where(
            QuestionCollectionItem.user_id == user_id,
            QuestionCollectionItem.collection_id == collection_id,
            QuestionCollectionItem.question_id.in_(list(question_ids)),
        )
        return set(self.session.execute(stmt).scalars().all())

    def add_items(
        self,
        *,
        user_id: uuid.UUID,
        collection_id: uuid.UUID,
        question_ids: Sequence[uuid.UUID],
        note: str | None = None,
    ) -> list[QuestionCollectionItem]:
        """批量新增题单收纳关联条目。"""
        created: list[QuestionCollectionItem] = []
        for qid in question_ids:
            item = QuestionCollectionItem(
                user_id=user_id,
                collection_id=collection_id,
                question_id=qid,
                note=note,
            )
            self.session.add(item)
            created.append(item)
        if created:
            self.session.flush()
        return created

    def remove_item(
        self,
        user_id: uuid.UUID,
        collection_id: uuid.UUID,
        question_id: uuid.UUID,
    ) -> bool:
        """从题单中移出指定题目关联（不删原题）。"""
        stmt = delete(QuestionCollectionItem).where(
            QuestionCollectionItem.user_id == user_id,
            QuestionCollectionItem.collection_id == collection_id,
            QuestionCollectionItem.question_id == question_id,
        )
        result = self.session.execute(stmt)
        self.session.flush()
        count = result.rowcount if isinstance(result, CursorResult) else 0
        return count > 0

    def list_collection_ids_for_question(
        self,
        user_id: uuid.UUID,
        question_id: uuid.UUID,
    ) -> list[uuid.UUID]:
        """查询单题当前归属的所有用户题单主键列表。"""
        stmt = (
            select(QuestionCollectionItem.collection_id)
            .join(
                QuestionCollection,
                QuestionCollection.id == QuestionCollectionItem.collection_id,
            )
            .where(
                QuestionCollectionItem.user_id == user_id,
                QuestionCollectionItem.question_id == question_id,
                QuestionCollection.user_id == user_id,
            )
            .order_by(QuestionCollection.is_pinned.desc(), QuestionCollection.updated_at.desc())
        )
        return list(self.session.execute(stmt).scalars().all())

    def list_valid_collection_ids(
        self,
        user_id: uuid.UUID,
        collection_ids: Sequence[uuid.UUID],
    ) -> set[uuid.UUID]:
        """批量校验题单主键均归属当前用户。"""
        if not collection_ids:
            return set()
        stmt = select(QuestionCollection.id).where(
            QuestionCollection.user_id == user_id,
            QuestionCollection.id.in_(list(collection_ids)),
        )
        return set(self.session.execute(stmt).scalars().all())

    def remove_question_from_collections(
        self,
        user_id: uuid.UUID,
        question_id: uuid.UUID,
        collection_ids: Sequence[uuid.UUID],
    ) -> int:
        """从多个指定题单中移除单题关联。"""
        if not collection_ids:
            return 0
        stmt = delete(QuestionCollectionItem).where(
            QuestionCollectionItem.user_id == user_id,
            QuestionCollectionItem.question_id == question_id,
            QuestionCollectionItem.collection_id.in_(list(collection_ids)),
        )
        result = self.session.execute(stmt)
        self.session.flush()
        return result.rowcount if isinstance(result, CursorResult) else 0

    def touch_collections(
        self,
        user_id: uuid.UUID,
        collection_ids: Sequence[uuid.UUID],
        updated_at: datetime,
    ) -> None:
        """刷新题单的 updated_at 时间戳。"""
        if not collection_ids:
            return
        stmt = (
            update(QuestionCollection)
            .where(
                QuestionCollection.user_id == user_id,
                QuestionCollection.id.in_(list(collection_ids)),
            )
            .values(updated_at=updated_at)
        )
        self.session.execute(stmt)
        self.session.flush()


__all__ = ["CollectionRepository"]
