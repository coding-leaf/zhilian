"""Unit tests for grading router endpoints in app/api/v1/grading.py.

Verifies:
1. POST /api/v1/grading/self-evaluate (self evaluate success, 403 objective, 404 not found).
2. POST /api/v1/grading/regrade (regrade success, 403 not allowed, 500 error, 404 not found).
3. GET /api/v1/attempts/{attempt_item_id}/grading (detail query success, 404 not found).
4. Tenant authentication enforcement (401 unauthenticated).
5. Cross-tenant isolation enforcement and user_id propagation.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from app.api.deps.auth import get_current_user
from app.api.deps.grading import get_grading_service
from app.api.v1.grading import router as grading_router
from app.core.errors import (
    AppError,
    AttemptItemNotFoundError,
    AuthenticationError,
    GradingExecutionError,
    GradingNotAllowedError,
)
from app.models.practice import GradingRecord
from app.models.user import User
from app.services.grading import AttemptGradingDetailDTO, GradingService


def create_test_app() -> FastAPI:
    """创建挂载了 grading 路由与 AppError 异常处理器的测试 FastAPI 应用。"""
    app = FastAPI(title="Grading Router Test App")

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
    api_router.include_router(grading_router)
    app.include_router(api_router)
    return app


@pytest.fixture
def mock_user() -> User:
    """提供当前已认证的租户用户对象。"""
    return User(
        id=uuid.uuid4(),
        nickname="test_learner",
        is_active=True,
        token_version=1,
    )


@pytest.fixture
def mock_grading_service() -> MagicMock:
    """提供已打桩的 GradingService 实例。"""
    return MagicMock(spec=GradingService)


def make_fake_grading_record(
    user_id: uuid.UUID,
    attempt_item_id: uuid.UUID,
    record_id: uuid.UUID | None = None,
    channel: str = "user_self",
    status_str: str = "success",
    score: float = 4.5,
    max_score: float = 5.0,
    feedback: str = "自评得分良好",
    is_final: bool = True,
) -> GradingRecord:
    """构造用于测试的 GradingRecord 实体。"""
    return GradingRecord(
        id=record_id or uuid.uuid4(),
        user_id=user_id,
        practice_id=uuid.uuid4(),
        attempt_item_id=attempt_item_id,
        question_id=uuid.uuid4(),
        channel=channel,
        status=status_str,
        is_final=is_final,
        score=score,
        max_score=max_score,
        confidence=1.0,
        feedback=feedback,
        hit_keywords=[],
        missing_keywords=[],
        grading_metadata={},
        created_at=datetime.now(UTC),
    )


# ==============================================================================
# 1. POST /api/v1/grading/self-evaluate 测试用例
# ==============================================================================


@pytest.mark.asyncio
async def test_self_evaluate_success(
    mock_user: User,
    mock_grading_service: MagicMock,
) -> None:
    """测试主观题自评成功返回 200 及对应自评结果。"""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_grading_service] = lambda: mock_grading_service

    attempt_item_id = uuid.uuid4()
    record_id = uuid.uuid4()
    mock_record = make_fake_grading_record(
        user_id=mock_user.id,
        attempt_item_id=attempt_item_id,
        record_id=record_id,
        channel="user_self",
        score=4.5,
        feedback="回答准确全面",
    )
    mock_grading_service.self_evaluate_attempt.return_value = mock_record

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/grading/self-evaluate",
            json={
                "attempt_item_id": str(attempt_item_id),
                "score": 4.5,
                "feedback": "回答准确全面",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["attempt_item_id"] == str(attempt_item_id)
    assert data["score"] == 4.5
    assert data["channel"] == "user_self"
    assert data["is_final"] is True
    assert data["grading_record_id"] == str(record_id)
    assert data["feedback"] == "回答准确全面"

    # 验证底层调用的 user_id 严格一致
    mock_grading_service.self_evaluate_attempt.assert_called_once()
    call_kwargs = mock_grading_service.self_evaluate_attempt.call_args.kwargs
    assert call_kwargs["user_id"] == mock_user.id
    assert call_kwargs["dto"].attempt_item_id == attempt_item_id
    assert call_kwargs["dto"].score == 4.5
    assert call_kwargs["dto"].feedback == "回答准确全面"


@pytest.mark.asyncio
async def test_self_evaluate_objective_not_allowed(
    mock_user: User,
    mock_grading_service: MagicMock,
) -> None:
    """测试客观题尝试自评被拦截映射为 HTTP 403 与错误码 40014。"""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_grading_service] = lambda: mock_grading_service

    attempt_item_id = uuid.uuid4()
    mock_grading_service.self_evaluate_attempt.side_effect = GradingNotAllowedError(
        message="客观选择与判断题由系统客观判分，不允许用户自主评分",
        details={"question_type": "single_choice"},
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/grading/self-evaluate",
            json={
                "attempt_item_id": str(attempt_item_id),
                "score": 5.0,
            },
        )

    assert response.status_code == 403
    body = response.json()
    assert body["code"] == 40014
    assert "不允许用户自主评分" in body["message"]
    assert body["details"]["question_type"] == "single_choice"


@pytest.mark.asyncio
async def test_self_evaluate_attempt_item_not_found(
    mock_user: User,
    mock_grading_service: MagicMock,
) -> None:
    """测试自评不存在或越权的作答项返回 HTTP 404 与错误码 40013。"""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_grading_service] = lambda: mock_grading_service

    attempt_item_id = uuid.uuid4()
    mock_grading_service.self_evaluate_attempt.side_effect = AttemptItemNotFoundError(
        attempt_item_id=attempt_item_id,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/grading/self-evaluate",
            json={
                "attempt_item_id": str(attempt_item_id),
                "score": 3.0,
            },
        )

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == 40013
    assert "不存在或无权访问" in body["message"]
    assert body["details"]["attempt_item_id"] == str(attempt_item_id)


# ==============================================================================
# 2. POST /api/v1/grading/regrade 测试用例
# ==============================================================================


@pytest.mark.asyncio
async def test_regrade_success(
    mock_user: User,
    mock_grading_service: MagicMock,
) -> None:
    """测试主观题重判同步完成返回 HTTP 200 与真实终态及新分数。"""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_grading_service] = lambda: mock_grading_service

    attempt_item_id = uuid.uuid4()
    record_id = uuid.uuid4()
    mock_record = make_fake_grading_record(
        user_id=mock_user.id,
        attempt_item_id=attempt_item_id,
        record_id=record_id,
        channel="ai",
        status_str="success",
        score=4.2,
    )
    mock_grading_service.regrade_attempt.return_value = mock_record

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/grading/regrade",
            json={
                "attempt_item_id": str(attempt_item_id),
                "reason": "采分点遗漏请重新判定",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["attempt_item_id"] == str(attempt_item_id)
    assert data["status"] == "success"
    assert data["score"] == 4.2
    assert data["is_final"] is True
    assert data["grading_record_id"] == str(record_id)
    assert "完成" in data["message"]

    mock_grading_service.regrade_attempt.assert_called_once()
    call_kwargs = mock_grading_service.regrade_attempt.call_args.kwargs
    assert call_kwargs["user_id"] == mock_user.id
    assert call_kwargs["dto"].attempt_item_id == attempt_item_id
    assert call_kwargs["dto"].reason == "采分点遗漏请重新判定"


@pytest.mark.asyncio
async def test_regrade_objective_not_allowed(
    mock_user: User,
    mock_grading_service: MagicMock,
) -> None:
    """测试客观题或未作答题目申请重判拦截映射为 HTTP 403 与错误码 40014。"""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_grading_service] = lambda: mock_grading_service

    attempt_item_id = uuid.uuid4()
    mock_grading_service.regrade_attempt.side_effect = GradingNotAllowedError(
        message="客观题目不支持重新判题",
        details={"question_type": "single_choice"},
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/grading/regrade",
            json={"attempt_item_id": str(attempt_item_id)},
        )

    assert response.status_code == 403
    body = response.json()
    assert body["code"] == 40014
    assert "不支持重新判题" in body["message"]


@pytest.mark.asyncio
async def test_regrade_execution_error(
    mock_user: User,
    mock_grading_service: MagicMock,
) -> None:
    """测试重判因大模型或系统故障失败映射为 HTTP 500 与错误码 40015。"""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_grading_service] = lambda: mock_grading_service

    attempt_item_id = uuid.uuid4()
    mock_grading_service.regrade_attempt.side_effect = GradingExecutionError(
        message="大模型服务调用超时或未配置",
        details={"attempt_item_id": str(attempt_item_id)},
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/grading/regrade",
            json={"attempt_item_id": str(attempt_item_id)},
        )

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == 40015
    assert "大模型服务调用超时" in body["message"]


@pytest.mark.asyncio
async def test_regrade_attempt_item_not_found(
    mock_user: User,
    mock_grading_service: MagicMock,
) -> None:
    """测试重判不存在作答项返回 HTTP 404 与错误码 40013。"""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_grading_service] = lambda: mock_grading_service

    attempt_item_id = uuid.uuid4()
    mock_grading_service.regrade_attempt.side_effect = AttemptItemNotFoundError(
        attempt_item_id=attempt_item_id,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/grading/regrade",
            json={"attempt_item_id": str(attempt_item_id)},
        )

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == 40013


# ==============================================================================
# 3. GET /api/v1/attempts/{attempt_item_id}/grading 测试用例
# ==============================================================================


@pytest.mark.asyncio
async def test_get_attempt_grading_detail_success(
    mock_user: User,
    mock_grading_service: MagicMock,
) -> None:
    """测试查询作答项判题历史与最新详情成功返回 HTTP 200 与完整结构。"""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_grading_service] = lambda: mock_grading_service

    attempt_item_id = uuid.uuid4()
    practice_id = uuid.uuid4()
    question_id = uuid.uuid4()

    latest_record = make_fake_grading_record(
        user_id=mock_user.id,
        attempt_item_id=attempt_item_id,
        channel="user_self",
        score=4.0,
        is_final=True,
    )
    old_record = make_fake_grading_record(
        user_id=mock_user.id,
        attempt_item_id=attempt_item_id,
        channel="ai",
        score=2.5,
        is_final=False,
    )

    mock_dto = AttemptGradingDetailDTO(
        attempt_item_id=attempt_item_id,
        practice_id=practice_id,
        question_id=question_id,
        latest_grading=latest_record,
        current_record=latest_record,
        records=[old_record, latest_record],
        history=[old_record, latest_record],
    )
    mock_grading_service.get_attempt_grading_detail.return_value = mock_dto

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            f"/api/v1/attempts/{attempt_item_id}/grading",
        )

    assert response.status_code == 200
    data = response.json()
    assert data["attempt_item_id"] == str(attempt_item_id)
    assert data["practice_id"] == str(practice_id)
    assert data["question_id"] == str(question_id)
    assert data["latest_grading"] is not None
    assert data["latest_grading"]["score"] == 4.0
    assert data["latest_grading"]["channel"] == "user_self"
    assert len(data["records"]) == 2
    assert data["records"][0]["score"] == 2.5
    assert data["records"][1]["score"] == 4.0

    mock_grading_service.get_attempt_grading_detail.assert_called_once_with(
        user_id=mock_user.id,
        attempt_item_id=attempt_item_id,
    )


@pytest.mark.asyncio
async def test_get_attempt_grading_detail_not_found(
    mock_user: User,
    mock_grading_service: MagicMock,
) -> None:
    """测试查询不存在的作答项判题详情返回 HTTP 404 与错误码 40013。"""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_grading_service] = lambda: mock_grading_service

    attempt_item_id = uuid.uuid4()
    mock_grading_service.get_attempt_grading_detail.side_effect = AttemptItemNotFoundError(
        attempt_item_id=attempt_item_id,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            f"/api/v1/attempts/{attempt_item_id}/grading",
        )

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == 40013


# ==============================================================================
# 4. 鉴权与跨租户安全隔离拦截测试
# ==============================================================================


@pytest.mark.asyncio
async def test_unauthenticated_request_rejected(
    mock_grading_service: MagicMock,
) -> None:
    """测试未登录用户请求自评、重判与明细查询均被 401 拦截。"""
    app = create_test_app()

    def raise_auth_error() -> User:
        raise AuthenticationError("用户凭证失效，请重新登录")

    app.dependency_overrides[get_current_user] = raise_auth_error
    app.dependency_overrides[get_grading_service] = lambda: mock_grading_service

    attempt_item_id = uuid.uuid4()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        res1 = await client.post(
            "/api/v1/grading/self-evaluate",
            json={"attempt_item_id": str(attempt_item_id), "score": 3.0},
        )
        res2 = await client.post(
            "/api/v1/grading/regrade",
            json={"attempt_item_id": str(attempt_item_id)},
        )
        res3 = await client.get(
            f"/api/v1/attempts/{attempt_item_id}/grading",
        )

    assert res1.status_code == 401
    assert res1.json()["code"] == 20001
    assert res2.status_code == 401
    assert res2.json()["code"] == 20001
    assert res3.status_code == 401
    assert res3.json()["code"] == 20001


@pytest.mark.asyncio
async def test_cross_tenant_isolation_propagation(
    mock_user: User,
    mock_grading_service: MagicMock,
) -> None:
    """测试租户 user_id 严格逐层透传至 Service，防止跨租户越权。"""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_grading_service] = lambda: mock_grading_service

    attempt_item_id = uuid.uuid4()
    mock_record = make_fake_grading_record(
        user_id=mock_user.id,
        attempt_item_id=attempt_item_id,
    )
    mock_grading_service.self_evaluate_attempt.return_value = mock_record

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        await client.post(
            "/api/v1/grading/self-evaluate",
            json={"attempt_item_id": str(attempt_item_id), "score": 4.0},
        )

    # 确证传入的 user_id 为当前用户的 id，而非客户端伪造的身份
    call_args = mock_grading_service.self_evaluate_attempt.call_args
    assert call_args.kwargs["user_id"] == mock_user.id
