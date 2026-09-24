"""Unit tests for practice router endpoints in app/api/v1/practices.py.

Verifies:
1. POST /api/v1/practices (create practice success 201, empty questions 40012, invalid mode 422).
2. GET /api/v1/practices (list pagination and filtering 200).
3. GET /api/v1/practices/{id} (get practice detail and snapshot 200, not found 404/40010).
4. PUT /api/v1/practices/{id}/answers (autosave draft 200, completed status error 400/40011).
5. POST /api/v1/practices/{id}/pause & resume (status transition 200 and error 400/40011).
6. POST /api/v1/practices/{id}/submit (idempotent submit 200, conflict 409, invalid key 400).
7. Tenant authentication (401/20001) and cross-tenant isolation enforcement.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from app.api.deps.auth import get_current_user
from app.api.deps.practice import get_practice_service
from app.api.v1.practices import router as practice_router
from app.core.errors import (
    AppError,
    AuthenticationError,
    IdempotencyConflictError,
    PracticeEmptyQuestionsError,
    PracticeNotFoundError,
    PracticeStatusError,
)
from app.models.practice import AttemptItem, Practice
from app.models.user import User
from app.services.practice import (
    PracticeService,
    PracticeSubmissionResult,
)


def create_test_app() -> FastAPI:
    """创建挂载了 practice 路由与 AppError 异常处理器的测试 FastAPI 应用。"""
    app = FastAPI(title="Practice Router Test App")

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
    """提供当前已认证的租户用户对象。"""
    return User(
        id=uuid.uuid4(),
        nickname="test_learner",
        is_active=True,
        token_version=1,
    )


@pytest.fixture
def mock_practice_service() -> MagicMock:
    """提供已打桩的 PracticeService 实例。"""
    return MagicMock(spec=PracticeService)


def make_fake_practice(
    user_id: uuid.UUID,
    practice_id: uuid.UUID | None = None,
    material_id: uuid.UUID | None = None,
    title: str = "计算机网络测试",
    status_str: str = "not_started",
    question_count: int = 2,
) -> Practice:
    """构造用于测试的 Practice 实体。"""
    resolved_practice_id = practice_id or uuid.uuid4()
    resolved_material_id = material_id or uuid.uuid4()
    practice = Practice(
        id=resolved_practice_id,
        user_id=user_id,
        material_id=resolved_material_id,
        title=title,
        status=status_str,
        source_type="normal",
        question_count=question_count,
        knowledge_point_ids=[str(uuid.uuid4())],
        question_types=["single_choice"],
        ordered_question_ids=[],
        created_at=datetime.now(UTC),
    )
    practice.items = [
        AttemptItem(
            id=uuid.uuid4(),
            practice_id=resolved_practice_id,
            question_id=uuid.uuid4(),
            user_id=user_id,
            order_index=1,
            is_answered=False,
            duration_seconds=0,
            max_score=1.0,
            question_snapshot={
                "stem": "TCP 建立连接需要几次握手？",
                "question_type": "single_choice",
                "options": [
                    {"key": "A", "content": "1次"},
                    {"key": "B", "content": "2次"},
                    {"key": "C", "content": "3次"},
                ],
                "answer": "C",
                "analysis": "TCP通过三次握手建立连接",
                "difficulty": 3,
            },
        )
    ]
    return practice


# ==============================================================================
# 1. POST /api/v1/practices (创建练习并组卷) 测试用例
# ==============================================================================


@pytest.mark.asyncio
async def test_create_practice_success(
    mock_user: User,
    mock_practice_service: MagicMock,
) -> None:
    """测试创建练习成功返回 201 及题目快照。"""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_practice_service] = lambda: mock_practice_service

    material_id = uuid.uuid4()
    knowledge_point_id = uuid.uuid4()
    practice = make_fake_practice(
        user_id=mock_user.id,
        material_id=material_id,
        title="网络协议专项测试",
    )
    mock_practice_service.create_practice.return_value = practice

    payload = {
        "title": "网络协议专项测试",
        "material_id": str(material_id),
        "knowledge_point_ids": [str(knowledge_point_id)],
        "question_count": 10,
        "mode": "sequential",
    }

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post("/api/v1/practices", json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["practice_id"] == str(practice.id)
    assert data["title"] == "网络协议专项测试"
    assert len(data["items"]) == 1
    assert data["items"][0]["question_snapshot"]["stem"] == "TCP 建立连接需要几次握手？"

    mock_practice_service.create_practice.assert_called_once()
    called_kwargs = mock_practice_service.create_practice.call_args.kwargs
    assert called_kwargs["user_id"] == mock_user.id
    assert called_kwargs["options"].title == "网络协议专项测试"


@pytest.mark.asyncio
async def test_create_practice_empty_questions_error(
    mock_user: User,
    mock_practice_service: MagicMock,
) -> None:
    """测试题库题目不足时返回 400 (40012)。"""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_practice_service] = lambda: mock_practice_service

    mock_practice_service.create_practice.side_effect = PracticeEmptyQuestionsError(
        "可用题目不足以满足组卷出题要求"
    )

    payload = {
        "title": "题量不足测试",
        "material_id": str(uuid.uuid4()),
        "knowledge_point_ids": [str(uuid.uuid4())],
        "question_count": 20,
    }

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post("/api/v1/practices", json=payload)

    assert response.status_code == 400
    data = response.json()
    assert data["code"] == 40012
    assert "可用题目不足" in data["message"]


@pytest.mark.asyncio
async def test_create_practice_invalid_mode(
    mock_user: User,
    mock_practice_service: MagicMock,
) -> None:
    """测试非法组卷模式返回 422 验证错误。"""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_practice_service] = lambda: mock_practice_service

    payload = {
        "title": "非法模式测试",
        "material_id": str(uuid.uuid4()),
        "knowledge_point_ids": [str(uuid.uuid4())],
        "question_count": 10,
        "mode": "invalid_mode",
    }

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post("/api/v1/practices", json=payload)

    assert response.status_code == 422


# ==============================================================================
# 2. GET /api/v1/practices (练习列表查询与分页) 测试用例
# ==============================================================================


@pytest.mark.asyncio
async def test_list_practices_success(
    mock_user: User,
    mock_practice_service: MagicMock,
) -> None:
    """测试查询练习列表与分页参数正常返回 200。"""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_practice_service] = lambda: mock_practice_service

    practice_one = make_fake_practice(user_id=mock_user.id, title="练习一")
    practice_two = make_fake_practice(user_id=mock_user.id, title="练习二")
    mock_practice_service.list_practices.return_value = [practice_one, practice_two]

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/practices?offset=0&limit=20")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert data["limit"] == 20
    assert data["offset"] == 0
    assert len(data["items"]) == 2
    assert data["items"][0]["title"] == "练习一"
    assert data["items"][1]["title"] == "练习二"

    mock_practice_service.list_practices.assert_called_once_with(
        user_id=mock_user.id,
        status=None,
        material_id=None,
        offset=0,
        limit=20,
    )


@pytest.mark.asyncio
async def test_list_practices_filtering(
    mock_user: User,
    mock_practice_service: MagicMock,
) -> None:
    """测试带状态与资料过滤条件的练习列表查询。"""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_practice_service] = lambda: mock_practice_service

    material_id = uuid.uuid4()
    mock_practice_service.list_practices.return_value = []

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            f"/api/v1/practices?status=in_progress&material_id={material_id}&offset=10&limit=5"
        )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["limit"] == 5
    assert data["offset"] == 10

    mock_practice_service.list_practices.assert_called_once_with(
        user_id=mock_user.id,
        status="in_progress",
        material_id=material_id,
        offset=10,
        limit=5,
    )


# ==============================================================================
# 3. GET /api/v1/practices/{id} (练习详情查询) 测试用例
# ==============================================================================


@pytest.mark.asyncio
async def test_get_practice_detail_success(
    mock_user: User,
    mock_practice_service: MagicMock,
) -> None:
    """测试获取练习详情与题目快照成功返回 200。"""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_practice_service] = lambda: mock_practice_service

    practice_id = uuid.uuid4()
    practice = make_fake_practice(user_id=mock_user.id, practice_id=practice_id)
    mock_practice_service.get_practice.return_value = practice

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(f"/api/v1/practices/{practice_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["practice_id"] == str(practice_id)
    assert len(data["items"]) == 1
    assert data["items"][0]["order_index"] == 1

    mock_practice_service.get_practice.assert_called_once_with(
        user_id=mock_user.id,
        practice_id=practice_id,
    )


@pytest.mark.asyncio
async def test_get_practice_detail_not_found(
    mock_user: User,
    mock_practice_service: MagicMock,
) -> None:
    """测试练习不存在或越权时返回 404 (40010)。"""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_practice_service] = lambda: mock_practice_service

    practice_id = uuid.uuid4()
    mock_practice_service.get_practice.side_effect = PracticeNotFoundError(
        "请求的练习不存在或无权访问"
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(f"/api/v1/practices/{practice_id}")

    assert response.status_code == 404
    data = response.json()
    assert data["code"] == 40010


# ==============================================================================
# 4. PUT /api/v1/practices/{id}/answers (逐题作答实时暂存) 测试用例
# ==============================================================================


@pytest.mark.asyncio
async def test_save_answer_success(
    mock_user: User,
    mock_practice_service: MagicMock,
) -> None:
    """测试逐题作答草稿实时暂存成功返回 200。"""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_practice_service] = lambda: mock_practice_service

    practice_id = uuid.uuid4()
    question_id = uuid.uuid4()
    attempt_item_id = uuid.uuid4()

    mock_item = AttemptItem(
        id=attempt_item_id,
        practice_id=practice_id,
        question_id=question_id,
        user_id=mock_user.id,
        order_index=1,
        user_answer="C",
        duration_seconds=15,
        is_answered=True,
        question_snapshot={"stem": "题干", "question_type": "single_choice", "answer": "C"},
    )
    mock_practice_service.save_answer.return_value = mock_item

    payload = {
        "question_id": str(question_id),
        "user_answer": "C",
        "time_spent_seconds": 15,
    }

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.put(f"/api/v1/practices/{practice_id}/answers", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["attempt_item_id"] == str(attempt_item_id)
    assert data["user_answer"] == "C"
    assert data["status"] == "answered"
    assert data["duration_seconds"] == 15

    mock_practice_service.save_answer.assert_called_once_with(
        user_id=mock_user.id,
        practice_id=practice_id,
        question_id=question_id,
        user_answer="C",
        time_spent_seconds=15,
    )


@pytest.mark.asyncio
async def test_save_answer_completed_status_forbidden(
    mock_user: User,
    mock_practice_service: MagicMock,
) -> None:
    """测试已完成的练习禁止修改作答返回 400 (40011)。"""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_practice_service] = lambda: mock_practice_service

    practice_id = uuid.uuid4()
    mock_practice_service.save_answer.side_effect = PracticeStatusError("练习已完成，禁止修改作答")

    payload = {
        "question_id": str(uuid.uuid4()),
        "user_answer": "B",
        "time_spent_seconds": 5,
    }

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.put(f"/api/v1/practices/{practice_id}/answers", json=payload)

    assert response.status_code == 400
    data = response.json()
    assert data["code"] == 40011
    assert "禁止修改" in data["message"]


@pytest.mark.asyncio
async def test_save_answer_paused_status_forbidden(
    mock_user: User,
    mock_practice_service: MagicMock,
) -> None:
    """测试暂停状态下的练习禁止作答返回 400 (40011)。"""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_practice_service] = lambda: mock_practice_service

    practice_id = uuid.uuid4()
    mock_practice_service.save_answer.side_effect = PracticeStatusError(
        "练习处于暂停状态，禁止提交作答"
    )

    payload = {
        "question_id": str(uuid.uuid4()),
        "user_answer": "B",
        "time_spent_seconds": 5,
    }

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.put(f"/api/v1/practices/{practice_id}/answers", json=payload)

    assert response.status_code == 400
    data = response.json()
    assert data["code"] == 40011
    assert "暂停状态" in data["message"]


# ==============================================================================
# 5. POST /api/v1/practices/{id}/pause & resume (暂停与恢复) 测试用例
# ==============================================================================


@pytest.mark.asyncio
async def test_pause_and_resume_practice_success(
    mock_user: User,
    mock_practice_service: MagicMock,
) -> None:
    """测试暂停与恢复生命周期流转正常返回 200。"""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_practice_service] = lambda: mock_practice_service

    practice_id = uuid.uuid4()

    # 1. 暂停测试
    paused_practice = make_fake_practice(
        user_id=mock_user.id,
        practice_id=practice_id,
        status_str="paused",
    )
    mock_practice_service.pause_practice.return_value = paused_practice

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        pause_response = await client.post(f"/api/v1/practices/{practice_id}/pause")

    assert pause_response.status_code == 200
    pause_data = pause_response.json()
    assert pause_data["practice_id"] == str(practice_id)
    assert pause_data["status"] == "paused"
    mock_practice_service.pause_practice.assert_called_once_with(
        user_id=mock_user.id,
        practice_id=practice_id,
    )

    # 2. 恢复测试
    resumed_practice = make_fake_practice(
        user_id=mock_user.id,
        practice_id=practice_id,
        status_str="in_progress",
    )
    mock_practice_service.resume_practice.return_value = resumed_practice

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resume_response = await client.post(f"/api/v1/practices/{practice_id}/resume")

    assert resume_response.status_code == 200
    resume_data = resume_response.json()
    assert resume_data["practice_id"] == str(practice_id)
    assert resume_data["status"] == "in_progress"
    mock_practice_service.resume_practice.assert_called_once_with(
        user_id=mock_user.id,
        practice_id=practice_id,
    )


@pytest.mark.asyncio
async def test_pause_practice_status_error(
    mock_user: User,
    mock_practice_service: MagicMock,
) -> None:
    """测试非进行中状态暂停报错返回 400 (40011)。"""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_practice_service] = lambda: mock_practice_service

    practice_id = uuid.uuid4()
    mock_practice_service.pause_practice.side_effect = PracticeStatusError("当前状态不允许暂停")

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(f"/api/v1/practices/{practice_id}/pause")

    assert response.status_code == 400
    data = response.json()
    assert data["code"] == 40011


@pytest.mark.asyncio
async def test_resume_practice_status_error(
    mock_user: User,
    mock_practice_service: MagicMock,
) -> None:
    """测试非暂停状态恢复报错返回 400 (40011)。"""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_practice_service] = lambda: mock_practice_service

    practice_id = uuid.uuid4()
    mock_practice_service.resume_practice.side_effect = PracticeStatusError("当前状态不允许恢复")

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(f"/api/v1/practices/{practice_id}/resume")

    assert response.status_code == 400
    data = response.json()
    assert data["code"] == 40011


# ==============================================================================
# 6. POST /api/v1/practices/{id}/submit (交卷强幂等调度) 测试用例
# ==============================================================================


@pytest.mark.asyncio
async def test_submit_practice_success(
    mock_user: User,
    mock_practice_service: MagicMock,
) -> None:
    """测试交卷强幂等提交成功返回 200 及调度状态。"""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_practice_service] = lambda: mock_practice_service

    practice_id = uuid.uuid4()
    idempotency_key = str(uuid.uuid4())
    now = datetime.now(UTC)

    mock_result = PracticeSubmissionResult(
        practice_id=practice_id,
        task_id="task_grading_7c9e",
        status="completed",
        unanswered_count=0,
        total_questions=10,
        submitted_at=now,
        answered_questions=10,
    )
    mock_practice_service.submit_practice.return_value = mock_result

    headers = {"Idempotency-Key": idempotency_key}
    payload = {"confirm_unanswered": False}

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            f"/api/v1/practices/{practice_id}/submit",
            headers=headers,
            json=payload,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["practice_id"] == str(practice_id)
    assert data["status"] == "completed"
    assert data["task_id"] == "task_grading_7c9e"
    assert data["uncompleted_count"] == 0

    mock_practice_service.submit_practice.assert_called_once_with(
        user_id=mock_user.id,
        practice_id=practice_id,
        idempotency_key=idempotency_key,
    )


@pytest.mark.asyncio
async def test_submit_practice_idempotency_conflict(
    mock_user: User,
    mock_practice_service: MagicMock,
) -> None:
    """测试并发交卷冲突时返回 409 (30017)。"""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_practice_service] = lambda: mock_practice_service

    practice_id = uuid.uuid4()
    idempotency_key = str(uuid.uuid4())

    mock_practice_service.submit_practice.side_effect = IdempotencyConflictError(
        "请求正在并发处理中，请勿重复提交"
    )

    headers = {"Idempotency-Key": idempotency_key}

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            f"/api/v1/practices/{practice_id}/submit",
            headers=headers,
        )

    assert response.status_code == 409
    data = response.json()
    assert data["code"] == 30017
    assert "并发处理中" in data["message"]


@pytest.mark.asyncio
async def test_submit_practice_invalid_idempotency_key(
    mock_user: User,
    mock_practice_service: MagicMock,
) -> None:
    """测试非法幂等键格式阻断返回 400 (10001)。"""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_practice_service] = lambda: mock_practice_service

    practice_id = uuid.uuid4()

    # 1. 包含非法字符的幂等键
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            f"/api/v1/practices/{practice_id}/submit",
            headers={"Idempotency-Key": "invalid key with spaces & *#$"},
        )

    assert response.status_code == 400
    data = response.json()
    assert data["code"] == 10001

    # 2. 空白字符幂等键
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response_blank = await client.post(
            f"/api/v1/practices/{practice_id}/submit",
            headers={"Idempotency-Key": "   "},
        )

    assert response_blank.status_code == 400
    data_blank = response_blank.json()
    assert data_blank["code"] == 10001


# ==============================================================================
# 7. 鉴权与租户跨访问隔离测试用例
# ==============================================================================


@pytest.mark.asyncio
async def test_unauthenticated_request(
    mock_practice_service: MagicMock,
) -> None:
    """测试未登录请求被鉴权拦截返回 401 (20001)。"""
    app = create_test_app()

    # 模拟未登录鉴权抛出 AuthenticationError
    def raise_auth_error() -> User:
        raise AuthenticationError("请求头缺失认证凭据")

    app.dependency_overrides[get_current_user] = raise_auth_error
    app.dependency_overrides[get_practice_service] = lambda: mock_practice_service

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/practices")

    assert response.status_code == 401
    data = response.json()
    assert data["code"] == 20001


@pytest.mark.asyncio
async def test_cross_tenant_isolation_propagation(
    mock_user: User,
    mock_practice_service: MagicMock,
) -> None:
    """测试跨租户访问练习被严格拦截并透传用户标识。"""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_practice_service] = lambda: mock_practice_service

    practice_id = uuid.uuid4()
    mock_practice_service.get_practice.side_effect = PracticeNotFoundError(
        "请求的练习不存在或无权访问"
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(f"/api/v1/practices/{practice_id}")

    assert response.status_code == 404
    data = response.json()
    assert data["code"] == 40010
    mock_practice_service.get_practice.assert_called_once_with(
        user_id=mock_user.id,
        practice_id=practice_id,
    )
