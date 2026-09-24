"""练习与答卷领域数据仓储模块。

封装针对 practices, attempt_items 表的数据库交互。
严格遵循 AGENTS.md 规范：
- 全仓储方法强制要求 user_id 参数并作为 SQL 过滤条件，严格阻断水平越权；
- 仓储层严禁导入 fastapi 与 app.integrations；
- 缩写白名单仅限 8 个 (api, id, url, ocr, llm, db, config, env)。
"""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import PracticeNotFoundError
from app.models.practice import AttemptItem, Practice, PracticeStatus


class PracticeRepository:
    """练习与作答项领域数据仓储。

    所有方法强制要求 user_id 作为租户过滤条件，杜绝任何水平越权。
    """

    def __init__(self, session: Session) -> None:
        """初始化练习仓储实例。

        Args:
            session: SQLAlchemy 数据库会话。
        """
        self.session = session

    # ==========================================
    # Practice 练习主表操作
    # ==========================================

    def create_practice(self, practice: Practice, user_id: uuid.UUID) -> Practice:
        """创建单个练习实体并重写绑定 user_id。

        Args:
            practice: 待持久化的练习实体。
            user_id: 租户用户标识。

        Returns:
            Practice: 已持久化加入会话的练习实体。
        """
        practice.user_id = user_id
        self.session.add(practice)
        self.session.flush()
        return practice

    def get_practice_by_id(
        self,
        practice_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        include_items: bool = True,
    ) -> Practice | None:
        """根据主键和租户用户查询单个练习。

        Args:
            practice_id: 练习主键。
            user_id: 租户用户标识。
            include_items: 是否预加载作答项列表，默认 True。

        Returns:
            Practice | None: 练习实体，不存在或越权返回 None。
        """
        stmt = select(Practice).where(
            Practice.id == practice_id,
            Practice.user_id == user_id,
        )
        if include_items:
            stmt = stmt.options(selectinload(Practice.items))
        return self.session.execute(stmt).scalars().first()

    def find_active_by_source_report(
        self,
        source_report_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Practice | None:
        """检索指定来源诊断报告且处于未开始 (not_started) 状态的练习。

        用于 FR-58 避免用户重复点击生成冗余练习会话。

        Args:
            source_report_id: 来源诊断报告标识。
            user_id: 租户用户标识。

        Returns:
            Practice | None: 命中的未开始练习实体，若无返回 None。
        """
        stmt = (
            select(Practice)
            .where(
                Practice.user_id == user_id,
                Practice.source_report_id == source_report_id,
                Practice.status == PracticeStatus.NOT_STARTED.value,
            )
            .order_by(Practice.created_at.desc())
            .limit(1)
        )
        return self.session.execute(stmt).scalars().first()

    def list_practices(
        self,
        user_id: uuid.UUID,
        *,
        material_id: uuid.UUID | None = None,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Practice]:
        """多维分页查询指定用户的练习列表。

        Args:
            user_id: 租户用户标识。
            material_id: 可选资料标识过滤。
            status: 可选练习状态过滤。
            limit: 分页大小，默认 20。
            offset: 分页偏移量，默认 0。

        Returns:
            list[Practice]: 练习实体列表。
        """
        stmt = select(Practice).where(Practice.user_id == user_id)
        if material_id is not None:
            stmt = stmt.where(Practice.material_id == material_id)
        if status is not None:
            stmt = stmt.where(Practice.status == status)

        stmt = stmt.order_by(Practice.created_at.desc()).limit(limit).offset(offset)
        return list(self.session.execute(stmt).scalars().all())

    def update_practice_status(
        self,
        practice_id: uuid.UUID,
        user_id: uuid.UUID,
        status: str,
        *,
        submit_idempotency_key: str | None = None,
        submitted_at: datetime | None = None,
    ) -> Practice | None:
        """更新练习生命周期状态与交卷相关属性。

        Args:
            practice_id: 练习标识。
            user_id: 租户用户标识。
            status: 新练习状态。
            submit_idempotency_key: 交卷幂等键。
            submitted_at: 交卷提交时间戳。

        Returns:
            Practice | None: 更新后的练习实体，不存在或越权返回 None。
        """
        practice = self.get_practice_by_id(practice_id, user_id, include_items=False)
        if practice is None:
            return None

        practice.status = status
        if submit_idempotency_key is not None:
            practice.submit_idempotency_key = submit_idempotency_key
        if submitted_at is not None:
            practice.submitted_at = submitted_at

        self.session.flush()
        return practice

    # ==========================================
    # AttemptItem 作答项操作
    # ==========================================

    def create_attempt_items(
        self,
        items: Sequence[AttemptItem],
        user_id: uuid.UUID,
    ) -> list[AttemptItem]:
        """批量创建练习作答项快照，强制重写并校验 user_id。

        Args:
            items: 作答项实体列表。
            user_id: 租户用户标识。

        Returns:
            list[AttemptItem]: 已加入会话的作答项实体列表。
        """
        created: list[AttemptItem] = []
        for item in items:
            item.user_id = user_id
            self.session.add(item)
            created.append(item)
        self.session.flush()
        return created

    def list_attempt_items(
        self,
        practice_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[AttemptItem]:
        """查询指定练习的所有作答项，严格按 order_index 升序排列。

        Args:
            practice_id: 关联练习主键。
            user_id: 租户用户标识。

        Returns:
            list[AttemptItem]: 有序的作答项实体列表。
        """
        stmt = (
            select(AttemptItem)
            .where(
                AttemptItem.practice_id == practice_id,
                AttemptItem.user_id == user_id,
            )
            .order_by(AttemptItem.order_index.asc())
        )
        return list(self.session.execute(stmt).scalars().all())

    def get_attempt_item(
        self,
        practice_id: uuid.UUID,
        question_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> AttemptItem | None:
        """根据练习标识、题目弱外键及租户标识检索单个作答项。

        Args:
            practice_id: 练习主键。
            question_id: 题目主键。
            user_id: 租户用户标识。

        Returns:
            AttemptItem | None: 作答项实体，不存在或越权返回 None。
        """
        stmt = select(AttemptItem).where(
            AttemptItem.practice_id == practice_id,
            AttemptItem.question_id == question_id,
            AttemptItem.user_id == user_id,
        )
        return self.session.execute(stmt).scalars().first()

    def save_answer(
        self,
        practice_id: uuid.UUID,
        question_id: uuid.UUID,
        user_id: uuid.UUID,
        user_answer: str | None,
        duration_seconds: int = 0,
    ) -> AttemptItem:
        """逐题作答保存（原子更新已存在的作答项）。

        Args:
            practice_id: 练习主键。
            question_id: 题目主键。
            user_id: 租户用户标识。
            user_answer: 用户作答文本或选项标识。
            duration_seconds: 本次作答累加耗时（秒）。

        Returns:
            AttemptItem: 更新后的作答项实体。

        Raises:
            PracticeNotFoundError: 作答项不存在或无权访问。
        """
        item = self.get_attempt_item(practice_id, question_id, user_id)
        if item is None:
            raise PracticeNotFoundError(
                "请求的作答题目不存在或无权访问",
                details={
                    "practice_id": str(practice_id),
                    "question_id": str(question_id),
                },
            )

        item.user_answer = user_answer
        item.is_answered = bool(user_answer is not None and user_answer.strip() != "")
        if duration_seconds > 0:
            item.duration_seconds += duration_seconds

        self.session.flush()
        return item

    save_attempt_answer = save_answer

    def count_unanswered_items(
        self,
        practice_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> int:
        """统计练习中未作答题目总数 (is_answered == False)。

        Args:
            practice_id: 练习主键。
            user_id: 租户用户标识。

        Returns:
            int: 未作答题目数量。
        """
        stmt = select(func.count(AttemptItem.id)).where(
            AttemptItem.practice_id == practice_id,
            AttemptItem.user_id == user_id,
            AttemptItem.is_answered.is_(False),
        )
        count_val = self.session.execute(stmt).scalar()
        return int(count_val or 0)

    def count_answered_items(
        self,
        practice_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> int:
        """统计练习中已作答题目总数 (is_answered == True)。

        Args:
            practice_id: 练习主键。
            user_id: 租户用户标识。

        Returns:
            int: 已作答题目数量。
        """
        stmt = select(func.count(AttemptItem.id)).where(
            AttemptItem.practice_id == practice_id,
            AttemptItem.user_id == user_id,
            AttemptItem.is_answered.is_(True),
        )
        count_val = self.session.execute(stmt).scalar()
        return int(count_val or 0)

    def count_total_items(
        self,
        practice_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> int:
        """统计练习中的作答项总数。

        Args:
            practice_id: 练习主键。
            user_id: 租户用户标识。

        Returns:
            int: 作答项总数。
        """
        stmt = select(func.count(AttemptItem.id)).where(
            AttemptItem.practice_id == practice_id,
            AttemptItem.user_id == user_id,
        )
        count_val = self.session.execute(stmt).scalar()
        return int(count_val or 0)


__all__ = [
    "PracticeRepository",
]
