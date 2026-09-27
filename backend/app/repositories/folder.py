"""课程文件夹领域数据仓储模块。

封装针对 material_folders 的数据库交互，以及按课程聚合的资料/考点/题目统计查询。
严格遵循 AGENTS.md 规范：
- 全仓储方法强制要求 user_id 参数并作为 SQL 过滤条件，严格阻断水平越权；
- 仓储层严禁导入 fastapi 与 app.integrations；
- 缩写白名单仅限 8 个 (api, id, url, ocr, llm, db, config, env)。
"""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.knowledge import KnowledgePoint
from app.models.material import Material, MaterialFolder
from app.models.practice import Practice
from app.models.question import Question


class FolderRepository:
    """课程文件夹领域数据仓储。

    铁律：所有涉及数据检索与变更的方法强制携带 user_id 参数，严格阻断水平越权。
    严禁导入 fastapi 与 app.integrations。
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    # ==========================================
    # 文件夹 CRUD 操作
    # ==========================================

    def create(
        self,
        *,
        user_id: uuid.UUID,
        name: str,
        parent_id: uuid.UUID | None = None,
        sort_order: int = 0,
    ) -> MaterialFolder:
        """创建课程文件夹。

        Args:
            user_id: 所属用户标识。
            name: 课程文件夹名称。
            parent_id: 父文件夹标识（预留嵌套，本期恒为 None）。
            sort_order: 排序权重。

        Returns:
            MaterialFolder: 已加入会话并刷新主键的课程文件夹实体。
        """
        folder = MaterialFolder(
            user_id=user_id,
            name=name,
            parent_id=parent_id,
            sort_order=sort_order,
            archived_at=None,
        )
        self.session.add(folder)
        self.session.flush()
        return folder

    def get_by_id(
        self,
        folder_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        include_archived: bool = False,
    ) -> MaterialFolder | None:
        """根据主键与所属用户查询课程文件夹。

        Args:
            folder_id: 课程文件夹主键。
            user_id: 租户用户标识（强制隔离）。
            include_archived: 是否允许命中已归档课程，默认 False。

        Returns:
            MaterialFolder | None: 课程文件夹实体，不存在或越权返回 None。
        """
        stmt = select(MaterialFolder).where(
            MaterialFolder.id == folder_id,
            MaterialFolder.user_id == user_id,
        )
        if not include_archived:
            stmt = stmt.where(MaterialFolder.archived_at.is_(None))
        return self.session.execute(stmt).scalar_one_or_none()

    def list_by_user(
        self,
        user_id: uuid.UUID,
        *,
        include_archived: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[MaterialFolder], int]:
        """分页获取用户所属课程文件夹及总数。

        Args:
            user_id: 租户用户标识。
            include_archived: 是否包含已归档课程，默认 False。
            limit: 单页记录数限制。
            offset: 偏移游标。

        Returns:
            tuple[list[MaterialFolder], int]: (课程文件列表, 总记录数)。
        """
        conditions = [MaterialFolder.user_id == user_id]
        if not include_archived:
            conditions.append(MaterialFolder.archived_at.is_(None))

        total_stmt = select(func.count(MaterialFolder.id)).where(*conditions)
        total = int(self.session.execute(total_stmt).scalar_one())

        stmt = (
            select(MaterialFolder)
            .where(*conditions)
            .order_by(MaterialFolder.sort_order.asc(), MaterialFolder.created_at.asc())
            .limit(limit)
            .offset(offset)
        )
        items = list(self.session.execute(stmt).scalars().all())
        return items, total

    def update_name(
        self,
        folder_id: uuid.UUID,
        user_id: uuid.UUID,
        name: str,
    ) -> MaterialFolder | None:
        """重命名课程文件夹。

        Args:
            folder_id: 课程文件夹主键。
            user_id: 租户用户标识。
            name: 新名称。

        Returns:
            MaterialFolder | None: 更新后的实体，不存在或越权返回 None。
        """
        folder = self.get_by_id(folder_id, user_id, include_archived=True)
        if folder is None:
            return None
        folder.name = name
        self.session.flush()
        return folder

    def archive(
        self,
        folder_id: uuid.UUID,
        user_id: uuid.UUID,
        archived_at: datetime,
    ) -> MaterialFolder | None:
        """归档课程文件夹（写 archived_at）。

        Args:
            folder_id: 课程文件夹主键。
            user_id: 租户用户标识。
            archived_at: 归档时间。

        Returns:
            MaterialFolder | None: 更新后的实体，不存在或越权返回 None。
        """
        folder = self.get_by_id(folder_id, user_id, include_archived=True)
        if folder is None:
            return None
        folder.archived_at = archived_at
        self.session.flush()
        return folder

    def restore(
        self,
        folder_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> MaterialFolder | None:
        """恢复已归档课程文件夹（清空 archived_at）。

        Args:
            folder_id: 课程文件夹主键。
            user_id: 租户用户标识。

        Returns:
            MaterialFolder | None: 更新后的实体，不存在或越权返回 None。
        """
        folder = self.get_by_id(folder_id, user_id, include_archived=True)
        if folder is None:
            return None
        folder.archived_at = None
        self.session.flush()
        return folder

    def list_expired(
        self,
        user_id: uuid.UUID,
        *,
        before: datetime,
    ) -> list[MaterialFolder]:
        """查询归档时间早于给定阈值（逾期）的课程文件夹。

        Args:
            user_id: 租户用户标识。
            before: 逾期判定阈值（archived_at < before）。

        Returns:
            list[MaterialFolder]: 逾期课程文件列表。
        """
        stmt = select(MaterialFolder).where(
            MaterialFolder.user_id == user_id,
            MaterialFolder.archived_at.is_not(None),
            MaterialFolder.archived_at < before,
        )
        return list(self.session.execute(stmt).scalars().all())

    def name_exists(
        self,
        user_id: uuid.UUID,
        name: str,
        *,
        exclude_id: uuid.UUID | None = None,
    ) -> bool:
        """判定同一租户下课程名称是否已存在。

        Args:
            user_id: 租户用户标识。
            name: 待校验名称。
            exclude_id: 可选排除的课程主键（重命名时排除自身）。

        Returns:
            bool: 已存在返回 True，否则 False。
        """
        stmt = select(func.count(MaterialFolder.id)).where(
            MaterialFolder.user_id == user_id,
            MaterialFolder.name == name,
        )
        if exclude_id is not None:
            stmt = stmt.where(MaterialFolder.id != exclude_id)
        return int(self.session.execute(stmt).scalar_one()) > 0

    def hard_delete(
        self,
        folder_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> bool:
        """物理删除课程文件夹主表记录。

        Args:
            folder_id: 课程文件夹主键。
            user_id: 租户用户标识。

        Returns:
            bool: 成功删除返回 True，不存在或越权返回 False。
        """
        folder = self.get_by_id(folder_id, user_id, include_archived=True)
        if folder is None:
            return False
        self.session.delete(folder)
        self.session.flush()
        return True

    def list_material_ids_by_folder(
        self,
        folder_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[uuid.UUID]:
        """查询课程文件夹下全部资料主键（含软删除，供物理级联清理）。

        Args:
            folder_id: 课程文件夹主键。
            user_id: 租户用户标识。

        Returns:
            list[uuid.UUID]: 归属该课程的资料主键列表。
        """
        stmt = select(Material.id).where(
            Material.user_id == user_id,
            Material.folder_id == folder_id,
        )
        return [row[0] for row in self.session.execute(stmt).all()]

    # ==========================================
    # 按课程维度聚合统计（批量分组查询，杜绝 N+1）
    # ==========================================

    def count_materials_by_folder_ids(
        self,
        folder_ids: Sequence[uuid.UUID],
        user_id: uuid.UUID,
    ) -> dict[uuid.UUID, int]:
        """批量统计各课程下有效资料数（is_deleted=False）。"""
        ids = self._unique_ids(folder_ids)
        if not ids:
            return {}
        stmt = (
            select(Material.folder_id, func.count(Material.id))
            .where(
                Material.user_id == user_id,
                Material.is_deleted.is_(False),
                Material.folder_id.in_(ids),
            )
            .group_by(Material.folder_id)
        )
        return {row[0]: int(row[1]) for row in self.session.execute(stmt).all()}

    def count_ready_materials_by_folder_ids(
        self,
        folder_ids: Sequence[uuid.UUID],
        user_id: uuid.UUID,
    ) -> dict[uuid.UUID, int]:
        """批量统计各课程下解析就绪（status=ready）资料数。"""
        ids = self._unique_ids(folder_ids)
        if not ids:
            return {}
        stmt = (
            select(Material.folder_id, func.count(Material.id))
            .where(
                Material.user_id == user_id,
                Material.is_deleted.is_(False),
                Material.status == "ready",
                Material.folder_id.in_(ids),
            )
            .group_by(Material.folder_id)
        )
        return {row[0]: int(row[1]) for row in self.session.execute(stmt).all()}

    def count_knowledge_points_by_folder_ids(
        self,
        folder_ids: Sequence[uuid.UUID],
        user_id: uuid.UUID,
    ) -> dict[uuid.UUID, int]:
        """批量统计各课程资料下知识点总数。"""
        ids = self._unique_ids(folder_ids)
        if not ids:
            return {}
        stmt = (
            select(Material.folder_id, func.count(KnowledgePoint.id))
            .join(KnowledgePoint, KnowledgePoint.material_id == Material.id)
            .where(
                Material.user_id == user_id,
                KnowledgePoint.user_id == user_id,
                Material.is_deleted.is_(False),
                Material.folder_id.in_(ids),
            )
            .group_by(Material.folder_id)
        )
        return {row[0]: int(row[1]) for row in self.session.execute(stmt).all()}

    def count_questions_by_folder_ids(
        self,
        folder_ids: Sequence[uuid.UUID],
        user_id: uuid.UUID,
    ) -> dict[uuid.UUID, int]:
        """批量统计各课程资料下题目总数。"""
        ids = self._unique_ids(folder_ids)
        if not ids:
            return {}
        stmt = (
            select(Material.folder_id, func.count(Question.id))
            .join(Question, Question.material_id == Material.id)
            .where(
                Material.user_id == user_id,
                Question.user_id == user_id,
                Material.is_deleted.is_(False),
                Material.folder_id.in_(ids),
            )
            .group_by(Material.folder_id)
        )
        return {row[0]: int(row[1]) for row in self.session.execute(stmt).all()}

    def last_practice_at_by_folder_ids(
        self,
        folder_ids: Sequence[uuid.UUID],
        user_id: uuid.UUID,
    ) -> dict[uuid.UUID, datetime]:
        """批量统计各课程资料相关练习的最近创建时间。"""
        ids = self._unique_ids(folder_ids)
        if not ids:
            return {}
        stmt = (
            select(Material.folder_id, func.max(Practice.created_at))
            .join(Practice, Practice.material_id == Material.id)
            .where(
                Material.user_id == user_id,
                Practice.user_id == user_id,
                Material.is_deleted.is_(False),
                Material.folder_id.in_(ids),
            )
            .group_by(Material.folder_id)
        )
        return {row[0]: row[1] for row in self.session.execute(stmt).all()}

    @staticmethod
    def _unique_ids(folder_ids: Sequence[uuid.UUID]) -> list[uuid.UUID]:
        """去重并保持顺序，返回非空主键列表。"""
        return list(dict.fromkeys(folder_ids))


__all__ = ["FolderRepository"]
