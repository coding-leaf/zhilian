"""知识点领域数据仓储模块。

封装针对 knowledge_points, knowledge_point_snippets 表的数据库交互。
严格遵循 AGENTS.md 规范：
- 全仓储方法强制要求 user_id 参数并作为 SQL 过滤条件，严格阻断水平越权；
- 仓储层严禁导入 fastapi 与 app.integrations；
- 缩写白名单仅限 8 个 (api, id, url, ocr, llm, db, config, env)。
"""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import CursorResult, delete, select
from sqlalchemy.orm import Session, defer

from app.models.knowledge import KnowledgePoint, KnowledgePointSnippet
from app.models.material import Material, MaterialFolder, MaterialSnippet


class KnowledgeRepository:
    """知识点与切片溯源关联数据仓储。

    所有方法强制要求 user_id 作为租户过滤条件，杜绝任何水平越权。
    """

    def __init__(self, session: Session) -> None:
        """初始化仓储实例。

        Args:
            session: SQLAlchemy 数据库会话。
        """
        self.session = session

    # ==========================================
    # KnowledgePoint 知识点 CRUD 操作
    # ==========================================

    def batch_create_knowledge_points(
        self,
        points: Sequence[KnowledgePoint | dict[str, Any]],
        user_id: uuid.UUID,
    ) -> list[KnowledgePoint]:
        """批量创建知识点记录，强制校验并重写 user_id。

        Args:
            points: 知识点实体或属性字典序列。
            user_id: 租户用户主键。

        Returns:
            list[KnowledgePoint]: 插入成功的知识点实体列表。
        """
        created: list[KnowledgePoint] = []
        for item in points:
            if isinstance(item, KnowledgePoint):
                item.user_id = user_id
                self.session.add(item)
                created.append(item)
            elif isinstance(item, dict):
                item_data = dict(item)
                item_data["user_id"] = user_id
                point = KnowledgePoint(**item_data)
                self.session.add(point)
                created.append(point)
        self.session.flush()
        return created

    def get_by_id(
        self,
        knowledge_point_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> KnowledgePoint | None:
        """根据主键和租户用户查询单个知识点。

        Args:
            knowledge_point_id: 知识点主键。
            user_id: 租户用户标识。

        Returns:
            KnowledgePoint | None: 知识点实体，不存在或越权返回 None。
        """
        stmt = select(KnowledgePoint).where(
            KnowledgePoint.id == knowledge_point_id,
            KnowledgePoint.user_id == user_id,
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def get_knowledge_point_by_id(
        self,
        knowledge_point_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> KnowledgePoint | None:
        """get_by_id 别名方法。"""
        return self.get_by_id(knowledge_point_id, user_id)

    def list_by_ids(
        self,
        knowledge_point_ids: Sequence[uuid.UUID],
        user_id: uuid.UUID,
    ) -> list[KnowledgePoint]:
        """按知识点主键集合与租户用户批量查询知识点。"""
        if not knowledge_point_ids:
            return []
        stmt = select(KnowledgePoint).where(
            KnowledgePoint.user_id == user_id,
            KnowledgePoint.id.in_(knowledge_point_ids),
        )
        return list(self.session.execute(stmt).scalars().all())

    def list_by_folder_scope(
        self,
        user_id: uuid.UUID,
        *,
        folder_id: uuid.UUID | None = None,
        unclassified: bool = False,
    ) -> list[KnowledgePoint]:
        """按课程文件夹或未分类范围查询当前用户的全部知识点。"""
        stmt = (
            select(KnowledgePoint)
            .join(Material, KnowledgePoint.material_id == Material.id)
            .outerjoin(MaterialFolder, Material.folder_id == MaterialFolder.id)
            .where(
                KnowledgePoint.user_id == user_id,
                Material.user_id == user_id,
                Material.is_deleted.is_(False),
            )
        )
        if unclassified:
            stmt = stmt.where(Material.folder_id.is_(None))
        elif folder_id is not None:
            stmt = stmt.where(
                Material.folder_id == folder_id,
                (MaterialFolder.id.is_(None)) | (MaterialFolder.archived_at.is_(None)),
            )
        stmt = stmt.order_by(
            KnowledgePoint.level.asc(),
            KnowledgePoint.sort_order.asc(),
            KnowledgePoint.created_at.asc(),
        )
        return list(self.session.execute(stmt).scalars().all())

    def list_by_material_id(
        self,
        material_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[KnowledgePoint]:
        """按资料标识与租户用户查询知识点列表。

        Args:
            material_id: 资料主键。
            user_id: 租户用户标识。

        Returns:
            list[KnowledgePoint]: 按层级递增排序的知识点列表。
        """
        stmt = (
            select(KnowledgePoint)
            .where(
                KnowledgePoint.material_id == material_id,
                KnowledgePoint.user_id == user_id,
            )
            .order_by(
                KnowledgePoint.level.asc(),
                KnowledgePoint.sort_order.asc(),
                KnowledgePoint.created_at.asc(),
            )
        )
        return list(self.session.execute(stmt).scalars().all())

    def list_all_by_user_id(
        self,
        user_id: uuid.UUID,
    ) -> list[KnowledgePoint]:
        """获取指定租户用户的全部知识点（无分页上限，跨资料聚合）。

        用于用户掌握度宏观全景在缺省资料时聚合该用户所有知识点，
        与按资料过滤的 list_by_material_id 严格区分（禁止退化为 material_id IS NULL）。

        Args:
            user_id: 租户用户标识。

        Returns:
            list[KnowledgePoint]: 按层级递增、创建时间递增排序的全部知识点列表。
        """
        stmt = (
            select(KnowledgePoint)
            .where(KnowledgePoint.user_id == user_id)
            .order_by(
                KnowledgePoint.level.asc(),
                KnowledgePoint.sort_order.asc(),
                KnowledgePoint.created_at.asc(),
            )
        )
        return list(self.session.execute(stmt).scalars().all())

    def get_knowledge_points_by_version(
        self,
        material_id: uuid.UUID,
        version_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[KnowledgePoint]:
        """按资料版本与租户用户获取全部知识点列表，按拓扑层级正序排序（延迟加载大 JSON 精讲）。

        Args:
            material_id: 资料标识。
            version_id: 版本标识。
            user_id: 租户用户标识。

        Returns:
            list[KnowledgePoint]: 排序后的知识点实体列表。
        """
        stmt = (
            select(KnowledgePoint)
            .options(defer(KnowledgePoint.study_guide))
            .where(
                KnowledgePoint.material_id == material_id,
                KnowledgePoint.version_id == version_id,
                KnowledgePoint.user_id == user_id,
            )
            .order_by(
                KnowledgePoint.level.asc(),
                KnowledgePoint.sort_order.asc(),
                KnowledgePoint.created_at.asc(),
            )
        )
        return list(self.session.execute(stmt).scalars().all())

    def list_tree_nodes_with_guide_flag(
        self,
        material_id: uuid.UUID,
        version_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[tuple[KnowledgePoint, bool]]:
        """按资料版本查询知识树节点及 ``has_study_guide`` 布尔投影，绝不传输大 JSON。"""
        stmt = (
            select(
                KnowledgePoint,
                KnowledgePoint.study_guide.is_not(None).label("has_study_guide"),
            )
            .options(defer(KnowledgePoint.study_guide))
            .where(
                KnowledgePoint.material_id == material_id,
                KnowledgePoint.version_id == version_id,
                KnowledgePoint.user_id == user_id,
            )
            .order_by(
                KnowledgePoint.level.asc(),
                KnowledgePoint.sort_order.asc(),
                KnowledgePoint.created_at.asc(),
            )
        )
        rows = self.session.execute(stmt).all()
        return [(row[0], bool(row[1])) for row in rows]

    def list_sibling_kp_names(
        self,
        material_id: uuid.UUID,
        version_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        exclude_kp_id: uuid.UUID,
        parent_id: uuid.UUID | None = None,
        limit: int = 12,
    ) -> list[str]:
        """查询同版本/同模块兄弟考点名称列表（用于考前精讲易混概念对比）。"""
        stmt = (
            select(KnowledgePoint.id, KnowledgePoint.parent_id, KnowledgePoint.name)
            .where(
                KnowledgePoint.material_id == material_id,
                KnowledgePoint.version_id == version_id,
                KnowledgePoint.user_id == user_id,
                KnowledgePoint.id != exclude_kp_id,
            )
            .order_by(KnowledgePoint.sort_order.asc(), KnowledgePoint.created_at.asc())
        )
        rows = self.session.execute(stmt).all()
        same_parent = [
            str(row[2])
            for row in rows
            if parent_id is not None and row[1] == parent_id and str(row[2]).strip()
        ]
        others = [
            str(row[2])
            for row in rows
            if (parent_id is None or row[1] != parent_id) and str(row[2]).strip()
        ]
        combined: list[str] = []
        seen: set[str] = set()
        for name in [*same_parent, *others]:
            if name not in seen:
                seen.add(name)
                combined.append(name)
            if len(combined) >= limit:
                break
        return combined

    def list_leaf_study_guide_statuses(
        self,
        material_id: uuid.UUID,
        version_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[tuple[uuid.UUID, str, bool]]:
        """查询指定版本所有叶子核心考点的 ``(kp_id, name, has_study_guide)`` 元组列表。"""
        stmt = (
            select(
                KnowledgePoint.id,
                KnowledgePoint.parent_id,
                KnowledgePoint.name,
                KnowledgePoint.study_guide.is_not(None).label("has_study_guide"),
            )
            .where(
                KnowledgePoint.material_id == material_id,
                KnowledgePoint.version_id == version_id,
                KnowledgePoint.user_id == user_id,
            )
            .order_by(KnowledgePoint.sort_order.asc(), KnowledgePoint.created_at.asc())
        )
        rows = self.session.execute(stmt).all()
        parent_ids = {row[1] for row in rows if row[1] is not None}
        return [(row[0], str(row[2]), bool(row[3])) for row in rows if row[0] not in parent_ids]

    def delete_knowledge_points_by_version(
        self,
        material_id: uuid.UUID,
        version_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> int:
        """级联清除指定资料版本的全部知识点及关联映射。

        Args:
            material_id: 资料标识。
            version_id: 版本标识。
            user_id: 租户用户标识。

        Returns:
            int: 实际删除的知识点行数。
        """
        stmt = delete(KnowledgePoint).where(
            KnowledgePoint.material_id == material_id,
            KnowledgePoint.version_id == version_id,
            KnowledgePoint.user_id == user_id,
        )
        result = self.session.execute(stmt)
        self.session.flush()
        count = result.rowcount if isinstance(result, CursorResult) else 0
        return int(count)

    # ==========================================
    # KnowledgePointSnippet 溯源关联操作
    # ==========================================

    def create_material_relations(
        self,
        relations: Sequence[KnowledgePointSnippet | dict[str, Any]],
        user_id: uuid.UUID,
    ) -> list[KnowledgePointSnippet]:
        """批量创建知识点与切片的溯源关联记录。

        Args:
            relations: 关联实体或字典序列。
            user_id: 租户用户标识。

        Returns:
            list[KnowledgePointSnippet]: 创建成功的关联实体列表。
        """
        created: list[KnowledgePointSnippet] = []
        for item in relations:
            if isinstance(item, KnowledgePointSnippet):
                item.user_id = user_id
                self.session.add(item)
                created.append(item)
            elif isinstance(item, dict):
                item_data = dict(item)
                item_data["user_id"] = user_id
                relation = KnowledgePointSnippet(**item_data)
                self.session.add(relation)
                created.append(relation)
        self.session.flush()
        return created

    def get_snippets_for_point(
        self,
        knowledge_point_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[MaterialSnippet]:
        """反向溯源：通过知识点查询关联的所有来源切片。

        Args:
            knowledge_point_id: 知识点主键。
            user_id: 租户用户标识。

        Returns:
            list[MaterialSnippet]: 关联来源切片列表，按切片序号升序排列。
        """
        stmt = (
            select(MaterialSnippet)
            .join(
                KnowledgePointSnippet,
                KnowledgePointSnippet.snippet_id == MaterialSnippet.id,
            )
            .where(
                KnowledgePointSnippet.knowledge_point_id == knowledge_point_id,
                KnowledgePointSnippet.user_id == user_id,
                MaterialSnippet.user_id == user_id,
            )
            .order_by(MaterialSnippet.snippet_index.asc())
        )
        return list(self.session.execute(stmt).scalars().all())

    def get_points_for_snippet(
        self,
        snippet_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[KnowledgePoint]:
        """正向溯源：通过切片查询关联的所有知识点。

        Args:
            snippet_id: 切片主键。
            user_id: 租户用户标识。

        Returns:
            list[KnowledgePoint]: 关联的知识点列表，按层级与名称升序排列。
        """
        stmt = (
            select(KnowledgePoint)
            .join(
                KnowledgePointSnippet,
                KnowledgePointSnippet.knowledge_point_id == KnowledgePoint.id,
            )
            .where(
                KnowledgePointSnippet.snippet_id == snippet_id,
                KnowledgePointSnippet.user_id == user_id,
                KnowledgePoint.user_id == user_id,
            )
            .order_by(KnowledgePoint.level.asc(), KnowledgePoint.name.asc())
        )
        return list(self.session.execute(stmt).scalars().all())


__all__ = ["KnowledgeRepository"]
