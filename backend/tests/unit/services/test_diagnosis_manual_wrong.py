"""DiagnosisService 手动标记错题 (题库 → 错题本) 单元测试模块。

覆盖 PRD `09-29-manual-wrong-mark` 的后端契约：

1. AC-1 手动标记：只收 question_id，知识点由服务端从题目解析；对已有错题记录的
   题目重复标记是幂等更新（仍只有 1 条，error_count 累加、is_mastered 重置）。
2. AC-2 快照不合法（如选择题 options 不足 2 项）→ 抛错且数据库无新增记录。
3. AC-4 手工路径不得抹掉判题路径写下的 practice_id / attempt_item_id。
4. 租户隔离与软删除题目：跨租户/已删除题目一律 QuestionNotFoundError (40009)。
5. AC-6（**有界**）手动错题进入「举一反三」的再生题范围：断言按错题聚合出的知识点
   包含该题的知识点（即 `collectUnmasteredKnowledgePointIds` 所需的输入成立）。
   **不**断言该考点真的被练到——`regenerateFromWrongPoints` 的 question_count
   截断缺陷属 `09-29-question-bank-tab`，不在本任务范围（见 PRD F8）。
"""

import uuid
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import AppError, QuestionNotFoundError
from app.models.base import Base
from app.models.knowledge import KnowledgePoint
from app.models.material import Material, MaterialVersion
from app.models.practice import ErrorType, WrongRecord, build_question_snapshot
from app.models.question import Question, QuestionStatus
from app.repositories.diagnosis import DiagnosisRepository
from app.services.diagnosis import DiagnosisService


@pytest.fixture
def session() -> Generator[Session, None, None]:
    """提供隔离的内存 SQLite 数据库会话（照模型建表，含可空归属列）。"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as sess:
        yield sess
    engine.dispose()


def seed_question(
    session: Session,
    *,
    user_id: uuid.UUID,
    options: list[dict[str, str]] | None = None,
    answer: str = "B",
    is_deleted: bool = False,
) -> Question:
    """造一道属于指定用户的单选题目及其资料/知识点前置数据。"""
    material_id = uuid.uuid4()
    version_id = uuid.uuid4()
    point_id = uuid.uuid4()
    question_id = uuid.uuid4()

    session.add_all(
        [
            Material(
                id=material_id,
                user_id=user_id,
                title="网络协议教材.pdf",
                file_format="pdf",
                file_size=2048,
            ),
            MaterialVersion(
                id=version_id,
                material_id=material_id,
                user_id=user_id,
                version_number=1,
                storage_key="raw/v1.pdf",
                content_hash=f"hash_{version_id.hex[:8]}",
            ),
            KnowledgePoint(
                id=point_id,
                material_id=material_id,
                version_id=version_id,
                user_id=user_id,
                name="TCP三次握手",
                batch_id="batch_001",
            ),
        ]
    )
    question = Question(
        id=question_id,
        user_id=user_id,
        material_id=material_id,
        version_id=version_id,
        knowledge_point_id=point_id,
        question_type="single_choice",
        status=QuestionStatus.AVAILABLE.value,
        is_deleted=is_deleted,
        stem="TCP 建立连接需要几次握手？",
        options=options
        if options is not None
        else [
            {"key": "A", "content": "一次"},
            {"key": "B", "content": "三次"},
        ],
        answer=answer,
        analysis="三次握手用于同步双方初始序列号。",
        difficulty=3,
        grading_rubric={},
        source_snippet_ids=[],
    )
    session.add(question)
    session.commit()
    return question


def wrong_records_of(session: Session, user_id: uuid.UUID) -> list[WrongRecord]:
    """读取该用户落库的全部错题记录。"""
    statement = select(WrongRecord).where(WrongRecord.user_id == user_id)
    return list(session.execute(statement).scalars().all())


class TestMarkQuestionAsWrong:
    """手动标记错题的创建、幂等、快照门禁与租户隔离。"""

    def test_creates_manual_wrong_record_without_practice_provenance(
        self, session: Session
    ) -> None:
        """AC-1：手工记录 practice_id / attempt_item_id 为 NULL，error_type 为 manual。"""
        user_id = uuid.uuid4()
        question = seed_question(session, user_id=user_id)
        service = DiagnosisService(session=session)

        record = service.mark_question_as_wrong(
            user_id=user_id,
            question_id=question.id,
        )

        assert record.practice_id is None
        assert record.attempt_item_id is None
        assert record.error_type == ErrorType.MANUAL.value
        assert record.error_count == 1
        assert record.is_mastered is False
        assert record.knowledge_point_id == question.knowledge_point_id
        # 快照与判题路径共用同一构造器：形状一致是两条来源渲染一致的前提。
        assert record.question_snapshot == build_question_snapshot(question)

    def test_repeat_mark_is_idempotent_update(self, session: Session) -> None:
        """AC-1：重复标记仍是 1 条记录，error_count 累加、is_mastered 重置。"""
        user_id = uuid.uuid4()
        question = seed_question(session, user_id=user_id)
        service = DiagnosisService(session=session)

        first = service.mark_question_as_wrong(user_id=user_id, question_id=question.id)
        first.is_mastered = True
        session.commit()

        second = service.mark_question_as_wrong(user_id=user_id, question_id=question.id)

        assert second.id == first.id
        assert second.error_count == 2
        assert second.is_mastered is False
        assert len(wrong_records_of(session, user_id)) == 1

    def test_manual_mark_preserves_judged_provenance(self, session: Session) -> None:
        """AC-4：手工标记不得抹掉判题路径写下的练习归属（端到端走 service）。"""
        user_id = uuid.uuid4()
        question = seed_question(session, user_id=user_id)
        service = DiagnosisService(session=session)

        practice_id = uuid.uuid4()
        attempt_item_id = uuid.uuid4()
        judged = service.diagnosis_repo.upsert_wrong_record(
            user_id=user_id,
            question_id=question.id,
            knowledge_point_id=question.knowledge_point_id,
            practice_id=practice_id,
            attempt_item_id=attempt_item_id,
            error_type=ErrorType.CONCEPTUAL.value,
            question_snapshot=build_question_snapshot(question),
        )
        session.commit()

        manual = service.mark_question_as_wrong(user_id=user_id, question_id=question.id)

        assert manual.id == judged.id
        assert manual.practice_id == practice_id
        assert manual.attempt_item_id == attempt_item_id
        assert manual.error_count == 2

    def test_invalid_snapshot_fails_without_writing(self, session: Session) -> None:
        """AC-2：选择题选项不足 2 项 → 40008 且数据库无新增记录。"""
        user_id = uuid.uuid4()
        question = seed_question(
            session, user_id=user_id, options=[{"key": "A", "content": "一次"}]
        )
        service = DiagnosisService(session=session)

        with pytest.raises(AppError) as exc_info:
            service.mark_question_as_wrong(user_id=user_id, question_id=question.id)

        assert exc_info.value.error_code == 40008
        assert exc_info.value.status_code == 400
        assert exc_info.value.details["question_id"] == str(question.id)
        assert exc_info.value.details["reason"]
        assert wrong_records_of(session, user_id) == []

    def test_empty_answer_fails_without_writing(self, session: Session) -> None:
        """AC-2：题干/答案缺失（answer 为空串）同样拒绝，不写一条渲染不出来的错题。"""
        user_id = uuid.uuid4()
        question = seed_question(session, user_id=user_id, answer="")
        service = DiagnosisService(session=session)

        with pytest.raises(AppError) as exc_info:
            service.mark_question_as_wrong(user_id=user_id, question_id=question.id)

        assert exc_info.value.error_code == 40008
        assert wrong_records_of(session, user_id) == []

    def test_other_tenant_question_is_not_found(self, session: Session) -> None:
        """租户隔离：标记他人题目一律 404/40009，且不产生记录。"""
        owner_id = uuid.uuid4()
        intruder_id = uuid.uuid4()
        question = seed_question(session, user_id=owner_id)
        service = DiagnosisService(session=session)

        with pytest.raises(QuestionNotFoundError) as exc_info:
            service.mark_question_as_wrong(user_id=intruder_id, question_id=question.id)

        assert exc_info.value.error_code == 40009
        assert wrong_records_of(session, intruder_id) == []

    def test_soft_deleted_question_is_not_found(self, session: Session) -> None:
        """软删除题目不可标记：它已与题库解耦，不该再出现在错题本里。"""
        user_id = uuid.uuid4()
        question = seed_question(session, user_id=user_id, is_deleted=True)
        service = DiagnosisService(session=session)

        with pytest.raises(QuestionNotFoundError):
            service.mark_question_as_wrong(user_id=user_id, question_id=question.id)

        assert wrong_records_of(session, user_id) == []

    def test_manual_record_enters_regeneration_scope(self, session: Session) -> None:
        """AC-6（有界）：手工错题的知识点必须出现在按错题聚合出的再生题范围里。

        断言的是「举一反三」收集知识点时的输入成立：手动错题在错题列表里可见、
        is_mastered=False、knowledge_point_id 非空且等于该题的考点。
        **不**据此推断该考点真的被练到（question_count 静默截断缺陷属父任务 C）。
        """
        user_id = uuid.uuid4()
        question = seed_question(session, user_id=user_id)
        service = DiagnosisService(session=session)

        service.mark_question_as_wrong(user_id=user_id, question_id=question.id)

        records, total = service.list_wrong_records(user_id=user_id)
        assert total == 1
        assert [r.question_id for r in records] == [question.id]
        # 前端 `collectUnmasteredKnowledgePointIds` 正是按这两个条件收集再生题考点。
        regenerate_scope = {
            r.knowledge_point_id for r in records if not r.is_mastered and r.knowledge_point_id
        }
        assert regenerate_scope == {question.knowledge_point_id}


class TestManualWrongRecordProvenance:
    """手工记录与判题记录的来源判据（前端取消标记分道所依赖的字段语义）。"""

    def test_manual_records_are_identified_by_null_practice_id(self, session: Session) -> None:
        """`practice_id IS NULL` 即「手工创建」，无需额外 source 列。"""
        repo = DiagnosisRepository(session)
        user_id = uuid.uuid4()
        manual_question = seed_question(session, user_id=user_id)
        judged_question = seed_question(session, user_id=user_id)

        repo.upsert_wrong_record(
            user_id=user_id,
            question_id=manual_question.id,
            knowledge_point_id=manual_question.knowledge_point_id,
            practice_id=None,
            attempt_item_id=None,
            error_type=ErrorType.MANUAL.value,
            question_snapshot=build_question_snapshot(manual_question),
        )
        repo.upsert_wrong_record(
            user_id=user_id,
            question_id=judged_question.id,
            knowledge_point_id=judged_question.knowledge_point_id,
            practice_id=uuid.uuid4(),
            attempt_item_id=uuid.uuid4(),
            error_type=ErrorType.CONCEPTUAL.value,
            question_snapshot=build_question_snapshot(judged_question),
        )
        session.commit()

        manual_ids = {
            record.question_id
            for record in wrong_records_of(session, user_id)
            if record.practice_id is None
        }
        assert manual_ids == {manual_question.id}
