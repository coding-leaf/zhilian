"""自定义题单领域服务编排模块。

负责题单 CRUD、批量幂等收纳、跨题单原子同步与零 N+1 视图聚合。
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError, FolderNotFoundError, QuestionNotFoundError
from app.models.collection import QuestionCollection
from app.repositories.collection import CollectionRepository
from app.repositories.folder import FolderRepository
from app.schemas.collection import (
    CollectionItemsAddResponse,
    CollectionListResponse,
    CollectionQuestionItemResponse,
    CollectionQuestionListResponse,
    QuestionCollectionResponse,
    QuestionCollectionsResponse,
    QuestionCollectionsSyncResponse,
)


class CollectionNotFoundError(AppError):
    """自定义题单不存在或无权访问异常 (HTTP 404)。"""

    def __init__(
        self,
        message: str = "请求的题单不存在或无权访问",
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(
            error_code=40023,
            message=message,
            status_code=404,
            details=details,
        )


class CollectionNameConflictError(AppError):
    """自定义题单重名冲突异常 (HTTP 409)。"""

    def __init__(
        self,
        message: str = "同名题单已存在",
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(
            error_code=40024,
            message=message,
            status_code=409,
            details=details,
        )


class CollectionService:
    """自定义题单领域服务。"""

    def __init__(
        self,
        session: Session,
        repo: CollectionRepository | None = None,
        folder_repo: FolderRepository | None = None,
    ) -> None:
        self.session = session
        self.repo = repo or CollectionRepository(session)
        self.folder_repo = folder_repo or FolderRepository(session)

    def _validate_folder_ownership(self, user_id: uuid.UUID, folder_id: uuid.UUID | None) -> None:
        if folder_id is None:
            return
        folder = self.folder_repo.get_by_id(folder_id, user_id)
        if folder is None:
            raise FolderNotFoundError(details={"folder_id": str(folder_id)})

    def _build_collection_responses(
        self,
        user_id: uuid.UUID,
        collections: list[QuestionCollection],
    ) -> list[QuestionCollectionResponse]:
        if not collections:
            return []
        collection_ids = [col.id for col in collections]
        folder_ids = list({col.folder_id for col in collections if col.folder_id is not None})
        counts = self.repo.count_active_questions_by_collection_ids(user_id, collection_ids)
        folder_names = self.repo.get_folder_names_by_ids(user_id, folder_ids)
        return [
            QuestionCollectionResponse(
                id=col.id,
                name=col.name,
                description=col.description,
                folder_id=col.folder_id,
                folder_name=folder_names.get(col.folder_id) if col.folder_id is not None else None,
                color_token=col.color_token,
                is_pinned=col.is_pinned,
                sort_order=col.sort_order,
                question_count=counts.get(col.id, 0),
                created_at=col.created_at,
                updated_at=col.updated_at,
            )
            for col in collections
        ]

    def list_collections(
        self,
        user_id: uuid.UUID,
        *,
        folder_id: uuid.UUID | None = None,
        unclassified: bool = False,
    ) -> CollectionListResponse:
        """查询当前用户的自定义题单列表（含活跃题目计数，零 N+1）。"""
        collections = self.repo.list_collections(
            user_id,
            folder_id=folder_id,
            unclassified=unclassified,
        )
        items = self._build_collection_responses(user_id, collections)
        return CollectionListResponse(items=items, total=len(items))

    def create_collection(
        self,
        user_id: uuid.UUID,
        *,
        name: str,
        description: str = "",
        folder_id: uuid.UUID | None = None,
        color_token: str | None = None,
        is_pinned: bool = False,
    ) -> QuestionCollectionResponse:
        """创建自定义题单（重名抛出 409）。"""
        cleaned_name = name.strip()
        self._validate_folder_ownership(user_id, folder_id)
        if self.repo.name_exists(user_id, cleaned_name):
            raise CollectionNameConflictError(
                f"题单名称 '{cleaned_name}' 已存在",
                details={"name": cleaned_name},
            )
        try:
            collection = self.repo.create_collection(
                user_id=user_id,
                name=cleaned_name,
                description=description.strip(),
                folder_id=folder_id,
                color_token=color_token,
                is_pinned=is_pinned,
            )
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise CollectionNameConflictError(
                f"题单名称 '{cleaned_name}' 已存在",
                details={"name": cleaned_name},
            ) from exc
        return self._build_collection_responses(user_id, [collection])[0]

    def update_collection(
        self,
        user_id: uuid.UUID,
        collection_id: uuid.UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        folder_id: uuid.UUID | None = None,
        clear_folder: bool = False,
        color_token: str | None = None,
        is_pinned: bool | None = None,
    ) -> QuestionCollectionResponse:
        """更新自定义题单元数据（重名 409，越权/不存在 404）。"""
        collection = self.repo.get_collection_by_id(collection_id, user_id)
        if collection is None:
            raise CollectionNotFoundError(details={"collection_id": str(collection_id)})

        if name is not None:
            cleaned_name = name.strip()
            if self.repo.name_exists(user_id, cleaned_name, exclude_collection_id=collection_id):
                raise CollectionNameConflictError(
                    f"题单名称 '{cleaned_name}' 已存在",
                    details={"name": cleaned_name},
                )
            collection.name = cleaned_name

        if description is not None:
            collection.description = description.strip()

        if clear_folder:
            collection.folder_id = None
        elif folder_id is not None:
            self._validate_folder_ownership(user_id, folder_id)
            collection.folder_id = folder_id

        if color_token is not None:
            collection.color_token = color_token
        if is_pinned is not None:
            collection.is_pinned = is_pinned

        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise CollectionNameConflictError(
                f"题单名称 '{collection.name}' 已存在",
                details={"name": collection.name},
            ) from exc
        self.session.refresh(collection)
        return self._build_collection_responses(user_id, [collection])[0]

    def delete_collection(self, user_id: uuid.UUID, collection_id: uuid.UUID) -> None:
        """删除题单及收纳关系，绝不删除原题。"""
        collection = self.repo.get_collection_by_id(collection_id, user_id)
        if collection is None:
            raise CollectionNotFoundError(details={"collection_id": str(collection_id)})
        self.repo.delete_collection(collection)
        self.session.commit()

    def list_collection_questions(
        self,
        user_id: uuid.UUID,
        collection_id: uuid.UUID,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> CollectionQuestionListResponse:
        """分页获取题单内活跃题目详情。"""
        collection = self.repo.get_collection_by_id(collection_id, user_id)
        if collection is None:
            raise CollectionNotFoundError(details={"collection_id": str(collection_id)})

        rows, total = self.repo.list_collection_questions(
            user_id,
            collection_id,
            page=page,
            page_size=page_size,
        )
        items = [
            CollectionQuestionItemResponse(
                id=item.id,
                collection_id=item.collection_id,
                question_id=question.id,
                question_type=question.question_type,
                difficulty=question.difficulty,
                content=question.stem,
                options=list(question.options or []),
                answer=question.answer,
                explanation=question.analysis or "",
                kp_id=question.knowledge_point_id,
                kp_name=kp_name,
                material_id=question.material_id,
                material_title=material_title,
                note=item.note,
                added_at=item.created_at,
            )
            for item, question, kp_name, material_title in rows
        ]
        return CollectionQuestionListResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
        )

    def add_items(
        self,
        user_id: uuid.UUID,
        collection_id: uuid.UUID,
        question_ids: list[uuid.UUID],
        *,
        note: str | None = None,
    ) -> CollectionItemsAddResponse:
        """批量幂等向题单收纳题目（校验越权与软删除）。"""
        collection = self.repo.get_collection_by_id(collection_id, user_id)
        if collection is None:
            raise CollectionNotFoundError(details={"collection_id": str(collection_id)})

        deduped_ids = list(dict.fromkeys(question_ids))
        valid_ids = self.repo.list_valid_user_question_ids(user_id, deduped_ids)
        missing_ids = [str(qid) for qid in deduped_ids if qid not in valid_ids]
        if missing_ids:
            raise QuestionNotFoundError(
                "部分题目不存在、已删除或无权访问",
                details={"question_ids": missing_ids},
            )

        existing_ids = self.repo.list_existing_question_ids(collection_id, user_id, deduped_ids)
        to_add = [qid for qid in deduped_ids if qid not in existing_ids]
        skipped_count = len(deduped_ids) - len(to_add)

        if to_add:
            self.repo.add_items(
                user_id=user_id,
                collection_id=collection_id,
                question_ids=to_add,
                note=note,
            )
            self.repo.touch_collections(user_id, [collection_id], datetime.now(UTC))

        self.session.commit()
        counts = self.repo.count_active_questions_by_collection_ids(user_id, [collection_id])
        return CollectionItemsAddResponse(
            added_count=len(to_add),
            skipped_count=skipped_count,
            total_count=counts.get(collection_id, 0),
        )

    def remove_item(
        self,
        user_id: uuid.UUID,
        collection_id: uuid.UUID,
        question_id: uuid.UUID,
    ) -> None:
        """从题单中移出指定题目（不删原题）。"""
        collection = self.repo.get_collection_by_id(collection_id, user_id)
        if collection is None:
            raise CollectionNotFoundError(details={"collection_id": str(collection_id)})
        removed = self.repo.remove_item(user_id, collection_id, question_id)
        if removed:
            self.repo.touch_collections(user_id, [collection_id], datetime.now(UTC))
        self.session.commit()

    def get_question_collections(
        self,
        user_id: uuid.UUID,
        question_id: uuid.UUID,
    ) -> QuestionCollectionsResponse:
        """查询单题已归属的题单主键列表。"""
        valid_ids = self.repo.list_valid_user_question_ids(user_id, [question_id])
        if question_id not in valid_ids:
            raise QuestionNotFoundError(details={"question_id": str(question_id)})
        collection_ids = self.repo.list_collection_ids_for_question(user_id, question_id)
        return QuestionCollectionsResponse(question_id=question_id, collection_ids=collection_ids)

    def sync_question_collections(
        self,
        user_id: uuid.UUID,
        question_id: uuid.UUID,
        collection_ids: list[uuid.UUID],
    ) -> QuestionCollectionsSyncResponse:
        """原子同步单题归属的全部题单。"""
        valid_q_ids = self.repo.list_valid_user_question_ids(user_id, [question_id])
        if question_id not in valid_q_ids:
            raise QuestionNotFoundError(details={"question_id": str(question_id)})

        target_ids = list(dict.fromkeys(collection_ids))
        valid_c_ids = self.repo.list_valid_collection_ids(user_id, target_ids)
        missing_c_ids = [str(cid) for cid in target_ids if cid not in valid_c_ids]
        if missing_c_ids:
            raise CollectionNotFoundError(
                "部分目标题单不存在或无权访问",
                details={"collection_ids": missing_c_ids},
            )

        current_ids = self.repo.list_collection_ids_for_question(user_id, question_id)
        current_set = set(current_ids)
        target_set = set(target_ids)

        to_add = [cid for cid in target_ids if cid not in current_set]
        to_remove = [cid for cid in current_ids if cid not in target_set]

        now = datetime.now(UTC)
        for cid in to_add:
            self.repo.add_items(user_id=user_id, collection_id=cid, question_ids=[question_id])
        removed_count = self.repo.remove_question_from_collections(user_id, question_id, to_remove)
        touched = list(dict.fromkeys([*to_add, *to_remove]))
        if touched:
            self.repo.touch_collections(user_id, touched, now)
        self.session.commit()

        final_ids = self.repo.list_collection_ids_for_question(user_id, question_id)
        return QuestionCollectionsSyncResponse(
            question_id=question_id,
            collection_ids=final_ids,
            added_count=len(to_add),
            removed_count=removed_count,
        )


__all__ = [
    "CollectionNameConflictError",
    "CollectionNotFoundError",
    "CollectionService",
]
