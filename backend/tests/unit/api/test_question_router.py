"""Unit tests for question router endpoints in app/api/v1/questions.py.

Verifies:
1. POST /api/v1/questions/generate (generation success, 40003 MissingSourceSnippetError).
2. GET /api/v1/questions/{id} (question detail query, 40009 QuestionNotFoundError).
3. GET /api/v1/questions (multi-filter and pagination query).
4. PUT /api/v1/questions/{id} (question update and audit logging, 404).
5. DELETE /api/v1/questions/{id} (question soft delete).
6. GET /api/v1/questions/{id}/edit-logs (edit audit logs query).
7. GET /api/v1/materials/{material_id}/quality-checks (quality checks query, 404).
8. Tenant cross-access isolation and authentication enforcement.
9. Dependency injection isolation and exception mapping compliance.
"""

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from app.api.deps.auth import get_current_user
from app.api.deps.question import get_question_service
from app.api.v1 import api_v1_router
from app.core.errors import (
    AppError,
    MaterialNotFoundError,
    MissingSourceSnippetError,
    PermissionDeniedError,
    QuestionNotFoundError,
)
from app.models.question import (
    Question,
    QuestionAuditLog,
    QuestionQualityCheck,
)
from app.models.user import User
from app.services.question import QuestionGenerationResult


def create_test_app() -> FastAPI:
    """Creates a test FastAPI application with AppError exception handler."""
    app = FastAPI(title="Question Router Test App")

    @app.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.error_code,
                "message": exc.message,
                "details": exc.details,
                "data": None,
            },
        )

    app.include_router(api_v1_router)
    return app


@pytest.fixture
def mock_user() -> User:
    """Fixture providing a mock authenticated User entity."""
    return User(
        id=uuid.uuid4(),
        nickname="test_instructor",
        is_active=True,
        token_version=1,
    )


@pytest.fixture
def mock_question_service() -> MagicMock:
    """Fixture providing a mocked QuestionService."""
    return MagicMock()


def make_fake_question(
    user_id: uuid.UUID,
    question_id: uuid.UUID | None = None,
    material_id: uuid.UUID | None = None,
    version_id: uuid.UUID | None = None,
    knowledge_point_id: uuid.UUID | None = None,
    question_type: str = "single_choice",
    status: str = "available",
    stem: str = "敏捷宣言首条价值观是什么？",
    options: list[dict[str, Any]] | None = None,
    answer: str = "A",
    difficulty: int = 3,
) -> Question:
    """Creates a mock Question entity."""
    now = datetime.now(UTC)
    return Question(
        id=question_id or uuid.uuid4(),
        user_id=user_id,
        material_id=material_id or uuid.uuid4(),
        version_id=version_id or uuid.uuid4(),
        knowledge_point_id=knowledge_point_id or uuid.uuid4(),
        source_snippet_id=uuid.uuid4(),
        question_type=question_type,
        status=status,
        is_deleted=False,
        stem=stem,
        options=(
            options
            if options is not None
            else [{"key": "A", "content": "个体与互动高于流程和工具"}]
        ),
        answer=answer,
        analysis="敏捷宣言的核心体现。",
        difficulty=difficulty,
        grading_rubric={},
        source_snippet_ids=[{"snippet_id": str(uuid.uuid4()), "score": 0.88}],
        created_at=now,
        updated_at=now,
    )


def make_fake_quality_check(
    user_id: uuid.UUID,
    question_id: uuid.UUID,
    batch_id: str = "batch_test123",
    check_type: str = "DUPLICATE",
    is_passed: bool = False,
    reason: str = "题干相似度超限",
    similarity_score: float = 0.94,
) -> QuestionQualityCheck:
    """Creates a mock QuestionQualityCheck entity."""
    now = datetime.now(UTC)
    return QuestionQualityCheck(
        id=uuid.uuid4(),
        user_id=user_id,
        question_id=question_id,
        batch_id=batch_id,
        check_type=check_type,
        is_passed=is_passed,
        reason=reason,
        similarity_score=similarity_score,
        check_metadata={"threshold": 0.85},
        created_at=now,
        updated_at=now,
    )


def make_fake_audit_log(
    user_id: uuid.UUID,
    question_id: uuid.UUID,
    action: str = "EDIT",
    changed_fields: list[str] | None = None,
    reason: str = "调整难度与题干",
) -> QuestionAuditLog:
    """Creates a mock QuestionAuditLog entity."""
    now = datetime.now(UTC)
    return QuestionAuditLog(
        id=uuid.uuid4(),
        user_id=user_id,
        question_id=question_id,
        action=action,
        changed_fields=changed_fields or ["stem", "difficulty"],
        before_payload={"difficulty": 3},
        after_payload={"difficulty": 4},
        reason=reason,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_generate_questions_success(
    mock_user: User, mock_question_service: MagicMock
) -> None:
    """Tests successful question generation via POST /api/v1/questions/generate."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_question_service] = lambda: mock_question_service

    mat_id = uuid.uuid4()
    ver_id = uuid.uuid4()
    kp_id = uuid.uuid4()
    fake_q = make_fake_question(
        user_id=mock_user.id,
        material_id=mat_id,
        version_id=ver_id,
        knowledge_point_id=kp_id,
    )
    fake_check = make_fake_quality_check(user_id=mock_user.id, question_id=fake_q.id)

    mock_question_service.generate_questions.return_value = QuestionGenerationResult(
        batch_id="batch_12345",
        material_id=mat_id,
        version_id=ver_id,
        knowledge_point_id=kp_id,
        total_generated=1,
        qualified_questions=[fake_q],
        pending_questions=[],
        quality_checks=[fake_check],
        retry_count=1,
    )

    payload = {
        "material_id": str(mat_id),
        "version_id": str(ver_id),
        "knowledge_point_id": str(kp_id),
        "count": 5,
        "difficulty": 3,
        "question_types": ["single_choice"],
        "max_retries": 2,
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/questions/generate", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["batch_id"] == "batch_12345"
    assert data["total_generated"] == 1
    assert data["qualified_count"] == 1
    assert data["pending_count"] == 0
    assert len(data["qualified_questions"]) == 1
    assert data["qualified_questions"][0]["id"] == str(fake_q.id)
    assert len(data["quality_checks"]) == 1
    assert data["quality_checks"][0]["check_type"] == "DUPLICATE"

    mock_question_service.generate_questions.assert_called_once()


@pytest.mark.asyncio
async def test_generate_questions_with_optional_version_id(
    mock_user: User, mock_question_service: MagicMock
) -> None:
    """Tests generating questions when version_id is omitted, empty, or equals material_id."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_question_service] = lambda: mock_question_service

    mat_id = uuid.uuid4()
    ver_id = uuid.uuid4()
    kp_id = uuid.uuid4()
    fake_q = make_fake_question(
        user_id=mock_user.id,
        material_id=mat_id,
        version_id=ver_id,
        knowledge_point_id=kp_id,
    )

    mock_question_service.generate_questions.return_value = QuestionGenerationResult(
        batch_id="batch_fallback_1",
        material_id=mat_id,
        version_id=ver_id,
        knowledge_point_id=kp_id,
        total_generated=1,
        qualified_questions=[fake_q],
        pending_questions=[],
        quality_checks=[],
        retry_count=0,
    )

    # 1. version_id omitted or null
    payload_null = {
        "material_id": str(mat_id),
        "version_id": None,
        "knowledge_point_id": str(kp_id),
        "count": 3,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp1 = await client.post("/api/v1/questions/generate", json=payload_null)
    assert resp1.status_code == 200

    # 2. version_id is empty string
    payload_empty = {
        "material_id": str(mat_id),
        "version_id": "",
        "knowledge_point_id": str(kp_id),
        "count": 3,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp2 = await client.post("/api/v1/questions/generate", json=payload_empty)
    assert resp2.status_code == 200

    # 3. version_id == material_id
    payload_mat = {
        "material_id": str(mat_id),
        "version_id": str(mat_id),
        "knowledge_point_id": str(kp_id),
        "count": 3,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp3 = await client.post("/api/v1/questions/generate", json=payload_mat)
    assert resp3.status_code == 200


@pytest.mark.asyncio
async def test_generate_questions_missing_source_snippet_40003(
    mock_user: User, mock_question_service: MagicMock
) -> None:
    """Tests 400 error (40003) when snippet gate is not satisfied."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_question_service] = lambda: mock_question_service

    mat_id = uuid.uuid4()
    ver_id = uuid.uuid4()
    kp_id = uuid.uuid4()

    mock_question_service.generate_questions.side_effect = MissingSourceSnippetError(
        "检索不到与知识点匹配的有效资料片段，拒绝出题",
        details={"max_similarity": 0.25},
    )

    payload = {
        "material_id": str(mat_id),
        "version_id": str(ver_id),
        "knowledge_point_id": str(kp_id),
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/questions/generate", json=payload)

    assert response.status_code == 400
    data = response.json()
    assert data["code"] == 40003
    assert "拒绝出题" in data["message"]


@pytest.mark.asyncio
async def test_get_question_detail_success(
    mock_user: User, mock_question_service: MagicMock
) -> None:
    """Tests successful question detail retrieval via GET /api/v1/questions/{id}."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_question_service] = lambda: mock_question_service

    fake_q = make_fake_question(user_id=mock_user.id)
    mock_question_service.get_question_detail.return_value = fake_q

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/questions/{fake_q.id}")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(fake_q.id)
    assert data["stem"] == fake_q.stem
    assert data["difficulty"] == fake_q.difficulty
    assert data["status"] == fake_q.status

    mock_question_service.get_question_detail.assert_called_once_with(
        question_id=fake_q.id,
        user_id=mock_user.id,
    )


@pytest.mark.asyncio
async def test_get_question_detail_not_found_40009(
    mock_user: User, mock_question_service: MagicMock
) -> None:
    """Tests 404 (40009) when question is not found."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_question_service] = lambda: mock_question_service

    q_id = uuid.uuid4()
    mock_question_service.get_question_detail.side_effect = QuestionNotFoundError(
        "请求的题目不存在或无权访问"
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/questions/{q_id}")

    assert response.status_code == 404
    data = response.json()
    assert data["code"] == 40009
    assert "题目不存在" in data["message"]


@pytest.mark.asyncio
async def test_list_questions_with_filters(
    mock_user: User, mock_question_service: MagicMock
) -> None:
    """Tests multi-filter and paginated listing via GET /api/v1/questions."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_question_service] = lambda: mock_question_service

    mat_id = uuid.uuid4()
    kp_id = uuid.uuid4()
    fake_q = make_fake_question(
        user_id=mock_user.id,
        material_id=mat_id,
        knowledge_point_id=kp_id,
    )

    mock_question_service.list_questions.return_value = ([fake_q], 42)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v1/questions",
            params={
                "material_id": str(mat_id),
                "knowledge_point_id": str(kp_id),
                "question_type": "single_choice",
                "difficulty": 3,
                "review_status": "available",
                "page": 2,
                "page_size": 10,
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 42
    assert data["limit"] == 10
    assert data["offset"] == 10
    assert len(data["items"]) == 1
    assert data["items"][0]["id"] == str(fake_q.id)

    mock_question_service.list_questions.assert_called_once_with(
        user_id=mock_user.id,
        material_id=mat_id,
        knowledge_point_id=kp_id,
        question_type="single_choice",
        difficulty=3,
        review_status="available",
        page=2,
        page_size=10,
        limit=10,
        offset=10,
    )


@pytest.mark.asyncio
async def test_update_question_and_audit_log(
    mock_user: User, mock_question_service: MagicMock
) -> None:
    """Tests updating a question with audit reason via PUT /api/v1/questions/{id}."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_question_service] = lambda: mock_question_service

    fake_q = make_fake_question(
        user_id=mock_user.id,
        stem="更新后的题干描述？",
        difficulty=4,
    )
    mock_question_service.update_question.return_value = fake_q

    payload = {
        "stem": "更新后的题干描述？",
        "difficulty": 4,
        "reason": "人工修订题干与难度",
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.put(f"/api/v1/questions/{fake_q.id}", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(fake_q.id)
    assert data["stem"] == "更新后的题干描述？"
    assert data["difficulty"] == 4

    mock_question_service.update_question.assert_called_once_with(
        question_id=fake_q.id,
        user_id=mock_user.id,
        update_data={"stem": "更新后的题干描述？", "difficulty": 4},
        edit_reason="人工修订题干与难度",
    )


@pytest.mark.asyncio
async def test_update_question_not_found(mock_user: User, mock_question_service: MagicMock) -> None:
    """Tests 404 when updating non-existent question."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_question_service] = lambda: mock_question_service

    q_id = uuid.uuid4()
    mock_question_service.update_question.side_effect = QuestionNotFoundError(
        "请求的题目不存在或无权访问"
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.put(
            f"/api/v1/questions/{q_id}",
            json={"stem": "尝试修改不存在的题目"},
        )

    assert response.status_code == 404
    data = response.json()
    assert data["code"] == 40009


@pytest.mark.asyncio
async def test_delete_question_success(mock_user: User, mock_question_service: MagicMock) -> None:
    """Tests soft deleting a question via DELETE /api/v1/questions/{id}."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_question_service] = lambda: mock_question_service

    q_id = uuid.uuid4()
    mock_question_service.delete_question.return_value = True

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete(
            f"/api/v1/questions/{q_id}",
            params={"reason": "清理过期测试题"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(q_id)
    assert data["is_deleted"] is True
    assert "题目已软删除" in data["message"]

    mock_question_service.delete_question.assert_called_once_with(
        question_id=q_id,
        user_id=mock_user.id,
        reason="清理过期测试题",
    )


@pytest.mark.asyncio
async def test_list_question_edit_logs_success(
    mock_user: User, mock_question_service: MagicMock
) -> None:
    """Tests fetching audit edit logs via GET /api/v1/questions/{id}/edit-logs."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_question_service] = lambda: mock_question_service

    q_id = uuid.uuid4()
    fake_log = make_fake_audit_log(user_id=mock_user.id, question_id=q_id)
    mock_question_service.list_edit_logs.return_value = [fake_log]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/questions/{q_id}/edit-logs")

    assert response.status_code == 200
    data = response.json()
    assert data["question_id"] == str(q_id)
    assert len(data["logs"]) == 1
    assert data["logs"][0]["action"] == "EDIT"
    assert "difficulty" in data["logs"][0]["changed_fields"]

    mock_question_service.list_edit_logs.assert_called_once_with(
        question_id=q_id,
        user_id=mock_user.id,
    )


@pytest.mark.asyncio
async def test_list_material_quality_checks_success(
    mock_user: User, mock_question_service: MagicMock
) -> None:
    """Tests fetching quality checks for material via GET /api/v1/materials/{id}/quality-checks."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_question_service] = lambda: mock_question_service

    mat_id = uuid.uuid4()
    q_id = uuid.uuid4()
    fake_check = make_fake_quality_check(
        user_id=mock_user.id,
        question_id=q_id,
        check_type="DUPLICATE",
    )
    mock_question_service.list_quality_checks.return_value = [fake_check]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/materials/{mat_id}/quality-checks")

    assert response.status_code == 200
    data = response.json()
    assert data["material_id"] == str(mat_id)
    assert len(data["quality_checks"]) == 1
    assert data["quality_checks"][0]["check_type"] == "DUPLICATE"
    assert data["quality_checks"][0]["similarity_score"] == 0.94

    mock_question_service.list_quality_checks.assert_called_once_with(
        material_id=mat_id,
        user_id=mock_user.id,
    )


@pytest.mark.asyncio
async def test_list_material_quality_checks_material_not_found(
    mock_user: User, mock_question_service: MagicMock
) -> None:
    """Tests 404 when material is not found for quality checks query."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_question_service] = lambda: mock_question_service

    mat_id = uuid.uuid4()
    mock_question_service.list_quality_checks.side_effect = MaterialNotFoundError(
        "请求的学习资料不存在或已被删除"
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/materials/{mat_id}/quality-checks")

    assert response.status_code == 404
    data = response.json()
    assert data["code"] == 40004
    assert "学习资料不存在" in data["message"]


@pytest.mark.asyncio
async def test_unauthenticated_request(mock_question_service: MagicMock) -> None:
    """Tests 401 when request is not authenticated."""
    app = create_test_app()
    app.dependency_overrides[get_question_service] = lambda: mock_question_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/questions/{uuid.uuid4()}")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_tenant_cross_access_isolation(
    mock_user: User, mock_question_service: MagicMock
) -> None:
    """Tests that cross-tenant access is rejected with PermissionDeniedError 403."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_question_service] = lambda: mock_question_service

    q_id = uuid.uuid4()
    mock_question_service.get_question_detail.side_effect = PermissionDeniedError(
        "无权访问非本人归属资源"
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/questions/{q_id}")

    assert response.status_code == 403
    data = response.json()
    assert data["code"] == 20002


def test_default_dependency_provider() -> None:
    """Tests that default dependency provider raises NotImplementedError."""
    with pytest.raises(NotImplementedError, match="QuestionService 生产装配工厂尚未挂载"):
        get_question_service()
