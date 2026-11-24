"""Unit tests for async question generation job router endpoints."""

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
from app.core.errors import AppError, QuestionGenerationJobNotFoundError
from app.models.question import QuestionGenerationJob, QuestionGenerationJobStatus
from app.models.user import User


def _create_test_app() -> FastAPI:
    app = FastAPI(title="Question Jobs Router Test App")

    @app.exception_handler(AppError)
    async def _app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
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


def _make_job(
    user_id: uuid.UUID,
    *,
    status: str = QuestionGenerationJobStatus.QUEUED.value,
    material_id: uuid.UUID | None = None,
    folder_id: uuid.UUID | None = None,
    total_kps: int = 2,
    completed_kps: int = 0,
    generated_count: int = 0,
) -> QuestionGenerationJob:
    now = datetime.now(UTC)
    return QuestionGenerationJob(
        id=uuid.uuid4(),
        user_id=user_id,
        material_id=material_id,
        folder_id=folder_id,
        status=status,
        request_payload={"count": 4},
        total_kps=total_kps,
        completed_kps=completed_kps,
        generated_count=generated_count,
        batch_id="batch_1" if generated_count else None,
        question_ids=[str(uuid.uuid4())] if generated_count else [],
        error_message=None,
        created_at=now,
        updated_at=now,
        completed_at=now if status == QuestionGenerationJobStatus.COMPLETED.value else None,
    )


@pytest.mark.asyncio
async def test_create_question_generation_job_returns_202_and_exact_contract() -> None:
    """POST /api/v1/questions/jobs returns 202 and serialized job state."""
    app = _create_test_app()
    user = User(id=uuid.uuid4(), nickname="tester", is_active=True, token_version=1)
    material_id = uuid.uuid4()
    kp_id = uuid.uuid4()
    job = _make_job(user.id, material_id=material_id, total_kps=1)

    mock_service = MagicMock()
    mock_service.create_generation_job.return_value = job
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_question_service] = lambda: mock_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/questions/jobs",
            json={
                "material_id": str(material_id),
                "knowledge_point_ids": [str(kp_id)],
                "question_types": ["single_choice"],
                "count": 4,
                "difficulty": 3,
            },
        )

    assert resp.status_code == 202
    data = resp.json()
    assert set(data.keys()) == {
        "id",
        "status",
        "material_id",
        "folder_id",
        "total_kps",
        "completed_kps",
        "generated_count",
        "batch_id",
        "question_ids",
        "result_practice_id",
        "source_type",
        "source_practice_id",
        "practice_title",
        "error_message",
        "created_at",
        "updated_at",
        "completed_at",
    }
    assert data["id"] == str(job.id)
    assert data["status"] == "queued"
    assert data["total_kps"] == 1
    mock_service.create_generation_job.assert_called_once()


@pytest.mark.asyncio
async def test_list_and_get_question_generation_jobs() -> None:
    """GET /api/v1/questions/jobs and /jobs/{job_id} return expected payloads and 404."""
    app = _create_test_app()
    user = User(id=uuid.uuid4(), nickname="tester", is_active=True, token_version=1)
    folder_id = uuid.uuid4()
    job = _make_job(
        user.id,
        status=QuestionGenerationJobStatus.COMPLETED.value,
        folder_id=folder_id,
        total_kps=3,
        completed_kps=3,
        generated_count=6,
    )

    mock_service = MagicMock()
    mock_service.list_generation_jobs.return_value = ([job], 1)
    mock_service.get_generation_job.return_value = job
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_question_service] = lambda: mock_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        list_resp = await client.get(
            f"/api/v1/questions/jobs?active_only=true&folder_id={folder_id}"
        )
        detail_resp = await client.get(f"/api/v1/questions/jobs/{job.id}")

        mock_service.get_generation_job.side_effect = QuestionGenerationJobNotFoundError(
            "出题任务不存在"
        )
        missing_resp = await client.get(f"/api/v1/questions/jobs/{uuid.uuid4()}")

    assert list_resp.status_code == 200
    assert list_resp.json()["total"] == 1
    assert list_resp.json()["items"][0]["generated_count"] == 6
    mock_service.list_generation_jobs.assert_called_once_with(
        user_id=user.id,
        active_only=True,
        material_id=None,
        folder_id=folder_id,
    )

    assert detail_resp.status_code == 200
    assert detail_resp.json()["status"] == "completed"
    assert detail_resp.json()["completed_kps"] == 3

    assert missing_resp.status_code == 404
    assert missing_resp.json()["code"] == 40022


@pytest.mark.asyncio
async def test_async_job_accepts_count_50_idempotency_header_and_sync_generate_deprecated() -> None:
    """POST /questions/jobs supports count<=50 & Idempotency-Key; sync /generate is deprecated."""
    app = _create_test_app()
    user = User(id=uuid.uuid4(), nickname="tester", is_active=True, token_version=1)
    material_id = uuid.uuid4()
    kp_id = uuid.uuid4()
    source_practice_id = uuid.uuid4()
    result_practice_id = uuid.uuid4()
    job = _make_job(user.id, material_id=material_id, total_kps=1)
    job.source_type = "wrong_record"
    job.source_practice_id = source_practice_id
    job.result_practice_id = result_practice_id
    job.request_payload = {"practice_title": "错题巩固卷"}

    mock_service = MagicMock()
    mock_service.create_generation_job.return_value = job
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_question_service] = lambda: mock_service

    openapi = app.openapi()
    assert openapi["paths"]["/api/v1/questions/generate"]["post"].get("deprecated") is True

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        async_resp = await client.post(
            "/api/v1/questions/jobs",
            headers={"Idempotency-Key": "job-key-50"},
            json={
                "material_id": str(material_id),
                "knowledge_point_ids": [str(kp_id)],
                "question_types": ["single_choice"],
                "count": 50,
                "difficulty": 3,
                "auto_create_practice": True,
                "practice_title": "错题巩固卷",
                "source_type": "wrong_record",
                "source_practice_id": str(source_practice_id),
            },
        )
        sync_over_limit = await client.post(
            "/api/v1/questions/generate",
            json={
                "material_id": str(material_id),
                "knowledge_point_ids": [str(kp_id)],
                "question_types": ["single_choice"],
                "count": 21,
                "difficulty": 3,
            },
        )

    assert async_resp.status_code == 202
    body = async_resp.json()
    assert body["result_practice_id"] == str(result_practice_id)
    assert body["source_type"] == "wrong_record"
    assert body["source_practice_id"] == str(source_practice_id)
    assert body["practice_title"] == "错题巩固卷"
    call_kwargs = mock_service.create_generation_job.call_args.kwargs
    assert call_kwargs["idempotency_key"] == "job-key-50"
    assert call_kwargs["payload"].count == 50
    assert call_kwargs["payload"].auto_create_practice is True

    assert sync_over_limit.status_code == 422
