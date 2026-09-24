"""Unit tests for QuestionRepository in app/repositories/question.py.

Verifies:
1. Question CRUD: create, batch create, read by id, list by knowledge point,
   list by material, list recent for deduplication, update, soft delete by id,
   soft delete by material.
2. QuestionQualityCheck batch creation and listing by batch and material.
3. QuestionAuditLog creation and listing by question.
4. Strict multi-tenant isolation (Anti-horizontal privilege escalation) preventing
   any cross-user data leakage, modification, or deletion.
"""

import uuid
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.base import Base
from app.models.knowledge import KnowledgePoint
from app.models.material import Material, MaterialSnippet, MaterialVersion
from app.models.question import (
    AuditAction,
    QualityCheckType,
    Question,
    QuestionAuditLog,
    QuestionQualityCheck,
    QuestionStatus,
    QuestionType,
)
from app.repositories.question import QuestionRepository


@pytest.fixture
def session() -> Generator[Session, None, None]:
    """Provides an isolated in-memory SQLite database session."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as sess:
        yield sess
    engine.dispose()


@pytest.fixture
def helper_setup(session: Session) -> dict[str, uuid.UUID]:
    """Sets up a material, version, and knowledge point for relationship testing."""
    user_id = uuid.uuid4()
    material_id = uuid.uuid4()
    version_id = uuid.uuid4()
    point_id = uuid.uuid4()
    snippet_id = uuid.uuid4()

    material = Material(
        id=material_id,
        user_id=user_id,
        title="软件工程导论.pdf",
        file_format="pdf",
        file_size=2048,
    )
    session.add(material)

    version = MaterialVersion(
        id=version_id,
        user_id=user_id,
        material_id=material_id,
        version_number=1,
        storage_key="materials/v1.pdf",
        content_hash="hash123456",
    )
    session.add(version)

    snippet = MaterialSnippet(
        id=snippet_id,
        user_id=user_id,
        material_id=material_id,
        version_id=version_id,
        snippet_index=0,
        content="敏捷开发是一种以人为核心、迭代、循序渐进的软件开发方法。",
        char_length=30,
        start_offset=0,
        end_offset=30,
        chapter_title="第一章 敏捷概述",
        source_info={"page_number": 1},
    )
    session.add(snippet)

    point = KnowledgePoint(
        id=point_id,
        user_id=user_id,
        material_id=material_id,
        version_id=version_id,
        name="敏捷开发核心概念",
        level=1,
        batch_id="batch_init_001",
    )
    session.add(point)
    session.commit()

    return {
        "user_id": user_id,
        "material_id": material_id,
        "version_id": version_id,
        "point_id": point_id,
        "snippet_id": snippet_id,
    }


class TestQuestionRepositoryCRUD:
    """Test suite for QuestionRepository CRUD operations."""

    def test_create_and_get_question(
        self, session: Session, helper_setup: dict[str, uuid.UUID]
    ) -> None:
        """Verify creating and retrieving a single question."""
        repo = QuestionRepository(session)
        user_id = helper_setup["user_id"]
        material_id = helper_setup["material_id"]
        version_id = helper_setup["version_id"]
        point_id = helper_setup["point_id"]
        snippet_id = helper_setup["snippet_id"]

        q = Question(
            material_id=material_id,
            version_id=version_id,
            knowledge_point_id=point_id,
            source_snippet_id=snippet_id,
            question_type=QuestionType.SINGLE_CHOICE.value,
            status=QuestionStatus.AVAILABLE.value,
            stem="下列关于敏捷开发的说法中正确的是？",
            options=[
                {"key": "A", "content": "敏捷开发强调文档至上"},
                {"key": "B", "content": "敏捷开发是一种以人为核心、迭代渐进的开发方法"},
            ],
            answer="B",
            analysis="敏捷宣言强调响应变化胜过遵循计划，以人为核心。",
            difficulty=2,
        )

        saved = repo.create_question(q, user_id)
        assert saved.id is not None
        assert saved.user_id == user_id

        fetched = repo.get_question_by_id(saved.id, user_id)
        assert fetched is not None
        assert fetched.id == saved.id
        assert fetched.stem == "下列关于敏捷开发的说法中正确的是？"
        assert fetched.options[1]["key"] == "B"

        # Verify alias get_by_id
        alias_fetched = repo.get_by_id(saved.id, user_id)
        assert alias_fetched is not None
        assert alias_fetched.id == saved.id

    def test_batch_create_and_list_by_knowledge_point(
        self, session: Session, helper_setup: dict[str, uuid.UUID]
    ) -> None:
        """Verify batch creation and listing by knowledge point."""
        repo = QuestionRepository(session)
        user_id = helper_setup["user_id"]
        material_id = helper_setup["material_id"]
        version_id = helper_setup["version_id"]
        point_id = helper_setup["point_id"]

        questions = [
            Question(
                material_id=material_id,
                version_id=version_id,
                knowledge_point_id=point_id,
                question_type=QuestionType.SINGLE_CHOICE.value,
                status=QuestionStatus.AVAILABLE.value,
                stem=f"单选题题干_{idx}：敏捷开发原则？",
                options=[{"key": "A", "content": "原则1"}],
                answer="A",
            )
            for idx in range(3)
        ]
        questions.append(
            Question(
                material_id=material_id,
                version_id=version_id,
                knowledge_point_id=point_id,
                question_type=QuestionType.SHORT_ANSWER.value,
                status=QuestionStatus.PENDING_REVIEW.value,
                stem="简答题：简述 Scrum 的三大支柱。",
                answer="透明、检视、适应",
            )
        )

        created = repo.batch_create_questions(questions, user_id)
        assert len(created) == 4

        # List all under knowledge point
        all_kp_questions = repo.list_questions_by_knowledge_point(point_id, user_id)
        assert len(all_kp_questions) == 4

        # List with status filter
        available = repo.list_by_knowledge_point(
            point_id, user_id, status=QuestionStatus.AVAILABLE.value
        )
        assert len(available) == 3

        pending = repo.list_questions_by_knowledge_point(
            point_id, user_id, status=QuestionStatus.PENDING_REVIEW.value
        )
        assert len(pending) == 1

    def test_list_by_material_and_deduplication(
        self, session: Session, helper_setup: dict[str, uuid.UUID]
    ) -> None:
        """Verify list_by_material and list_recent_for_deduplication."""
        repo = QuestionRepository(session)
        user_id = helper_setup["user_id"]
        material_id = helper_setup["material_id"]
        version_id = helper_setup["version_id"]
        point_id = helper_setup["point_id"]

        questions = [
            Question(
                material_id=material_id,
                version_id=version_id,
                knowledge_point_id=point_id,
                question_type=QuestionType.TRUE_FALSE.value,
                status=QuestionStatus.AVAILABLE.value,
                stem=f"判断题_{idx}：敏捷开发不写代码？",
                answer="错误",
            )
            for idx in range(5)
        ]
        # One deleted question and one pending question
        questions.append(
            Question(
                material_id=material_id,
                version_id=version_id,
                knowledge_point_id=point_id,
                question_type=QuestionType.TRUE_FALSE.value,
                status=QuestionStatus.AVAILABLE.value,
                stem="判断题_已软删除：已废弃？",
                answer="正确",
                is_deleted=True,
            )
        )
        questions.append(
            Question(
                material_id=material_id,
                version_id=version_id,
                knowledge_point_id=point_id,
                question_type=QuestionType.TRUE_FALSE.value,
                status=QuestionStatus.PENDING_REVIEW.value,
                stem="判断题_待审核：歧义题目？",
                answer="正确",
            )
        )
        repo.batch_create_questions(questions, user_id)

        # list_by_material without deleted
        mat_questions = repo.list_by_material(material_id, user_id)
        assert len(mat_questions) == 6

        # list_by_material with deleted
        mat_with_deleted = repo.list_questions_by_material(
            material_id, user_id, include_deleted=True
        )
        assert len(mat_with_deleted) == 7

        # list_by_material with version_id and status
        mat_version_avail = repo.list_by_material(
            material_id,
            user_id,
            version_id=version_id,
            status=QuestionStatus.AVAILABLE.value,
        )
        assert len(mat_version_avail) == 5

        # list_recent_for_deduplication only returns AVAILABLE and non-deleted
        dedup_questions = repo.list_recent_for_deduplication(material_id, user_id, limit=10)
        assert len(dedup_questions) == 5

    def test_update_and_soft_delete(
        self, session: Session, helper_setup: dict[str, uuid.UUID]
    ) -> None:
        """Verify update_question and soft_delete_question."""
        repo = QuestionRepository(session)
        user_id = helper_setup["user_id"]
        material_id = helper_setup["material_id"]
        version_id = helper_setup["version_id"]
        point_id = helper_setup["point_id"]

        q = Question(
            material_id=material_id,
            version_id=version_id,
            knowledge_point_id=point_id,
            question_type=QuestionType.SHORT_ANSWER.value,
            stem="简述看板方法。",
            answer="可视化工作流、限制在制品。",
            difficulty=3,
        )
        saved = repo.create_question(q, user_id)

        # Update difficulty and analysis
        updated = repo.update_question(
            saved.id,
            user_id,
            {"difficulty": 4, "analysis": "补充解析：度量提前期。"},
        )
        assert updated is not None
        assert updated.difficulty == 4
        assert updated.analysis == "补充解析：度量提前期。"

        # Attempting to tamper user_id or material_id is ignored
        another_user_id = uuid.uuid4()
        repo.update_question(saved.id, user_id, {"user_id": another_user_id})
        re_fetched = repo.get_question_by_id(saved.id, user_id)
        assert re_fetched is not None
        assert re_fetched.user_id == user_id

        # Soft delete
        deleted = repo.soft_delete_question(saved.id, user_id)
        assert deleted is True

        # Now get_question_by_id returns None unless include_deleted=True
        assert repo.get_question_by_id(saved.id, user_id) is None
        assert repo.get_question_by_id(saved.id, user_id, include_deleted=True) is not None

    def test_soft_delete_by_material(
        self, session: Session, helper_setup: dict[str, uuid.UUID]
    ) -> None:
        """Verify soft_delete_by_material affects matching questions."""
        repo = QuestionRepository(session)
        user_id = helper_setup["user_id"]
        material_id = helper_setup["material_id"]
        version_id = helper_setup["version_id"]
        point_id = helper_setup["point_id"]

        questions = [
            Question(
                material_id=material_id,
                version_id=version_id,
                knowledge_point_id=point_id,
                question_type=QuestionType.FILL_IN_BLANK.value,
                stem=f"填空题_{idx}：极限编程简写为_____",
                answer="XP",
            )
            for idx in range(4)
        ]
        repo.batch_create_questions(questions, user_id)

        affected = repo.soft_delete_by_material(material_id, user_id, version_id=version_id)
        assert affected == 4

        remaining = repo.list_by_material(material_id, user_id)
        assert len(remaining) == 0

    def test_quality_checks_and_audit_logs(
        self, session: Session, helper_setup: dict[str, uuid.UUID]
    ) -> None:
        """Verify QualityCheck and AuditLog batch and list operations."""
        repo = QuestionRepository(session)
        user_id = helper_setup["user_id"]
        material_id = helper_setup["material_id"]
        version_id = helper_setup["version_id"]
        point_id = helper_setup["point_id"]

        q = Question(
            material_id=material_id,
            version_id=version_id,
            knowledge_point_id=point_id,
            question_type=QuestionType.TRUE_FALSE.value,
            stem="判断题：CI/CD 指持续集成与持续交付。",
            answer="正确",
        )
        saved = repo.create_question(q, user_id)
        batch_id = "batch_test_001"

        checks = [
            QuestionQualityCheck(
                question_id=saved.id,
                batch_id=batch_id,
                check_type=QualityCheckType.NO_SOURCE.value,
                is_passed=True,
            ),
            QuestionQualityCheck(
                question_id=saved.id,
                batch_id=batch_id,
                check_type=QualityCheckType.DUPLICATE.value,
                is_passed=True,
                similarity_score=0.45,
            ),
        ]
        saved_checks = repo.batch_create_quality_checks(checks, user_id)
        assert len(saved_checks) == 2

        by_batch = repo.list_quality_checks_by_batch(batch_id, user_id)
        assert len(by_batch) == 2

        by_mat = repo.list_quality_checks_by_material(material_id, user_id)
        assert len(by_mat) == 2

        # Audit logs
        log = QuestionAuditLog(
            question_id=saved.id,
            action=AuditAction.EDIT.value,
            changed_fields=["stem"],
            before_payload={"stem": "old"},
            after_payload={"stem": "new"},
            reason="用户修正标点符号",
        )
        repo.create_audit_log(log, user_id)

        logs = repo.list_audit_logs_by_question(saved.id, user_id)
        assert len(logs) == 1
        assert logs[0].action == AuditAction.EDIT.value
        assert logs[0].reason == "用户修正标点符号"


class TestQuestionRepositoryTenantIsolation:
    """Test suite for strict multi-tenant isolation in QuestionRepository."""

    def test_tenant_cross_access_blocked(
        self, session: Session, helper_setup: dict[str, uuid.UUID]
    ) -> None:
        """Verify cross-tenant read/update/delete operations are blocked."""
        repo = QuestionRepository(session)
        user_a = helper_setup["user_id"]
        user_b = uuid.uuid4()
        material_id = helper_setup["material_id"]
        version_id = helper_setup["version_id"]
        point_id = helper_setup["point_id"]

        q = Question(
            material_id=material_id,
            version_id=version_id,
            knowledge_point_id=point_id,
            question_type=QuestionType.SINGLE_CHOICE.value,
            stem="租户测试题目：属于用户A？",
            options=[{"key": "A", "content": "是"}],
            answer="A",
        )
        saved = repo.create_question(q, user_a)

        # User B cannot read User A's question
        assert repo.get_question_by_id(saved.id, user_b) is None
        assert repo.list_questions_by_knowledge_point(point_id, user_b) == []
        assert repo.list_questions_by_material(material_id, user_b) == []
        assert repo.list_recent_for_deduplication(material_id, user_b) == []

        # User B cannot update User A's question
        update_result = repo.update_question(saved.id, user_b, {"stem": "篡改题干"})
        assert update_result is None

        # User B cannot soft delete User A's question
        assert repo.soft_delete_question(saved.id, user_b) is False
        assert repo.soft_delete_by_material(material_id, user_b) == 0

        # User B cannot list User A's quality checks or audit logs
        batch_id = "batch_user_a"
        check = QuestionQualityCheck(
            question_id=saved.id,
            batch_id=batch_id,
            check_type=QualityCheckType.NO_SOURCE.value,
            is_passed=True,
        )
        repo.batch_create_quality_checks([check], user_a)

        assert repo.list_quality_checks_by_batch(batch_id, user_b) == []
        assert repo.list_quality_checks_by_material(material_id, user_b) == []

        audit = QuestionAuditLog(
            question_id=saved.id,
            action=AuditAction.CREATE.value,
            changed_fields=["stem"],
        )
        repo.create_audit_log(audit, user_a)
        assert repo.list_audit_logs_by_question(saved.id, user_b) == []
