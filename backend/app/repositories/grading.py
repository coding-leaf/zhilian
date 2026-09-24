"""混合判题记录与审计追踪领域数据仓储模块。

封装针对 grading_records 表的数据库交互与多渠道历史追溯。
严格遵循 AGENTS.md 规范：
- 全仓储方法强制要求 user_id 参数并作为 SQL 过滤条件，严格阻断水平越权；
- 仓储层严禁导入 fastapi 与 app.integrations；
- 缩写白名单仅限 8 个 (api, id, url, ocr, llm, db, config, env)。
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.practice import GradingRecord, GradingStatus


class GradingRepository:
    """混合判题记录数据仓储。

    所有方法强制要求 user_id 作为租户过滤条件，杜绝任何水平越权。
    支持离线规则、AI 判题、用户自评与异步重判多版本审计溯源。
    """

    def __init__(self, session: Session) -> None:
        """初始化判题记录仓储实例。

        Args:
            session: SQLAlchemy 数据库会话。
        """
        self.session = session

    def create_record(self, record: GradingRecord, user_id: uuid.UUID) -> GradingRecord:
        """创建单个判题记录实体并强制绑定租户 user_id。

        Args:
            record: 待持久化的判题记录实体。
            user_id: 租户用户标识。

        Returns:
            GradingRecord: 已持久化加入会话的判题记录实体。
        """
        record.user_id = user_id
        self.session.add(record)
        self.session.flush()
        return record

    create_grading_record = create_record

    def batch_create_records(
        self,
        records: Sequence[GradingRecord],
        user_id: uuid.UUID,
    ) -> list[GradingRecord]:
        """批量创建判题记录，强制重写并校验租户 user_id。

        Args:
            records: 待持久化的判题记录实体序列。
            user_id: 租户用户标识。

        Returns:
            list[GradingRecord]: 已加入会话的判题记录列表。
        """
        created: list[GradingRecord] = []
        for record in records:
            record.user_id = user_id
            self.session.add(record)
            created.append(record)
        self.session.flush()
        return created

    batch_create_grading_records = batch_create_records

    def get_record_by_id(
        self,
        record_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> GradingRecord | None:
        """根据主键和租户用户标识查询单个判题记录。

        Args:
            record_id: 判题记录主键 UUID。
            user_id: 租户用户标识。

        Returns:
            GradingRecord | None: 命中的判题记录，不存在或越权返回 None。
        """
        stmt = select(GradingRecord).where(
            GradingRecord.id == record_id,
            GradingRecord.user_id == user_id,
        )
        return self.session.execute(stmt).scalars().first()

    get_grading_record_by_id = get_record_by_id

    def list_records_by_attempt_item(
        self,
        attempt_item_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[GradingRecord]:
        """查询指定作答项的所有判题历史记录，按创建时间升序排列。

        Args:
            attempt_item_id: 作答项标识。
            user_id: 租户用户标识。

        Returns:
            list[GradingRecord]: 判题历史记录列表。
        """
        stmt = (
            select(GradingRecord)
            .where(
                GradingRecord.attempt_item_id == attempt_item_id,
                GradingRecord.user_id == user_id,
            )
            .order_by(GradingRecord.created_at.asc())
        )
        return list(self.session.execute(stmt).scalars().all())

    list_records_by_attempt_id = list_records_by_attempt_item

    def get_final_record_for_attempt(
        self,
        attempt_item_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> GradingRecord | None:
        """获取指定作答项当前生效的最终判题记录 (is_final == True)。

        Args:
            attempt_item_id: 作答项标识。
            user_id: 租户用户标识。

        Returns:
            GradingRecord | None: 当前生效的判题记录，若无返回 None。
        """
        stmt = (
            select(GradingRecord)
            .where(
                GradingRecord.attempt_item_id == attempt_item_id,
                GradingRecord.user_id == user_id,
                GradingRecord.is_final.is_(True),
            )
            .order_by(GradingRecord.created_at.desc())
            .limit(1)
        )
        return self.session.execute(stmt).scalars().first()

    get_final_record_by_attempt_id = get_final_record_for_attempt

    def list_final_records_by_practice(
        self,
        practice_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[GradingRecord]:
        """查询指定练习中所有作答项当前生效的判题记录 (is_final == True)。

        Args:
            practice_id: 关联练习主键。
            user_id: 租户用户标识。

        Returns:
            list[GradingRecord]: 生效判题记录列表。
        """
        stmt = (
            select(GradingRecord)
            .where(
                GradingRecord.practice_id == practice_id,
                GradingRecord.user_id == user_id,
                GradingRecord.is_final.is_(True),
            )
            .order_by(GradingRecord.created_at.asc())
        )
        return list(self.session.execute(stmt).scalars().all())

    list_final_records_by_practice_id = list_final_records_by_practice

    def update_final_flag(
        self,
        attempt_item_id: uuid.UUID,
        user_id: uuid.UUID,
        is_final: bool,
    ) -> int:
        """原子更新指定作答项的所有判题记录生效指针。

        Args:
            attempt_item_id: 作答项标识。
            user_id: 租户用户标识。
            is_final: 目标生效状态布尔值。

        Returns:
            int: 实际受影响更新的记录行数。
        """
        stmt = (
            update(GradingRecord)
            .where(
                GradingRecord.attempt_item_id == attempt_item_id,
                GradingRecord.user_id == user_id,
            )
            .values(is_final=is_final)
        )
        result = self.session.execute(stmt)
        self.session.flush()
        return int(result.rowcount or 0)

    def set_records_non_final_by_attempt_id(
        self,
        attempt_item_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> int:
        """将指定作答项的所有判题记录置为失效 (is_final = False)。

        Args:
            attempt_item_id: 作答项标识。
            user_id: 租户用户标识。

        Returns:
            int: 实际受影响更新的记录行数。
        """
        return self.update_final_flag(attempt_item_id, user_id, is_final=False)

    def count_pending_regrade(
        self,
        practice_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> int:
        """统计练习中当前生效且处于待重判状态的题目数量 (status == pending_regrade)。

        Args:
            practice_id: 关联练习主键。
            user_id: 租户用户标识。

        Returns:
            int: 待重判生效记录数量。
        """
        stmt = select(func.count(GradingRecord.id)).where(
            GradingRecord.practice_id == practice_id,
            GradingRecord.user_id == user_id,
            GradingRecord.is_final.is_(True),
            GradingRecord.status == GradingStatus.PENDING_REGRADE.value,
        )
        count_val = self.session.execute(stmt).scalar()
        return int(count_val or 0)

    count_pending_regrade_by_practice_id = count_pending_regrade


__all__ = [
    "GradingRepository",
]
