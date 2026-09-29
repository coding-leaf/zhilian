"""题目领域数据仓储模块。

封装针对 questions, question_quality_checks, question_audit_logs 表的数据库交互。
严格遵循 AGENTS.md 规范：
- 全仓储方法强制要求 user_id 参数并作为 SQL 过滤条件，严格阻断水平越权；
- 仓储层严禁导入 fastapi 与 app.integrations；
- 缩写白名单仅限 8 个 (api, id, url, ocr, llm, db, config, env)。
"""

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import and_, case, func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.models.knowledge import KnowledgePoint
from app.models.material import Material, MaterialFolder, MaterialStatus
from app.models.question import (
    Question,
    QuestionAuditLog,
    QuestionQualityCheck,
    QuestionStatus,
)


class QuestionRepository:
    """题目主表、质检记录与审计日志数据仓储。

    所有方法强制要求 user_id 作为租户过滤条件，杜绝任何水平越权。
    """

    def __init__(self, session: Session) -> None:
        """初始化题目仓储实例。

        Args:
            session: SQLAlchemy 数据库会话。
        """
        self.session = session

    # ==========================================
    # Question 题目主表 CRUD 操作
    # ==========================================

    def create_question(self, question: Question, user_id: uuid.UUID) -> Question:
        """创建单个题目实体并重写绑定 user_id。

        Args:
            question: 待持久化的题目实体。
            user_id: 租户用户标识。

        Returns:
            Question: 已持久化加入会话的题目实体。
        """
        question.user_id = user_id
        self.session.add(question)
        self.session.flush()
        return question

    def batch_create_questions(
        self,
        questions: Sequence[Question],
        user_id: uuid.UUID,
    ) -> list[Question]:
        """批量创建题目记录，强制校验并重写 user_id。

        Args:
            questions: 题目实体序列。
            user_id: 租户用户标识。

        Returns:
            list[Question]: 插入成功的题目实体列表。
        """
        created: list[Question] = []
        for item in questions:
            item.user_id = user_id
            self.session.add(item)
            created.append(item)
        self.session.flush()
        return created

    def get_question_by_id(
        self,
        question_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        include_deleted: bool = False,
    ) -> Question | None:
        """根据主键和租户用户查询单个题目。

        Args:
            question_id: 题目主键。
            user_id: 租户用户标识。
            include_deleted: 是否包含已软删除题目，默认 False。

        Returns:
            Question | None: 题目实体，不存在或越权返回 None。
        """
        stmt = select(Question).where(
            Question.id == question_id,
            Question.user_id == user_id,
        )
        if not include_deleted:
            stmt = stmt.where(Question.is_deleted.is_(False))
        return self.session.execute(stmt).scalar_one_or_none()

    get_by_id = get_question_by_id

    def list_questions_by_ids(
        self,
        question_ids: Sequence[uuid.UUID],
        user_id: uuid.UUID,
        *,
        include_deleted: bool = False,
    ) -> list[Question]:
        """批量根据主键列表和租户用户查询题目列表。

        Args:
            question_ids: 题目主键序列。
            user_id: 租户用户主键。
            include_deleted: 是否包含软删除记录，默认 False。

        Returns:
            list[Question]: 查询到的题目实体列表。
        """
        if not question_ids:
            return []
        stmt = select(Question).where(
            Question.id.in_(list(question_ids)),
            Question.user_id == user_id,
        )
        if not include_deleted:
            stmt = stmt.where(Question.is_deleted.is_(False))
        return list(self.session.execute(stmt).scalars().all())

    def list_questions_by_knowledge_point(
        self,
        knowledge_point_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        status: str | None = None,
        include_deleted: bool = False,
    ) -> list[Question]:
        """按知识点标识与租户用户查询题目列表。

        Args:
            knowledge_point_id: 知识点标识。
            user_id: 租户用户标识。
            status: 可选的题目状态过滤 (available / pending_review)。
            include_deleted: 是否包含已软删除题目，默认 False。

        Returns:
            list[Question]: 题目实体列表。
        """
        stmt = select(Question).where(
            Question.knowledge_point_id == knowledge_point_id,
            Question.user_id == user_id,
        )
        if not include_deleted:
            stmt = stmt.where(Question.is_deleted.is_(False))
        if status is not None:
            stmt = stmt.where(Question.status == status)

        stmt = stmt.order_by(Question.created_at.asc())
        return list(self.session.execute(stmt).scalars().all())

    list_by_knowledge_point = list_questions_by_knowledge_point

    def list_questions_by_material(
        self,
        material_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        version_id: uuid.UUID | None = None,
        status: str | None = None,
        include_deleted: bool = False,
        limit: int = 500,
    ) -> list[Question]:
        """按资料标识与租户用户查询题目列表。

        Args:
            material_id: 资料标识。
            user_id: 租户用户标识。
            version_id: 可选的资料版本标识过滤。
            status: 可选的题目状态过滤。
            include_deleted: 是否包含软删除题目，默认 False。
            limit: 最大返回条数，默认 500。

        Returns:
            list[Question]: 题目实体列表。
        """
        stmt = select(Question).where(
            Question.material_id == material_id,
            Question.user_id == user_id,
        )
        if version_id is not None:
            stmt = stmt.where(Question.version_id == version_id)
        if not include_deleted:
            stmt = stmt.where(Question.is_deleted.is_(False))
        if status is not None:
            stmt = stmt.where(Question.status == status)

        stmt = stmt.order_by(Question.created_at.desc()).limit(limit)
        return list(self.session.execute(stmt).scalars().all())

    list_by_material = list_questions_by_material

    def list_questions(
        self,
        user_id: uuid.UUID,
        *,
        material_id: uuid.UUID | None = None,
        folder_id: uuid.UUID | None = None,
        version_id: uuid.UUID | None = None,
        knowledge_point_id: uuid.UUID | None = None,
        question_type: str | None = None,
        difficulty: int | None = None,
        status: str | None = None,
        batch_id: str | None = None,
        unbatched: bool = False,
        include_deleted: bool = False,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Question], int]:
        """多条件筛选分页查询题目列表及匹配总数。

        Args:
            user_id: 租户用户标识。
            material_id: 可选的资料标识过滤。
            folder_id: 可选的课程文件夹标识过滤（按 materials.folder_id join，
                仅纳入未归档课程资料）。
            version_id: 可选的版本标识过滤。
            knowledge_point_id: 可选的知识点标识过滤。
            question_type: 可选的题型过滤。
            difficulty: 可选的难度过滤。
            status: 可选的状态过滤。
            batch_id: 可选的出题生成批次标识过滤。
            unbatched: 为 True 时只返回 ``batch_id IS NULL`` 的历史题目
                （``batch_id`` 过滤无法表达 IS NULL）。
            include_deleted: 是否包含已软删除题目，默认 False。
            limit: 单页记录数限制，默认 20。
            offset: 偏移游标，默认 0。

        Returns:
            tuple[list[Question], int]: (题目实体列表, 总匹配数)。
        """
        count_stmt = select(func.count(Question.id)).where(
            Question.user_id == user_id,
        )
        if not include_deleted:
            count_stmt = count_stmt.where(Question.is_deleted.is_(False))
        if material_id is not None:
            count_stmt = count_stmt.where(Question.material_id == material_id)
        if folder_id is not None:
            count_stmt = self._apply_folder_filter(count_stmt, folder_id, user_id)
        if version_id is not None:
            count_stmt = count_stmt.where(Question.version_id == version_id)
        if knowledge_point_id is not None:
            count_stmt = count_stmt.where(Question.knowledge_point_id == knowledge_point_id)
        if question_type is not None:
            count_stmt = count_stmt.where(Question.question_type == question_type)
        if difficulty is not None:
            count_stmt = count_stmt.where(Question.difficulty == difficulty)
        if status is not None:
            count_stmt = count_stmt.where(Question.status == status)
        if batch_id is not None:
            count_stmt = count_stmt.where(Question.batch_id == batch_id)
        if unbatched:
            count_stmt = count_stmt.where(Question.batch_id.is_(None))

        total = self.session.execute(count_stmt).scalar_one()

        stmt = select(Question).where(
            Question.user_id == user_id,
        )
        if not include_deleted:
            stmt = stmt.where(Question.is_deleted.is_(False))
        if material_id is not None:
            stmt = stmt.where(Question.material_id == material_id)
        if folder_id is not None:
            stmt = self._apply_folder_filter(stmt, folder_id, user_id)
        if version_id is not None:
            stmt = stmt.where(Question.version_id == version_id)
        if knowledge_point_id is not None:
            stmt = stmt.where(Question.knowledge_point_id == knowledge_point_id)
        if question_type is not None:
            stmt = stmt.where(Question.question_type == question_type)
        if difficulty is not None:
            stmt = stmt.where(Question.difficulty == difficulty)
        if status is not None:
            stmt = stmt.where(Question.status == status)
        if batch_id is not None:
            stmt = stmt.where(Question.batch_id == batch_id)
        if unbatched:
            stmt = stmt.where(Question.batch_id.is_(None))

        stmt = stmt.order_by(Question.created_at.desc()).offset(offset).limit(limit)
        items = list(self.session.execute(stmt).scalars().all())
        return items, int(total)

    @staticmethod
    def _apply_folder_filter(
        stmt: Any,
        folder_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Any:
        """为题目查询追加课程文件夹归属过滤（排除已归档课程资料）。

        Args:
            stmt: 待追加过滤的 SQLAlchemy 查询语句。
            folder_id: 课程文件夹主键。
            user_id: 租户用户标识。

        Returns:
            Any: 已追加 join 与 where 条件的新查询语句。
        """
        return (
            stmt.join(Material, Question.material_id == Material.id)
            .join(MaterialFolder, Material.folder_id == MaterialFolder.id)
            .where(
                Material.user_id == user_id,
                Material.folder_id == folder_id,
                MaterialFolder.archived_at.is_(None),
            )
        )

    # ==========================================
    # 出题批次聚合 (题库视图)
    # ==========================================

    def list_question_batches(
        self,
        user_id: uuid.UUID,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> list[tuple[str | None, int, int, datetime]]:
        """按出题批次聚合分页查询批次摘要。

        服务端 group by 完成聚合：前端按页拉取题目再本地分组会把题干正文
        一并传回，且请求数随题目总量线性增长。

        同一批次可横跨多份资料：``QuestionService.generate_questions_for_folder``
        按 (material_id, version_id) 分组生成却只分配一个 batch_id。

        Args:
            user_id: 租户用户标识。
            limit: 单页批次数量限制，默认 20。
            offset: 分页游标偏移量，默认 0。

        Returns:
            list[tuple[str | None, int, int, datetime]]: 每项为
                (批次标识 | None 表示未分批, 题量, 可用题量, 批次最早创建时间)，
                按批次最早创建时间倒序；``batch_id IS NULL`` 的历史题目单独成组。
        """
        # sum(case ...) 而非 count(*) FILTER：两种数据库都接受，SQLite 不必依赖 3.30+。
        available_count = func.sum(
            case((Question.status == QuestionStatus.AVAILABLE.value, 1), else_=0)
        ).label("available_count")
        first_created_at = func.min(Question.created_at).label("first_created_at")

        stmt = (
            select(
                Question.batch_id,
                func.count(Question.id).label("question_count"),
                available_count,
                first_created_at,
            )
            .where(
                Question.user_id == user_id,
                Question.is_deleted.is_(False),
            )
            .group_by(Question.batch_id)
            .order_by(first_created_at.desc(), Question.batch_id.asc())
            .limit(limit)
            .offset(offset)
        )
        rows = self.session.execute(stmt).all()
        return [(row[0], int(row[1]), int(row[2]), row[3]) for row in rows]

    def count_question_batches(self, user_id: uuid.UUID) -> int:
        """统计用户真实批次总数 (与 ``list_question_batches`` 同一 WHERE 条件)。

        Args:
            user_id: 租户用户标识。

        Returns:
            int: 未软删除题目覆盖的批次总数，含 ``batch_id IS NULL`` 的未分批组。
        """
        grouped = (
            select(Question.batch_id)
            .where(
                Question.user_id == user_id,
                Question.is_deleted.is_(False),
            )
            .group_by(Question.batch_id)
            .subquery()
        )
        total = self.session.execute(select(func.count()).select_from(grouped)).scalar_one()
        return int(total)

    def list_batch_sources(
        self,
        user_id: uuid.UUID,
        batch_ids: Sequence[str],
    ) -> list[tuple[str, uuid.UUID, str | None, uuid.UUID | None, str | None]]:
        """批量查询指定批次的来源资料集合 (仅针对本页批次，禁止逐批查询)。

        对 materials 与 material_folders 均使用 ``LEFT JOIN`` 且把租户条件写在
        ON 子句：资料已被物理删除时批次来源位保留为空值，由装配层给出可读降级标签，
        而不是因 JOIN 不中而整条批次从列表里消失。

        Args:
            user_id: 租户用户标识。
            batch_ids: 本页批次的非空批次标识集合。

        Returns:
            list[tuple[str, uuid.UUID, str | None, uuid.UUID | None, str | None]]:
                (批次标识, 资料主键, 资料标题, 课程主键, 课程名称)，已去重。
        """
        if not batch_ids:
            return []
        stmt = (
            select(
                Question.batch_id,
                Question.material_id,
                Material.title,
                Material.folder_id,
                MaterialFolder.name,
            )
            .outerjoin(
                Material,
                and_(
                    Material.id == Question.material_id,
                    Material.user_id == user_id,
                ),
            )
            .outerjoin(
                MaterialFolder,
                and_(
                    MaterialFolder.id == Material.folder_id,
                    MaterialFolder.user_id == user_id,
                ),
            )
            .where(
                Question.user_id == user_id,
                Question.is_deleted.is_(False),
                Question.batch_id.in_(list(batch_ids)),
            )
            .distinct()
        )
        rows = self.session.execute(stmt).all()
        return [(row[0], row[1], row[2], row[3], row[4]) for row in rows]

    def list_knowledge_points_for_folder(
        self,
        user_id: uuid.UUID,
        folder_id: uuid.UUID,
    ) -> list[KnowledgePoint]:
        """查询课程文件夹下全部 ready 未归档资料的知识点。

        用于课程范围出题的缺省考点集；仅纳入未归档课程、未软删除且解析就绪
        （``status == ready``）的资料。

        Args:
            user_id: 租户用户标识。
            folder_id: 课程文件夹主键。

        Returns:
            list[KnowledgePoint]: 按层级与创建时间排序的知识点列表。
        """
        stmt = (
            select(KnowledgePoint)
            .join(Material, KnowledgePoint.material_id == Material.id)
            .join(MaterialFolder, Material.folder_id == MaterialFolder.id)
            .where(
                KnowledgePoint.user_id == user_id,
                Material.user_id == user_id,
                Material.folder_id == folder_id,
                Material.is_deleted.is_(False),
                Material.status == MaterialStatus.READY.value,
                MaterialFolder.archived_at.is_(None),
            )
            .order_by(KnowledgePoint.level.asc(), KnowledgePoint.created_at.asc())
        )
        return list(self.session.execute(stmt).scalars().all())

    def list_folder_knowledge_points_with_material(
        self,
        user_id: uuid.UUID,
        folder_id: uuid.UUID,
    ) -> list[tuple[KnowledgePoint, uuid.UUID, str]]:
        """查询课程文件夹下 ready 资料的考点及其来源资料标识与标题。

        用于课程范围出题的「按资料分组考点选择」接口；口径与
        ``list_knowledge_points_for_folder`` 完全一致（仅未归档课程、未软删除、
        解析就绪资料），并附带资料标题以便前端分组展示。

        Args:
            user_id: 租户用户标识。
            folder_id: 课程文件夹主键。

        Returns:
            list[tuple[KnowledgePoint, uuid.UUID, str]]: (考点, 资料主键, 资料标题)。
        """
        stmt = (
            select(KnowledgePoint, Material.id, Material.title)
            .join(Material, KnowledgePoint.material_id == Material.id)
            .join(MaterialFolder, Material.folder_id == MaterialFolder.id)
            .where(
                KnowledgePoint.user_id == user_id,
                Material.user_id == user_id,
                Material.folder_id == folder_id,
                Material.is_deleted.is_(False),
                Material.status == MaterialStatus.READY.value,
                MaterialFolder.archived_at.is_(None),
            )
            .order_by(
                Material.created_at.asc(),
                KnowledgePoint.level.asc(),
                KnowledgePoint.created_at.asc(),
            )
        )
        return [(row[0], row[1], row[2]) for row in self.session.execute(stmt).all()]

    def list_material_ids_for_folder(
        self,
        user_id: uuid.UUID,
        folder_id: uuid.UUID,
        *,
        ready_only: bool = False,
    ) -> list[uuid.UUID]:
        """查询课程文件夹下未软删除且未归档的资料主键。

        Args:
            user_id: 租户用户标识。
            folder_id: 课程文件夹主键。
            ready_only: 是否仅纳入解析就绪（ready）资料，默认 False。

        Returns:
            list[uuid.UUID]: 归属该未归档课程的资料主键列表。
        """
        stmt = (
            select(Material.id)
            .join(MaterialFolder, Material.folder_id == MaterialFolder.id)
            .where(
                Material.user_id == user_id,
                Material.folder_id == folder_id,
                Material.is_deleted.is_(False),
                MaterialFolder.archived_at.is_(None),
            )
        )
        if ready_only:
            stmt = stmt.where(Material.status == MaterialStatus.READY.value)
        return [row[0] for row in self.session.execute(stmt).all()]

    def list_current_versions_for_folder(
        self, user_id: uuid.UUID, folder_id: uuid.UUID
    ) -> dict[uuid.UUID, uuid.UUID]:
        """Resolve ready current versions in one tenant-filtered query."""
        statement = (
            select(Material.id, Material.current_version_id)
            .join(MaterialFolder, Material.folder_id == MaterialFolder.id)
            .where(
                Material.user_id == user_id,
                MaterialFolder.user_id == user_id,
                Material.folder_id == folder_id,
                Material.is_deleted.is_(False),
                Material.status == MaterialStatus.READY.value,
                Material.current_version_id.is_not(None),
                MaterialFolder.archived_at.is_(None),
            )
        )
        return {row[0]: row[1] for row in self.session.execute(statement).all()}

    def list_recent_for_deduplication(
        self,
        material_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        limit: int = 500,
    ) -> list[Question]:
        """获取同资料下最近入库的合格题目作为质检比对基准。

        Args:
            material_id: 资料标识。
            user_id: 租户用户标识。
            limit: 比对窗口最大题数，默认 500。

        Returns:
            list[Question]: 供质检查重比对的历史题目列表。
        """
        stmt = (
            select(Question)
            .where(
                Question.material_id == material_id,
                Question.user_id == user_id,
                Question.is_deleted.is_(False),
                Question.status == QuestionStatus.AVAILABLE.value,
            )
            .order_by(Question.created_at.desc())
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars().all())

    def update_question(
        self,
        question_id: uuid.UUID,
        user_id: uuid.UUID,
        updates: dict[str, Any],
    ) -> Question | None:
        """更新题目实体信息，严格校验租户归属并禁止篡改主键与租户。

        Args:
            question_id: 题目主键。
            user_id: 租户用户标识。
            updates: 变更字段映射字典。

        Returns:
            Question | None: 更新后的题目实体，越权或不存在返回 None。
        """
        question = self.get_question_by_id(question_id, user_id, include_deleted=True)
        if question is None:
            return None

        forbidden_fields = {"id", "user_id", "material_id", "version_id"}
        for key, value in updates.items():
            if key not in forbidden_fields and hasattr(question, key):
                setattr(question, key, value)

        self.session.flush()
        return question

    def soft_delete_question(
        self,
        question_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> bool:
        """软删除单个题目，阻断任何水平越权。

        Args:
            question_id: 题目主键。
            user_id: 租户用户标识。

        Returns:
            bool: 软删除是否成功。
        """
        question = self.get_question_by_id(question_id, user_id, include_deleted=False)
        if question is None:
            return False

        question.is_deleted = True
        self.session.flush()
        return True

    soft_delete_by_id = soft_delete_question

    def soft_delete_by_material(
        self,
        material_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        version_id: uuid.UUID | None = None,
    ) -> int:
        """按资料标识批量软删除题目。

        Args:
            material_id: 资料标识。
            user_id: 租户用户标识。
            version_id: 可选的版本标识。

        Returns:
            int: 影响软删除的题目总数。
        """
        stmt = (
            update(Question)
            .where(
                Question.material_id == material_id,
                Question.user_id == user_id,
                Question.is_deleted.is_(False),
            )
            .values(is_deleted=True)
        )
        if version_id is not None:
            stmt = stmt.where(Question.version_id == version_id)

        result = self.session.execute(stmt)
        self.session.flush()
        count = result.rowcount if isinstance(result, CursorResult) else 0
        return int(count)

    # ==========================================
    # QuestionQualityCheck 质检记录操作
    # ==========================================

    def batch_create_quality_checks(
        self,
        checks: Sequence[QuestionQualityCheck],
        user_id: uuid.UUID,
    ) -> list[QuestionQualityCheck]:
        """批量创建题目质检结果记录。

        Args:
            checks: 质检实体记录序列。
            user_id: 租户用户标识。

        Returns:
            list[QuestionQualityCheck]: 已持久化的质检实体列表。
        """
        created: list[QuestionQualityCheck] = []
        for item in checks:
            item.user_id = user_id
            self.session.add(item)
            created.append(item)
        self.session.flush()
        return created

    def list_quality_checks_by_batch(
        self,
        batch_id: str,
        user_id: uuid.UUID,
    ) -> list[QuestionQualityCheck]:
        """按出题批次号查询质检记录列表。

        Args:
            batch_id: 出题生成批次号。
            user_id: 租户用户标识。

        Returns:
            list[QuestionQualityCheck]: 质检实体记录列表。
        """
        stmt = (
            select(QuestionQualityCheck)
            .where(
                QuestionQualityCheck.batch_id == batch_id,
                QuestionQualityCheck.user_id == user_id,
            )
            .order_by(QuestionQualityCheck.created_at.asc())
        )
        return list(self.session.execute(stmt).scalars().all())

    def list_quality_checks_by_material(
        self,
        material_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[QuestionQualityCheck]:
        """按资料标识联合查询所有关联题目的质检明细记录。

        Args:
            material_id: 资料标识。
            user_id: 租户用户标识。

        Returns:
            list[QuestionQualityCheck]: 质检实体记录列表。
        """
        stmt = (
            select(QuestionQualityCheck)
            .join(Question, QuestionQualityCheck.question_id == Question.id)
            .where(
                Question.material_id == material_id,
                Question.user_id == user_id,
                QuestionQualityCheck.user_id == user_id,
            )
            .order_by(QuestionQualityCheck.created_at.asc())
        )
        return list(self.session.execute(stmt).scalars().all())

    # ==========================================
    # QuestionAuditLog 审计日志操作
    # ==========================================

    def create_audit_log(
        self,
        audit_log: QuestionAuditLog,
        user_id: uuid.UUID,
    ) -> QuestionAuditLog:
        """创建单个题目修改痕迹不可变审计日志。

        Args:
            audit_log: 待保存的审计日志实体。
            user_id: 租户用户标识。

        Returns:
            QuestionAuditLog: 已保存的审计日志实体。
        """
        audit_log.user_id = user_id
        self.session.add(audit_log)
        self.session.flush()
        return audit_log

    create_edit_log = create_audit_log

    def list_audit_logs_by_question(
        self,
        question_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[QuestionAuditLog]:
        """根据题目标识与租户用户查询修改痕迹审计日志列表。

        Args:
            question_id: 题目主键。
            user_id: 租户用户标识。

        Returns:
            list[QuestionAuditLog]: 按时间倒序排序的审计日志列表。
        """
        stmt = (
            select(QuestionAuditLog)
            .where(
                QuestionAuditLog.question_id == question_id,
                QuestionAuditLog.user_id == user_id,
            )
            .order_by(QuestionAuditLog.created_at.desc())
        )
        return list(self.session.execute(stmt).scalars().all())

    list_edit_logs = list_audit_logs_by_question
