"""Unit tests for knowledge router endpoints in app/api/v1/knowledge.py.

Verifies:
1. GET /api/v1/materials/{material_id}/knowledge-tree (tree hierarchy, 404).
2. GET /api/v1/knowledge/{id} (knowledge point detail query, 404).
3. GET /api/v1/knowledge/{id}/snippets (reverse sourcing, 404).
4. GET /api/v1/knowledge/snippets/{snippet_id}/knowledge-points (forward sourcing).
5. POST /api/v1/materials/{material_id}/knowledge/extract (trigger extraction, 400).
6. Tenant cross-access isolation and authentication enforcement.
7. Dependency injection isolation and exception mapping compliance.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from app.api.deps.auth import get_current_user
from app.api.deps.knowledge import get_db_session, get_knowledge_service
from app.api.v1 import api_v1_router
from app.core.errors import (
    AppError,
    KnowledgeNotFoundError,
    MaterialInvalidError,
    MaterialNotFoundError,
    PermissionDeniedError,
)
from app.models.knowledge import KnowledgePoint
from app.models.material import MaterialSnippet
from app.models.user import User


def create_test_app() -> FastAPI:
    """Creates a test FastAPI application with AppError exception handler."""
    app = FastAPI(title="Knowledge Router Test App")

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
        nickname="test_learner",
        is_active=True,
        token_version=1,
    )


@pytest.fixture
def mock_knowledge_service() -> MagicMock:
    """Fixture providing a mocked KnowledgeService."""
    return MagicMock()


@pytest.mark.asyncio
async def test_get_knowledge_tree_success(
    mock_user: User, mock_knowledge_service: MagicMock
) -> None:
    """Tests successful tree query via GET /api/v1/materials/{material_id}/knowledge-tree."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_knowledge_service] = lambda: mock_knowledge_service

    material_id = uuid.uuid4()
    version_id = uuid.uuid4()
    root_id = uuid.uuid4()
    child_id = uuid.uuid4()

    mock_knowledge_service.get_knowledge_tree.return_value = [
        {
            "id": str(root_id),
            "material_id": str(material_id),
            "version_id": str(version_id),
            "parent_id": None,
            "name": "高等数学基础",
            "description": "基础知识框架",
            "level": 1,
            "is_low_confidence": False,
            "children": [
                {
                    "id": str(child_id),
                    "material_id": str(material_id),
                    "version_id": str(version_id),
                    "parent_id": str(root_id),
                    "name": "极限的定义与性质",
                    "description": "数列与函数极限",
                    "level": 2,
                    "is_low_confidence": False,
                    "children": [],
                }
            ],
        }
    ]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/materials/{material_id}/knowledge-tree")

    assert response.status_code == 200
    data = response.json()
    assert data["material_id"] == str(material_id)
    assert data["version_id"] == str(version_id)
    assert len(data["nodes"]) == 1
    assert data["nodes"][0]["name"] == "高等数学基础"
    assert len(data["nodes"][0]["children"]) == 1
    assert data["nodes"][0]["children"][0]["name"] == "极限的定义与性质"

    mock_knowledge_service.get_knowledge_tree.assert_called_once_with(
        material_id=material_id,
        version_id=None,
        user_id=mock_user.id,
    )


@pytest.mark.asyncio
async def test_get_knowledge_tree_with_explicit_version(
    mock_user: User, mock_knowledge_service: MagicMock
) -> None:
    """Tests tree query with explicit version_id query parameter."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_knowledge_service] = lambda: mock_knowledge_service

    material_id = uuid.uuid4()
    version_id = uuid.uuid4()

    mock_knowledge_service.get_knowledge_tree.return_value = []
    mock_knowledge_service.get_latest_version_id.return_value = version_id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/materials/{material_id}/knowledge-tree?version_id={version_id}"
        )

    assert response.status_code == 200
    data = response.json()
    assert data["material_id"] == str(material_id)
    assert data["version_id"] == str(version_id)
    assert data["nodes"] == []

    mock_knowledge_service.get_knowledge_tree.assert_called_once_with(
        material_id=material_id,
        version_id=version_id,
        user_id=mock_user.id,
    )


@pytest.mark.asyncio
async def test_get_knowledge_tree_material_not_found(
    mock_user: User, mock_knowledge_service: MagicMock
) -> None:
    """Tests 404 error when requested material does not exist."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_knowledge_service] = lambda: mock_knowledge_service

    material_id = uuid.uuid4()
    mock_knowledge_service.get_knowledge_tree.side_effect = MaterialNotFoundError(
        "请求的学习资料不存在或已被删除",
        details={"material_id": str(material_id)},
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/materials/{material_id}/knowledge-tree")

    assert response.status_code == 404
    data = response.json()
    assert data["code"] == 40004
    assert "学习资料不存在" in data["message"]


@pytest.mark.asyncio
async def test_get_knowledge_point_detail_success(
    mock_user: User, mock_knowledge_service: MagicMock
) -> None:
    """Tests successful detail retrieval via GET /api/v1/knowledge/{id}."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_knowledge_service] = lambda: mock_knowledge_service

    kp_id = uuid.uuid4()
    material_id = uuid.uuid4()
    version_id = uuid.uuid4()
    now = datetime.now(UTC)

    fake_point = KnowledgePoint(
        id=kp_id,
        user_id=mock_user.id,
        material_id=material_id,
        version_id=version_id,
        parent_id=None,
        name="导数与微分",
        description="导数几何意义与计算法则",
        level=1,
        batch_id="batch_001",
        is_low_confidence=False,
    )
    fake_point.created_at = now
    fake_point.updated_at = now

    mock_knowledge_service.get_knowledge_point_detail.return_value = fake_point

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/knowledge/{kp_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(kp_id)
    assert data["name"] == "导数与微分"
    assert data["level"] == 1
    assert data["batch_id"] == "batch_001"
    assert data["is_low_confidence"] is False

    mock_knowledge_service.get_knowledge_point_detail.assert_called_once_with(
        knowledge_point_id=kp_id,
        user_id=mock_user.id,
    )


@pytest.mark.asyncio
async def test_get_knowledge_point_detail_not_found(
    mock_user: User, mock_knowledge_service: MagicMock
) -> None:
    """Tests 404 when requested knowledge point is missing or cross-tenant."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_knowledge_service] = lambda: mock_knowledge_service

    kp_id = uuid.uuid4()
    mock_knowledge_service.get_knowledge_point_detail.side_effect = KnowledgeNotFoundError(
        "请求的知识点不存在或已被删除",
        details={"knowledge_point_id": str(kp_id)},
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/knowledge/{kp_id}")

    assert response.status_code == 404
    data = response.json()
    assert data["code"] == 40007
    assert "知识点不存在" in data["message"]


@pytest.mark.asyncio
async def test_reverse_sourcing_snippets_success(
    mock_user: User, mock_knowledge_service: MagicMock
) -> None:
    """Tests reverse sourcing snippets for knowledge point via GET /knowledge/{id}/snippets."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_knowledge_service] = lambda: mock_knowledge_service

    kp_id = uuid.uuid4()
    material_id = uuid.uuid4()
    version_id = uuid.uuid4()
    snippet_id = uuid.uuid4()

    fake_snippet = MaterialSnippet(
        id=snippet_id,
        user_id=mock_user.id,
        material_id=material_id,
        version_id=version_id,
        snippet_index=0,
        content="设函数在点及其去心邻域内有定义...",
        char_length=20,
        start_offset=0,
        end_offset=20,
        chapter_title="第一章 极限与连续",
        source_info={"page_number": 3},
    )

    mock_knowledge_service.get_snippets_for_point.return_value = [fake_snippet]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/knowledge/{kp_id}/snippets")

    assert response.status_code == 200
    data = response.json()
    assert data["knowledge_point_id"] == str(kp_id)
    assert len(data["snippets"]) == 1
    snippet_item = data["snippets"][0]
    assert snippet_item["id"] == str(snippet_id)
    assert snippet_item["page_index"] == 3
    assert snippet_item["snippet_index"] == 0
    assert snippet_item["chapter_title"] == "第一章 极限与连续"
    assert "设函数在点" in snippet_item["content"]

    mock_knowledge_service.get_snippets_for_point.assert_called_once_with(
        knowledge_point_id=kp_id,
        user_id=mock_user.id,
    )


@pytest.mark.asyncio
async def test_reverse_sourcing_point_not_found(
    mock_user: User, mock_knowledge_service: MagicMock
) -> None:
    """Tests 404 when reverse sourcing a non-existent knowledge point."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_knowledge_service] = lambda: mock_knowledge_service

    kp_id = uuid.uuid4()
    mock_knowledge_service.get_snippets_for_point.side_effect = KnowledgeNotFoundError(
        "请求的知识点不存在或已被删除",
        details={"knowledge_point_id": str(kp_id)},
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/knowledge/{kp_id}/snippets")

    assert response.status_code == 404
    data = response.json()
    assert data["code"] == 40007


@pytest.mark.asyncio
async def test_forward_sourcing_knowledge_points_success(
    mock_user: User, mock_knowledge_service: MagicMock
) -> None:
    """Tests forward sourcing points for snippet via GET /knowledge/snippets/.../points."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_knowledge_service] = lambda: mock_knowledge_service

    snippet_id = uuid.uuid4()
    kp_id = uuid.uuid4()
    material_id = uuid.uuid4()
    version_id = uuid.uuid4()
    now = datetime.now(UTC)

    fake_point = KnowledgePoint(
        id=kp_id,
        user_id=mock_user.id,
        material_id=material_id,
        version_id=version_id,
        parent_id=None,
        name="无穷小量比较法则",
        description="等价无穷小替换定理",
        level=2,
        batch_id="batch_002",
        is_low_confidence=False,
    )
    fake_point.created_at = now
    fake_point.updated_at = now

    mock_knowledge_service.get_points_for_snippet.return_value = [fake_point]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/knowledge/snippets/{snippet_id}/knowledge-points")

    assert response.status_code == 200
    data = response.json()
    assert data["snippet_id"] == str(snippet_id)
    assert len(data["knowledge_points"]) == 1
    assert data["knowledge_points"][0]["id"] == str(kp_id)
    assert data["knowledge_points"][0]["name"] == "无穷小量比较法则"

    mock_knowledge_service.get_points_for_snippet.assert_called_once_with(
        snippet_id=snippet_id,
        user_id=mock_user.id,
    )


@pytest.mark.asyncio
async def test_forward_sourcing_empty_points(
    mock_user: User, mock_knowledge_service: MagicMock
) -> None:
    """Tests forward sourcing returning empty list."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_knowledge_service] = lambda: mock_knowledge_service

    snippet_id = uuid.uuid4()
    mock_knowledge_service.get_points_for_snippet.return_value = []

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/knowledge/snippets/{snippet_id}/knowledge-points")

    assert response.status_code == 200
    data = response.json()
    assert data["snippet_id"] == str(snippet_id)
    assert data["knowledge_points"] == []


@pytest.mark.asyncio
async def test_trigger_extraction_success(
    mock_user: User, mock_knowledge_service: MagicMock
) -> None:
    """Tests triggering knowledge extraction via POST /materials/{id}/knowledge/extract."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_knowledge_service] = lambda: mock_knowledge_service

    material_id = uuid.uuid4()
    version_id = uuid.uuid4()

    mock_knowledge_service.trigger_extraction.return_value = {
        "material_id": material_id,
        "version_id": version_id,
        "extracted_count": 8,
        "has_low_confidence": False,
        "status": "ready",
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/materials/{material_id}/knowledge/extract",
            json={"version_id": str(version_id)},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["material_id"] == str(material_id)
    assert data["version_id"] == str(version_id)
    assert data["extracted_count"] == 8
    assert data["has_low_confidence"] is False
    assert data["status"] == "ready"

    mock_knowledge_service.trigger_extraction.assert_called_once_with(
        material_id=material_id,
        version_id=version_id,
        user_id=mock_user.id,
    )


@pytest.mark.asyncio
async def test_trigger_extraction_default_version(
    mock_user: User, mock_knowledge_service: MagicMock
) -> None:
    """Tests triggering extraction without version_id in payload."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_knowledge_service] = lambda: mock_knowledge_service

    material_id = uuid.uuid4()
    resolved_version_id = uuid.uuid4()

    mock_knowledge_service.trigger_extraction.return_value = {
        "material_id": material_id,
        "version_id": resolved_version_id,
        "extracted_count": 12,
        "has_low_confidence": True,
        "status": "ready",
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/materials/{material_id}/knowledge/extract",
            json={},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["extracted_count"] == 12
    assert data["has_low_confidence"] is True

    mock_knowledge_service.trigger_extraction.assert_called_once_with(
        material_id=material_id,
        version_id=None,
        user_id=mock_user.id,
    )


@pytest.mark.asyncio
async def test_trigger_extraction_material_invalid(
    mock_user: User, mock_knowledge_service: MagicMock
) -> None:
    """Tests 400 error when extraction is triggered on empty snippets material."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_knowledge_service] = lambda: mock_knowledge_service

    material_id = uuid.uuid4()
    mock_knowledge_service.trigger_extraction.side_effect = MaterialInvalidError(
        "学习资料切片为空，无法进行知识点抽取",
        details={"material_id": str(material_id)},
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/materials/{material_id}/knowledge/extract",
            json={},
        )

    assert response.status_code == 400
    data = response.json()
    assert data["code"] == 40001
    assert "切片为空" in data["message"]


@pytest.mark.asyncio
async def test_unauthenticated_requests(mock_knowledge_service: MagicMock) -> None:
    """Tests 401 when request is unauthenticated."""
    app = create_test_app()
    # No get_current_user override, default raises AuthenticationError or 401
    app.dependency_overrides[get_knowledge_service] = lambda: mock_knowledge_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/knowledge/{uuid.uuid4()}")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_tenant_cross_access_isolation(
    mock_user: User, mock_knowledge_service: MagicMock
) -> None:
    """Tests tenant isolation: service called with user.id and handles unauthorized access."""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_knowledge_service] = lambda: mock_knowledge_service

    kp_id = uuid.uuid4()
    # Service rejects cross-tenant access with 403 or 404
    mock_knowledge_service.get_knowledge_point_detail.side_effect = PermissionDeniedError(
        "无权访问非本人归属资源",
        details={"resource_id": str(kp_id)},
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/knowledge/{kp_id}")

    assert response.status_code == 403
    data = response.json()
    assert data["code"] == 20002


def test_default_dependency_providers() -> None:
    """Tests that calling default dependency providers directly raises NotImplementedError."""
    with pytest.raises(NotImplementedError, match="KnowledgeService 生产装配工厂尚未挂载"):
        get_knowledge_service()

    with pytest.raises(NotImplementedError, match="数据库会话工厂尚未挂载"):
        get_db_session()
