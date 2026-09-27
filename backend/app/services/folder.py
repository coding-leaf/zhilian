"""课程文件夹领域服务编排模块。

统领课程文件夹 CRUD、归档/恢复、7 天惰性物理清理与资料归属移动。
严格遵循 AGENTS.md 规范：
- app/services 是全系统唯一允许开启数据库事务的层；
- 惰性清理在只读查询入口触发并显式提交事务（副作用已记录于质量规范）；
- 缩写白名单仅限 8 个 (api, id, url, ocr, llm, db, config, env)。
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.errors import (
    FolderNameConflictError,
    FolderNotFoundError,
    MaterialNotFoundError,
)
from app.core.security import generate_user_ref
from app.models.knowledge import KnowledgePoint
from app.models.material import Material, MaterialFolder
from app.repositories.folder import FolderRepository
from app.repositories.question import QuestionRepository
from app.services.material import MaterialService

logger = logging.getLogger(__name__)

# 依据：父契约 §3.1 — 归档后保留 7 天反悔期，逾期惰性物理清理
ARCHIVE_RETENTION: timedelta = timedelta(days=7)


@dataclass(frozen=True)
class FolderAggregate:
    """课程文件夹及其聚合计数视图对象。"""

    folder: MaterialFolder
    material_count: int
    ready_material_count: int
    knowledge_point_count: int
    question_count: int
    last_practice_at: datetime | None

    @property
    def purge_after(self) -> datetime | None:
        """归档后物理清理时间 (archived_at + 7 天)，未归档返回 None。"""
        if self.folder.archived_at is None:
            return None
        return self.folder.archived_at + ARCHIVE_RETENTION


class FolderService:
    """课程文件夹领域服务编排。

    全系统唯一允许开启数据库事务的层，负责课程生命周期与资料归属编排。
    """

    def __init__(
        self,
        session: Session,
        material_service: MaterialService,
        folder_repo: FolderRepository | None = None,
    ) -> None:
        self.session = session
        self.material_service = material_service
        self.repo = folder_repo or FolderRepository(session)

    # ==========================================
    # 课程 CRUD
    # ==========================================

    def create_folder(self, user_id: uuid.UUID, name: str) -> FolderAggregate:
        """创建课程文件夹。

        Args:
            user_id: 租户用户标识。
            name: 课程名称。

        Returns:
            FolderAggregate: 新建课程的聚合计数据。

        Raises:
            FolderNameConflictError: 同用户下课程名称重复。
        """
        cleaned_name = name.strip()
        if self.repo.name_exists(user_id, cleaned_name):
            raise FolderNameConflictError(
                f"课程名称 '{cleaned_name}' 已存在",
                details={"name": cleaned_name},
            )
        folder = self.repo.create(user_id=user_id, name=cleaned_name)
        self.session.commit()
        return self._build_aggregates([folder])[0]

    def list_folders(
        self,
        user_id: uuid.UUID,
        *,
        include_archived: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[FolderAggregate], int]:
        """分页查询课程文件夹列表（入口先执行逾期惰性清理）。

        Args:
            user_id: 租户用户标识。
            include_archived: 是否包含已归档课程。
            limit: 单页记录数限制。
            offset: 偏移游标。

        Returns:
            tuple[list[FolderAggregate], int]: (聚合课程列表, 总数)。
        """
        self._purge_expired(user_id)
        folders, total = self.repo.list_by_user(
            user_id,
            include_archived=include_archived,
            limit=limit,
            offset=offset,
        )
        return self._build_aggregates(folders), total

    def get_folder(self, user_id: uuid.UUID, folder_id: uuid.UUID) -> FolderAggregate:
        """查询单个课程文件夹详情（入口先执行逾期惰性清理）。

        Args:
            user_id: 租户用户标识。
            folder_id: 课程文件夹主键。

        Returns:
            FolderAggregate: 课程聚合详情。

        Raises:
            FolderNotFoundError: 课程不存在或无权访问。
        """
        self._purge_expired(user_id)
        folder = self.repo.get_by_id(folder_id, user_id, include_archived=True)
        if folder is None:
            raise FolderNotFoundError()
        return self._build_aggregates([folder])[0]

    def rename_folder(
        self,
        user_id: uuid.UUID,
        folder_id: uuid.UUID,
        name: str,
    ) -> FolderAggregate:
        """重命名课程文件夹。

        Args:
            user_id: 租户用户标识。
            folder_id: 课程文件夹主键。
            name: 新名称。

        Returns:
            FolderAggregate: 更新后的课程聚合详情。

        Raises:
            FolderNotFoundError: 课程不存在或无权访问。
            FolderNameConflictError: 同用户下课程名称重复。
        """
        cleaned_name = name.strip()
        folder = self.repo.get_by_id(folder_id, user_id, include_archived=True)
        if folder is None:
            raise FolderNotFoundError()
        if self.repo.name_exists(user_id, cleaned_name, exclude_id=folder_id):
            raise FolderNameConflictError(
                f"课程名称 '{cleaned_name}' 已存在",
                details={"name": cleaned_name},
            )
        updated = self.repo.update_name(folder_id, user_id, cleaned_name)
        if updated is None:
            raise FolderNotFoundError()
        self.session.commit()
        return self._build_aggregates([updated])[0]

    # ==========================================
    # 归档 / 恢复 / 物理清理
    # ==========================================

    def archive_folder(self, user_id: uuid.UUID, folder_id: uuid.UUID) -> FolderAggregate:
        """归档课程文件夹（软删除，写 archived_at）。

        Args:
            user_id: 租户用户标识。
            folder_id: 课程文件夹主键。

        Returns:
            FolderAggregate: 归档后的课程聚合详情。

        Raises:
            FolderNotFoundError: 课程不存在或无权访问。
        """
        user_ref = generate_user_ref(user_id)
        folder = self.repo.get_by_id(folder_id, user_id, include_archived=True)
        if folder is None:
            raise FolderNotFoundError()
        archived = self.repo.archive(folder_id, user_id, datetime.now(UTC))
        if archived is None:
            raise FolderNotFoundError()
        self.session.commit()
        logger.info(
            "folder archived",
            extra={"user_ref": user_ref, "target_id": str(folder_id), "error_code": 0},
        )
        return self._build_aggregates([archived])[0]

    def restore_folder(self, user_id: uuid.UUID, folder_id: uuid.UUID) -> FolderAggregate:
        """恢复已归档课程文件夹（清空 archived_at）。

        Args:
            user_id: 租户用户标识。
            folder_id: 课程文件夹主键。

        Returns:
            FolderAggregate: 恢复后的课程聚合详情。

        Raises:
            FolderNotFoundError: 课程不存在或无权访问。
            FolderNameConflictError: 恢复后将与某个活跃课程重名。
        """
        folder = self.repo.get_by_id(folder_id, user_id, include_archived=True)
        if folder is None:
            raise FolderNotFoundError()
        # 归档期内可能已有同名活跃课程被创建；恢复前须校验，避免违唯一约束。
        if self.repo.name_exists(user_id, folder.name, exclude_id=folder_id):
            raise FolderNameConflictError(
                f"课程名称 '{folder.name}' 已被其他活跃课程占用，无法恢复",
                details={"name": folder.name},
            )
        restored = self.repo.restore(folder_id, user_id)
        if restored is None:
            raise FolderNotFoundError()
        self.session.commit()
        return self._build_aggregates([restored])[0]

    def purge_folder(self, user_id: uuid.UUID, folder_id: uuid.UUID) -> None:
        """立即物理清理课程：先级联硬删其下资料，再删除课程主表记录。

        Args:
            user_id: 租户用户标识。
            folder_id: 课程文件夹主键。

        Raises:
            FolderNotFoundError: 课程不存在或无权访问。
        """
        folder = self.repo.get_by_id(folder_id, user_id, include_archived=True)
        if folder is None:
            raise FolderNotFoundError()
        self._hard_delete_materials(folder_id, user_id)
        self.repo.hard_delete(folder_id, user_id)
        self.session.commit()

    def _hard_delete_materials(self, folder_id: uuid.UUID, user_id: uuid.UUID) -> None:
        """逐个物理级联删除课程下的全部资料（含软删除资料）。"""
        for material_id in self.repo.list_material_ids_by_folder(folder_id, user_id):
            try:
                self.material_service.hard_delete_material(user_id=user_id, material_id=material_id)
            except MaterialNotFoundError:
                continue

    def _purge_expired(self, user_id: uuid.UUID) -> int:
        """对 archived_at 超过 7 天的课程执行物理级联清理。

        惰性清理副作用：在只读查询入口触发写操作并显式提交；单课程清理失败
        仅回滚而不阻断本次查询返回（降级为不清理，等待下次触发）。

        Args:
            user_id: 租户用户标识。

        Returns:
            int: 实际处理（尝试清理）的逾期课程数。
        """
        threshold = datetime.now(UTC) - ARCHIVE_RETENTION
        expired = self.repo.list_expired(user_id, before=threshold)
        for folder in expired:
            try:
                self.purge_folder(user_id, folder.id)
            except Exception as exc:
                self.session.rollback()
                logger.warning(
                    "lazy purge of expired folder failed",
                    extra={"target_id": str(folder.id), "details": str(exc)},
                )
        return len(expired)

    # ==========================================
    # 资料归属移动
    # ==========================================

    def move_material(
        self,
        user_id: uuid.UUID,
        material_id: uuid.UUID,
        folder_id: uuid.UUID | None,
    ) -> Material:
        """移动资料归属课程（None 表示移回未分类）。

        Args:
            user_id: 租户用户标识。
            material_id: 资料主键。
            folder_id: 目标课程主键，None 表示未分类。

        Returns:
            Material: 移动后的资料实体。

        Raises:
            MaterialNotFoundError: 资料不存在或越权。
            FolderNotFoundError: 目标课程不存在、已归档或越权。
        """
        material = self.material_service.repo.get_material_by_id(
            material_id, user_id, include_deleted=False
        )
        if material is None:
            raise MaterialNotFoundError("请求的学习资料不存在或已被删除")
        if folder_id is not None:
            folder = self.repo.get_by_id(folder_id, user_id, include_archived=False)
            if folder is None:
                raise FolderNotFoundError("目标课程文件夹不存在、已归档或无权访问")
        moved = self.material_service.repo.move_folder(material_id, user_id, folder_id)
        if moved is None:
            raise MaterialNotFoundError("请求的学习资料不存在或已被删除")
        self.session.commit()
        return moved

    def list_folder_knowledge_points(
        self,
        user_id: uuid.UUID,
        folder_id: uuid.UUID,
    ) -> list[tuple[KnowledgePoint, uuid.UUID, str]]:
        """列出课程内 ready 资料的考点及来源资料 (主键与标题)。

        用于课程范围出题时按资料分组选择必出考点。口径与课程范围出题的缺省考点集
        一致：仅未归档课程、未软删除且解析就绪的资料。

        Args:
            user_id: 租户用户标识。
            folder_id: 课程文件夹主键（必须归属当前用户且未归档）。

        Returns:
            list[tuple[KnowledgePoint, uuid.UUID, str]]: (考点, 资料主键, 资料标题)。

        Raises:
            FolderNotFoundError: 课程不存在、已归档或越权。
        """
        folder = self.repo.get_by_id(folder_id, user_id, include_archived=False)
        if folder is None:
            raise FolderNotFoundError()
        question_repo = QuestionRepository(self.session)
        return question_repo.list_folder_knowledge_points_with_material(user_id, folder_id)

    # ==========================================
    # 聚合装配
    # ==========================================
    def _build_aggregates(self, folders: list[MaterialFolder]) -> list[FolderAggregate]:
        """批量装配课程聚合计数（单组分组查询，杜绝逐课程 N+1）。"""
        if not folders:
            return []
        user_id = folders[0].user_id
        folder_ids = [folder.id for folder in folders]
        materials = self.repo.count_materials_by_folder_ids(folder_ids, user_id)
        ready = self.repo.count_ready_materials_by_folder_ids(folder_ids, user_id)
        points = self.repo.count_knowledge_points_by_folder_ids(folder_ids, user_id)
        questions = self.repo.count_questions_by_folder_ids(folder_ids, user_id)
        last_practice = self.repo.last_practice_at_by_folder_ids(folder_ids, user_id)
        return [
            FolderAggregate(
                folder=folder,
                material_count=materials.get(folder.id, 0),
                ready_material_count=ready.get(folder.id, 0),
                knowledge_point_count=points.get(folder.id, 0),
                question_count=questions.get(folder.id, 0),
                last_practice_at=last_practice.get(folder.id),
            )
            for folder in folders
        ]


__all__ = ["ARCHIVE_RETENTION", "FolderAggregate", "FolderService"]
