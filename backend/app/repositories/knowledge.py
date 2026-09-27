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
from sqlalchemy.orm import Session

from app.models.knowledge import KnowledgePoint, KnowledgePointSnippet
from app.models.material import MaterialSnippet


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

    def create_knowledge_point(
        self,
        *,
        user_id: uuid.UUID,
        material_id: uuid.UUID,
        version_id: uuid.UUID,
        name: str,
        description: str = "",
        level: int = 1,
        parent_id: uuid.UUID | None = None,
        batch_id: str = "",
        is_low_confidence: bool = False,
    ) -> KnowledgePoint:
        """创建单个知识点实体。

        Args:
            user_id: 租户用户主键。
            material_id: 归属资料主键。
            version_id: 归属版本主键。
            name: 知识点名称。
            description: 知识点描述。
            level: 拓扑层级 (1~5)。
            parent_id: 父节点标识（若有）。
            batch_id: 抽取批次标识。
            is_low_confidence: 是否标记为低可信度。

        Returns:
            KnowledgePoint: 已持久化加入会话的知识点实体。
        """
        point = KnowledgePoint(
            user_id=user_id,
            material_id=material_id,
            version_id=version_id,
            name=name,
            description=description,
            level=level,
            parent_id=parent_id,
            batch_id=batch_id,
            is_low_confidence=is_low_confidence,
        )
        self.session.add(point)
        self.session.flush()
        return point

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

    def create_knowledge_points(
        self,
        points: Sequence[KnowledgePoint],
        user_id: uuid.UUID,
    ) -> list[KnowledgePoint]:
        """批量创建知识点记录 (契约别名)。"""
        return self.batch_create_knowledge_points(points, user_id)

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
            .order_by(KnowledgePoint.level.asc(), KnowledgePoint.created_at.asc())
        )
        return list(self.session.execute(stmt).scalars().all())

    def list_by_user_id(
        self,
        user_id: uuid.UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[KnowledgePoint]:
        """分页获取用户所属的所有知识点。

        Args:
            user_id: 租户用户标识。
            limit: 单页上限条数。
            offset: 偏移游标。

        Returns:
            list[KnowledgePoint]: 知识点实体列表。
        """
        stmt = (
            select(KnowledgePoint)
            .where(KnowledgePoint.user_id == user_id)
            .order_by(KnowledgePoint.created_at.desc())
            .limit(limit)
            .offset(offset)
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
            .order_by(KnowledgePoint.level.asc(), KnowledgePoint.created_at.asc())
        )
        return list(self.session.execute(stmt).scalars().all())

    def get_knowledge_points_by_version(
        self,
        material_id: uuid.UUID,
        version_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[KnowledgePoint]:
        """按资料版本与租户用户获取全部知识点列表，按拓扑层级正序排序。

        Args:
            material_id: 资料标识。
            version_id: 版本标识。
            user_id: 租户用户标识。

        Returns:
            list[KnowledgePoint]: 排序后的知识点实体列表。
        """
        stmt = (
            select(KnowledgePoint)
            .where(
                KnowledgePoint.material_id == material_id,
                KnowledgePoint.version_id == version_id,
                KnowledgePoint.user_id == user_id,
            )
            .order_by(KnowledgePoint.level.asc(), KnowledgePoint.created_at.asc())
        )
        return list(self.session.execute(stmt).scalars().all())

    def update_knowledge_point(
        self,
        knowledge_point_id: uuid.UUID,
        user_id: uuid.UUID,
        **kwargs: Any,
    ) -> KnowledgePoint | None:
        """更新单个知识点属性。

        Args:
            knowledge_point_id: 知识点标识。
            user_id: 租户用户标识。
            **kwargs: 待更新的字段键值对。

        Returns:
            KnowledgePoint | None: 更新后的实体，不存在或越权返回 None。
        """
        point = self.get_by_id(knowledge_point_id, user_id)
        if point is None:
            return None

        immutable_fields = {"id", "user_id"}
        for key, value in kwargs.items():
            if hasattr(point, key) and key not in immutable_fields:
                setattr(point, key, value)
        self.session.flush()
        return point

    def delete_by_id(
        self,
        knowledge_point_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> bool:
        """根据主键和租户用户删除单个知识点。

        Args:
            knowledge_point_id: 知识点标识。
            user_id: 租户用户标识。

        Returns:
            bool: 成功删除返回 True，未找到或越权返回 False。
        """
        stmt = delete(KnowledgePoint).where(
            KnowledgePoint.id == knowledge_point_id,
            KnowledgePoint.user_id == user_id,
        )
        result = self.session.execute(stmt)
        self.session.flush()
        count = result.rowcount if isinstance(result, CursorResult) else 0
        return bool(count > 0)

    def soft_delete_by_material_id(
        self,
        material_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> int:
        """按资料主键清除其下全部知识点。

        Args:
            material_id: 资料主键。
            user_id: 租户用户标识。

        Returns:
            int: 影响的记录行数。
        """
        stmt_delete = delete(KnowledgePoint).where(
            KnowledgePoint.material_id == material_id,
            KnowledgePoint.user_id == user_id,
        )
        result = self.session.execute(stmt_delete)
        self.session.flush()
        count = result.rowcount if isinstance(result, CursorResult) else 0
        return int(count)

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

    def create_knowledge_point_snippets(
        self,
        mappings: Sequence[KnowledgePointSnippet],
        user_id: uuid.UUID,
    ) -> list[KnowledgePointSnippet]:
        """create_material_relations 别名方法。"""
        return self.create_material_relations(mappings, user_id)

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

    def get_snippets_by_knowledge_point(
        self,
        knowledge_point_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[MaterialSnippet]:
        """get_snippets_for_point 契约别名。"""
        return self.get_snippets_for_point(knowledge_point_id, user_id)

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

    def get_knowledge_points_by_snippet(
        self,
        snippet_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[KnowledgePoint]:
        """get_points_for_snippet 契约别名。"""
        return self.get_points_for_snippet(snippet_id, user_id)


__all__ = ["KnowledgeRepository"]
