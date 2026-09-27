"""Unit tests for course-folder parameters on the practices router.

Verifies:
1. POST /api/v1/practices forwards folder_id into CreatePracticeOptions.
2. The response exposes folder_id with a null material_id for folder-scope practices.
3. Omitting both folder_id and knowledge_point_ids is rejected with 422.
"""

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from app.api.deps.auth import get_current_user
from app.api.deps.practice import get_practice_service
from app.api.v1.practices import router as practice_router
from app.core.errors import AppError
from app.models.practice import Practice
from app.models.user import User
from app.services.practice import PracticeService


def create_test_app() -> FastAPI:
    """Creates a test FastAPI app with the practices router and AppError handler."""
    app = FastAPI(title="Practice Folder Router Test App")

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

    api_router = APIRouter(prefix="/api/v1")
    api_router.include_router(practice_router)
    app.include_router(api_router)
    return app


@pytest.fixture
def mock_user() -> User:
    """Provides an authenticated tenant user."""
    return User(id=uuid.uuid4(), nickname="folder_learner", is_active=True, token_version=1)


@pytest.fixture
def mock_practice_service() -> MagicMock:
    """Provides a stubbed PracticeService."""
    return MagicMock(spec=PracticeService)


def make_folder_practice(user_id: uuid.UUID, folder_id: uuid.UUID) -> Practice:
    """Builds a folder-scope Practice with a null material_id and no items."""
    return Practice(
        id=uuid.uuid4(),
        user_id=user_id,
        material_id=None,
        folder_id=folder_id,
        title="课程范围练习",
        status="not_started",
        source_type="normal",
        question_count=0,
        knowledge_point_ids=[str(uuid.uuid4())],
        question_types=["single_choice"],
        ordered_question_ids=[],
        created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_create_practice_folder_scope(
    mock_user: User, mock_practice_service: MagicMock
) -> None:
    """Tests folder_id is forwarded and the response binds folder_id with null material."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_practice_service] = lambda: mock_practice_service

    folder_id = uuid.uuid4()
    practice = make_folder_practice(mock_user.id, folder_id)
    mock_practice_service.create_practice.return_value = practice

    payload: dict[str, Any] = {
        "title": "课程范围练习",
        "folder_id": str(folder_id),
        "question_count": 4,
        "mode": "sequential",
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/practices", json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["folder_id"] == str(folder_id)
    assert data["material_id"] is None

    called_kwargs = mock_practice_service.create_practice.call_args.kwargs
    assert called_kwargs["options"].folder_id == folder_id
    assert called_kwargs["options"].knowledge_point_ids == []


@pytest.mark.asyncio
async def test_create_practice_requires_scope(
    mock_user: User, mock_practice_service: MagicMock
) -> None:
    """Tests 422 when neither folder_id nor knowledge_point_ids is provided."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_practice_service] = lambda: mock_practice_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/practices",
            json={"title": "无范围练习", "question_count": 3},
        )

    assert response.status_code == 422
    mock_practice_service.create_practice.assert_not_called()
