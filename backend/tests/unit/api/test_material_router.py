"""Unit tests for material router endpoints in app/api/v1/materials.py.

Verifies:
1. POST /api/v1/materials/upload (successful upload, custom parameters, error mapping).
2. GET /api/v1/materials/{material_id} (detail query, version counting, 404, 401, 422).
3. Dependency injection isolation and exception mapping compliance.
"""

import io
import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from app.api.deps.auth import get_current_user
from app.api.deps.material import get_material_service
from app.api.v1 import api_v1_router
from app.core.errors import (
    AppError,
    AuthenticationError,
    MaterialInvalidError,
    MaterialNotFoundError,
    ReshootLimitExceededError,
)
from app.models.material import (
    Material,
    MaterialOCRPage,
    MaterialStatus,
    MaterialVersion,
    ParseStatus,
    SourceType,
)
from app.models.user import User


def create_test_app() -> FastAPI:
    """Creates a test FastAPI application with AppError exception handler."""
    app = FastAPI(title="Material Router Test App")

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
    user = User(
        id=uuid.uuid4(),
        nickname="test_student",
        is_active=True,
        token_version=1,
    )
    return user


@pytest.fixture
def mock_material_service() -> MagicMock:
    """Fixture providing a mocked MaterialService."""
    return MagicMock()


@pytest.mark.asyncio
async def test_upload_material_success(mock_user: User, mock_material_service: MagicMock) -> None:
    """Tests successful file upload via POST /api/v1/materials/upload."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_material_service] = lambda: mock_material_service

    material_id = uuid.uuid4()
    version_id = uuid.uuid4()
    now = datetime.now(UTC)

    fake_material = Material(
        id=material_id,
        user_id=mock_user.id,
        title="高等数学讲义.pdf",
        file_format="pdf",
        file_size=1024,
        source_type=SourceType.LOCAL.value,
        status=MaterialStatus.PENDING.value,
    )
    fake_material.created_at = now

    fake_version = MaterialVersion(
        id=version_id,
        material_id=material_id,
        user_id=mock_user.id,
        version_number=1,
        storage_key="users/.../v1.pdf",
        content_hash="mockhash",
        parse_status=ParseStatus.QUEUED.value,
    )

    mock_material_service.import_material_file.return_value = (fake_material, fake_version)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        file_bytes = b"%PDF-1.4 test document content"
        files = {"file": ("高等数学讲义.pdf", io.BytesIO(file_bytes), "application/pdf")}
        data = {"title": "高等数学讲义.pdf", "source_type": "local"}
        headers = {"Idempotency-Key": "idem-key-12345678"}

        response = await client.post(
            "/api/v1/materials/upload",
            files=files,
            data=data,
            headers=headers,
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["id"] == str(material_id)
    assert payload["version_id"] == str(version_id)
    assert payload["title"] == "高等数学讲义.pdf"
    assert payload["file_format"] == "pdf"
    assert payload["file_size"] == 1024
    assert payload["status"] == "pending"

    # Verify service delegation parameters
    mock_material_service.import_material_file.assert_called_once_with(
        user_id=mock_user.id,
        file_content=file_bytes,
        filename="高等数学讲义.pdf",
        title="高等数学讲义.pdf",
        source_type="local",
        idempotency_key="idem-key-12345678",
    )


@pytest.mark.asyncio
async def test_upload_material_default_title(
    mock_user: User, mock_material_service: MagicMock
) -> None:
    """Tests file upload when title is omitted."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_material_service] = lambda: mock_material_service

    material_id = uuid.uuid4()
    version_id = uuid.uuid4()
    now = datetime.now(UTC)

    fake_material = Material(
        id=material_id,
        user_id=mock_user.id,
        title="notes.txt",
        file_format="txt",
        file_size=12,
        source_type=SourceType.LOCAL.value,
        status=MaterialStatus.PENDING.value,
    )
    fake_material.created_at = now

    fake_version = MaterialVersion(
        id=version_id,
        material_id=material_id,
        user_id=mock_user.id,
        version_number=1,
        storage_key="users/.../notes.txt",
        content_hash="mockhash",
        parse_status=ParseStatus.QUEUED.value,
    )

    mock_material_service.import_material_file.return_value = (fake_material, fake_version)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        file_bytes = b"Hello world!"
        files = {"file": ("notes.txt", io.BytesIO(file_bytes), "text/plain")}

        response = await client.post("/api/v1/materials/upload", files=files)

    assert response.status_code == 201
    mock_material_service.import_material_file.assert_called_once_with(
        user_id=mock_user.id,
        file_content=file_bytes,
        filename="notes.txt",
        title=None,
        source_type="local",
        idempotency_key=None,
    )


@pytest.mark.asyncio
async def test_upload_material_invalid_file_rejected(
    mock_user: User, mock_material_service: MagicMock
) -> None:
    """Tests upload failure when service raises MaterialInvalidError."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_material_service] = lambda: mock_material_service

    mock_material_service.import_material_file.side_effect = MaterialInvalidError(
        "文件内容魔数与声明格式不匹配",
        details={"declared_format": "pdf"},
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        files = {"file": ("bad.pdf", io.BytesIO(b"not a real pdf"), "application/pdf")}
        response = await client.post("/api/v1/materials/upload", files=files)

    assert response.status_code == 400
    payload = response.json()
    assert payload["code"] == 40001
    assert "魔数" in payload["message"]


@pytest.mark.asyncio
async def test_upload_material_unauthorized(mock_material_service: MagicMock) -> None:
    """Tests that unauthenticated upload request receives HTTP 401."""
    app = create_test_app()
    app.dependency_overrides[get_material_service] = lambda: mock_material_service

    def fail_auth() -> User:
        raise AuthenticationError("请求头缺失认证凭据 (Authorization Header)")

    app.dependency_overrides[get_current_user] = fail_auth

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        files = {"file": ("test.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")}
        response = await client.post("/api/v1/materials/upload", files=files)

    assert response.status_code == 401
    payload = response.json()
    assert payload["code"] == 20001


@pytest.mark.asyncio
async def test_get_material_detail_success(
    mock_user: User, mock_material_service: MagicMock
) -> None:
    """Tests GET /api/v1/materials/{material_id} returns correct detail data."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_material_service] = lambda: mock_material_service

    material_id = uuid.uuid4()
    version_id = uuid.uuid4()
    now = datetime.now(UTC)

    fake_material = Material(
        id=material_id,
        user_id=mock_user.id,
        title="微积分精讲.pdf",
        file_format="pdf",
        file_size=2048,
        source_type=SourceType.LOCAL.value,
        status=MaterialStatus.READY.value,
        current_version_id=version_id,
    )
    fake_material.created_at = now
    fake_material.updated_at = now

    fake_version = MaterialVersion(
        id=version_id,
        material_id=material_id,
        user_id=mock_user.id,
        version_number=1,
        storage_key="users/.../v1.pdf",
        content_hash="mockhash",
        parse_status=ParseStatus.READY.value,
    )
    fake_material.versions = [fake_version]

    mock_material_service.get_material_detail.return_value = fake_material

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/materials/{material_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == str(material_id)
    assert payload["title"] == "微积分精讲.pdf"
    assert payload["file_format"] == "pdf"
    assert payload["file_size"] == 2048
    assert payload["status"] == "ready"
    assert payload["current_version_id"] == str(version_id)
    assert payload["versions_count"] == 1
    assert "parse_status" in payload
    assert "progress_percentage" in payload

    mock_material_service.get_material_detail.assert_called_once_with(
        material_id=material_id,
        user_id=mock_user.id,
    )


@pytest.mark.asyncio
async def test_get_material_detail_not_found(
    mock_user: User, mock_material_service: MagicMock
) -> None:
    """Tests GET /api/v1/materials/{material_id} returns 404 when material not found."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_material_service] = lambda: mock_material_service

    material_id = uuid.uuid4()
    mock_material_service.get_material_detail.side_effect = MaterialNotFoundError(
        "请求的学习资料不存在或已被删除"
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/materials/{material_id}")

    assert response.status_code == 404
    payload = response.json()
    assert payload["code"] == 40004
    assert "不存在" in payload["message"]


@pytest.mark.asyncio
async def test_get_material_detail_unauthorized(mock_material_service: MagicMock) -> None:
    """Tests GET /api/v1/materials/{material_id} returns 401 when not authenticated."""
    app = create_test_app()
    app.dependency_overrides[get_material_service] = lambda: mock_material_service

    def fail_auth() -> User:
        raise AuthenticationError("用户不存在或已被移除")

    app.dependency_overrides[get_current_user] = fail_auth

    material_id = uuid.uuid4()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/materials/{material_id}")

    assert response.status_code == 401
    payload = response.json()
    assert payload["code"] == 20001


@pytest.mark.asyncio
async def test_get_material_detail_invalid_uuid(
    mock_user: User, mock_material_service: MagicMock
) -> None:
    """Tests GET /api/v1/materials/invalid-uuid returns 422 validation error."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_material_service] = lambda: mock_material_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/materials/not-a-valid-uuid")

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_materials_success(mock_user: User, mock_material_service: MagicMock) -> None:
    """Tests GET /api/v1/materials with pagination, keyword, and status filters."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_material_service] = lambda: mock_material_service

    now = datetime.now(UTC)
    m1 = Material(
        id=uuid.uuid4(),
        user_id=mock_user.id,
        title="高等数学讲义.pdf",
        file_format="pdf",
        file_size=1024,
        source_type=SourceType.LOCAL.value,
        status=MaterialStatus.READY.value,
        current_version_id=uuid.uuid4(),
    )
    m1.created_at = now
    m1.updated_at = now

    m2 = Material(
        id=uuid.uuid4(),
        user_id=mock_user.id,
        title="线性代数讲义.pdf",
        file_format="pdf",
        file_size=2048,
        source_type=SourceType.LOCAL.value,
        status=MaterialStatus.READY.value,
        current_version_id=uuid.uuid4(),
    )
    m2.created_at = now
    m2.updated_at = now

    mock_material_service.list_materials.return_value = ([m1, m2], 15)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v1/materials?page=2&page_size=2&keyword=讲义&status=ready"
        )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 15
    assert data["limit"] == 2
    assert data["offset"] == 2
    assert len(data["items"]) == 2
    assert data["items"][0]["id"] == str(m1.id)
    assert data["items"][0]["title"] == "高等数学讲义.pdf"
    assert data["items"][1]["id"] == str(m2.id)

    mock_material_service.list_materials.assert_called_once_with(
        user_id=mock_user.id,
        keyword="讲义",
        status="ready",
        page=2,
        page_size=2,
        limit=2,
        offset=2,
    )


@pytest.mark.asyncio
async def test_list_materials_default_params(
    mock_user: User, mock_material_service: MagicMock
) -> None:
    """Tests GET /api/v1/materials with default parameters."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_material_service] = lambda: mock_material_service

    mock_material_service.list_materials.return_value = ([], 0)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/materials")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["limit"] == 20
    assert data["offset"] == 0
    assert data["items"] == []

    mock_material_service.list_materials.assert_called_once_with(
        user_id=mock_user.id,
        keyword=None,
        status=None,
        page=1,
        page_size=20,
        limit=20,
        offset=0,
    )


@pytest.mark.asyncio
async def test_list_materials_status_filter_normalization(
    mock_user: User, mock_material_service: MagicMock
) -> None:
    """Tests GET /api/v1/materials cleans invalid or empty status to None."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_material_service] = lambda: mock_material_service

    mock_material_service.list_materials.return_value = ([], 0)

    for invalid_status in ["", "   ", "all", "undefined", "null", "invalid_val"]:
        mock_material_service.reset_mock()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/materials?status={invalid_status}")

        assert response.status_code == 200
        mock_material_service.list_materials.assert_called_once_with(
            user_id=mock_user.id,
            keyword=None,
            status=None,
            page=1,
            page_size=20,
            limit=20,
            offset=0,
        )


@pytest.mark.asyncio
async def test_list_materials_status_filter_passthrough_known_aliases(
    mock_user: User, mock_material_service: MagicMock
) -> None:
    """Tests GET /api/v1/materials forwards valid statuses and frontend aliases."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_material_service] = lambda: mock_material_service

    mock_material_service.list_materials.return_value = ([], 0)

    for known_status in ["parsing", "ready", "pending", "failed", "retake_required", "completed"]:
        mock_material_service.reset_mock()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/materials?status={known_status}")

        assert response.status_code == 200
        mock_material_service.list_materials.assert_called_once_with(
            user_id=mock_user.id,
            keyword=None,
            status=known_status,
            page=1,
            page_size=20,
            limit=20,
            offset=0,
        )


@pytest.mark.asyncio
async def test_list_materials_with_limit_offset(
    mock_user: User, mock_material_service: MagicMock
) -> None:
    """Tests GET /api/v1/materials with limit and offset query parameters."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_material_service] = lambda: mock_material_service

    mock_material_service.list_materials.return_value = ([], 10)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/materials?limit=5&offset=10")

    assert response.status_code == 200
    data = response.json()
    assert data["limit"] == 5
    assert data["offset"] == 10
    mock_material_service.list_materials.assert_called_once_with(
        user_id=mock_user.id,
        keyword=None,
        status=None,
        page=3,
        page_size=5,
        limit=5,
        offset=10,
    )


@pytest.mark.asyncio
async def test_list_materials_unauthorized(mock_material_service: MagicMock) -> None:
    """Tests GET /api/v1/materials returns 401 when unauthenticated."""
    app = create_test_app()
    app.dependency_overrides[get_material_service] = lambda: mock_material_service

    def fail_auth() -> User:
        raise AuthenticationError("用户凭证失效")

    app.dependency_overrides[get_current_user] = fail_auth

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/materials")

    assert response.status_code == 401
    assert response.json()["code"] == 20001


@pytest.mark.asyncio
async def test_trigger_parse_async_success(
    mock_user: User, mock_material_service: MagicMock
) -> None:
    """Tests POST /api/v1/materials/{id}/parse default async dispatch."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_material_service] = lambda: mock_material_service

    material_id = uuid.uuid4()
    version_id = uuid.uuid4()

    fake_version = MaterialVersion(
        id=version_id,
        material_id=material_id,
        user_id=mock_user.id,
        version_number=1,
        storage_key="key",
        content_hash="hash",
        parse_status=ParseStatus.QUEUED.value,
        is_active=True,
    )
    mock_material_service.trigger_parse.return_value = fake_version

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/v1/materials/{material_id}/parse", json={})

    assert response.status_code == 200
    data = response.json()
    assert data["material_id"] == str(material_id)
    assert data["version_id"] == str(version_id)
    assert data["parse_status"] == "queued"
    assert data["is_active"] is True
    assert "已加入队列" in data["message"]

    mock_material_service.trigger_parse.assert_called_once_with(
        user_id=mock_user.id,
        material_id=material_id,
        version_id=None,
        sync=False,
    )


@pytest.mark.asyncio
async def test_trigger_parse_sync_success(
    mock_user: User, mock_material_service: MagicMock
) -> None:
    """Tests POST /api/v1/materials/{id}/parse sync execution with specific version."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_material_service] = lambda: mock_material_service

    material_id = uuid.uuid4()
    version_id = uuid.uuid4()

    fake_version = MaterialVersion(
        id=version_id,
        material_id=material_id,
        user_id=mock_user.id,
        version_number=2,
        storage_key="key",
        content_hash="hash",
        parse_status=ParseStatus.READY.value,
        is_active=True,
    )
    mock_material_service.trigger_parse.return_value = fake_version

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/materials/{material_id}/parse",
            json={"version_id": str(version_id), "sync": True},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["parse_status"] == "ready"
    assert "同步执行完成" in data["message"]

    mock_material_service.trigger_parse.assert_called_once_with(
        user_id=mock_user.id,
        material_id=material_id,
        version_id=version_id,
        sync=True,
    )


@pytest.mark.asyncio
async def test_trigger_parse_not_found(mock_user: User, mock_material_service: MagicMock) -> None:
    """Tests POST /api/v1/materials/{id}/parse returns 404 when material not found."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_material_service] = lambda: mock_material_service

    material_id = uuid.uuid4()
    mock_material_service.trigger_parse.side_effect = MaterialNotFoundError("请求的学习资料不存在")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/v1/materials/{material_id}/parse", json={})

    assert response.status_code == 404
    assert response.json()["code"] == 40004


@pytest.mark.asyncio
async def test_list_material_versions_success(
    mock_user: User, mock_material_service: MagicMock
) -> None:
    """Tests GET /api/v1/materials/{id}/versions returns version list."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_material_service] = lambda: mock_material_service

    material_id = uuid.uuid4()
    now = datetime.now(UTC)

    v1 = MaterialVersion(
        id=uuid.uuid4(),
        material_id=material_id,
        user_id=mock_user.id,
        version_number=1,
        storage_key="v1.pdf",
        content_hash="hash1",
        parse_status=ParseStatus.READY.value,
        is_active=False,
    )
    v1.created_at = now
    v2 = MaterialVersion(
        id=uuid.uuid4(),
        material_id=material_id,
        user_id=mock_user.id,
        version_number=2,
        storage_key="v2.pdf",
        content_hash="hash2",
        parse_status=ParseStatus.READY.value,
        is_active=True,
    )
    v2.created_at = now

    mock_material_service.list_material_versions.return_value = [v2, v1]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/materials/{material_id}/versions")

    assert response.status_code == 200
    data = response.json()
    assert data["material_id"] == str(material_id)
    assert len(data["versions"]) == 2
    assert data["versions"][0]["version_number"] == 2
    assert data["versions"][0]["is_active"] is True
    assert data["versions"][1]["version_number"] == 1
    assert data["versions"][1]["is_active"] is False

    mock_material_service.list_material_versions.assert_called_once_with(
        user_id=mock_user.id,
        material_id=material_id,
    )


@pytest.mark.asyncio
async def test_list_material_versions_not_found(
    mock_user: User, mock_material_service: MagicMock
) -> None:
    """Tests GET /api/v1/materials/{id}/versions returns 404 when not found."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_material_service] = lambda: mock_material_service

    material_id = uuid.uuid4()
    mock_material_service.list_material_versions.side_effect = MaterialNotFoundError(
        "请求的学习资料不存在"
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/materials/{material_id}/versions")

    assert response.status_code == 404
    assert response.json()["code"] == 40004


@pytest.mark.asyncio
async def test_switch_material_version_success(
    mock_user: User, mock_material_service: MagicMock
) -> None:
    """Tests POST /api/v1/materials/{id}/versions/{version_id}/switch."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_material_service] = lambda: mock_material_service

    material_id = uuid.uuid4()
    version_id = uuid.uuid4()
    now = datetime.now(UTC)

    updated_material = Material(
        id=material_id,
        user_id=mock_user.id,
        title="资料.pdf",
        file_format="pdf",
        file_size=1024,
        source_type=SourceType.LOCAL.value,
        status=MaterialStatus.READY.value,
        current_version_id=version_id,
    )
    updated_material.created_at = now
    updated_material.updated_at = now
    updated_material.versions = []

    mock_material_service.switch_material_version.return_value = updated_material

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/materials/{material_id}/versions/{version_id}/switch"
        )

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(material_id)
    assert data["current_version_id"] == str(version_id)
    assert data["status"] == "ready"

    mock_material_service.switch_material_version.assert_called_once_with(
        user_id=mock_user.id,
        material_id=material_id,
        version_id=version_id,
    )


@pytest.mark.asyncio
async def test_switch_material_version_not_ready(
    mock_user: User, mock_material_service: MagicMock
) -> None:
    """Tests POST /api/v1/materials/{id}/versions/{version_id}/switch
    returns 400 when version not ready.
    """
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_material_service] = lambda: mock_material_service

    material_id = uuid.uuid4()
    version_id = uuid.uuid4()
    mock_material_service.switch_material_version.side_effect = MaterialInvalidError(
        "该版本尚未解析完成，无法切换为当前激活版本"
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/materials/{material_id}/versions/{version_id}/switch"
        )

    assert response.status_code == 400
    assert response.json()["code"] == 40001


@pytest.mark.asyncio
async def test_reshoot_material_page_success(
    mock_user: User, mock_material_service: MagicMock
) -> None:
    """Tests POST /api/v1/materials/{id}/reshoot succeeds with form-data."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_material_service] = lambda: mock_material_service

    material_id = uuid.uuid4()
    version_id = uuid.uuid4()

    fake_page = MaterialOCRPage(
        id=uuid.uuid4(),
        material_id=material_id,
        version_id=version_id,
        page_number=2,
        image_storage_key="users/.../page_2.png",
        raw_text="清晰扫描文本",
        gibberish_ratio=0.02,
        valid_char_count=120,
        is_qualified=True,
        reshoot_count=1,
    )
    fake_version = MaterialVersion(
        id=version_id,
        material_id=material_id,
        user_id=mock_user.id,
        version_number=1,
        storage_key="...",
        content_hash="...",
        parse_status=ParseStatus.READY.value,
    )
    fake_page.version = fake_version
    mock_material_service.reshoot_material_page.return_value = fake_page

    image_content = b"\x89PNG\r\n\x1a\nfakeimagebytes"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/materials/{material_id}/reshoot",
            data={"page_index": 2, "version_id": str(version_id)},
            files={"file": ("page_2.png", io.BytesIO(image_content), "image/png")},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["material_id"] == str(material_id)
    assert data["version_id"] == str(version_id)
    assert data["page_index"] == 2
    assert data["is_qualified"] is True
    assert data["reshoot_count"] == 1
    assert data["parse_status"] == "ready"

    mock_material_service.reshoot_material_page.assert_called_once_with(
        user_id=mock_user.id,
        material_id=material_id,
        page_index=2,
        file_content=image_content,
        version_id=version_id,
    )


@pytest.mark.asyncio
async def test_reshoot_material_page_exceeded_error_40002(
    mock_user: User, mock_material_service: MagicMock
) -> None:
    """Tests POST /api/v1/materials/{id}/reshoot maps ReshootLimitExceededError to 40002."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_material_service] = lambda: mock_material_service

    material_id = uuid.uuid4()
    mock_material_service.reshoot_material_page.side_effect = ReshootLimitExceededError(
        "页面重拍次数已达上限熔断，请重新上传清晰文件"
    )

    image_content = b"\x89PNG\r\n\x1a\nfakeimagebytes"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/materials/{material_id}/reshoot",
            data={"page_index": 1},
            files={"file": ("page_1.png", io.BytesIO(image_content), "image/png")},
        )

    assert response.status_code == 400
    data = response.json()
    assert data["code"] == 40002
    assert "熔断" in data["message"]


@pytest.mark.asyncio
async def test_reshoot_material_page_invalid_index(
    mock_user: User, mock_material_service: MagicMock
) -> None:
    """Tests POST /api/v1/materials/{id}/reshoot rejects page_index < 1 with 422."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_material_service] = lambda: mock_material_service

    material_id = uuid.uuid4()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/materials/{material_id}/reshoot",
            data={"page_index": 0},
            files={"file": ("page_0.png", io.BytesIO(b"data"), "image/png")},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_soft_delete_material_success(
    mock_user: User, mock_material_service: MagicMock
) -> None:
    """Tests DELETE /api/v1/materials/{id} soft deletes material."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_material_service] = lambda: mock_material_service

    material_id = uuid.uuid4()
    mock_material_service.soft_delete_material.return_value = True

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete(f"/api/v1/materials/{material_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["material_id"] == str(material_id)
    assert data["is_deleted"] is True
    assert data["permanent"] is False
    assert "回收站" in data["message"]

    mock_material_service.soft_delete_material.assert_called_once_with(
        user_id=mock_user.id,
        material_id=material_id,
    )


@pytest.mark.asyncio
async def test_soft_delete_material_not_found(
    mock_user: User, mock_material_service: MagicMock
) -> None:
    """Tests DELETE /api/v1/materials/{id} returns 404 when material not found."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_material_service] = lambda: mock_material_service

    material_id = uuid.uuid4()
    mock_material_service.soft_delete_material.side_effect = MaterialNotFoundError(
        "请求的学习资料不存在或已被删除"
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete(f"/api/v1/materials/{material_id}")

    assert response.status_code == 404
    assert response.json()["code"] == 40004


@pytest.mark.asyncio
async def test_hard_delete_material_success(
    mock_user: User, mock_material_service: MagicMock
) -> None:
    """Tests DELETE /api/v1/materials/{id}/hard physical cascade destruction."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_material_service] = lambda: mock_material_service

    material_id = uuid.uuid4()
    mock_material_service.hard_delete_material.return_value = True

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete(f"/api/v1/materials/{material_id}/hard?permanent=true")

    assert response.status_code == 200
    data = response.json()
    assert data["material_id"] == str(material_id)
    assert data["is_deleted"] is True
    assert data["permanent"] is True
    assert "物理级联销毁" in data["message"]

    mock_material_service.hard_delete_material.assert_called_once_with(
        user_id=mock_user.id,
        material_id=material_id,
    )


@pytest.mark.asyncio
async def test_hard_delete_material_not_found(
    mock_user: User, mock_material_service: MagicMock
) -> None:
    """Tests DELETE /api/v1/materials/{id}/hard returns 404 when not found."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_material_service] = lambda: mock_material_service

    material_id = uuid.uuid4()
    mock_material_service.hard_delete_material.side_effect = MaterialNotFoundError(
        "请求的学习资料不存在"
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete(f"/api/v1/materials/{material_id}/hard")

    assert response.status_code == 404
    assert response.json()["code"] == 40004


@pytest.mark.asyncio
async def test_tenant_cross_access_isolation(
    mock_user: User, mock_material_service: MagicMock
) -> None:
    """Tests tenant isolation: accessing another user's material yields 404 without leaking info."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_material_service] = lambda: mock_material_service

    alien_material_id = uuid.uuid4()
    mock_material_service.get_material_detail.side_effect = MaterialNotFoundError(
        "请求的学习资料不存在"
    )
    mock_material_service.soft_delete_material.side_effect = MaterialNotFoundError(
        "请求的学习资料不存在"
    )
    mock_material_service.hard_delete_material.side_effect = MaterialNotFoundError(
        "请求的学习资料不存在"
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res_get = await client.get(f"/api/v1/materials/{alien_material_id}")
        res_soft = await client.delete(f"/api/v1/materials/{alien_material_id}")
        res_hard = await client.delete(f"/api/v1/materials/{alien_material_id}/hard")

    assert res_get.status_code == 404
    assert res_get.json()["code"] == 40004
    assert res_soft.status_code == 404
    assert res_soft.json()["code"] == 40004
    assert res_hard.status_code == 404
    assert res_hard.json()["code"] == 40004


def test_unimplemented_service_dependency() -> None:
    """Tests that calling default get_material_service raises NotImplementedError."""
    with pytest.raises(NotImplementedError) as exc_info:
        get_material_service()
    assert "MaterialService 生产装配工厂尚未挂载" in str(exc_info.value)


@pytest.mark.asyncio
async def test_upload_material_triggers_background_tasks(
    mock_user: User,
    mock_material_service: MagicMock,
) -> None:
    """验证 POST /api/v1/materials/upload 注册 BackgroundTasks 且后台任务通过独立 Session 调度。"""
    from contextlib import contextmanager
    from unittest.mock import MagicMock, patch

    from app.api.v1.materials import run_material_pipeline_background

    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_material_service] = lambda: mock_material_service

    material_id = uuid.uuid4()
    version_id = uuid.uuid4()
    fake_material = Material(
        id=material_id,
        user_id=mock_user.id,
        title="测试讲义.pdf",
        file_format="pdf",
        file_size=1024,
        source_type=SourceType.LOCAL.value,
        status=MaterialStatus.PENDING.value,
    )
    fake_material.created_at = datetime.now(UTC)
    fake_version = MaterialVersion(
        id=version_id,
        material_id=material_id,
        user_id=mock_user.id,
        version_number=1,
        storage_key="users/.../v1.pdf",
        content_hash="mockhash",
        parse_status=ParseStatus.QUEUED.value,
    )
    mock_material_service.import_material_file.return_value = (fake_material, fake_version)

    mock_container = MagicMock()
    app.state.container = mock_container

    # 1. 验证 POST /upload 触发了后台任务调度
    with patch("app.api.v1.materials.run_material_pipeline_background") as mock_bg_runner:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            file_bytes = b"%PDF-1.4 test document content"
            files = {"file": ("测试讲义.pdf", io.BytesIO(file_bytes), "application/pdf")}
            response = await client.post("/api/v1/materials/upload", files=files)

        assert response.status_code == 201
        mock_bg_runner.assert_called_once_with(
            mock_container,
            material_id,
            version_id,
            mock_user.id,
        )

    # 2. 验证 run_material_pipeline_background 独立 Session 执行体
    isolated_session = MagicMock()

    @contextmanager
    def fake_get_session():
        yield isolated_session

    mock_bg_container = MagicMock()
    mock_bg_container.get_session.side_effect = fake_get_session
    mock_bg_mat_service = MagicMock()
    mock_bg_container.create_material_service.return_value = mock_bg_mat_service

    run_material_pipeline_background(
        container=mock_bg_container,
        material_id=material_id,
        version_id=version_id,
        user_id=mock_user.id,
    )

    mock_bg_container.get_session.assert_called_once()
    mock_bg_container.create_material_service.assert_called_once_with(session=isolated_session)
    mock_bg_mat_service.parse_material_pipeline.assert_called_once_with(
        material_id=material_id,
        version_id=version_id,
        user_id=mock_user.id,
    )


@pytest.mark.asyncio
async def test_retry_material_success(mock_user: User, mock_material_service: MagicMock) -> None:
    """Tests POST /api/v1/materials/{material_id}/retry success flow."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_material_service] = lambda: mock_material_service

    material_id = uuid.uuid4()
    version_id = uuid.uuid4()
    now = datetime.now(UTC)

    fake_material = Material(
        id=material_id,
        user_id=mock_user.id,
        title="重试测试.pdf",
        file_format="pdf",
        file_size=2048,
        source_type=SourceType.LOCAL.value,
        status=MaterialStatus.PENDING.value,
    )
    fake_material.created_at = now
    fake_material.updated_at = now

    fake_version = MaterialVersion(
        id=version_id,
        material_id=material_id,
        user_id=mock_user.id,
        version_number=1,
        storage_key="users/test/materials/v1.pdf",
        content_hash="hash_retry_123",
        parse_status=ParseStatus.QUEUED.value,
    )

    mock_material_service.retry_material_pipeline.return_value = (fake_material, fake_version)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(f"/api/v1/materials/{material_id}/retry")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(material_id)
    assert data["status"] == MaterialStatus.PENDING.value
    assert data["current_version_id"] == str(version_id)
    mock_material_service.retry_material_pipeline.assert_called_once_with(
        material_id=material_id,
        user_id=mock_user.id,
    )


@pytest.mark.asyncio
async def test_retry_material_not_found(mock_user: User, mock_material_service: MagicMock) -> None:
    """Tests POST /api/v1/materials/{material_id}/retry when material does not exist."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_material_service] = lambda: mock_material_service

    material_id = uuid.uuid4()
    mock_material_service.retry_material_pipeline.side_effect = MaterialNotFoundError(
        "学习资料不存在"
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(f"/api/v1/materials/{material_id}/retry")

    assert response.status_code == 404
    data = response.json()
    assert data["code"] == 40004
    assert "学习资料不存在" in data["message"]
