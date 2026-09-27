"""Unit tests for course-folder parameters on the question router.

Verifies:
1. POST /api/v1/questions/generate with folder_id routes to the folder orchestration
   and never touches the single-material path.
2. GET /api/v1/questions passes folder_id through to the service.
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
from app.core.errors import AppError
from app.models.question import Question
from app.models.user import User
from app.services.question import MultiKnowledgePointGenerationResult


def create_test_app() -> FastAPI:
    """Creates a test FastAPI application with the AppError exception handler."""
    app = FastAPI(title="Question Folder Router Test App")

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
    return User(id=uuid.uuid4(), nickname="folder_learner", is_active=True, token_version=1)


@pytest.fixture
def mock_question_service() -> MagicMock:
    """Fixture providing a mocked QuestionService."""
    return MagicMock()


def make_fake_question(
    user_id: uuid.UUID,
    material_id: uuid.UUID,
    version_id: uuid.UUID,
    knowledge_point_id: uuid.UUID,
) -> Question:
    """Creates a mock Question entity bound to the given material."""
    now = datetime.now(UTC)
    return Question(
        id=uuid.uuid4(),
        user_id=user_id,
        material_id=material_id,
        version_id=version_id,
        knowledge_point_id=knowledge_point_id,
        question_type="single_choice",
        status="available",
        is_deleted=False,
        stem="课程范围题目？",
        options=[{"key": "A", "content": "选项A"}],
        answer="A",
        analysis="解析",
        difficulty=3,
        grading_rubric={},
        source_snippet_ids=[],
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_generate_questions_folder_scope(
    mock_user: User, mock_question_service: MagicMock
) -> None:
    """Tests folder_id routes generation to the folder orchestration."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_question_service] = lambda: mock_question_service

    folder_id = uuid.uuid4()
    material_id = uuid.uuid4()
    version_id = uuid.uuid4()
    kp_ids = [uuid.uuid4(), uuid.uuid4()]
    fake_questions = [
        make_fake_question(mock_user.id, material_id, version_id, kp) for kp in kp_ids
    ]

    mock_question_service.generate_questions_for_folder.return_value = (
        MultiKnowledgePointGenerationResult(
            batch_id="batch_folder",
            material_id=material_id,
            version_id=version_id,
            knowledge_point_id=kp_ids[0],
            knowledge_point_ids=tuple(kp_ids),
            requested_count=4,
            total_generated=2,
            qualified_questions=fake_questions,
            pending_questions=[],
            quality_checks=[],
            retry_count=0,
        )
    )

    payload: dict[str, Any] = {"folder_id": str(folder_id), "count": 4}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/questions/generate", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["batch_id"] == "batch_folder"
    assert data["knowledge_point_id"] == str(kp_ids[0])
    assert data["knowledge_point_ids"] == [str(kp) for kp in kp_ids]
    assert data["total_generated"] == 2

    mock_question_service.generate_questions_for_folder.assert_called_once()
    called_kwargs = mock_question_service.generate_questions_for_folder.call_args.kwargs
    assert called_kwargs["folder_id"] == folder_id
    assert called_kwargs["knowledge_point_ids"] is None
    mock_question_service.generate_questions.assert_not_called()
    mock_question_service.generate_questions_for_knowledge_points.assert_not_called()


@pytest.mark.asyncio
async def test_generate_questions_folder_scope_forwards_explicit_points(
    mock_user: User, mock_question_service: MagicMock
) -> None:
    """Tests explicit knowledge_point_ids are forwarded to the folder orchestration."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_question_service] = lambda: mock_question_service

    folder_id = uuid.uuid4()
    kp_ids = [uuid.uuid4(), uuid.uuid4()]
    mock_question_service.generate_questions_for_folder.return_value = (
        MultiKnowledgePointGenerationResult(
            batch_id="batch_folder_2",
            material_id=uuid.uuid4(),
            version_id=uuid.uuid4(),
            knowledge_point_id=kp_ids[0],
            knowledge_point_ids=tuple(kp_ids),
            requested_count=2,
            total_generated=0,
            qualified_questions=[],
            pending_questions=[],
            quality_checks=[],
            retry_count=0,
        )
    )

    payload: dict[str, Any] = {
        "folder_id": str(folder_id),
        "knowledge_point_ids": [str(kp) for kp in kp_ids],
        "count": 2,
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/questions/generate", json=payload)

    assert response.status_code == 200
    called_kwargs = mock_question_service.generate_questions_for_folder.call_args.kwargs
    assert called_kwargs["knowledge_point_ids"] == kp_ids


@pytest.mark.asyncio
async def test_generate_questions_requires_material_or_folder(
    mock_user: User, mock_question_service: MagicMock
) -> None:
    """Tests 422 when neither material_id nor folder_id is provided."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_question_service] = lambda: mock_question_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/questions/generate",
            json={"knowledge_point_id": str(uuid.uuid4()), "count": 2},
        )

    assert response.status_code == 422
    mock_question_service.generate_questions_for_folder.assert_not_called()


@pytest.mark.asyncio
async def test_list_questions_folder_filter(
    mock_user: User, mock_question_service: MagicMock
) -> None:
    """Tests GET /questions forwards folder_id to the service."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_question_service] = lambda: mock_question_service

    folder_id = uuid.uuid4()
    fake_q = make_fake_question(mock_user.id, uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    mock_question_service.list_questions.return_value = ([fake_q], 1)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/questions", params={"folder_id": str(folder_id)})

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == str(fake_q.id)
    called_kwargs = mock_question_service.list_questions.call_args.kwargs
    assert called_kwargs["folder_id"] == folder_id
