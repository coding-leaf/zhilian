"""学习资料领域数据仓储模块。

封装针对 materials, material_versions, material_snippets, material_ocr_pages 的数据库交互。
严格遵循 AGENTS.md 规范：
- 全仓储方法强制要求 user_id 参数并作为 SQL 过滤条件，严格阻断水平越权；
- 仓储层严禁导入 fastapi 与 app.integrations；
- 缩写白名单仅限 8 个 (api, id, url, ocr, llm, db, config, env)。
"""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, selectinload

from app.models.knowledge import KnowledgePoint
from app.models.material import (
    Material,
    MaterialFolder,
    MaterialOCRPage,
    MaterialSnippet,
    MaterialStatus,
    MaterialVersion,
    ParseStatus,
    SourceType,
)


class MaterialRepository:
    """学习资料领域数据仓储。

    铁律：所有涉及数据检索与变更的方法强制携带 user_id 参数，严格阻断水平越权。
    严禁导入 fastapi 与 app.integrations。
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    # ==========================================
    # Material 主表操作
    # ==========================================

    def create_material(
        self,
        *,
        user_id: uuid.UUID,
        title: str,
        file_format: str,
        file_size: int,
        source_type: str = SourceType.LOCAL.value,
        status: str = MaterialStatus.PENDING.value,
        folder_id: uuid.UUID | None = None,
    ) -> Material:
        """创建资料主表记录。

        Args:
            user_id: 所属用户标识。
            title: 资料标题或原始文件名。
            file_format: 文件格式扩展名 (如 pdf, docx, png)。
            file_size: 文件大小（字节）。
            source_type: 导入渠道来源，默认为 local。
            status: 初始状态，默认为 pending。
            folder_id: 归属课程文件夹标识（None=未分类）。

        Returns:
            Material: 已加入会话并刷新主键的资料实体。
        """
        material = Material(
            user_id=user_id,
            title=title,
            file_format=file_format,
            file_size=file_size,
            source_type=source_type,
            status=status,
            folder_id=folder_id,
            is_deleted=False,
        )
        self.session.add(material)
        self.session.flush()
        return material

    def get_material_by_id(
        self,
        material_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        include_deleted: bool = False,
        exclude_archived_folder: bool = False,
    ) -> Material | None:
        """根据主键和所属用户查询资料详情。

        Args:
            material_id: 资料主键。
            user_id: 租户用户标识（强制隔离）。
            include_deleted: 是否包含软删除记录，默认 False。
            exclude_archived_folder: 是否排除归属已归档课程的资料，默认 False。

        Returns:
            Material | None: 资料实体，不存在或越权时返回 None。
        """
        stmt = select(Material).where(
            Material.id == material_id,
            Material.user_id == user_id,
        )
        if not include_deleted:
            stmt = stmt.where(Material.is_deleted.is_(False))
        if exclude_archived_folder:
            stmt = stmt.outerjoin(MaterialFolder, Material.folder_id == MaterialFolder.id).where(
                self._visible_folder_condition()
            )
        return self.session.execute(stmt).scalar_one_or_none()

    def list_materials(
        self,
        user_id: uuid.UUID,
        *,
        is_deleted: bool = False,
        limit: int = 20,
        offset: int = 0,
        keyword: str | None = None,
        status: str | None = None,
        statuses: list[str] | None = None,
        folder_id: uuid.UUID | None = None,
        unclassified: bool = False,
    ) -> list[Material]:
        """分页获取用户所属资料列表。

        Args:
            user_id: 租户用户标识。
            is_deleted: 软删除状态过滤，默认 False。
            limit: 单页记录数限制，默认 20。
            offset: 偏移游标，默认 0。
            keyword: 可选标题模糊搜索词。
            status: 可选资料生命周期状态过滤（单值）。
            statuses: 可选资料生命周期状态集合过滤（优先于 status，支持多状态聚合）。
            folder_id: 可选课程文件夹过滤（归属该课程的资料）。
            unclassified: 是否仅返回未分类资料（folder_id IS NULL）。

        Returns:
            list[Material]: 资料实体列表，版本集合已通过 selectinload 预加载。

        Note:
            使用 ``selectinload`` 一次性批量预加载 ``Material.versions``（固定 1 次额外查询），
            避免上层逐条解析进度时的 N+1 查询。
        """
        stmt = select(Material).where(
            Material.user_id == user_id,
            Material.is_deleted == is_deleted,
        )
        if keyword:
            stmt = stmt.where(Material.title.ilike(f"%{keyword}%"))
        if statuses is not None:
            stmt = stmt.where(Material.status.in_(statuses))
        elif status:
            stmt = stmt.where(Material.status == status)
        stmt = self._apply_folder_filter(stmt, folder_id=folder_id, unclassified=unclassified)

        stmt = (
            stmt.options(selectinload(Material.versions).selectinload(MaterialVersion.ocr_pages))
            .order_by(Material.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.execute(stmt).scalars().all())

    @staticmethod
    def _visible_folder_condition() -> Any:
        """构造「资料未归属归档课程」的可见性过滤条件。

        未分类资料（folder_id IS NULL）恒可见；归属课程的资料仅当课程未归档时可见。
        """
        return or_(Material.folder_id.is_(None), MaterialFolder.archived_at.is_(None))

    @classmethod
    def _apply_folder_filter(
        cls,
        stmt: Any,
        *,
        folder_id: uuid.UUID | None,
        unclassified: bool,
    ) -> Any:
        """为查询语句附加课程可见性与归属过滤。

        Args:
            stmt: 待附加的 SQLAlchemy select 语句。
            folder_id: 目标课程主键，None 表示不按课程限定。
            unclassified: 是否仅返回未分类资料。

        Returns:
            Any: 附加过滤后的 select 语句。
        """
        stmt = stmt.outerjoin(MaterialFolder, Material.folder_id == MaterialFolder.id).where(
            cls._visible_folder_condition()
        )
        if unclassified:
            return stmt.where(Material.folder_id.is_(None))
        if folder_id is not None:
            return stmt.where(Material.folder_id == folder_id)
        return stmt

    def count_knowledge_points_by_version_ids(
        self,
        version_ids: Sequence[uuid.UUID],
        user_id: uuid.UUID,
    ) -> dict[uuid.UUID, int]:
        """按版本批量统计知识点实体数量（单次分组查询，杜绝 N+1）。

        Args:
            version_ids: 待统计的目标版本主键集合。
            user_id: 租户用户标识（强制隔离）。

        Returns:
            dict[uuid.UUID, int]: 版本主键到知识点数量的映射，缺失版本不在字典中。
        """
        unique_ids = list(dict.fromkeys(version_ids))
        if not unique_ids:
            return {}
        stmt = (
            select(KnowledgePoint.version_id, func.count(KnowledgePoint.id))
            .where(
                KnowledgePoint.user_id == user_id,
                KnowledgePoint.version_id.in_(unique_ids),
            )
            .group_by(KnowledgePoint.version_id)
        )
        return {row[0]: int(row[1]) for row in self.session.execute(stmt).all()}

    def list_materials_by_user(
        self,
        user_id: uuid.UUID,
        *,
        is_deleted: bool = False,
        limit: int = 20,
        offset: int = 0,
        keyword: str | None = None,
        status: str | None = None,
        statuses: list[str] | None = None,
        folder_id: uuid.UUID | None = None,
        unclassified: bool = False,
    ) -> tuple[list[Material], int]:
        """分页获取用户所属资料列表及符合条件的总记录数。

        Args:
            user_id: 租户用户标识。
            is_deleted: 软删除状态过滤，默认 False。
            limit: 单页记录数限制，默认 20。
            offset: 偏移游标，默认 0。
            keyword: 可选标题模糊搜索词。
            status: 可选资料生命周期状态过滤（单值）。
            statuses: 可选资料生命周期状态集合过滤（优先于 status，支持多状态聚合）。
            folder_id: 可选课程文件夹过滤（归属该课程的资料）。
            unclassified: 是否仅返回未分类资料（folder_id IS NULL）。

        Returns:
            tuple[list[Material], int]: (资料实体列表, 总记录数)。
        """
        count_stmt = select(func.count(Material.id)).where(
            Material.user_id == user_id,
            Material.is_deleted == is_deleted,
        )
        if keyword:
            count_stmt = count_stmt.where(Material.title.ilike(f"%{keyword}%"))
        if statuses is not None:
            count_stmt = count_stmt.where(Material.status.in_(statuses))
        elif status:
            count_stmt = count_stmt.where(Material.status == status)
        count_stmt = self._apply_folder_filter(
            count_stmt, folder_id=folder_id, unclassified=unclassified
        )

        total = self.session.execute(count_stmt).scalar_one()

        items = self.list_materials(
            user_id=user_id,
            is_deleted=is_deleted,
            limit=limit,
            offset=offset,
            keyword=keyword,
            status=status,
            statuses=statuses,
            folder_id=folder_id,
            unclassified=unclassified,
        )
        return items, int(total)

    def move_folder(
        self,
        material_id: uuid.UUID,
        user_id: uuid.UUID,
        folder_id: uuid.UUID | None,
    ) -> Material | None:
        """移动资料归属课程（None 表示移回未分类）。

        Args:
            material_id: 资料主键。
            user_id: 租户用户标识。
            folder_id: 目标课程主键，None 表示未分类。

        Returns:
            Material | None: 更新后的资料实体，不存在或越权返回 None。
        """
        material = self.get_material_by_id(material_id, user_id, include_deleted=False)
        if material is None:
            return None
        material.folder_id = folder_id
        self.session.flush()
        return material

    def update_material_status(
        self,
        material_id: uuid.UUID,
        user_id: uuid.UUID,
        status: str,
        *,
        current_version_id: uuid.UUID | None = None,
    ) -> bool:
        """更新资料主表状态与当前激活版本。

        Args:
            material_id: 资料主键。
            user_id: 租户用户标识。
            status: 目标生命周期状态。
            current_version_id: 可选激活版本标识。

        Returns:
            bool: 成功更新返回 True，不存在或越权返回 False。
        """
        material = self.get_material_by_id(material_id, user_id, include_deleted=True)
        if material is None:
            return False
        material.status = status
        if current_version_id is not None:
            material.current_version_id = current_version_id
        self.session.flush()
        return True

    def soft_delete_material(
        self,
        material_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> bool:
        """软删除资料：标记 is_deleted=True。

        Args:
            material_id: 资料主键。
            user_id: 租户用户标识。

        Returns:
            bool: 成功软删除返回 True，未找到或已删除返回 False。
        """
        material = self.get_material_by_id(material_id, user_id, include_deleted=False)
        if material is None:
            return False
        material.is_deleted = True
        self.session.flush()
        return True

    def hard_delete_material(
        self,
        material_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> bool:
        """物理级联销毁资料主表及关联数据。

        Args:
            material_id: 资料主键。
            user_id: 租户用户标识。

        Returns:
            bool: 成功删除返回 True，未找到或越权返回 False。
        """
        material = self.get_material_by_id(material_id, user_id, include_deleted=True)
        if material is None:
            return False
        self.session.delete(material)
        self.session.flush()
        return True

    # ==========================================
    # MaterialVersion 版本表操作
    # ==========================================

    def create_version(
        self,
        *,
        material_id: uuid.UUID,
        user_id: uuid.UUID,
        version_number: int,
        storage_key: str,
        content_hash: str,
        parse_status: str = ParseStatus.QUEUED.value,
        raw_text_storage_key: str | None = None,
        is_active: bool = True,
    ) -> MaterialVersion:
        """创建资料历史版本记录。

        Args:
            material_id: 归属资料主键。
            user_id: 租户用户标识。
            version_number: 递增版本号。
            storage_key: MinIO 原文件存储路径键。
            content_hash: 原文件 SHA-256 摘要。
            parse_status: 初始细粒度解析状态。
            raw_text_storage_key: 提取纯文本存储键。
            is_active: 是否为激活版本，默认 True。

        Returns:
            MaterialVersion: 已持久化的版本实体。
        """
        version = MaterialVersion(
            material_id=material_id,
            user_id=user_id,
            version_number=version_number,
            storage_key=storage_key,
            content_hash=content_hash,
            parse_status=parse_status,
            raw_text_storage_key=raw_text_storage_key,
            is_active=is_active,
        )
        self.session.add(version)
        self.session.flush()
        return version

    def get_version_by_id(
        self,
        version_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> MaterialVersion | None:
        """根据主键和所属用户查询版本详情。

        Args:
            version_id: 版本主键。
            user_id: 租户用户标识。

        Returns:
            MaterialVersion | None: 版本实体，不存在或越权返回 None。
        """
        stmt = select(MaterialVersion).where(
            MaterialVersion.id == version_id,
            MaterialVersion.user_id == user_id,
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def list_versions_by_material(
        self,
        material_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[MaterialVersion]:
        """查询指定资料所属的所有历史版本列表 (按版本号降序排序)。

        Args:
            material_id: 资料主键。
            user_id: 租户用户标识。

        Returns:
            list[MaterialVersion]: 版本实体列表。
        """
        stmt = (
            select(MaterialVersion)
            .where(
                MaterialVersion.material_id == material_id,
                MaterialVersion.user_id == user_id,
            )
            .order_by(MaterialVersion.version_number.desc())
        )
        return list(self.session.execute(stmt).scalars().all())

    def find_version_by_hash(
        self,
        user_id: uuid.UUID,
        content_hash: str,
    ) -> MaterialVersion | None:
        """根据内容 SHA-256 哈希查询用户所属最新版本。

        Args:
            user_id: 租户用户标识。
            content_hash: 待查重的 SHA-256 摘要。

        Returns:
            MaterialVersion | None: 命中的最新版本实体，无命中返回 None。
        """
        stmt = (
            select(MaterialVersion)
            .where(
                MaterialVersion.user_id == user_id,
                MaterialVersion.content_hash == content_hash,
            )
            .order_by(MaterialVersion.version_number.desc())
            .limit(1)
        )
        return self.session.execute(stmt).scalars().first()

    def get_latest_version(
        self,
        material_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> MaterialVersion | None:
        """获取指定资料的最新版本（按版本号降序第一条）。

        Args:
            material_id: 资料主键。
            user_id: 租户用户标识。

        Returns:
            MaterialVersion | None: 最新版本实体，不存在或越权返回 None。
        """
        stmt = (
            select(MaterialVersion)
            .where(
                MaterialVersion.material_id == material_id,
                MaterialVersion.user_id == user_id,
            )
            .order_by(MaterialVersion.version_number.desc())
            .limit(1)
        )
        return self.session.execute(stmt).scalars().first()

    def get_latest_version_by_hash(
        self,
        user_id: uuid.UUID,
        content_hash: str,
    ) -> MaterialVersion | None:
        """find_version_by_hash 别名方法。"""
        return self.find_version_by_hash(user_id=user_id, content_hash=content_hash)

    def update_version_status(
        self,
        version_id: uuid.UUID,
        user_id: uuid.UUID,
        status: str,
        error_message: str | None = None,
        *,
        failed_stage: str | None = None,
        raw_text_storage_key: str | None = None,
        is_active: bool | None = None,
        reset_errors: bool = False,
    ) -> bool:
        """更新版本细粒度解析状态与执行结果。

        Args:
            version_id: 版本主键。
            user_id: 租户用户标识。
            status: 细粒度解析状态 (ParseStatus)。
            error_message: 脱敏错误提示。
            failed_stage: 失败阶段标识。
            raw_text_storage_key: 提取文本存储键。
            is_active: 激活状态。
            reset_errors: 是否清空错误提示与失败阶段。

        Returns:
            bool: 成功更新返回 True，未找到或越权返回 False。
        """
        version = self.get_version_by_id(version_id, user_id)
        if version is None:
            return False
        version.parse_status = status
        if reset_errors:
            version.error_message = None
            version.failed_stage = None
        else:
            if error_message is not None:
                version.error_message = error_message
            if failed_stage is not None:
                version.failed_stage = failed_stage
        if raw_text_storage_key is not None:
            version.raw_text_storage_key = raw_text_storage_key
        if is_active is not None:
            version.is_active = is_active
        self.session.flush()
        return True

    def try_transition_version_status(
        self,
        version_id: uuid.UUID,
        material_id: uuid.UUID,
        *,
        from_status: str,
        to_status: str,
        reset_errors: bool = False,
    ) -> bool:
        """以条件更新原子地跃迁版本解析状态 (compare-and-swap)。

        解析派发是「用户命令 -> 置 QUEUED -> 入队」，若跃迁用「先读后写」，两个并发
        请求会凭同一次陈旧读各自入队一次，同一版本被两个 worker 同时解析（重复 OCR/
        LLM 开销与重复切片）。因此跃迁必须由数据库判定：只有真正把该行从
        ``from_status`` 改到 ``to_status`` 的调用返回 True。

        租户隔离由调用方先行校验资料归属保证；此处再以 ``material_id`` 收窄作用域。

        Args:
            version_id: 版本标识。
            material_id: 归属资料标识。
            from_status: 期望的当前解析状态。
            to_status: 目标解析状态。
            reset_errors: 是否同时清空 ``error_message`` 与 ``failed_stage``。

        Returns:
            bool: 是否由本次调用完成状态跃迁 (False 表示状态已被其他请求改变)。
        """
        values: dict[str, Any] = {"parse_status": to_status}
        if reset_errors:
            values["error_message"] = None
            values["failed_stage"] = None

        stmt = (
            update(MaterialVersion)
            .where(
                MaterialVersion.id == version_id,
                MaterialVersion.material_id == material_id,
                MaterialVersion.parse_status == from_status,
            )
            .values(**values)
            .execution_options(synchronize_session="fetch")
        )
        result = self.session.execute(stmt)
        self.session.flush()
        count = result.rowcount if isinstance(result, CursorResult) else 0
        return count == 1

    # ==========================================
    # MaterialSnippet 切片表操作
    # ==========================================

    def create_snippets(
        self,
        snippets: Sequence[MaterialSnippet],
    ) -> None:
        """批量创建知识切片实体。

        Args:
            snippets: 切片实体序列。
        """
        for snippet in snippets:
            self.session.add(snippet)
        self.session.flush()

    def bulk_create_snippets(
        self,
        snippets: Sequence[dict[str, Any]],
        user_id: uuid.UUID,
    ) -> int:
        """批量根据字典结构创建切片。

        Args:
            snippets: 切片参数字典序列。
            user_id: 租户用户标识。

        Returns:
            int: 写入成功的切片条数。
        """
        created = 0
        for item in snippets:
            snip = MaterialSnippet(
                user_id=user_id,
                material_id=item["material_id"],
                version_id=item["version_id"],
                snippet_index=item["snippet_index"],
                content=item["content"],
                char_length=item["char_length"],
                start_offset=item["start_offset"],
                end_offset=item["end_offset"],
                chapter_title=item.get("chapter_title", ""),
                source_info=item.get("source_info", {}),
                embedding=item.get("embedding"),
            )
            self.session.add(snip)
            created += 1
        self.session.flush()
        return created

    def get_snippets(
        self,
        version_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[MaterialSnippet]:
        """获取指定版本所属的全部知识切片。

        Args:
            version_id: 版本标识。
            user_id: 租户用户标识。

        Returns:
            list[MaterialSnippet]: 按序号递增排序的切片列表。
        """
        stmt = (
            select(MaterialSnippet)
            .where(
                MaterialSnippet.version_id == version_id,
                MaterialSnippet.user_id == user_id,
            )
            .order_by(MaterialSnippet.snippet_index.asc())
        )
        return list(self.session.execute(stmt).scalars().all())

    def list_snippets_by_version(
        self,
        version_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[MaterialSnippet]:
        """get_snippets 别名。"""
        return self.get_snippets(version_id=version_id, user_id=user_id)

    def list_snippets_by_ids(
        self,
        snippet_ids: Sequence[uuid.UUID],
        user_id: uuid.UUID,
    ) -> list[MaterialSnippet]:
        """批量按主键集合检索知识切片 (强制租户隔离)。

        Args:
            snippet_ids: 目标切片主键集合。
            user_id: 租户用户标识。

        Returns:
            list[MaterialSnippet]: 命中的切片实体列表；集合为空时返回空列表。
        """
        resolved_ids = list(snippet_ids)
        if not resolved_ids:
            return []
        stmt = select(MaterialSnippet).where(
            MaterialSnippet.id.in_(resolved_ids),
            MaterialSnippet.user_id == user_id,
        )
        return list(self.session.execute(stmt).scalars().all())

    def delete_snippets_by_version(
        self,
        version_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> int:
        """按版本清除全部切片（例如重新分块时）。

        Args:
            version_id: 版本标识。
            user_id: 租户用户标识。

        Returns:
            int: 实际删除的行数。
        """
        stmt = delete(MaterialSnippet).where(
            MaterialSnippet.version_id == version_id,
            MaterialSnippet.user_id == user_id,
        )
        result = self.session.execute(stmt)
        self.session.flush()
        count = result.rowcount if isinstance(result, CursorResult) else 0
        return int(count)

    # ==========================================
    # MaterialOCRPage 页级门禁表操作
    # ==========================================

    def create_ocr_pages(
        self,
        pages: Sequence[MaterialOCRPage],
    ) -> None:
        """批量创建页级 OCR 门禁记录。

        Args:
            pages: 页级实体序列。
        """
        for page in pages:
            self.session.add(page)
        self.session.flush()

    def bulk_create_ocr_pages(
        self,
        pages: Sequence[dict[str, Any]],
        user_id: uuid.UUID,
    ) -> int:
        """根据字典序列批量创建页级 OCR 记录。

        Args:
            pages: 页级记录字典序列。
            user_id: 租户用户标识。

        Returns:
            int: 写入成功的页面条数。
        """
        created = 0
        for item in pages:
            page = MaterialOCRPage(
                user_id=user_id,
                material_id=item["material_id"],
                version_id=item["version_id"],
                page_number=item["page_number"],
                image_storage_key=item["image_storage_key"],
                raw_text=item.get("raw_text", ""),
                gibberish_ratio=item.get("gibberish_ratio", 0.0),
                valid_char_count=item.get("valid_char_count", 0),
                is_qualified=item.get("is_qualified", True),
                unqualified_reason=item.get("unqualified_reason"),
                reshoot_count=item.get("reshoot_count", 0),
            )
            self.session.add(page)
            created += 1
        self.session.flush()
        return created

    def get_ocr_pages(
        self,
        version_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[MaterialOCRPage]:
        """获取版本全部 OCR 页记录。

        Args:
            version_id: 版本标识。
            user_id: 租户用户标识。

        Returns:
            list[MaterialOCRPage]: 按页码正序排序的页面列表。
        """
        stmt = (
            select(MaterialOCRPage)
            .where(
                MaterialOCRPage.version_id == version_id,
                MaterialOCRPage.user_id == user_id,
            )
            .order_by(MaterialOCRPage.page_number.asc())
        )
        return list(self.session.execute(stmt).scalars().all())

    def list_ocr_pages_by_version(
        self,
        version_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[MaterialOCRPage]:
        """get_ocr_pages 别名。"""
        return self.get_ocr_pages(version_id=version_id, user_id=user_id)

    def get_ocr_page(
        self,
        version_id: uuid.UUID,
        page_number: int,
        user_id: uuid.UUID,
    ) -> MaterialOCRPage | None:
        """按页码查询单页 OCR 记录。

        Args:
            version_id: 版本标识。
            page_number: 页码序号。
            user_id: 租户用户标识。

        Returns:
            MaterialOCRPage | None: 单页记录实体，不存在返回 None。
        """
        stmt = select(MaterialOCRPage).where(
            MaterialOCRPage.version_id == version_id,
            MaterialOCRPage.page_number == page_number,
            MaterialOCRPage.user_id == user_id,
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def update_ocr_page(
        self,
        *,
        page_id: uuid.UUID,
        user_id: uuid.UUID,
        raw_text: str,
        gibberish_ratio: float,
        valid_char_count: int,
        is_qualified: bool,
        unqualified_reason: str | None,
        reshoot_count: int,
        image_storage_key: str | None = None,
    ) -> bool:
        """更新单页 OCR 重拍与质检结果。

        Args:
            page_id: 页面主键。
            user_id: 租户用户标识。
            raw_text: 重新识别所得文本。
            gibberish_ratio: 乱码率。
            valid_char_count: 有效字数。
            is_qualified: 门禁合格标记。
            unqualified_reason: 不合格原因。
            reshoot_count: 递增后的重拍计数。
            image_storage_key: 新上传重拍图片存储键。

        Returns:
            bool: 成功更新返回 True，未找到或越权返回 False。
        """
        stmt = select(MaterialOCRPage).where(
            MaterialOCRPage.id == page_id,
            MaterialOCRPage.user_id == user_id,
        )
        page = self.session.execute(stmt).scalar_one_or_none()
        if page is None:
            return False
        page.raw_text = raw_text
        page.gibberish_ratio = gibberish_ratio
        page.valid_char_count = valid_char_count
        page.is_qualified = is_qualified
        page.unqualified_reason = unqualified_reason
        page.reshoot_count = reshoot_count
        if image_storage_key is not None:
            page.image_storage_key = image_storage_key
        self.session.flush()
        return True

    def update_ocr_page_result(
        self,
        page_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        raw_text: str,
        gibberish_ratio: float,
        valid_char_count: int,
        is_qualified: bool,
        unqualified_reason: str | None,
        reshoot_count: int,
        image_storage_key: str | None = None,
    ) -> bool:
        """update_ocr_page 别名。"""
        return self.update_ocr_page(
            page_id=page_id,
            user_id=user_id,
            raw_text=raw_text,
            gibberish_ratio=gibberish_ratio,
            valid_char_count=valid_char_count,
            is_qualified=is_qualified,
            unqualified_reason=unqualified_reason,
            reshoot_count=reshoot_count,
            image_storage_key=image_storage_key,
        )


__all__ = ["MaterialRepository"]
