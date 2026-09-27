"""多租户与端到端闭环集成测试模块。

覆盖 Milestone 4 核心验收要求：
1. 端到端完整闭环流转测试：
   (1) 创建练习 (POST /api/v1/practices)；
   (2) 逐题保存作答 (PUT /api/v1/practices/{id}/answers)；
   (3) 暂停与恢复练习 (POST /api/v1/practices/{id}/pause & POST /api/v1/practices/{id}/resume)；
   (4) 提交交卷携带幂等键 (POST /api/v1/practices/{id}/submit)；
   (5) 重复交卷验证强幂等性回放；
   (6) 查看作答项判题明细 (GET /api/v1/attempts/{attempt_item_id}/grading)；
   (7) 主观题用户自评打分覆盖 (POST /api/v1/grading/self-evaluate)；
   (8) 申请大模型重新判题 (POST /api/v1/grading/regrade)。
2. 多租户越权攻击拦截测试：
   - 用户 B 携带合法 Token 试图读取、修改、暂停、恢复、提交用户 A 的练习，
     或查询、自评、重判用户 A 的作答项；
   - 断言 100% 拦截并返回 404 (NotFoundError) 或 403 (NotAllowedError)；
   - 绝密脱敏与无数据跨租户泄漏保障。
3. 全局路由装配验证：
   - 挂载由 app/api/v1/__init__.py 聚合的全局 api_v1_router，验证 practices 与 grading 路由拓扑。
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
from app.api.deps.grading import get_grading_service
from app.api.deps.practice import get_practice_service
from app.api.v1 import api_v1_router
from app.core.errors import (
    AppError,
    AttemptItemNotFoundError,
    AuthenticationError,
    GradingNotAllowedError,
    IdempotencyConflictError,
    PracticeNotFoundError,
)
from app.models.practice import AttemptItem, GradingRecord, Practice
from app.models.user import User
from app.services.grading import AttemptGradingDetailDTO, GradingService
from app.services.practice import PracticeService, PracticeSubmissionResult


def create_test_app() -> FastAPI:
    """创建挂载全局 api_v1_router 与 AppError 异常处理器的测试 FastAPI 应用。

    Returns:
        FastAPI: 配置完毕的测试应用实例。
    """
    app = FastAPI(title="Practice & Grading Flow Integration Test App")

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
def user_a() -> User:
    """提供租户用户 A 实例。"""
    return User(
        id=uuid.uuid4(),
        nickname="learner_a",
        is_active=True,
        token_version=1,
    )


@pytest.fixture
def user_b() -> User:
    """提供租户用户 B 实例。"""
    return User(
        id=uuid.uuid4(),
        nickname="learner_b",
        is_active=True,
        token_version=1,
    )


@pytest.fixture
def mock_practice_service() -> MagicMock:
    """提供已打桩的 PracticeService 实例。"""
    return MagicMock(spec=PracticeService)


@pytest.fixture
def mock_grading_service() -> MagicMock:
    """提供已打桩的 GradingService 实例。"""
    return MagicMock(spec=GradingService)


def make_fake_practice(
    user_id: uuid.UUID,
    practice_id: uuid.UUID | None = None,
    material_id: uuid.UUID | None = None,
    status_str: str = "not_started",
    question_count: int = 2,
) -> tuple[Practice, AttemptItem, AttemptItem]:
    """构造用于集成测试的练习及关联的客观题与主观题作答项。

    Args:
        user_id: 租户用户标识。
        practice_id: 练习标识。
        material_id: 资料标识。
        status_str: 练习状态。
        question_count: 题目数量。

    Returns:
        tuple[Practice, AttemptItem, AttemptItem]: 练习实体与客观题、主观题作答项实体。
    """
    resolved_practice_id = practice_id or uuid.uuid4()
    resolved_material_id = material_id or uuid.uuid4()
    question_1_id = uuid.uuid4()
    question_2_id = uuid.uuid4()
    attempt_item_1_id = uuid.uuid4()
    attempt_item_2_id = uuid.uuid4()

    item_objective = AttemptItem(
        id=attempt_item_1_id,
        practice_id=resolved_practice_id,
        question_id=question_1_id,
        user_id=user_id,
        order_index=1,
        is_answered=False,
        duration_seconds=0,
        max_score=2.0,
        question_snapshot={
            "stem": "TCP 三次握手第二次握手 SYN 报文包含什么？",
            "question_type": "single_choice",
            "options": [
                {"key": "A", "content": "SYN=1, ACK=0"},
                {"key": "B", "content": "SYN=1, ACK=1"},
                {"key": "C", "content": "FIN=1, ACK=1"},
            ],
            "answer": "B",
            "analysis": "第二次握手由服务端发送 SYN+ACK 报文",
            "difficulty": 3,
        },
    )

    item_subjective = AttemptItem(
        id=attempt_item_2_id,
        practice_id=resolved_practice_id,
        question_id=question_2_id,
        user_id=user_id,
        order_index=2,
        is_answered=False,
        duration_seconds=0,
        max_score=5.0,
        question_snapshot={
            "stem": "简述拥塞控制与流量控制的区别与联系。",
            "question_type": "short_answer",
            "options": [],
            "answer": "流量控制是点对点通信量的控制；拥塞控制是防止过量数据注入网络。",
            "analysis": "考查端到端通信与网络全局视角的区别",
            "difficulty": 4,
        },
    )

    practice = Practice(
        id=resolved_practice_id,
        user_id=user_id,
        material_id=resolved_material_id,
        title="计算机网络全链路自测",
        status=status_str,
        source_type="normal",
        question_count=question_count,
        knowledge_point_ids=[str(uuid.uuid4())],
        question_types=["single_choice", "short_answer"],
        ordered_question_ids=[str(question_1_id), str(question_2_id)],
        created_at=datetime.now(UTC),
    )
    practice.items = [item_objective, item_subjective]
    return practice, item_objective, item_subjective


def make_fake_grading_record(
    user_id: uuid.UUID,
    attempt_item_id: uuid.UUID,
    practice_id: uuid.UUID,
    question_id: uuid.UUID,
    channel: str = "ai",
    status_str: str = "success",
    score: float = 4.5,
    max_score: float = 5.0,
    feedback: str = "重点采分点齐全",
    is_final: bool = True,
) -> GradingRecord:
    """构造用于测试的判题记录实体。

    Args:
        user_id: 租户用户标识。
        attempt_item_id: 作答项标识。
        practice_id: 练习标识。
        question_id: 题目标识。
        channel: 判题渠道 (system, user_self, ai)。
        status_str: 判题状态。
        score: 得分。
        max_score: 满分。
        feedback: 评语反馈。
        is_final: 是否为终局判定。

    Returns:
        GradingRecord: 判题记录实体。
    """
    return GradingRecord(
        id=uuid.uuid4(),
        user_id=user_id,
        practice_id=practice_id,
        attempt_item_id=attempt_item_id,
        question_id=question_id,
        channel=channel,
        status=status_str,
        is_final=is_final,
        score=score,
        max_score=max_score,
        confidence=0.92,
        feedback=feedback,
        hit_keywords=["流量控制", "拥塞控制"],
        missing_keywords=[],
        grading_metadata={"algorithm": "ai_scoring_v1"},
        created_at=datetime.now(UTC),
    )


# ==============================================================================
# 1. 端到端完整闭环流转测试 (End-to-End Closed-Loop Flow)
# ==============================================================================


@pytest.mark.asyncio
async def test_practice_grading_full_closed_loop_flow(
    user_a: User,
    mock_practice_service: MagicMock,
    mock_grading_service: MagicMock,
) -> None:
    """端到端完整闭环流转验证。

    依次执行：
    1. POST /api/v1/practices (创建练习与组卷)
    2. PUT /api/v1/practices/{id}/answers (逐题保存作答草稿)
    3. POST /api/v1/practices/{id}/pause & resume (生命周期暂停与恢复)
    4. POST /api/v1/practices/{id}/submit (交卷携带幂等键)
    5. 重复 POST /api/v1/practices/{id}/submit (回放相同快照与幂等性验证)
    6. GET /api/v1/attempts/{attempt_item_id}/grading (查看判题详情与历史)
    7. POST /api/v1/grading/self-evaluate (主观题用户自主评分)
    8. POST /api/v1/grading/regrade (申请大模型异步重新判题)
    """
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: user_a
    app.dependency_overrides[get_practice_service] = lambda: mock_practice_service
    app.dependency_overrides[get_grading_service] = lambda: mock_grading_service

    material_id = uuid.uuid4()
    knowledge_point_id = uuid.uuid4()
    practice, item_obj, item_sub = make_fake_practice(user_id=user_a.id, material_id=material_id)
    practice_id = practice.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # ----------------------------------------------------------------------
        # 步骤 1: 创建练习会话 (POST /api/v1/practices)
        # ----------------------------------------------------------------------
        mock_practice_service.create_practice.return_value = practice

        create_payload: dict[str, Any] = {
            "title": "计算机网络全链路自测",
            "material_id": str(material_id),
            "knowledge_point_ids": [str(knowledge_point_id)],
            "question_count": 2,
            "mode": "sequential",
        }
        create_response = await client.post("/api/v1/practices", json=create_payload)
        assert create_response.status_code == 201
        created_data = create_response.json()
        assert created_data["practice_id"] == str(practice_id)
        assert len(created_data["items"]) == 2
        assert created_data["items"][0]["order_index"] == 1
        assert created_data["items"][1]["order_index"] == 2

        # ----------------------------------------------------------------------
        # 步骤 2: 逐题保存作答草稿 (PUT /api/v1/practices/{id}/answers)
        # ----------------------------------------------------------------------
        item_obj.user_answer = "B"
        item_obj.duration_seconds = 18
        item_obj.is_answered = True
        mock_practice_service.save_answer.return_value = item_obj

        save_obj_response = await client.put(
            f"/api/v1/practices/{practice_id}/answers",
            json={
                "question_id": str(item_obj.question_id),
                "user_answer": "B",
                "time_spent_seconds": 18,
            },
        )
        assert save_obj_response.status_code == 200
        save_obj_data = save_obj_response.json()
        assert save_obj_data["attempt_item_id"] == str(item_obj.id)
        assert save_obj_data["user_answer"] == "B"
        assert save_obj_data["duration_seconds"] == 18

        item_sub.user_answer = "流量控制是点对点，拥塞控制是端系统与全局网络控制。"
        item_sub.duration_seconds = 45
        item_sub.is_answered = True
        mock_practice_service.save_answer.return_value = item_sub

        save_sub_response = await client.put(
            f"/api/v1/practices/{practice_id}/answers",
            json={
                "question_id": str(item_sub.question_id),
                "user_answer": "流量控制是点对点，拥塞控制是端系统与全局网络控制。",
                "time_spent_seconds": 45,
            },
        )
        assert save_sub_response.status_code == 200
        save_sub_data = save_sub_response.json()
        assert save_sub_data["attempt_item_id"] == str(item_sub.id)
        assert save_sub_data["duration_seconds"] == 45

        # ----------------------------------------------------------------------
        # 步骤 3: 暂停与恢复练习 (POST /api/v1/practices/{id}/pause & resume)
        # ----------------------------------------------------------------------
        practice.status = "paused"
        mock_practice_service.pause_practice.return_value = practice

        pause_response = await client.post(f"/api/v1/practices/{practice_id}/pause")
        assert pause_response.status_code == 200
        assert pause_response.json()["status"] == "paused"

        practice.status = "in_progress"
        mock_practice_service.resume_practice.return_value = practice

        resume_response = await client.post(f"/api/v1/practices/{practice_id}/resume")
        assert resume_response.status_code == 200
        assert resume_response.json()["status"] == "in_progress"

        # ----------------------------------------------------------------------
        # 步骤 4: 提交交卷携带 Idempotency-Key (POST /api/v1/practices/{id}/submit)
        # ----------------------------------------------------------------------
        idempotency_key = "idem-flow-test-" + str(uuid.uuid4())
        submission_now = datetime.now(UTC)
        submit_result = PracticeSubmissionResult(
            practice_id=practice_id,
            task_id="task_pipeline_batch_001",
            status="completed",
            unanswered_count=0,
            total_questions=2,
            submitted_at=submission_now,
            answered_questions=2,
        )
        mock_practice_service.submit_practice.return_value = submit_result

        submit_response = await client.post(
            f"/api/v1/practices/{practice_id}/submit",
            headers={"Idempotency-Key": idempotency_key},
            json={"confirm_unanswered": False},
        )
        assert submit_response.status_code == 200
        submit_data = submit_response.json()
        assert submit_data["practice_id"] == str(practice_id)
        assert submit_data["status"] == "completed"
        assert submit_data["task_id"] == "task_pipeline_batch_001"
        assert submit_data["uncompleted_count"] == 0

        # ----------------------------------------------------------------------
        # 步骤 5: 重复交卷验证幂等性回放
        # ----------------------------------------------------------------------
        duplicate_submit_response = await client.post(
            f"/api/v1/practices/{practice_id}/submit",
            headers={"Idempotency-Key": idempotency_key},
            json={"confirm_unanswered": False},
        )
        assert duplicate_submit_response.status_code == 200
        duplicate_data = duplicate_submit_response.json()
        assert duplicate_data["practice_id"] == str(practice_id)
        assert duplicate_data["task_id"] == "task_pipeline_batch_001"
        assert duplicate_data["status"] == "completed"

        # ----------------------------------------------------------------------
        # 步骤 6: 查看判题记录明细 (GET /api/v1/attempts/{attempt_item_id}/grading)
        # ----------------------------------------------------------------------
        sub_question_id = uuid.UUID(str(item_sub.question_id))
        ai_grading_record = make_fake_grading_record(
            user_id=user_a.id,
            attempt_item_id=item_sub.id,
            practice_id=practice_id,
            question_id=sub_question_id,
            channel="ai",
            score=3.5,
            feedback="答出核心概念，但缺乏对比细节",
            is_final=True,
        )
        mock_dto = AttemptGradingDetailDTO(
            attempt_item_id=item_sub.id,
            practice_id=practice_id,
            question_id=sub_question_id,
            latest_grading=ai_grading_record,
            current_record=ai_grading_record,
            records=[ai_grading_record],
            history=[ai_grading_record],
        )
        mock_grading_service.get_attempt_grading_detail.return_value = mock_dto

        grading_detail_response = await client.get(f"/api/v1/attempts/{item_sub.id}/grading")
        assert grading_detail_response.status_code == 200
        grading_detail_data = grading_detail_response.json()
        assert grading_detail_data["attempt_item_id"] == str(item_sub.id)
        assert grading_detail_data["latest_grading"]["score"] == 3.5
        assert grading_detail_data["latest_grading"]["channel"] == "ai"
        assert len(grading_detail_data["records"]) == 1

        # ----------------------------------------------------------------------
        # 步骤 7: 主观题用户自评打分覆盖 (POST /api/v1/grading/self-evaluate)
        # ----------------------------------------------------------------------
        self_eval_record = make_fake_grading_record(
            user_id=user_a.id,
            attempt_item_id=item_sub.id,
            practice_id=practice_id,
            question_id=sub_question_id,
            channel="user_self",
            score=4.5,
            feedback="对照标准答案，自我评估逻辑严谨",
            is_final=True,
        )
        mock_grading_service.self_evaluate_attempt.return_value = self_eval_record

        self_eval_response = await client.post(
            "/api/v1/grading/self-evaluate",
            json={
                "attempt_item_id": str(item_sub.id),
                "score": 4.5,
                "feedback": "对照标准答案，自我评估逻辑严谨",
            },
        )
        assert self_eval_response.status_code == 200
        self_eval_data = self_eval_response.json()
        assert self_eval_data["attempt_item_id"] == str(item_sub.id)
        assert self_eval_data["score"] == 4.5
        assert self_eval_data["channel"] == "user_self"
        assert self_eval_data["is_final"] is True
        assert self_eval_data["feedback"] == "对照标准答案，自我评估逻辑严谨"

        # ----------------------------------------------------------------------
        # 步骤 8: 申请大模型重新判题 (POST /api/v1/grading/regrade，同步完成)
        # ----------------------------------------------------------------------
        regrade_record = make_fake_grading_record(
            user_id=user_a.id,
            attempt_item_id=item_sub.id,
            practice_id=practice_id,
            question_id=sub_question_id,
            channel="ai",
            status_str="success",
            score=4.2,
            feedback="重判后得分更新",
            is_final=True,
        )
        mock_grading_service.regrade_attempt.return_value = regrade_record

        regrade_response = await client.post(
            "/api/v1/grading/regrade",
            json={
                "attempt_item_id": str(item_sub.id),
                "reason": "自我评估与AI差异较大，申请AI专家重判",
            },
        )
        assert regrade_response.status_code == 200
        regrade_data = regrade_response.json()
        assert regrade_data["attempt_item_id"] == str(item_sub.id)
        assert regrade_data["status"] == "success"
        assert regrade_data["score"] == 4.2
        assert regrade_data["is_final"] is True
        assert "完成" in regrade_data["message"]


# ==============================================================================
# 2. 幂等性冲突与异常防御测试 (Idempotency Defenses)
# ==============================================================================


@pytest.mark.asyncio
async def test_submit_practice_concurrent_conflict(
    user_a: User,
    mock_practice_service: MagicMock,
) -> None:
    """交卷并发冲突防御测试：相同幂等键在处理中时返回 409 (错误码 30017)。"""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: user_a
    app.dependency_overrides[get_practice_service] = lambda: mock_practice_service

    practice_id = uuid.uuid4()
    mock_practice_service.submit_practice.side_effect = IdempotencyConflictError(
        "请求正在并发处理中，请勿重复提交"
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/practices/{practice_id}/submit",
            headers={"Idempotency-Key": "concurrent-lock-key-123"},
        )

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == 30017
    assert "并发处理中" in body["message"]


# ==============================================================================
# 3. 多租户越权攻击拦截与数据隔离测试 (Multi-Tenant Isolation & Attacks)
# ==============================================================================


@pytest.mark.asyncio
async def test_multi_tenant_unauthorized_practice_access_intercepted(
    user_a: User,
    user_b: User,
    mock_practice_service: MagicMock,
) -> None:
    """多租户越权攻击防御：用户 B 试图查看、修改、暂停、恢复、提交用户 A 的练习。

    断言：
    - 路由层获取并透传的必须是已认证用户 B 的真实 ID；
    - Service 层因所属租户不符抛出 PracticeNotFoundError；
    - 统一返回 404 Not Found (错误码 40010)；
    - 绝无用户 A 的练习、题目或答案信息泄漏。
    """
    app = create_test_app()
    # 当前已认证上下文为用户 B
    app.dependency_overrides[get_current_user] = lambda: user_b
    app.dependency_overrides[get_practice_service] = lambda: mock_practice_service

    practice_a, item_a, _ = make_fake_practice(user_id=user_a.id)
    practice_a_id = practice_a.id

    # 模拟用户 B 访问用户 A 练习时，Service 校验 user_id 发现不匹配抛出 404
    def practice_side_effect(user_id: uuid.UUID, *args: Any, **kwargs: Any) -> Any:
        if user_id != user_a.id:
            raise PracticeNotFoundError(f"练习 {practice_a_id} 不存在或无权访问")
        return practice_a

    mock_practice_service.get_practice.side_effect = practice_side_effect
    mock_practice_service.save_answer.side_effect = practice_side_effect
    mock_practice_service.pause_practice.side_effect = practice_side_effect
    mock_practice_service.resume_practice.side_effect = practice_side_effect
    mock_practice_service.submit_practice.side_effect = practice_side_effect

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. 用户 B 试图查询用户 A 的练习详情
        get_response = await client.get(f"/api/v1/practices/{practice_a_id}")
        assert get_response.status_code == 404
        assert get_response.json()["code"] == 40010
        assert "无权访问" in get_response.json()["message"]
        mock_practice_service.get_practice.assert_called_with(
            user_id=user_b.id,
            practice_id=practice_a_id,
        )

        # 2. 用户 B 试图修改用户 A 的作答草稿
        put_response = await client.put(
            f"/api/v1/practices/{practice_a_id}/answers",
            json={
                "question_id": str(item_a.question_id),
                "user_answer": "恶意篡改答案",
                "time_spent_seconds": 1,
            },
        )
        assert put_response.status_code == 404
        assert put_response.json()["code"] == 40010
        mock_practice_service.save_answer.assert_called_with(
            user_id=user_b.id,
            practice_id=practice_a_id,
            question_id=item_a.question_id,
            user_answer="恶意篡改答案",
            time_spent_seconds=1,
        )

        # 3. 用户 B 试图暂停用户 A 的练习
        pause_response = await client.post(f"/api/v1/practices/{practice_a_id}/pause")
        assert pause_response.status_code == 404
        assert pause_response.json()["code"] == 40010
        mock_practice_service.pause_practice.assert_called_with(
            user_id=user_b.id,
            practice_id=practice_a_id,
        )

        # 4. 用户 B 试图恢复用户 A 的练习
        resume_response = await client.post(f"/api/v1/practices/{practice_a_id}/resume")
        assert resume_response.status_code == 404
        assert resume_response.json()["code"] == 40010
        mock_practice_service.resume_practice.assert_called_with(
            user_id=user_b.id,
            practice_id=practice_a_id,
        )

        # 5. 用户 B 试图代提交用户 A 的练习
        submit_response = await client.post(
            f"/api/v1/practices/{practice_a_id}/submit",
            headers={"Idempotency-Key": "malicious-submit-" + str(uuid.uuid4())},
        )
        assert submit_response.status_code == 404
        assert submit_response.json()["code"] == 40010
        mock_practice_service.submit_practice.assert_called_with(
            user_id=user_b.id,
            practice_id=practice_a_id,
            idempotency_key=submit_response.request.headers.get("Idempotency-Key"),
        )


@pytest.mark.asyncio
async def test_multi_tenant_unauthorized_grading_access_intercepted(
    user_a: User,
    user_b: User,
    mock_grading_service: MagicMock,
) -> None:
    """多租户越权攻击防御：用户 B 试图查询、自评、重判用户 A 的作答项。

    断言：
    - 路由层将已认证用户 B 的真实 ID 透传至 Service；
    - Service 层校验租户不一致抛出 AttemptItemNotFoundError；
    - 返回 404 Not Found (错误码 40013)；
    - 严禁透露用户 A 的作答原图、答案或历史判分。
    """
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: user_b
    app.dependency_overrides[get_grading_service] = lambda: mock_grading_service

    attempt_item_a_id = uuid.uuid4()

    def grading_side_effect(user_id: uuid.UUID, *args: Any, **kwargs: Any) -> Any:
        if user_id != user_a.id:
            raise AttemptItemNotFoundError(attempt_item_id=attempt_item_a_id)
        return None

    mock_grading_service.get_attempt_grading_detail.side_effect = grading_side_effect
    mock_grading_service.self_evaluate_attempt.side_effect = grading_side_effect
    mock_grading_service.regrade_attempt.side_effect = grading_side_effect

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. 用户 B 试图查询用户 A 的作答项判题详情与历史
        detail_response = await client.get(f"/api/v1/attempts/{attempt_item_a_id}/grading")
        assert detail_response.status_code == 404
        detail_data = detail_response.json()
        assert detail_data["code"] == 40013
        assert "不存在或无权访问" in detail_data["message"]
        mock_grading_service.get_attempt_grading_detail.assert_called_with(
            user_id=user_b.id,
            attempt_item_id=attempt_item_a_id,
        )

        # 2. 用户 B 试图篡改用户 A 主观题的自评打分
        self_eval_response = await client.post(
            "/api/v1/grading/self-evaluate",
            json={
                "attempt_item_id": str(attempt_item_a_id),
                "score": 5.0,
                "feedback": "恶意自评冒充满分",
            },
        )
        assert self_eval_response.status_code == 404
        self_eval_data = self_eval_response.json()
        assert self_eval_data["code"] == 40013
        call_kwargs = mock_grading_service.self_evaluate_attempt.call_args.kwargs
        assert call_kwargs["user_id"] == user_b.id
        assert call_kwargs["dto"].attempt_item_id == attempt_item_a_id

        # 3. 用户 B 试图对用户 A 的作答项恶意触发重判
        regrade_response = await client.post(
            "/api/v1/grading/regrade",
            json={
                "attempt_item_id": str(attempt_item_a_id),
                "reason": "恶意消耗配额重判",
            },
        )
        assert regrade_response.status_code == 404
        regrade_data = regrade_response.json()
        assert regrade_data["code"] == 40013
        regrade_call_kwargs = mock_grading_service.regrade_attempt.call_args.kwargs
        assert regrade_call_kwargs["user_id"] == user_b.id
        assert regrade_call_kwargs["dto"].attempt_item_id == attempt_item_a_id


# ==============================================================================
# 4. 客观题自评/重判权限拦截测试
# ==============================================================================


@pytest.mark.asyncio
async def test_objective_question_self_evaluate_and_regrade_forbidden(
    user_a: User,
    mock_grading_service: MagicMock,
) -> None:
    """测试客观题尝试自评或重判被拦截返回 403 (错误码 40014)。"""
    app = create_test_app()
    app.dependency_overrides[get_current_user] = lambda: user_a
    app.dependency_overrides[get_grading_service] = lambda: mock_grading_service

    attempt_item_id = uuid.uuid4()
    mock_grading_service.self_evaluate_attempt.side_effect = GradingNotAllowedError(
        message="客观选择题由系统自动判定，不允许用户自主评分",
        details={"question_type": "single_choice"},
    )
    mock_grading_service.regrade_attempt.side_effect = GradingNotAllowedError(
        message="客观选择题不支持大模型重判",
        details={"question_type": "single_choice"},
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 自评拦截
        self_eval_response = await client.post(
            "/api/v1/grading/self-evaluate",
            json={"attempt_item_id": str(attempt_item_id), "score": 2.0},
        )
        assert self_eval_response.status_code == 403
        assert self_eval_response.json()["code"] == 40014
        assert "不允许用户自主评分" in self_eval_response.json()["message"]

        # 重判拦截
        regrade_response = await client.post(
            "/api/v1/grading/regrade",
            json={"attempt_item_id": str(attempt_item_id)},
        )
        assert regrade_response.status_code == 403
        assert regrade_response.json()["code"] == 40014
        assert "不支持大模型重判" in regrade_response.json()["message"]


# ==============================================================================
# 5. 未认证请求统一拦截测试 (401 Authentication Required)
# ==============================================================================


@pytest.mark.asyncio
async def test_unauthenticated_request_rejected_on_all_endpoints() -> None:
    """未登录游客访问受保护端点一律拦截返回 401 (错误码 20001)。"""
    app = create_test_app()
    # 模拟未认证抛出 AuthenticationError
    app.dependency_overrides[get_current_user] = lambda: (_ for _ in ()).throw(
        AuthenticationError("缺少访问令牌或令牌无效")
    )

    random_id = uuid.uuid4()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        endpoints: list[tuple[str, str, dict[str, Any] | None]] = [
            ("POST", "/api/v1/practices", {"title": "t", "material_id": str(random_id)}),
            ("GET", f"/api/v1/practices/{random_id}", None),
            ("PUT", f"/api/v1/practices/{random_id}/answers", {"question_id": str(random_id)}),
            ("POST", f"/api/v1/practices/{random_id}/pause", None),
            ("POST", f"/api/v1/practices/{random_id}/resume", None),
            ("POST", f"/api/v1/practices/{random_id}/submit", None),
            ("GET", f"/api/v1/attempts/{random_id}/grading", None),
            ("POST", "/api/v1/grading/self-evaluate", {"attempt_item_id": str(random_id)}),
            ("POST", "/api/v1/grading/regrade", {"attempt_item_id": str(random_id)}),
        ]

        for method, url, json_body in endpoints:
            if method == "POST":
                res = await client.post(url, json=json_body)
            elif method == "GET":
                res = await client.get(url)
            elif method == "PUT":
                res = await client.put(url, json=json_body)
            else:
                continue

            assert res.status_code == 401, f"{method} {url} 未返回 401，实际为 {res.status_code}"
            assert res.json()["code"] == 20001
