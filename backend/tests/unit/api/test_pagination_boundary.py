"""接口行为边界测试：分页参数越界（《代码管理工作介绍 V1.0》§4.4 第五类）。

文档要求：「分页参数越界返回参数校验失败而不是空列表」。
生产契约（`app/main.py`）：`RequestValidationError` -> HTTP 422 + `code=10001`
「请求参数校验失败」。本文件以代表性列表接口（materials / questions）锁定该行为，防止：

1. 越界被静默接受并返回 200 + 空列表（把参数错误伪装成「没有数据」）；
2. 校验失败被改写为业务错误码或 500。

说明：`code=10002`「分页参数越界」在《软件需求规格说明书》错误码表中登记，
当前实现统一归并为 10001 参数校验失败（未单独细分）；如需细分须走契约变更评审。
"""

import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from app.api.deps.auth import get_current_user
from app.api.deps.material import get_material_service
from app.api.deps.question import get_question_service
from app.api.v1 import api_v1_router
from app.core.errors import AppError
from app.models.user import User


def create_test_app() -> FastAPI:
    """构造与生产一致的测试应用：AppError + RequestValidationError 双处理器。"""
    app = FastAPI(title="Pagination Boundary Test App")

    @app.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.error_code,
                "message": exc.message,
                "details": exc.details,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # 与 app/main.py 的 validation_error_handler 保持一致（422 + 10001）。
        return JSONResponse(
            status_code=422,
            content={
                "code": 10001,
                "message": "请求参数校验失败",
                "details": exc.errors(),
            },
        )

    app.include_router(api_v1_router)
    return app


@pytest.fixture
def mock_user() -> User:
    return User(
        id=uuid.uuid4(),
        nickname="pagination_student",
        is_active=True,
        token_version=1,
    )


def _client_for(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


class TestMaterialsPaginationBoundary:
    """`GET /api/v1/materials` 分页越界。"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("query", "field"),
        [
            ("page=0", "page"),
            ("page=-1", "page"),
            ("page_size=0", "page_size"),
            ("page_size=101", "page_size"),
            ("limit=101", "limit"),
        ],
    )
    async def test_out_of_range_returns_validation_failure_not_empty_list(
        self, mock_user: User, query: str, field: str
    ) -> None:
        """越界必须返回 422 + 10001，且错误详情指向具体越界字段。"""
        app = create_test_app()
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_material_service] = lambda: MagicMock()

        async with _client_for(app) as client:
            response = await client.get(f"/api/v1/materials?{query}")

        assert response.status_code == 422
        payload = response.json()
        assert payload["code"] == 10001
        assert any(field in str(item) for item in payload["details"])

    @pytest.mark.asyncio
    async def test_valid_pagination_passes_validation(self, mock_user: User) -> None:
        """对照组：合法分页不得被误杀（防「一律 422」的假阳性）。"""
        service = MagicMock()
        service.list_materials.return_value = ([], 0)
        app = create_test_app()
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_material_service] = lambda: service

        async with _client_for(app) as client:
            response = await client.get("/api/v1/materials?page=1&page_size=100")

        assert response.status_code == 200
        assert response.json()["total"] == 0
        assert response.json()["items"] == []


class TestQuestionsPaginationBoundary:
    """`GET /api/v1/questions` 分页越界（跨 router 一致性）。"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("query", ["page=0", "page_size=101"])
    async def test_out_of_range_returns_validation_failure(
        self, mock_user: User, query: str
    ) -> None:
        app = create_test_app()
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_question_service] = lambda: MagicMock()

        async with _client_for(app) as client:
            response = await client.get(f"/api/v1/questions?{query}")

        assert response.status_code == 422
        assert response.json()["code"] == 10001
