"""学情诊断、掌握度沉淀与错题本领域数据仓储模块。

封装针对 diagnosis_reports, mastery_records, wrong_records 表的数据库交互。
严格遵循 AGENTS.md 规范：
- 全仓储方法强制要求 user_id 参数并作为 SQL 过滤条件，严格阻断水平越权；
- 仓储层严禁导入 fastapi 与 app.integrations；
- 缩写白名单仅限 8 个 (api, id, url, ocr, llm, db, config, env)。
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.knowledge import KnowledgePoint
from app.models.material import Material, MaterialFolder
from app.models.practice import (
    AttemptItem,
    DiagnosisReport,
    GradingRecord,
    MasteryRecord,
    WrongRecord,
)
from app.models.question import Question


class DiagnosisRepository:
    """学情诊断、掌握度与错题本领域数据仓储。

    所有方法强制要求 user_id 作为租户过滤条件，杜绝任何水平越权。
    """

    def __init__(self, session: Session) -> None:
        """初始化诊断仓储实例。

        Args:
            session: SQLAlchemy 数据库会话。
        """
        self.session = session

    # ==========================================
    # DiagnosisReport 诊断报告主表操作
    # ==========================================

    def create_diagnosis_report(
        self,
        report: DiagnosisReport,
        user_id: uuid.UUID,
    ) -> DiagnosisReport:
        """创建单个诊断报告实体并绑定租户 user_id。

        Args:
            report: 待持久化的诊断报告实体。
            user_id: 租户用户标识。

        Returns:
            DiagnosisReport: 已持久化加入会话的诊断报告实体。
        """
        report.user_id = user_id
        self.session.add(report)
        self.session.flush()
        return report

    def get_diagnosis_report_by_id(
        self,
        report_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> DiagnosisReport | None:
        """根据报告主键与租户用户标识查询诊断报告。

        Args:
            report_id: 诊断报告主键。
            user_id: 租户用户标识。

        Returns:
            DiagnosisReport | None: 命中的诊断报告实体，未命中返回 None。
        """
        statement = select(DiagnosisReport).where(
            DiagnosisReport.id == report_id,
            DiagnosisReport.user_id == user_id,
        )
        return self.session.execute(statement).scalar_one_or_none()

    def get_diagnosis_report_by_practice_id(
        self,
        practice_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> DiagnosisReport | None:
        """根据关联练习主键与租户用户标识查询诊断报告。

        Args:
            practice_id: 练习主键。
            user_id: 租户用户标识。

        Returns:
            DiagnosisReport | None: 命中的诊断报告实体，未命中返回 None。
        """
        statement = select(DiagnosisReport).where(
            DiagnosisReport.practice_id == practice_id,
            DiagnosisReport.user_id == user_id,
        )
        return self.session.execute(statement).scalar_one_or_none()

    def list_diagnosis_reports_by_user(
        self,
        user_id: uuid.UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> list[DiagnosisReport]:
        """分页获取指定租户用户的诊断报告列表。

        Args:
            user_id: 租户用户标识。
            limit: 每页最大返回记录数，默认 20。
            offset: 分页偏移量，默认 0。

        Returns:
            list[DiagnosisReport]: 诊断报告实体列表。
        """
        statement = (
            select(DiagnosisReport)
            .where(DiagnosisReport.user_id == user_id)
            .order_by(DiagnosisReport.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.execute(statement).scalars().all())

    list_diagnosis_reports = list_diagnosis_reports_by_user

    # ==========================================
    # MasteryRecord 知识点掌握度持久化操作
    # ==========================================

    def get_mastery_record(
        self,
        knowledge_point_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> MasteryRecord | None:
        """查询指定租户用户针对单一知识点的掌握度记录。

        Args:
            knowledge_point_id: 知识点标识。
            user_id: 租户用户标识。

        Returns:
            MasteryRecord | None: 命中的掌握度实体，未命中返回 None。
        """
        statement = select(MasteryRecord).where(
            MasteryRecord.knowledge_point_id == knowledge_point_id,
            MasteryRecord.user_id == user_id,
        )
        return self.session.execute(statement).scalar_one_or_none()

    def list_mastery_records_by_knowledge_point_ids(
        self,
        knowledge_point_ids: Sequence[uuid.UUID],
        user_id: uuid.UUID,
    ) -> list[MasteryRecord]:
        """批量获取指定知识点集合在当前租户下的掌握度记录。

        Args:
            knowledge_point_ids: 知识点标识序列。
            user_id: 租户用户标识。

        Returns:
            list[MasteryRecord]: 命中的掌握度实体列表。
        """
        if not knowledge_point_ids:
            return []
        statement = select(MasteryRecord).where(
            MasteryRecord.user_id == user_id,
            MasteryRecord.knowledge_point_id.in_(knowledge_point_ids),
        )
        return list(self.session.execute(statement).scalars().all())

    list_mastery_records_by_points = list_mastery_records_by_knowledge_point_ids

    def list_mastery_records_by_user(
        self,
        user_id: uuid.UUID,
    ) -> list[MasteryRecord]:
        """获取指定租户用户全部知识点的掌握度记录。

        Args:
            user_id: 租户用户标识。

        Returns:
            list[MasteryRecord]: 掌握度实体列表。
        """
        statement = (
            select(MasteryRecord)
            .where(MasteryRecord.user_id == user_id)
            .order_by(MasteryRecord.updated_at.desc())
        )
        return list(self.session.execute(statement).scalars().all())

    def list_mastery_records_by_material(
        self,
        material_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[MasteryRecord]:
        """获取指定学习资料下所有知识点的租户掌握度记录。

        通过内联关联 KnowledgePoint 实体，严格约束租户隔离。

        Args:
            material_id: 学习资料标识。
            user_id: 租户用户标识。

        Returns:
            list[MasteryRecord]: 掌握度实体列表。
        """
        statement = (
            select(MasteryRecord)
            .join(
                KnowledgePoint,
                MasteryRecord.knowledge_point_id == KnowledgePoint.id,
            )
            .where(
                MasteryRecord.user_id == user_id,
                KnowledgePoint.material_id == material_id,
                KnowledgePoint.user_id == user_id,
            )
            .order_by(MasteryRecord.updated_at.desc())
        )
        return list(self.session.execute(statement).scalars().all())

    def upsert_mastery_record(
        self,
        *,
        user_id: uuid.UUID,
        knowledge_point_id: uuid.UUID,
        mastery_score: float,
        level: str,
        practice_count: int,
        correct_count: int,
        last_practiced_at: datetime | None,
        decayed_at: datetime | None,
        recent_records_snapshot: list[dict[str, Any]],
    ) -> MasteryRecord:
        """防重插入或更新知识点掌握度记录。

        Args:
            user_id: 租户用户标识。
            knowledge_point_id: 知识点标识。
            mastery_score: 连续掌握度数值 (0.0~1.0)。
            level: 掌握度等级 (MasteryLevel)。
            practice_count: 累计有效作答题数。
            correct_count: 累计正确题数。
            last_practiced_at: 最后有效作答时间。
            decayed_at: 上次衰减计算时间。
            recent_records_snapshot: 最近作答记录快照元数据列表 (至多 200 条)。

        Returns:
            MasteryRecord: 持久化或更新后的掌握度实体。
        """
        record = self.get_mastery_record(knowledge_point_id, user_id)
        if record is None:
            record = MasteryRecord(
                user_id=user_id,
                knowledge_point_id=knowledge_point_id,
                mastery_score=mastery_score,
                level=level,
                practice_count=practice_count,
                correct_count=correct_count,
                last_practiced_at=last_practiced_at,
                decayed_at=decayed_at,
                recent_records_snapshot=recent_records_snapshot,
            )
            self.session.add(record)
        else:
            record.mastery_score = mastery_score
            record.level = level
            record.practice_count = practice_count
            record.correct_count = correct_count
            record.last_practiced_at = last_practiced_at
            record.decayed_at = decayed_at
            record.recent_records_snapshot = recent_records_snapshot

        self.session.flush()
        return record

    def get_attempt_history_for_knowledge_point(
        self,
        knowledge_point_id: uuid.UUID,
        user_id: uuid.UUID,
        limit: int = 200,
    ) -> list[tuple[AttemptItem, GradingRecord | None]]:
        """获取指定知识点下用户的历史有效作答项与最终生效判题记录。

        Args:
            knowledge_point_id: 知识点标识。
            user_id: 租户用户标识。
            limit: 最大返回记录数，默认 200。

        Returns:
            list[tuple[AttemptItem, GradingRecord | None]]: 作答项与生效判题记录元组列表。
        """
        statement = (
            select(AttemptItem, GradingRecord)
            .join(
                Question,
                AttemptItem.question_id == Question.id,
            )
            .outerjoin(
                GradingRecord,
                (GradingRecord.attempt_item_id == AttemptItem.id)
                & (GradingRecord.is_final.is_(True))
                & (GradingRecord.user_id == user_id),
            )
            .where(
                AttemptItem.user_id == user_id,
                Question.knowledge_point_id == knowledge_point_id,
                Question.user_id == user_id,
            )
            .order_by(AttemptItem.created_at.desc())
            .limit(limit)
        )
        results = self.session.execute(statement).all()
        return [(row[0], row[1]) for row in results]

    # ==========================================
    # WrongRecord 错题本持久化操作
    # ==========================================

    def get_wrong_record(
        self,
        question_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> WrongRecord | None:
        """根据题目标识与租户用户标识查询错题记录。

        Args:
            question_id: 关联题目标识。
            user_id: 租户用户标识。

        Returns:
            WrongRecord | None: 命中的错题实体，未命中返回 None。
        """
        statement = select(WrongRecord).where(
            WrongRecord.question_id == question_id,
            WrongRecord.user_id == user_id,
        )
        return self.session.execute(statement).scalar_one_or_none()

    def get_wrong_record_by_id(
        self,
        record_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> WrongRecord | None:
        """根据错题记录主键与租户用户标识查询错题记录。

        Args:
            record_id: 错题记录主键。
            user_id: 租户用户标识。

        Returns:
            WrongRecord | None: 命中的错题实体，未命中返回 None。
        """
        statement = select(WrongRecord).where(
            WrongRecord.id == record_id,
            WrongRecord.user_id == user_id,
        )
        return self.session.execute(statement).scalar_one_or_none()

    def upsert_wrong_record(
        self,
        *,
        user_id: uuid.UUID,
        question_id: uuid.UUID | None,
        knowledge_point_id: uuid.UUID,
        practice_id: uuid.UUID | None,
        attempt_item_id: uuid.UUID | None,
        error_type: str,
        question_snapshot: dict[str, Any],
        last_wrong_answer: str | None = None,
    ) -> WrongRecord:
        """防重插入或累加更新错题记录。

        若已存在同用户该题错题，累加 error_count，重置 is_mastered 为 False，刷新快照与作答；
        若不存在，创建全新错题记录。

        **练习归属契约**：错题记录的 practice_id / attempt_item_id 一旦写下，
        不会被后续无归属（传 None）的 upsert 清除——手工标记路径没有练习归属，
        无权抹掉判题路径写下的真实来源。只有非 None 入参才会覆盖这两个字段。

        Args:
            user_id: 租户用户标识。
            question_id: 关联题目标识。
            knowledge_point_id: 关联知识点标识。
            practice_id: 最近答错练习标识；None = 无练习归属（手工标记），不覆盖已有值。
            attempt_item_id: 最近答错作答项标识；None 同上。
            error_type: 错误分类 (ErrorType)。
            question_snapshot: 题目快照字典。
            last_wrong_answer: 最近一次错误作答内容。

        Returns:
            WrongRecord: 持久化或累加更新后的错题记录。
        """
        record: WrongRecord | None = None
        if question_id is not None:
            record = self.get_wrong_record(question_id, user_id)

        if record is None:
            record = WrongRecord(
                user_id=user_id,
                question_id=question_id,
                knowledge_point_id=knowledge_point_id,
                practice_id=practice_id,
                attempt_item_id=attempt_item_id,
                error_type=error_type,
                error_count=1,
                is_mastered=False,
                question_snapshot=question_snapshot,
                last_wrong_answer=last_wrong_answer,
                mastered_at=None,
            )
            self.session.add(record)
        else:
            record.error_count += 1
            record.is_mastered = False
            record.mastered_at = None
            record.knowledge_point_id = knowledge_point_id
            # None = 本次调用没有练习归属（手工标记）：不得抹掉判题写下的真实来源。
            if practice_id is not None:
                record.practice_id = practice_id
            if attempt_item_id is not None:
                record.attempt_item_id = attempt_item_id
            record.error_type = error_type
            record.question_snapshot = question_snapshot
            record.last_wrong_answer = last_wrong_answer

        self.session.flush()
        return record

    def mark_wrong_record_mastered(
        self,
        question_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        *,
        is_mastered: bool = True,
        wrong_record_id: uuid.UUID | None = None,
        record_id: uuid.UUID | None = None,
    ) -> WrongRecord | None:
        """标记或取消指定错题记录的攻克掌握状态。

        Args:
            question_id: 题目标识。
            user_id: 租户用户标识。
            is_mastered: 目标攻克状态，默认 True (向后兼容)。
            wrong_record_id: 错题记录主键 (可选)。
            record_id: 错题记录主键别名 (可选)。

        Returns:
            WrongRecord | None: 更新后的错题实体，未命中返回 None。
        """
        if user_id is None:
            return None
        target_record_id = wrong_record_id or record_id
        if target_record_id is not None:
            record = self.get_wrong_record_by_id(target_record_id, user_id)
        elif question_id is not None:
            record = self.get_wrong_record(question_id, user_id)
        else:
            return None

        if record is None:
            return None
        record.is_mastered = is_mastered
        record.mastered_at = datetime.now(UTC) if is_mastered else None
        self.session.flush()
        return record

    def update_wrong_record_status(
        self,
        question_id: uuid.UUID,
        user_id: uuid.UUID,
        is_mastered: bool,
    ) -> WrongRecord | None:
        """更新指定错题的攻克掌握状态。

        Args:
            question_id: 题目标识。
            user_id: 租户用户标识。
            is_mastered: 是否已攻克掌握。

        Returns:
            WrongRecord | None: 更新后的错题实体，未命中返回 None。
        """
        record = self.get_wrong_record(question_id, user_id)
        if record is None:
            return None
        record.is_mastered = is_mastered
        record.mastered_at = datetime.now(UTC) if is_mastered else None
        self.session.flush()
        return record

    def list_wrong_records(
        self,
        user_id: uuid.UUID,
        is_mastered: bool | None = None,
        knowledge_point_id: uuid.UUID | None = None,
        material_id: uuid.UUID | None = None,
        folder_id: uuid.UUID | None = None,
        unclassified: bool = False,
        error_type: str | None = None,
        question_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[WrongRecord]:
        """多维度过滤查询租户用户的错题列表。

        Args:
            user_id: 租户用户标识。
            is_mastered: 攻克掌握状态过滤 (None 表示不限)。
            knowledge_point_id: 指定知识点过滤 (None 表示不限)。
            material_id: 指定学习资料过滤 (通过 KnowledgePoint 关联, None 表示不限)。
            error_type: 错误类型精确过滤 (None 表示不限)。
            question_type: 题目快照题型过滤 (None 表示不限)。
            limit: 最大返回记录数，默认 50。
            offset: 分页偏移量，默认 0。

        Returns:
            list[WrongRecord]: 错题实体列表。
        """
        statement = select(WrongRecord).where(WrongRecord.user_id == user_id)
        if material_id is not None or folder_id is not None or unclassified:
            statement = statement.join(
                KnowledgePoint,
                WrongRecord.knowledge_point_id == KnowledgePoint.id,
            ).where(KnowledgePoint.user_id == user_id)
            if material_id is not None:
                statement = statement.where(KnowledgePoint.material_id == material_id)
            if folder_id is not None or unclassified:
                statement = statement.join(
                    Material, KnowledgePoint.material_id == Material.id
                ).where(Material.user_id == user_id)
                if folder_id is not None:
                    statement = statement.where(Material.folder_id == folder_id)
                if unclassified:
                    statement = statement.where(Material.folder_id.is_(None))
        if is_mastered is not None:
            statement = statement.where(WrongRecord.is_mastered == is_mastered)
        if knowledge_point_id is not None:
            statement = statement.where(WrongRecord.knowledge_point_id == knowledge_point_id)
        if error_type is not None:
            statement = statement.where(WrongRecord.error_type == error_type)
        if question_type is not None:
            statement = statement.where(
                WrongRecord.question_snapshot["question_type"].as_string() == question_type
            )

        statement = statement.order_by(WrongRecord.updated_at.desc()).offset(offset).limit(limit)
        return list(self.session.execute(statement).scalars().all())

    def count_wrong_records(
        self,
        user_id: uuid.UUID,
        is_mastered: bool | None = None,
        knowledge_point_id: uuid.UUID | None = None,
        material_id: uuid.UUID | None = None,
        folder_id: uuid.UUID | None = None,
        unclassified: bool = False,
        error_type: str | None = None,
        question_type: str | None = None,
    ) -> int:
        """统计符合过滤条件的租户用户错题总数 (与 list_wrong_records 同条件)。

        Args:
            user_id: 租户用户标识。
            is_mastered: 攻克掌握状态过滤 (None 表示不限)。
            knowledge_point_id: 指定知识点过滤 (None 表示不限)。
            material_id: 指定学习资料过滤 (通过 KnowledgePoint 关联, None 表示不限)。
            error_type: 错误类型精确过滤 (None 表示不限)。
            question_type: 题目快照题型过滤 (None 表示不限)。

        Returns:
            int: 符合过滤条件的错题总数。
        """
        statement = (
            select(func.count()).select_from(WrongRecord).where(WrongRecord.user_id == user_id)
        )
        if material_id is not None or folder_id is not None or unclassified:
            statement = statement.join(
                KnowledgePoint,
                WrongRecord.knowledge_point_id == KnowledgePoint.id,
            ).where(KnowledgePoint.user_id == user_id)
            if material_id is not None:
                statement = statement.where(KnowledgePoint.material_id == material_id)
            if folder_id is not None or unclassified:
                statement = statement.join(
                    Material, KnowledgePoint.material_id == Material.id
                ).where(Material.user_id == user_id)
                if folder_id is not None:
                    statement = statement.where(Material.folder_id == folder_id)
                if unclassified:
                    statement = statement.where(Material.folder_id.is_(None))
        if is_mastered is not None:
            statement = statement.where(WrongRecord.is_mastered == is_mastered)
        if knowledge_point_id is not None:
            statement = statement.where(WrongRecord.knowledge_point_id == knowledge_point_id)
        if error_type is not None:
            statement = statement.where(WrongRecord.error_type == error_type)
        if question_type is not None:
            statement = statement.where(
                WrongRecord.question_snapshot["question_type"].as_string() == question_type
            )

        return int(self.session.execute(statement).scalar_one())

    def get_wrong_record_scopes(
        self, user_id: uuid.UUID, knowledge_point_ids: set[uuid.UUID]
    ) -> dict[uuid.UUID, tuple[uuid.UUID, uuid.UUID | None]]:
        """Batch-resolve each wrong record's source material and course."""
        if not knowledge_point_ids:
            return {}
        rows = self.session.execute(
            select(KnowledgePoint.id, Material.id, Material.folder_id)
            .join(Material, Material.id == KnowledgePoint.material_id)
            .where(
                KnowledgePoint.id.in_(knowledge_point_ids),
                KnowledgePoint.user_id == user_id,
                Material.user_id == user_id,
            )
        ).all()
        return {point_id: (material_id, folder_id) for point_id, material_id, folder_id in rows}

    def list_wrong_record_groups(
        self, user_id: uuid.UUID, is_mastered: bool | None = None
    ) -> list[tuple[uuid.UUID | None, str | None, uuid.UUID, str, int]]:
        """Count all wrong records per material, preserving unclassified sources."""
        statement = (
            select(
                Material.folder_id,
                MaterialFolder.name,
                Material.id,
                Material.title,
                func.count(WrongRecord.id),
            )
            .select_from(WrongRecord)
            .join(KnowledgePoint, WrongRecord.knowledge_point_id == KnowledgePoint.id)
            .join(Material, KnowledgePoint.material_id == Material.id)
            .outerjoin(MaterialFolder, Material.folder_id == MaterialFolder.id)
            .where(
                WrongRecord.user_id == user_id,
                KnowledgePoint.user_id == user_id,
                Material.user_id == user_id,
            )
            .group_by(Material.folder_id, MaterialFolder.name, Material.id, Material.title)
        )
        if is_mastered is not None:
            statement = statement.where(WrongRecord.is_mastered == is_mastered)
        return [
            (folder_id, folder_name, material_id, material_title, int(count))
            for folder_id, folder_name, material_id, material_title, count in self.session.execute(
                statement
            ).all()
        ]

    def delete_wrong_record(
        self,
        record_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> bool:
        """删除指定错题记录。

        Args:
            record_id: 错题记录主键。
            user_id: 租户用户标识。

        Returns:
            bool: 若成功删除返回 True，未命中或越权返回 False。
        """
        record = self.get_wrong_record_by_id(record_id, user_id)
        if record is None:
            return False
        self.session.delete(record)
        self.session.flush()
        return True

    remove_wrong_record = delete_wrong_record
