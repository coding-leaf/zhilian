"""Unit tests for folder router and material folder-attribution endpoints.

Verifies:
1. POST/GET/GET-by-id/PATCH/DELETE/POST-restore/DELETE-purge on /api/v1/folders.
2. POST /materials/upload accepts optional folder_id.
3. GET /materials supports __none__ (unclassified) filtering.
4. PATCH /materials/{id}/folder moves material attribution.
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
from app.api.deps.folder import get_folder_service
from app.api.deps.material import get_material_service
from app.api.v1 import api_v1_router
from app.core.errors import (
    AppError,
    FolderNameConflictError,
    FolderNotFoundError,
    MaterialNotFoundError,
)
from app.models.knowledge import KnowledgePoint
from app.models.material import (
    Material,
    MaterialFolder,
    MaterialStatus,
    MaterialVersion,
    ParseStatus,
)
from app.models.user import User
from app.services.folder import FolderAggregate


def create_test_app() -> FastAPI:
    """Creates a test FastAPI application with AppError exception handler."""
    app = FastAPI(title="Folder Router Test App")

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
    return User(id=uuid.uuid4(), nickname="folder_user", is_active=True, token_version=1)


@pytest.fixture
def mock_folder_service() -> MagicMock:
    """Fixture providing a mocked FolderService."""
    return MagicMock()


@pytest.fixture
def mock_material_service() -> MagicMock:
    """Fixture providing a mocked MaterialService."""
    return MagicMock()


def _make_folder(name: str = "计算机网络") -> MaterialFolder:
    """Build a detached MaterialFolder with populated timestamps."""
    now = datetime.now(UTC)
    folder = MaterialFolder(id=uuid.uuid4(), name=name, sort_order=0, archived_at=None)
    folder.created_at = now
    folder.updated_at = now
    folder.user_id = uuid.uuid4()
    return folder


def _make_aggregate(folder: MaterialFolder, **overrides: object) -> FolderAggregate:
    """Build a FolderAggregate with zeroed counts and optional overrides."""
    defaults: dict[str, object] = {
        "material_count": 0,
        "ready_material_count": 0,
        "knowledge_point_count": 0,
        "question_count": 0,
        "last_practice_at": None,
    }
    defaults.update(overrides)
    return FolderAggregate(folder=folder, **defaults)  # type: ignore[arg-type]


def _make_material(folder_id: uuid.UUID | None) -> Material:
    """Build a detached Material with populated timestamps."""
    now = datetime.now(UTC)
    material = Material(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        title="资料.pdf",
        file_format="pdf",
        file_size=10,
        source_type="local",
        status=MaterialStatus.READY.value,
        folder_id=folder_id,
    )
    material.created_at = now
    material.updated_at = now
    return material


@pytest.mark.asyncio
async def test_create_folder(mock_user: User, mock_folder_service: MagicMock) -> None:
    """POST /folders creates a folder and returns 201."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_folder_service] = lambda: mock_folder_service

    folder = _make_folder("计算机网络")
    mock_folder_service.create_folder.return_value = _make_aggregate(
        folder, material_count=3, ready_material_count=2
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/folders", json={"name": "计算机网络"})

    assert response.status_code == 201
    payload = response.json()
    assert payload["name"] == "计算机网络"
    assert payload["is_archived"] is False
    assert payload["material_count"] == 3
    assert payload["ready_material_count"] == 2
    mock_folder_service.create_folder.assert_called_once_with(
        user_id=mock_user.id, name="计算机网络"
    )


@pytest.mark.asyncio
async def test_create_folder_name_conflict(mock_user: User, mock_folder_service: MagicMock) -> None:
    """POST /folders maps FolderNameConflictError to 409."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_folder_service] = lambda: mock_folder_service
    mock_folder_service.create_folder.side_effect = FolderNameConflictError()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/folders", json={"name": "重复课程"})

    assert response.status_code == 409
    assert response.json()["code"] == 40021


@pytest.mark.asyncio
async def test_list_folders(mock_user: User, mock_folder_service: MagicMock) -> None:
    """GET /folders returns aggregated list and total."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_folder_service] = lambda: mock_folder_service

    folder = _make_folder("课程一")
    mock_folder_service.list_folders.return_value = ([_make_aggregate(folder)], 1)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/folders", params={"include_archived": "true"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["name"] == "课程一"
    mock_folder_service.list_folders.assert_called_once_with(
        user_id=mock_user.id, include_archived=True, limit=100, offset=0
    )


@pytest.mark.asyncio
async def test_get_folder_not_found(mock_user: User, mock_folder_service: MagicMock) -> None:
    """GET /folders/{id} maps FolderNotFoundError to 404."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_folder_service] = lambda: mock_folder_service
    mock_folder_service.get_folder.side_effect = FolderNotFoundError()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/folders/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["code"] == 40020


@pytest.mark.asyncio
async def test_rename_folder(mock_user: User, mock_folder_service: MagicMock) -> None:
    """PATCH /folders/{id} renames and returns 200."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_folder_service] = lambda: mock_folder_service
    folder = _make_folder("新名称")
    mock_folder_service.rename_folder.return_value = _make_aggregate(folder)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch(f"/api/v1/folders/{folder.id}", json={"name": "新名称"})

    assert response.status_code == 200
    assert response.json()["name"] == "新名称"


@pytest.mark.asyncio
async def test_archive_folder(mock_user: User, mock_folder_service: MagicMock) -> None:
    """DELETE /folders/{id} archives and returns purge_after."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_folder_service] = lambda: mock_folder_service

    folder = _make_folder("归档课程")
    folder.archived_at = datetime.now(UTC)
    mock_folder_service.archive_folder.return_value = _make_aggregate(folder)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete(f"/api/v1/folders/{folder.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["is_deleted"] is True
    assert payload["archived_at"] is not None
    assert payload["purge_after"] is not None


@pytest.mark.asyncio
async def test_restore_folder(mock_user: User, mock_folder_service: MagicMock) -> None:
    """POST /folders/{id}/restore returns restored folder."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_folder_service] = lambda: mock_folder_service
    folder = _make_folder("恢复课程")
    mock_folder_service.restore_folder.return_value = _make_aggregate(folder)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/v1/folders/{folder.id}/restore")

    assert response.status_code == 200
    assert response.json()["is_archived"] is False
    mock_folder_service.restore_folder.assert_called_once()


@pytest.mark.asyncio
async def test_purge_folder(mock_user: User, mock_folder_service: MagicMock) -> None:
    """DELETE /folders/{id}/purge performs immediate physical cleanup."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_folder_service] = lambda: mock_folder_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete(f"/api/v1/folders/{uuid.uuid4()}/purge")

    assert response.status_code == 200
    assert response.json()["is_deleted"] is True
    mock_folder_service.purge_folder.assert_called_once()


@pytest.mark.asyncio
async def test_upload_material_with_folder_id(
    mock_user: User, mock_material_service: MagicMock
) -> None:
    """POST /materials/upload forwards folder_id to the service."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_material_service] = lambda: mock_material_service

    folder_id = uuid.uuid4()
    material = _make_material(folder_id)
    version = MaterialVersion(
        id=uuid.uuid4(),
        material_id=material.id,
        user_id=mock_user.id,
        version_number=1,
        storage_key="k",
        content_hash="h",
        parse_status=ParseStatus.QUEUED.value,
    )
    mock_material_service.import_material_file.return_value = (material, version)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/materials/upload",
            files={"file": ("资料.pdf", io.BytesIO(b"%PDF-1.4 content"), "application/pdf")},
            data={"folder_id": str(folder_id)},
        )

    assert response.status_code == 201
    assert mock_material_service.import_material_file.call_args.kwargs["folder_id"] == folder_id


@pytest.mark.asyncio
async def test_list_materials_unclassified_filter(
    mock_user: User, mock_material_service: MagicMock
) -> None:
    """GET /materials?folder_id=__none__ maps to unclassified filtering."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_material_service] = lambda: mock_material_service
    mock_material_service.list_materials.return_value = ([_make_material(None)], 1)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/materials", params={"folder_id": "__none__"})

    assert response.status_code == 200
    kwargs = mock_material_service.list_materials.call_args.kwargs
    assert kwargs["unclassified"] is True
    assert kwargs["folder_id"] is None
    assert response.json()["items"][0]["folder_id"] is None


@pytest.mark.asyncio
async def test_list_materials_invalid_folder_id(
    mock_user: User, mock_material_service: MagicMock
) -> None:
    """GET /materials with malformed folder_id returns 400."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_material_service] = lambda: mock_material_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/materials", params={"folder_id": "not-a-uuid"})

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_move_material_folder(
    mock_user: User,
    mock_folder_service: MagicMock,
    mock_material_service: MagicMock,
) -> None:
    """PATCH /materials/{id}/folder delegates move then returns detail."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_folder_service] = lambda: mock_folder_service
    app.dependency_overrides[get_material_service] = lambda: mock_material_service

    folder_id = uuid.uuid4()
    material = _make_material(folder_id)
    mock_material_service.get_material_detail.return_value = material

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch(
            f"/api/v1/materials/{material.id}/folder",
            json={"folder_id": str(folder_id)},
        )

    assert response.status_code == 200
    assert response.json()["folder_id"] == str(folder_id)
    mock_folder_service.move_material.assert_called_once_with(
        user_id=mock_user.id, material_id=material.id, folder_id=folder_id
    )


@pytest.mark.asyncio
async def test_move_material_folder_bad_target(
    mock_user: User,
    mock_folder_service: MagicMock,
    mock_material_service: MagicMock,
) -> None:
    """PATCH /materials/{id}/folder maps errors to 4xx."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_folder_service] = lambda: mock_folder_service
    app.dependency_overrides[get_material_service] = lambda: mock_material_service
    mock_folder_service.move_material.side_effect = FolderNotFoundError()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch(
            f"/api/v1/materials/{uuid.uuid4()}/folder",
            json={"folder_id": str(uuid.uuid4())},
        )

    assert response.status_code == 404

    mock_folder_service.move_material.side_effect = MaterialNotFoundError()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch(
            f"/api/v1/materials/{uuid.uuid4()}/folder",
            json={"folder_id": None},
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_folder_knowledge_points_groups_by_material(
    mock_user: User,
    mock_folder_service: MagicMock,
) -> None:
    """GET /folders/{id}/knowledge-points groups knowledge points by source material."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_folder_service] = lambda: mock_folder_service

    folder_id = uuid.uuid4()
    material_a = uuid.uuid4()
    material_b = uuid.uuid4()
    point_a1 = KnowledgePoint(
        id=uuid.uuid4(),
        user_id=mock_user.id,
        material_id=material_a,
        version_id=uuid.uuid4(),
        name="导数",
        level=1,
        batch_id="batch-kp",
    )
    point_a2 = KnowledgePoint(
        id=uuid.uuid4(),
        user_id=mock_user.id,
        material_id=material_a,
        version_id=point_a1.version_id,
        name="定积分",
        level=2,
        parent_id=point_a1.id,
        batch_id="batch-kp",
    )
    point_b1 = KnowledgePoint(
        id=uuid.uuid4(),
        user_id=mock_user.id,
        material_id=material_b,
        version_id=uuid.uuid4(),
        name="概率",
        level=1,
        batch_id="batch-kp",
    )
    mock_folder_service.list_folder_knowledge_points.return_value = [
        (point_a1, material_a, "高数笔记"),
        (point_a2, material_a, "高数笔记"),
        (point_b1, material_b, "概率论讲义"),
    ]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/folders/{folder_id}/knowledge-points")

    assert response.status_code == 200
    payload = response.json()
    assert payload["folder_id"] == str(folder_id)
    assert payload["total"] == 3
    assert [group["material_title"] for group in payload["groups"]] == ["高数笔记", "概率论讲义"]
    assert len(payload["groups"][0]["knowledge_points"]) == 2
    assert payload["groups"][1]["knowledge_points"][0]["name"] == "概率"
    mock_folder_service.list_folder_knowledge_points.assert_called_once_with(
        user_id=mock_user.id, folder_id=folder_id
    )


@pytest.mark.asyncio
async def test_list_folder_knowledge_points_archived_maps_404(
    mock_user: User,
    mock_folder_service: MagicMock,
) -> None:
    """GET /folders/{id}/knowledge-points maps archived/unknown folder to 404."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_folder_service] = lambda: mock_folder_service
    mock_folder_service.list_folder_knowledge_points.side_effect = FolderNotFoundError()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/folders/{uuid.uuid4()}/knowledge-points")

    assert response.status_code == 404
