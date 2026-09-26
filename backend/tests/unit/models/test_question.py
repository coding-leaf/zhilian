"""Unit tests for Question, QuestionQualityCheck, and QuestionAuditLog persistence models.

Covers the 7 question types, 6 key elements, rubric validation, quality check logs,
audit trails, soft deletion, desensitized __repr__, and Alembic migration symmetry.
"""

import importlib
import uuid
from collections.abc import Generator
from datetime import datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.models.base import Base
from app.models.knowledge import KnowledgePoint
from app.models.material import Material, MaterialDocType, MaterialSnippet, MaterialVersion
from app.models.question import (
    AuditAction,
    QualityCheckType,
    Question,
    QuestionAuditLog,
    QuestionQualityCheck,
    QuestionStatus,
    QuestionType,
    validate_question_payload,
)
from app.models.user import User


@pytest.fixture
def db_session() -> Generator[sessionmaker[Session], None, None]:
    """Creates an in-memory SQLite database session factory for question tests."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory: sessionmaker[Session] = sessionmaker(bind=engine)
    try:
        yield session_factory
    finally:
        engine.dispose()


@pytest.fixture
def setup_question_context(
    db_session: sessionmaker[Session],
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """Fixture providing user, material, version, knowledge point, and snippet."""
    user_id = uuid.uuid4()
    material_id = uuid.uuid4()
    version_id = uuid.uuid4()
    kp_id = uuid.uuid4()
    snippet_id = uuid.uuid4()

    with db_session() as session:
        user = User(id=user_id, openid=f"test_q_user_{user_id.hex[:8]}")
        session.add(user)
        session.commit()

        material = Material(
            id=material_id,
            user_id=user_id,
            title="Database System Concepts",
            file_format=MaterialDocType.PDF.value,
            file_size=2048000,
        )
        session.add(material)
        session.commit()

        version = MaterialVersion(
            id=version_id,
            user_id=user_id,
            material_id=material_id,
            version_number=1,
            storage_key="materials/db_v1.pdf",
            content_hash="content_hash_db_01",
        )
        session.add(version)
        session.commit()

        kp = KnowledgePoint(
            id=kp_id,
            user_id=user_id,
            material_id=material_id,
            version_id=version_id,
            parent_id=None,
            name="ACID Properties",
            level=1,
            batch_id="batch_q_001",
        )
        snippet = MaterialSnippet(
            id=snippet_id,
            user_id=user_id,
            material_id=material_id,
            version_id=version_id,
            snippet_index=0,
            content="Atomicity ensures that all operations within the work unit are completed.",
            char_length=76,
            start_offset=0,
            end_offset=76,
        )
        session.add_all([kp, snippet])
        session.commit()

    return user_id, material_id, version_id, kp_id, snippet_id


class TestQuestionEnumsAndPayloadValidation:
    """Test suite for Question enums and validate_question_payload pure function."""

    def test_question_types_and_status_enums(self) -> None:
        """Verify all 7 question types, status, and audit/check enums."""
        assert QuestionType.SINGLE_CHOICE.value == "single_choice"
        assert QuestionType.MULTIPLE_CHOICE.value == "multiple_choice"
        assert QuestionType.TRUE_FALSE.value == "true_false"
        assert QuestionType.FILL_IN_BLANK.value == "fill_in_blank"
        assert QuestionType.TERM_EXPLANATION.value == "term_explanation"
        assert QuestionType.SHORT_ANSWER.value == "short_answer"
        assert QuestionType.CASE_ANALYSIS.value == "case_analysis"

        assert QuestionStatus.AVAILABLE.value == "available"
        assert QuestionStatus.PENDING_REVIEW.value == "pending_review"

        assert QualityCheckType.NO_SOURCE.value == "NO_SOURCE"
        assert QualityCheckType.DUPLICATE.value == "DUPLICATE"
        assert QualityCheckType.ANSWER_CONFLICT.value == "ANSWER_CONFLICT"
        assert QualityCheckType.AMBIGUITY.value == "AMBIGUITY"

        assert AuditAction.CREATE.value == "CREATE"
        assert AuditAction.EDIT.value == "EDIT"
        assert AuditAction.DELETE.value == "DELETE"
        assert AuditAction.REGENERATE.value == "REGENERATE"

    def test_validate_question_payload_validation_branches(self) -> None:
        """Verify negative branches of validate_question_payload."""
        # Missing or empty stem
        res, err = validate_question_payload({"stem": ""})
        assert res is False and "stem" in str(err)

        res, err = validate_question_payload({"stem": 123})  # type: ignore[dict-item]
        assert res is False and "stem" in str(err)

        # Missing question_type
        res, err = validate_question_payload({"stem": "valid stem"})
        assert res is False and "question_type" in str(err)

        # Missing or empty answer
        res, err = validate_question_payload(
            {"stem": "valid", "question_type": QuestionType.FILL_IN_BLANK.value, "answer": ""}
        )
        assert res is False and "answer" in str(err)

        # Option invalid structure
        res, err = validate_question_payload(
            {
                "stem": "valid",
                "question_type": QuestionType.SINGLE_CHOICE.value,
                "answer": "A",
                "options": [{"key": "A"}],  # missing content
            }
        )
        assert res is False and "content" in str(err)

        res, err = validate_question_payload(
            {
                "stem": "valid",
                "question_type": QuestionType.SINGLE_CHOICE.value,
                "answer": "A",
                "options": ["invalid_option_str"],  # type: ignore[list-item]
            }
        )
        assert res is False and "content" in str(err)

    def test_validate_question_payload_subjective_rubric(self) -> None:
        """Verify payload validation for subjective rubric points score summing to total_score."""
        # Valid subjective rubric: 4 + 3 + 3 = 10
        valid_payload = {
            "stem": "Explain the two-phase locking protocol (2PL).",
            "question_type": QuestionType.SHORT_ANSWER.value,
            "answer": "Growing phase and shrinking phase...",
            "grading_rubric": {
                "total_score": 10,
                "points": [
                    {"point_id": 1, "score": 4, "description": "Growing phase definition"},
                    {"point_id": 2, "score": 3, "description": "Shrinking phase definition"},
                    {"point_id": 3, "score": 3, "description": "Serializability guarantee"},
                ],
            },
        }
        is_valid, err = validate_question_payload(valid_payload)
        assert is_valid is True
        assert err is None

        # Invalid subjective rubric: 4 + 3 = 7 != 10
        invalid_payload = {
            "stem": "Explain the two-phase locking protocol (2PL).",
            "question_type": QuestionType.SHORT_ANSWER.value,
            "answer": "Growing phase and shrinking phase...",
            "grading_rubric": {
                "total_score": 10,
                "points": [
                    {"point_id": 1, "score": 4, "description": "Growing phase"},
                    {"point_id": 2, "score": 3, "description": "Shrinking phase"},
                ],
            },
        }
        is_valid, err = validate_question_payload(invalid_payload)
        assert is_valid is False
        assert "score" in str(err).lower()


class TestQuestionModel:
    """Test suite for Question model fields, 6 elements, soft delete, and relationships."""

    def test_question_creation_and_6_elements(
        self,
        db_session: sessionmaker[Session],
        setup_question_context: tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID],
    ) -> None:
        """Verify Question model persists all 6 key elements and relationships."""
        user_id, mat_id, ver_id, kp_id, snip_id = setup_question_context

        options_data = [
            {"key": "A", "content": "Atomicity"},
            {"key": "B", "content": "Consistency"},
            {"key": "C", "content": "Isolation"},
            {"key": "D", "content": "Durability"},
        ]
        source_snippet_ids = [
            {"snippet_id": str(snip_id), "is_primary": True, "similarity_score": 0.92}
        ]

        with db_session() as session:
            question = Question(
                user_id=user_id,
                material_id=mat_id,
                version_id=ver_id,
                knowledge_point_id=kp_id,
                source_snippet_id=snip_id,
                question_type=QuestionType.SINGLE_CHOICE.value,
                status=QuestionStatus.AVAILABLE.value,
                is_deleted=False,
                stem="Which property guarantees all-or-nothing execution of a transaction?",
                options=options_data,
                answer="A",
                analysis=(
                    "Atomicity ensures that all changes to data are performed as a single unit."
                ),
                difficulty=2,
                source_snippet_ids=source_snippet_ids,
                embedding=[0.05] * 1024,
            )
            session.add(question)
            session.commit()

            q_id = question.id
            assert isinstance(q_id, uuid.UUID)
            assert isinstance(question.created_at, datetime)
            assert isinstance(question.updated_at, datetime)

            # Query and reload
            session.expire_all()
            reloaded = session.scalar(select(Question).where(Question.id == q_id))
            assert reloaded is not None
            assert (
                reloaded.stem
                == "Which property guarantees all-or-nothing execution of a transaction?"
            )
            assert len(reloaded.options) == 4
            assert reloaded.difficulty == 2
            assert reloaded.knowledge_point_id == kp_id
            assert reloaded.source_snippet_id == snip_id
            assert reloaded.knowledge_point.name == "ACID Properties"
            assert reloaded.source_snippet is not None
            assert reloaded.source_snippet.id == snip_id

    def test_question_soft_delete(
        self,
        db_session: sessionmaker[Session],
        setup_question_context: tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID],
    ) -> None:
        """Verify soft deletion flag toggling leaves question record in DB for paper snapshots."""
        user_id, mat_id, ver_id, kp_id, _snip_id = setup_question_context

        with db_session() as session:
            question = Question(
                user_id=user_id,
                material_id=mat_id,
                version_id=ver_id,
                knowledge_point_id=kp_id,
                question_type=QuestionType.TRUE_FALSE.value,
                stem="SQL is a declarative language.",
                answer="True",
                difficulty=1,
            )
            session.add(question)
            session.commit()
            q_id = question.id

            assert question.is_deleted is False

            # Toggle soft delete
            question.is_deleted = True
            session.commit()

            reloaded = session.scalar(select(Question).where(Question.id == q_id))
            assert reloaded is not None
            assert reloaded.is_deleted is True

            # Active question query excludes deleted
            active = session.scalars(
                select(Question).where(Question.user_id == user_id, Question.is_deleted.is_(False))
            ).all()
            assert len(active) == 0


class TestQualityCheckAndAuditLogs:
    """Test suite for QuestionQualityCheck and QuestionAuditLog records and cascades."""

    def test_quality_check_logging_and_cascade(
        self,
        db_session: sessionmaker[Session],
        setup_question_context: tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID],
    ) -> None:
        """Verify QuestionQualityCheck persists check results and cascades on Question delete."""
        user_id, mat_id, ver_id, kp_id, _snip_id = setup_question_context

        with db_session() as session:
            question = Question(
                user_id=user_id,
                material_id=mat_id,
                version_id=ver_id,
                knowledge_point_id=kp_id,
                question_type=QuestionType.SHORT_ANSWER.value,
                stem="What is serializability?",
                answer="Equivalent to serial execution schedule.",
            )
            session.add(question)
            session.commit()

            check = QuestionQualityCheck(
                user_id=user_id,
                question_id=question.id,
                batch_id="batch_qc_001",
                check_type=QualityCheckType.DUPLICATE.value,
                is_passed=False,
                reason="Similarity score 0.94 exceeds threshold 0.90",
                similarity_score=0.94,
                check_metadata={"matched_question_id": str(uuid.uuid4())},
            )
            session.add(check)
            session.commit()

            check_id = check.id
            reloaded_check = session.scalar(
                select(QuestionQualityCheck).where(QuestionQualityCheck.id == check_id)
            )
            assert reloaded_check is not None
            assert reloaded_check.similarity_score == 0.94
            assert reloaded_check.is_passed is False
            assert reloaded_check.question.id == question.id

            # Cascade delete test
            session.delete(question)
            session.commit()
            assert (
                session.scalar(
                    select(QuestionQualityCheck).where(QuestionQualityCheck.id == check_id)
                )
                is None
            )

    def test_audit_log_recording_and_cascade(
        self,
        db_session: sessionmaker[Session],
        setup_question_context: tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID],
    ) -> None:
        """Verify QuestionAuditLog tracks revisions and cascades on Question delete."""
        user_id, mat_id, ver_id, kp_id, _snip_id = setup_question_context

        with db_session() as session:
            question = Question(
                user_id=user_id,
                material_id=mat_id,
                version_id=ver_id,
                knowledge_point_id=kp_id,
                question_type=QuestionType.TERM_EXPLANATION.value,
                stem="Explain B+ Tree.",
                answer="Self-balancing search tree...",
            )
            session.add(question)
            session.commit()

            audit_log = QuestionAuditLog(
                user_id=user_id,
                question_id=question.id,
                action=AuditAction.EDIT.value,
                changed_fields=["stem", "answer"],
                before_payload={"stem": "Old stem", "answer": "Old answer"},
                after_payload={
                    "stem": "Explain B+ Tree.",
                    "answer": "Self-balancing search tree...",
                },
                reason="Improved terminology precision",
            )
            session.add(audit_log)
            session.commit()

            log_id = audit_log.id
            reloaded_log = session.scalar(
                select(QuestionAuditLog).where(QuestionAuditLog.id == log_id)
            )
            assert reloaded_log is not None
            assert reloaded_log.action == AuditAction.EDIT.value
            assert reloaded_log.changed_fields == ["stem", "answer"]
            assert reloaded_log.before_payload["stem"] == "Old stem"

            # Cascade delete test
            session.delete(question)
            session.commit()
            assert (
                session.scalar(select(QuestionAuditLog).where(QuestionAuditLog.id == log_id))
                is None
            )


class TestQuestionPrivacyDesensitizationAndTenant:
    """Test suite for privacy redlines and tenant isolation."""

    def test_question_repr_redaction_redline(self) -> None:
        """Verify Question __repr__ strictly excludes sensitive texts."""
        user_id = uuid.uuid4()
        q_id = uuid.uuid4()

        confidential_stem = "TOP_SECRET_EXAM_STEM_CONTENT_DO_NOT_REVEAL"
        confidential_answer = "TOP_SECRET_ANSWER_KEY_ABSOLUTELY_CONFIDENTIAL"
        confidential_analysis = "TOP_SECRET_ANALYSIS_DO_NOT_PRINT_ANYWHERE"
        confidential_option = "TOP_SECRET_DISTRACTOR_OPTION_TEXT"
        confidential_rubric = "TOP_SECRET_RUBRIC_KEYWORDS"

        question = Question(
            id=q_id,
            user_id=user_id,
            material_id=uuid.uuid4(),
            version_id=uuid.uuid4(),
            knowledge_point_id=uuid.uuid4(),
            question_type=QuestionType.SINGLE_CHOICE.value,
            status=QuestionStatus.AVAILABLE.value,
            stem=confidential_stem,
            options=[{"key": "A", "content": confidential_option}],
            answer=confidential_answer,
            analysis=confidential_analysis,
            difficulty=4,
            grading_rubric={"keywords": [confidential_rubric]},
            is_deleted=False,
        )

        qc = QuestionQualityCheck(
            id=uuid.uuid4(),
            user_id=user_id,
            question_id=q_id,
            batch_id="batch_repr",
            check_type=QualityCheckType.NO_SOURCE.value,
            is_passed=True,
        )

        audit = QuestionAuditLog(
            id=uuid.uuid4(),
            user_id=user_id,
            question_id=q_id,
            action=AuditAction.CREATE.value,
            changed_fields=["stem"],
        )

        q_repr = repr(question)
        qc_repr = repr(qc)
        audit_repr = repr(audit)

        assert confidential_stem not in q_repr, "Redline violated: question stem leaked in repr"
        assert confidential_answer not in q_repr, "Redline violated: question answer leaked in repr"
        assert confidential_analysis not in q_repr, (
            "Redline violated: question analysis leaked in repr"
        )
        assert confidential_option not in q_repr, (
            "Redline violated: question options leaked in repr"
        )
        assert confidential_rubric not in q_repr, "Redline violated: question rubric leaked in repr"

        assert str(q_id) in q_repr
        assert f"stem_len={len(confidential_stem)}" in q_repr
        assert str(q_id) in qc_repr
        assert str(q_id) in audit_repr

    def test_tenant_foreign_key_on_question_models(self) -> None:
        """Verify Question, QuestionQualityCheck, and QuestionAuditLog inherit TenantModelMixin."""
        for model_cls in (Question, QuestionQualityCheck, QuestionAuditLog):
            col = next(iter(model_cls.user_id.property.columns))
            fk = next(iter(col.foreign_keys))
            assert fk.target_fullname == "users.id"
            assert fk.ondelete == "CASCADE"


class TestQuestionMigration:
    """Test suite for 0002 Alembic migration upgrade and downgrade symmetry."""

    def test_migration_0002_upgrade_and_downgrade(self) -> None:
        """Verify migration 0002 can cleanly upgrade and symmetrically downgrade."""
        migration_0001 = importlib.import_module(
            "migrations.versions.0001_create_material_tables_and_vector"
        )
        migration_0002 = importlib.import_module(
            "migrations.versions.0002_create_knowledge_and_question_tables"
        )

        engine = create_engine("sqlite:///:memory:")
        try:
            with engine.begin() as connection:
                from alembic.operations import Operations
                from alembic.runtime.migration import MigrationContext

                context = MigrationContext.configure(connection)
                op = Operations(context)

                import alembic.op as alembic_op

                alembic_op._proxy = op  # type: ignore[attr-defined]

                # 2. Run migration 0001 first
                migration_0001.upgrade()

                # 3. Test migration 0002 upgrade
                migration_0002.upgrade()

                from sqlalchemy import inspect

                inspector = inspect(connection)
                table_names = set(inspector.get_table_names())
                assert "knowledge_points" in table_names
                assert "knowledge_point_snippets" in table_names
                assert "questions" in table_names
                assert "question_quality_checks" in table_names
                assert "question_audit_logs" in table_names

                # 4. Test migration 0002 downgrade
                migration_0002.downgrade()
                inspector.clear_cache()
                tables_after_downgrade = set(inspector.get_table_names())

                assert "question_audit_logs" not in tables_after_downgrade
                assert "question_quality_checks" not in tables_after_downgrade
                assert "questions" not in tables_after_downgrade
                assert "knowledge_point_snippets" not in tables_after_downgrade
                assert "knowledge_points" not in tables_after_downgrade

                # Verify 0001 tables still present after 0002 downgrade
                assert "materials" in tables_after_downgrade
                assert "material_versions" in tables_after_downgrade
                assert "material_snippets" in tables_after_downgrade
                assert "users" in tables_after_downgrade
        finally:
            engine.dispose()
