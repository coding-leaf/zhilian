"""Unit tests for GET /api/v1/questions/batches in app/api/v1/questions.py.

Verifies:
1. Route registration order: ``/questions/batches`` resolves to the batches endpoint
   (200 with ``items`` / ``total``) rather than being captured by ``/questions/{id}``
   and rejected as a malformed UUID (422).
2. Pagination contract: ``page`` / ``page_size`` map onto the service paging arguments
   and echo back as ``limit`` / ``offset``.
3. Authentication is enforced.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from app.api.deps.auth import get_current_user
from app.api.deps.question import get_question_service
from app.api.v1 import api_v1_router
from app.core.errors import AppError
from app.models.user import User
from app.schemas.question import QuestionBatchSummaryResponse


def create_test_app() -> FastAPI:
    """Creates a test FastAPI application with the AppError exception handler."""
    app = FastAPI(title="Question Batch Router Test App")

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


def _batch_summary(
    batch_id: str | None, *, available: int = 2, pending: int = 1
) -> QuestionBatchSummaryResponse:
    return QuestionBatchSummaryResponse(
        batch_id=batch_id,
        question_count=available + pending,
        available_count=available,
        pending_review_count=pending,
        created_at=datetime(2026, 3, 1, 8, 0, tzinfo=UTC),
    )


class TestQuestionBatchesEndpoint:
    """Route order, pagination and auth for the batch aggregation endpoint."""

    @pytest.mark.asyncio
    async def test_batches_path_is_not_captured_by_question_id_route(
        self,
        mock_user: User,
        mock_question_service: MagicMock,
    ) -> None:
        """回归断言：路由注册位置放错时本用例会以 422 (UUID 解析失败) 失败。"""
        app = create_test_app()
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_question_service] = lambda: mock_question_service
        mock_question_service.list_question_batches.return_value = (
            [_batch_summary("batch_a"), _batch_summary(None)],
            2,
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/questions/batches")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 2
        assert [item["batch_id"] for item in body["items"]] == ["batch_a", None]
        assert body["items"][1]["available_count"] == 2
        assert body["items"][1]["pending_review_count"] == 1
        assert body["items"][1]["sources"] == []

    @pytest.mark.asyncio
    async def test_page_and_page_size_map_to_paging_arguments(
        self,
        mock_user: User,
        mock_question_service: MagicMock,
    ) -> None:
        app = create_test_app()
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_question_service] = lambda: mock_question_service
        mock_question_service.list_question_batches.return_value = ([], 7)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/v1/questions/batches",
                params={"page": 3, "page_size": 5},
            )

        assert response.status_code == 200, response.text
        assert response.json() == {"items": [], "total": 7, "limit": 5, "offset": 10}
        kwargs = mock_question_service.list_question_batches.call_args.kwargs
        assert kwargs == {"user_id": mock_user.id, "page": 3, "page_size": 5}

    @pytest.mark.asyncio
    async def test_page_size_upper_bound_is_enforced(
        self,
        mock_user: User,
        mock_question_service: MagicMock,
    ) -> None:
        app = create_test_app()
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_question_service] = lambda: mock_question_service

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/v1/questions/batches",
                params={"page_size": 101},
            )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_authentication_is_required(self) -> None:
        app = create_test_app()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/questions/batches")

        assert response.status_code == 401


class TestUnbatchedQuestionFilter:
    """`GET /questions?unbatched=true` 供题库的「未分批」分组展开使用。"""

    @pytest.mark.asyncio
    async def test_unbatched_query_param_reaches_the_service(
        self,
        mock_user: User,
        mock_question_service: MagicMock,
    ) -> None:
        app = create_test_app()
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_question_service] = lambda: mock_question_service
        mock_question_service.list_questions.return_value = ([], 0)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/questions", params={"unbatched": "true"})

        assert response.status_code == 200, response.text
        assert mock_question_service.list_questions.call_args.kwargs["unbatched"] is True

    @pytest.mark.asyncio
    async def test_unbatched_defaults_to_false(
        self,
        mock_user: User,
        mock_question_service: MagicMock,
    ) -> None:
        app = create_test_app()
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_question_service] = lambda: mock_question_service
        mock_question_service.list_questions.return_value = ([], 0)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/questions")

        assert response.status_code == 200, response.text
        assert mock_question_service.list_questions.call_args.kwargs["unbatched"] is False
