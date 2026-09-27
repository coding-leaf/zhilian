"""学情诊断、掌握度衰减聚合与错题闭环 API 路由单元测试模块。

覆盖 app/api/v1/diagnosis.py 的全量端点：
1. POST /practices/{id}/diagnosis (生成诊断报告 200，未判题 400/40016，练习不存在 404/40010)
2. GET /practices/{id}/diagnosis (查询练习诊断报告 200，不存在 404/40017)
3. GET /diagnosis/reports (分页查询报告列表 200，含备用分支)
4. GET /diagnosis/reports/{id} (查询报告详情 200，不存在 404/40017)
5. GET /mastery 与 GET /mastery/overview (掌握度宏观全景 200)
6. GET /mastery/{knowledge_point_id} (单知识点掌握度 200，未评估 404/40018)
7. GET /wrong-records (错题本多维检索 200，含类型过滤与备用分支)
8. POST /wrong-records/{id}/master (标记攻克掌握 200，不存在 404/40019)
9. DELETE /wrong-records/{id} (移除错题记录 200，不存在 404/40019)
10. 未认证请求拦截 (401 / 20001) 与租户隔离 (user_id 透传) 校验。
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi import APIRouter, FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.api.deps.auth import get_current_user
from app.api.deps.diagnosis import get_diagnosis_service
from app.api.v1.diagnosis import router as diagnosis_router
from app.core.errors import (
    AppError,
    DiagnosisReportNotFoundError,
    MasteryRecordNotFoundError,
    PracticeNotFoundError,
    PracticeNotGradedError,
    WrongRecordNotFoundError,
)
from app.models.user import User
from app.schemas.diagnosis import (
    DeleteWrongRecordResponse,
    DiagnosisReportListResponse,
    DiagnosisReportResponse,
    KnowledgeMasterySummaryResponse,
    MarkWrongRecordMasteredResponse,
    UserMasteryOverviewResponse,
    WrongRecordItemResponse,
    WrongRecordListResponse,
)
from app.services.diagnosis import DiagnosisService


def create_test_app() -> FastAPI:
    """创建挂载了学情诊断路由与 AppError 异常处理器的测试 FastAPI 应用。

    Returns:
        FastAPI: 配置好异常映射与路由挂载的测试应用实例。
    """
    test_application = FastAPI(title="Diagnosis Router Test App")

    @test_application.exception_handler(AppError)
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

    test_application.include_router(diagnosis_router)
    api_v1_router = APIRouter(prefix="/api/v1")
    api_v1_router.include_router(diagnosis_router)
    test_application.include_router(api_v1_router)
    return test_application


@pytest.fixture
def mock_user() -> User:
    """提供当前已认证的租户用户对象。

    Returns:
        User: 测试认证租户实体。
    """
    return User(
        id=uuid.uuid4(),
        nickname="test_learner",
        is_active=True,
        token_version=1,
    )


@pytest.fixture
def mock_diagnosis_service() -> MagicMock:
    """提供打桩的 DiagnosisService 实例。

    Returns:
        MagicMock: 诊断领域编排服务打桩对象。
    """
    return MagicMock(spec=DiagnosisService)


@pytest.fixture
def app(mock_user: User, mock_diagnosis_service: MagicMock) -> FastAPI:
    """创建并注入依赖覆盖的测试应用实例。

    Args:
        mock_user: 测试用户。
        mock_diagnosis_service: 打桩的诊断服务。

    Returns:
        FastAPI: 依赖覆盖后的应用实例。
    """
    test_application = create_test_app()
    test_application.dependency_overrides[get_current_user] = lambda: mock_user
    test_application.dependency_overrides[get_diagnosis_service] = lambda: mock_diagnosis_service
    return test_application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """提供 FastAPI TestClient 同步测试客户端。

    Args:
        app: 测试应用实例。

    Returns:
        TestClient: 测试客户端。
    """
    return TestClient(app)


def make_fake_diagnosis_report(
    report_id: uuid.UUID | None = None,
    practice_id: uuid.UUID | None = None,
) -> DiagnosisReportResponse:
    """构造学情诊断报告假数据响应实体。

    Args:
        report_id: 可选的报告主键标识。
        practice_id: 可选的练习主键标识。

    Returns:
        DiagnosisReportResponse: 初始化的诊断报告实体。
    """
    resolved_report_id = report_id or uuid.uuid4()
    resolved_practice_id = practice_id or uuid.uuid4()
    return DiagnosisReportResponse(
        id=resolved_report_id,
        practice_id=resolved_practice_id,
        mastery_before=0.60,
        mastery_after=0.75,
        knowledge_evaluations=[],
        weak_knowledge_points=[],
        regressed_knowledge_points=[],
        analysis_causes=[],
        actionable_suggestions=[],
        root_causes=["概念模糊"],
        suggestions=["建议复习 TCP 三次握手机制"],
        summary="整体掌握良好，需加强传输层协议理解",
        unanswered_count=0,
        wrong_count=1,
        pending_regrade_count=0,
        total_questions=10,
        score_rate=0.85,
        is_structure_degraded=False,
        created_at=datetime.now(UTC),
    )


def make_fake_mastery_overview(
    material_id: uuid.UUID | None = None,
) -> UserMasteryOverviewResponse:
    """构造用户掌握度宏观全景假数据实体。

    Args:
        material_id: 可选的关联资料标识。

    Returns:
        UserMasteryOverviewResponse: 掌握度概览实体。
    """
    resolved_material_id = material_id or uuid.uuid4()
    knowledge_point_id = uuid.uuid4()
    weak_item = KnowledgeMasterySummaryResponse(
        knowledge_point_id=knowledge_point_id,
        knowledge_name="三次握手与四次挥手",
        mastery_score=0.45,
        level="weak",
        practice_count=6,
        correct_count=2,
        last_practiced_at=datetime.now(UTC),
    )
    return UserMasteryOverviewResponse(
        material_id=resolved_material_id,
        total_points=12,
        mastered_count=5,
        learning_count=4,
        weak_count=2,
        unlearned_count=1,
        overall_score=0.72,
        overall_mastery_score=0.72,
        total_knowledge_points=12,
        basic_count=4,
        proficient_count=5,
        points=[weak_item],
        weak_knowledge_points=[weak_item],
    )


def make_fake_wrong_record(
    record_id: uuid.UUID | None = None,
    practice_id: uuid.UUID | None = None,
    knowledge_point_id: uuid.UUID | None = None,
) -> WrongRecordItemResponse:
    """构造错题记录明细假数据实体。

    Args:
        record_id: 可选的错题主键标识。
        practice_id: 可选的练习会话标识。
        knowledge_point_id: 可选的知识点主键标识。

    Returns:
        WrongRecordItemResponse: 错题记录响应实体。
    """
    resolved_record_id = record_id or uuid.uuid4()
    resolved_practice_id = practice_id or uuid.uuid4()
    resolved_knowledge_point_id = knowledge_point_id or uuid.uuid4()
    return WrongRecordItemResponse(
        id=resolved_record_id,
        question_id=uuid.uuid4(),
        practice_id=resolved_practice_id,
        attempt_item_id=uuid.uuid4(),
        knowledge_point_id=resolved_knowledge_point_id,
        error_type="conceptual",
        is_mastered=False,
        wrong_count=2,
        error_count=2,
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
        },
        first_wrong_at=datetime.now(UTC),
        mastered_at=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


# ==============================================================================
# 1. POST /practices/{id}/diagnosis (生成学情诊断报告) 测试
# ==============================================================================


def test_generate_diagnosis_report_success(
    client: TestClient,
    mock_diagnosis_service: MagicMock,
    mock_user: User,
) -> None:
    """测试触发生成学情诊断报告成功并返回 200 状态码。"""
    practice_id = uuid.uuid4()
    fake_report = make_fake_diagnosis_report(practice_id=practice_id)
    mock_diagnosis_service.generate_diagnosis_report.return_value = fake_report

    response = client.post(f"/practices/{practice_id}/diagnosis")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["id"] == str(fake_report.id)
    assert data["practice_id"] == str(practice_id)
    assert data["score_rate"] == 0.85
    assert data["root_causes"] == ["概念模糊"]
    mock_diagnosis_service.generate_diagnosis_report.assert_called_once_with(
        user_id=mock_user.id,
        practice_id=practice_id,
    )


def test_generate_diagnosis_report_not_graded_400(
    client: TestClient,
    mock_diagnosis_service: MagicMock,
) -> None:
    """测试未完成判题时触发诊断报告抛出 PracticeNotGradedError 并映射 400 (40016)。"""
    practice_id = uuid.uuid4()
    mock_diagnosis_service.generate_diagnosis_report.side_effect = PracticeNotGradedError(
        "练习尚未完成全量判题（存在待重判题目），无法生成诊断报告"
    )

    response = client.post(f"/practices/{practice_id}/diagnosis")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    data = response.json()
    assert data["code"] == 40016
    assert "尚未完成全量判题" in data["message"]


def test_generate_diagnosis_report_practice_not_found_404(
    client: TestClient,
    mock_diagnosis_service: MagicMock,
) -> None:
    """测试练习不存在时触发诊断报告抛出 PracticeNotFoundError 并映射 404 (40010)。"""
    practice_id = uuid.uuid4()
    mock_diagnosis_service.generate_diagnosis_report.side_effect = PracticeNotFoundError(
        "请求的练习记录不存在或无权访问"
    )

    response = client.post(f"/practices/{practice_id}/diagnosis")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    data = response.json()
    assert data["code"] == 40010
    assert "不存在或无权访问" in data["message"]


# ==============================================================================
# 2. GET /practices/{id}/diagnosis (查询指定练习关联诊断报告) 测试
# ==============================================================================


def test_get_diagnosis_report_by_practice_success(
    client: TestClient,
    mock_diagnosis_service: MagicMock,
    mock_user: User,
) -> None:
    """测试查询指定练习已生成的学情诊断报告成功返回 200。"""
    practice_id = uuid.uuid4()
    fake_report = make_fake_diagnosis_report(practice_id=practice_id)
    mock_diagnosis_service.get_diagnosis_report_by_practice.return_value = fake_report

    response = client.get(f"/practices/{practice_id}/diagnosis")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["id"] == str(fake_report.id)
    assert data["practice_id"] == str(practice_id)
    mock_diagnosis_service.get_diagnosis_report_by_practice.assert_called_once_with(
        user_id=mock_user.id,
        practice_id=practice_id,
    )


def test_get_diagnosis_report_by_practice_not_found_404(
    client: TestClient,
    mock_diagnosis_service: MagicMock,
) -> None:
    """测试练习尚未生成诊断报告时查询抛出 DiagnosisReportNotFoundError 并映射 404 (40017)。"""
    practice_id = uuid.uuid4()
    mock_diagnosis_service.get_diagnosis_report_by_practice.side_effect = (
        DiagnosisReportNotFoundError("诊断报告不存在")
    )

    response = client.get(f"/practices/{practice_id}/diagnosis")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    data = response.json()
    assert data["code"] == 40017
    assert "诊断报告不存在" in data["message"]


# ==============================================================================
# 3. GET /diagnosis/reports (分页查询用户历史诊断报告) 测试
# ==============================================================================


def test_list_diagnosis_reports_success(
    client: TestClient,
    mock_diagnosis_service: MagicMock,
    mock_user: User,
) -> None:
    """测试分页查询诊断报告列表成功返回 200，并验证分页参数透传。"""
    fake_reports = [make_fake_diagnosis_report(), make_fake_diagnosis_report()]
    paginated_response = DiagnosisReportListResponse(
        items=fake_reports,
        total=25,
        page=2,
        page_size=10,
        limit=10,
        offset=10,
    )
    mock_diagnosis_service.list_diagnosis_reports.return_value = paginated_response

    response = client.get("/diagnosis/reports", params={"page": 2, "page_size": 10})

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["total"] == 25
    assert len(data["items"]) == 2
    assert data["page"] == 2
    assert data["page_size"] == 10
    mock_diagnosis_service.list_diagnosis_reports.assert_called_once_with(
        user_id=mock_user.id,
        page=2,
        page_size=10,
        limit=10,
        offset=10,
    )


# ==============================================================================
# 4. GET /diagnosis/reports/{id} (查询诊断报告详情) 测试
# ==============================================================================


def test_get_diagnosis_report_by_id_success(
    client: TestClient,
    mock_diagnosis_service: MagicMock,
    mock_user: User,
) -> None:
    """测试根据报告主键查询诊断报告详情成功返回 200。"""
    report_id = uuid.uuid4()
    fake_report = make_fake_diagnosis_report(report_id=report_id)
    mock_diagnosis_service.get_diagnosis_report.return_value = fake_report

    response = client.get(f"/diagnosis/reports/{report_id}")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["id"] == str(report_id)
    mock_diagnosis_service.get_diagnosis_report.assert_called_once_with(
        user_id=mock_user.id,
        report_id=report_id,
    )


def test_get_diagnosis_report_by_id_not_found_404(
    client: TestClient,
    mock_diagnosis_service: MagicMock,
) -> None:
    """测试根据报告主键查询不存在的报告抛出 DiagnosisReportNotFoundError 并映射 404 (40017)。"""
    report_id = uuid.uuid4()
    mock_diagnosis_service.get_diagnosis_report.side_effect = DiagnosisReportNotFoundError(
        "学情诊断报告不存在或无权访问"
    )

    response = client.get(f"/diagnosis/reports/{report_id}")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    data = response.json()
    assert data["code"] == 40017


# ==============================================================================
# 5. GET /mastery 与 /mastery/overview (掌握度概览) 测试
# ==============================================================================


def test_get_user_mastery_overview_success(
    client: TestClient,
    mock_diagnosis_service: MagicMock,
    mock_user: User,
) -> None:
    """测试获取用户全量/指定资料掌握度宏观全景成功返回 200。"""
    material_id = uuid.uuid4()
    fake_overview = make_fake_mastery_overview(material_id=material_id)
    mock_diagnosis_service.get_user_mastery_overview.return_value = fake_overview

    response = client.get("/mastery", params={"material_id": str(material_id)})

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["total_points"] == 12
    assert data["proficient_count"] == 5
    assert data["weak_count"] == 2
    assert len(data["weak_knowledge_points"]) == 1
    mock_diagnosis_service.get_user_mastery_overview.assert_called_once_with(
        user_id=mock_user.id,
        material_id=material_id,
    )


# ==============================================================================
# 6. GET /mastery/{knowledge_point_id} (单知识点掌握度) 测试
# ==============================================================================


def test_get_single_knowledge_mastery_success(
    client: TestClient,
    mock_diagnosis_service: MagicMock,
    mock_user: User,
) -> None:
    """测试查询单个知识点艾宾浩斯衰减掌握度成功返回 200。"""
    knowledge_point_id = uuid.uuid4()
    fake_summary = KnowledgeMasterySummaryResponse(
        knowledge_point_id=knowledge_point_id,
        knowledge_name="三次握手",
        mastery_score=0.45,
        level="weak",
        practice_count=6,
        correct_count=2,
        last_practiced_at=datetime.now(UTC),
    )
    mock_diagnosis_service.get_knowledge_mastery.return_value = fake_summary

    response = client.get(f"/mastery/{knowledge_point_id}")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["knowledge_point_id"] == str(knowledge_point_id)
    assert data["mastery_score"] == 0.45
    assert data["level"] == "weak"
    mock_diagnosis_service.get_knowledge_mastery.assert_called_once_with(
        user_id=mock_user.id,
        knowledge_point_id=knowledge_point_id,
    )


def test_get_single_knowledge_mastery_not_found_404(
    client: TestClient,
    mock_diagnosis_service: MagicMock,
) -> None:
    """测试查询尚未评估的知识点掌握度抛出 MasteryRecordNotFoundError 并映射 404 (40018)。"""
    knowledge_point_id = uuid.uuid4()
    mock_diagnosis_service.get_knowledge_mastery.side_effect = MasteryRecordNotFoundError(
        "该知识点尚未产生掌握度评估记录",
        knowledge_point_id=knowledge_point_id,
    )

    response = client.get(f"/mastery/{knowledge_point_id}")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    data = response.json()
    assert data["code"] == 40018
    assert "尚未产生掌握度评估记录" in data["message"]


# ==============================================================================
# 7. GET /wrong-records (错题本多维检索与分页) 测试
# ==============================================================================


def test_list_wrong_records_success(
    client: TestClient,
    mock_diagnosis_service: MagicMock,
    mock_user: User,
) -> None:
    """测试多维条件检索错题本列表成功返回 200。"""
    material_id = uuid.uuid4()
    knowledge_point_id = uuid.uuid4()
    fake_wrong = make_fake_wrong_record(
        knowledge_point_id=knowledge_point_id,
    )
    paginated_response = WrongRecordListResponse(
        items=[fake_wrong],
        total=1,
        page=1,
        page_size=15,
        limit=15,
        offset=0,
    )
    mock_diagnosis_service.list_wrong_records.return_value = paginated_response

    response = client.get(
        "/wrong-records",
        params={
            "material_id": str(material_id),
            "knowledge_point_id": str(knowledge_point_id),
            "status": "active",
            "is_mastered": False,
            "page": 1,
            "page_size": 15,
        },
    )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["error_type"] == "conceptual"
    mock_diagnosis_service.list_wrong_records.assert_called_once_with(
        user_id=mock_user.id,
        material_id=material_id,
        status="active",
        is_mastered=False,
        knowledge_point_id=knowledge_point_id,
        error_type=None,
        question_type=None,
        page=1,
        page_size=15,
        limit=15,
        offset=0,
    )


def test_list_wrong_records_question_type_and_error_type_forwarded(
    client: TestClient,
    mock_diagnosis_service: MagicMock,
    mock_user: User,
) -> None:
    """测试 question_type 与 error_type 查询参数完整透传至 Service 层 (DIAG-010/011)。"""
    mock_diagnosis_service.list_wrong_records.return_value = ([], 0)

    response = client.get(
        "/wrong-records",
        params={
            "question_type": "single_choice",
            "error_type": "incomplete_expression",
            "page": 1,
            "page_size": 20,
        },
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["total"] == 0
    called_kwargs = mock_diagnosis_service.list_wrong_records.call_args.kwargs
    assert called_kwargs["question_type"] == "single_choice"
    assert called_kwargs["error_type"] == "incomplete_expression"


def test_list_wrong_records_real_total_from_tuple(
    client: TestClient,
    mock_diagnosis_service: MagicMock,
) -> None:
    """测试 Service 返回 (items, real_total) 元组时路由下发真实总数而非当前页条数。"""
    fake_wrong = make_fake_wrong_record()
    mock_diagnosis_service.list_wrong_records.return_value = ([fake_wrong], 42)

    response = client.get("/wrong-records", params={"page": 1, "page_size": 1})

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["total"] == 42
    assert len(data["items"]) == 1


# ==============================================================================
# 8. POST /wrong-records/{id}/master (错题攻克标记) 测试
# ==============================================================================
def test_mark_wrong_record_mastered_success(
    client: TestClient,
    mock_diagnosis_service: MagicMock,
    mock_user: User,
) -> None:
    """测试手动将错题标记为已攻克成功返回 200。"""
    record_id = uuid.uuid4()
    now_time = datetime.now(UTC)
    mock_diagnosis_service.mark_wrong_record_mastered.return_value = (
        MarkWrongRecordMasteredResponse(
            id=record_id,
            is_mastered=True,
            mastered_at=now_time,
            message="错题已成功标记为已攻克",
        )
    )

    response = client.post(f"/wrong-records/{record_id}/master")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["id"] == str(record_id)
    assert data["is_mastered"] is True
    mock_diagnosis_service.mark_wrong_record_mastered.assert_called_once_with(
        user_id=mock_user.id,
        record_id=record_id,
        is_mastered=True,
    )


def test_mark_wrong_record_unmastered_with_body(
    client: TestClient,
    mock_diagnosis_service: MagicMock,
    mock_user: User,
) -> None:
    """测试请求体 {is_mastered:false} 时取消攻克并透传 False。"""
    record_id = uuid.uuid4()
    mock_record = MagicMock()
    mock_record.id = record_id
    mock_record.is_mastered = False
    mock_record.mastered_at = None
    mock_diagnosis_service.mark_wrong_record_mastered.return_value = mock_record

    response = client.post(
        f"/wrong-records/{record_id}/master",
        json={"is_mastered": False},
    )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["is_mastered"] is False
    assert data["mastered_at"] is None
    assert "取消" in data["message"]
    mock_diagnosis_service.mark_wrong_record_mastered.assert_called_once_with(
        user_id=mock_user.id,
        record_id=record_id,
        is_mastered=False,
    )


def test_mark_wrong_record_mastered_not_found_404(
    client: TestClient,
    mock_diagnosis_service: MagicMock,
) -> None:
    """测试攻克不存在的错题抛出 WrongRecordNotFoundError 并映射 404 (40019)。"""
    record_id = uuid.uuid4()
    mock_diagnosis_service.mark_wrong_record_mastered.side_effect = WrongRecordNotFoundError(
        "错题记录不存在或无权访问",
        record_id=record_id,
    )

    response = client.post(f"/wrong-records/{record_id}/master")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    data = response.json()
    assert data["code"] == 40019


# ==============================================================================
# 9. DELETE /wrong-records/{id} (错题彻底移除) 测试
# ==============================================================================


def test_delete_wrong_record_success(
    client: TestClient,
    mock_diagnosis_service: MagicMock,
    mock_user: User,
) -> None:
    """测试彻底移除错题记录成功返回 200。"""
    record_id = uuid.uuid4()
    mock_diagnosis_service.remove_wrong_record.return_value = DeleteWrongRecordResponse(
        id=record_id,
        success=True,
        message="错题记录已成功移除",
    )

    response = client.delete(f"/wrong-records/{record_id}")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["id"] == str(record_id)
    assert data["success"] is True
    # BUG-DIAG-013: 响应必须同时下发 removed 字段供前端读取。
    assert data["removed"] is True
    mock_diagnosis_service.remove_wrong_record.assert_called_once_with(
        user_id=mock_user.id,
        record_id=record_id,
    )


def test_delete_wrong_record_not_found_404(
    client: TestClient,
    mock_diagnosis_service: MagicMock,
) -> None:
    """测试移除不存在的错题抛出 WrongRecordNotFoundError 并映射 404 (40019)。"""
    record_id = uuid.uuid4()
    mock_diagnosis_service.remove_wrong_record.side_effect = WrongRecordNotFoundError(
        "错题记录不存在或无权访问",
        record_id=record_id,
    )

    response = client.delete(f"/wrong-records/{record_id}")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    data = response.json()
    assert data["code"] == 40019


# ==============================================================================
# 10. 租户认证与安全隔离测试
# ==============================================================================


def test_unauthenticated_request_401(mock_diagnosis_service: MagicMock) -> None:
    """测试未提供 Authorization 请求头时访问各端点统一被 401 (20001) 拦截。"""
    unauth_app = create_test_app()
    # 仅注入 Service，不注入当前用户依赖
    unauth_app.dependency_overrides[get_diagnosis_service] = lambda: mock_diagnosis_service
    unauth_client = TestClient(unauth_app)

    test_id = uuid.uuid4()
    endpoints = [
        ("POST", f"/practices/{test_id}/diagnosis"),
        ("GET", f"/practices/{test_id}/diagnosis"),
        ("GET", "/diagnosis/reports"),
        ("GET", f"/diagnosis/reports/{test_id}"),
        ("GET", "/mastery"),
        ("GET", f"/mastery/{test_id}"),
        ("GET", "/wrong-records"),
        ("POST", f"/wrong-records/{test_id}/master"),
        ("DELETE", f"/wrong-records/{test_id}"),
    ]

    for method, path in endpoints:
        response = unauth_client.request(method, path)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED, f"Failed at {method} {path}"
        data = response.json()
        assert data["code"] == 20001, f"Expected code 20001 at {method} {path}"


def test_tenant_isolation_user_id_passed_correctly(
    client: TestClient,
    mock_diagnosis_service: MagicMock,
    mock_user: User,
) -> None:
    """测试全部端点严格将当前登录用户的 user_id 透传至 Service 层，杜绝水平越权。"""
    test_id = uuid.uuid4()

    # 1. POST /practices/{id}/diagnosis
    mock_diagnosis_service.generate_diagnosis_report.return_value = make_fake_diagnosis_report()
    client.post(f"/practices/{test_id}/diagnosis")
    assert (
        mock_diagnosis_service.generate_diagnosis_report.call_args.kwargs["user_id"] == mock_user.id
    )

    # 2. GET /practices/{id}/diagnosis
    mock_diagnosis_service.get_diagnosis_report_by_practice.return_value = (
        make_fake_diagnosis_report()
    )
    client.get(f"/practices/{test_id}/diagnosis")
    assert (
        mock_diagnosis_service.get_diagnosis_report_by_practice.call_args.kwargs["user_id"]
        == mock_user.id
    )

    # 3. GET /diagnosis/reports
    mock_diagnosis_service.list_diagnosis_reports.return_value = DiagnosisReportListResponse(
        items=[], total=0
    )
    client.get("/diagnosis/reports")
    assert mock_diagnosis_service.list_diagnosis_reports.call_args.kwargs["user_id"] == mock_user.id

    # 4. GET /diagnosis/reports/{id}
    mock_diagnosis_service.get_diagnosis_report.return_value = make_fake_diagnosis_report()
    client.get(f"/diagnosis/reports/{test_id}")
    assert mock_diagnosis_service.get_diagnosis_report.call_args.kwargs["user_id"] == mock_user.id

    # 5. GET /mastery
    mock_diagnosis_service.get_user_mastery_overview.return_value = make_fake_mastery_overview()
    client.get("/mastery")
    assert (
        mock_diagnosis_service.get_user_mastery_overview.call_args.kwargs["user_id"] == mock_user.id
    )

    # 6. GET /mastery/{knowledge_point_id}
    mock_diagnosis_service.get_knowledge_mastery.return_value = KnowledgeMasterySummaryResponse(
        knowledge_point_id=test_id,
        knowledge_name="测试知识点",
    )
    client.get(f"/mastery/{test_id}")
    assert mock_diagnosis_service.get_knowledge_mastery.call_args.kwargs["user_id"] == mock_user.id

    # 7. GET /wrong-records
    mock_diagnosis_service.list_wrong_records.return_value = WrongRecordListResponse(
        items=[], total=0
    )
    client.get("/wrong-records")
    assert mock_diagnosis_service.list_wrong_records.call_args.kwargs["user_id"] == mock_user.id

    # 8. POST /wrong-records/{id}/master
    mock_diagnosis_service.mark_wrong_record_mastered.return_value = (
        MarkWrongRecordMasteredResponse(id=test_id)
    )
    client.post(f"/wrong-records/{test_id}/master")
    assert (
        mock_diagnosis_service.mark_wrong_record_mastered.call_args.kwargs["user_id"]
        == mock_user.id
    )

    # 9. DELETE /wrong-records/{id}
    mock_diagnosis_service.remove_wrong_record.return_value = DeleteWrongRecordResponse(id=test_id)
    client.delete(f"/wrong-records/{test_id}")
    assert mock_diagnosis_service.remove_wrong_record.call_args.kwargs["user_id"] == mock_user.id


# ==============================================================================
# 11. 边界分支与模型转换容错测试 (用于实现 100% 覆盖率)
# ==============================================================================


def test_list_diagnosis_reports_fallback_plain_list(
    client: TestClient,
    mock_diagnosis_service: MagicMock,
) -> None:
    """测试 Service 返回普通列表或携带 total 容器时，路由层自动打包为列表响应。"""
    fake_reports = [make_fake_diagnosis_report()]
    mock_diagnosis_service.list_diagnosis_reports.return_value = fake_reports

    response = client.get("/diagnosis/reports", params={"offset": 0, "limit": 10})

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1

    # 覆盖具有 total 属性的列表容器分支
    class CustomReportList(list[DiagnosisReportResponse]):
        total: int = 42

    mock_container = CustomReportList([make_fake_diagnosis_report()])
    mock_diagnosis_service.list_diagnosis_reports.return_value = mock_container
    response_with_total = client.get("/diagnosis/reports")
    assert response_with_total.status_code == status.HTTP_200_OK
    assert response_with_total.json()["total"] == 42


def test_list_wrong_records_fallback_list_and_filter(
    client: TestClient,
    mock_diagnosis_service: MagicMock,
) -> None:
    """测试 Service 返回普通列表时路由层不加后置过滤，仅包装为列表响应。

    BUG-DIAG-010 修复后 error_type 过滤已全量下推 Service/仓储，路由层不再做
    内存切片（否则会破坏真实总数与分页语义）。
    """
    record_one = make_fake_wrong_record()
    record_one.error_type = "conceptual"
    record_two = make_fake_wrong_record()
    record_two.error_type = "calculation"

    mock_diagnosis_service.list_wrong_records.return_value = [record_one, record_two]

    response = client.get(
        "/wrong-records",
        params={"error_type": "conceptual", "offset": 0, "limit": 10},
    )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    # 路由不再后置切片：过滤由 Service/仓储负责，此处仅保证 error_type 已被透传。
    assert data["total"] == 2
    assert len(data["items"]) == 2
    assert mock_diagnosis_service.list_wrong_records.call_args.kwargs["error_type"] == "conceptual"

    # 覆盖 error_type 为 None 且带有 total 属性的分支
    class CustomWrongList(list[WrongRecordItemResponse]):
        total: int = 99

    mock_wrong_container = CustomWrongList([record_one, record_two])
    mock_diagnosis_service.list_wrong_records.return_value = mock_wrong_container
    response_no_filter = client.get("/wrong-records")
    assert response_no_filter.status_code == status.HTTP_200_OK
    assert response_no_filter.json()["total"] == 99


def test_mark_wrong_record_mastered_fallback_object(
    client: TestClient,
    mock_diagnosis_service: MagicMock,
) -> None:
    """测试 Service 返回非标准 DTO 实体时路由自动封装 MarkWrongRecordMasteredResponse。"""
    record_id = uuid.uuid4()
    mock_obj = MagicMock()
    mock_obj.id = record_id
    mock_obj.is_mastered = True
    mock_obj.mastered_at = None
    mock_diagnosis_service.mark_wrong_record_mastered.return_value = mock_obj

    response = client.post(f"/wrong-records/{record_id}/master")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["id"] == str(record_id)
    assert data["is_mastered"] is True


def test_delete_wrong_record_fallback_boolean(
    client: TestClient,
    mock_diagnosis_service: MagicMock,
) -> None:
    """测试 Service 仅返回布尔值时路由层自动封装 DeleteWrongRecordResponse。"""
    record_id = uuid.uuid4()
    mock_diagnosis_service.remove_wrong_record.return_value = True

    response = client.delete(f"/wrong-records/{record_id}")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["id"] == str(record_id)
    assert data["success"] is True
    assert data["removed"] is True


def test_get_mastery_overview_alias_endpoint(
    client: TestClient,
    mock_diagnosis_service: MagicMock,
    mock_user: User,
) -> None:
    """测试 /mastery/overview 别名路由与主路由行为一致。"""
    fake_overview = make_fake_mastery_overview()
    mock_diagnosis_service.get_user_mastery_overview.return_value = fake_overview

    response = client.get("/mastery/overview")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["total_points"] == 12
    # DIAG-007: no material_id must forward None (aggregate all user points), not a dummy UUID.
    mock_diagnosis_service.get_user_mastery_overview.assert_called_once_with(
        user_id=mock_user.id,
        material_id=None,
    )


def test_model_validate_conversion_branches(
    client: TestClient,
    mock_diagnosis_service: MagicMock,
) -> None:
    """测试各端点返回模型数据时通过 model_validate 转换的兼容分支。"""
    practice_id = uuid.uuid4()
    report_id = uuid.uuid4()
    kp_id = uuid.uuid4()

    fake_report_dict = make_fake_diagnosis_report(
        report_id=report_id, practice_id=practice_id
    ).model_dump()
    fake_overview_dict = make_fake_mastery_overview().model_dump()
    fake_summary_dict = KnowledgeMasterySummaryResponse(
        knowledge_point_id=kp_id,
        knowledge_name="测试知识点",
    ).model_dump()

    # 1. generate_diagnosis_report dict
    mock_diagnosis_service.generate_diagnosis_report.return_value = fake_report_dict
    res_gen = client.post(f"/practices/{practice_id}/diagnosis")
    assert res_gen.status_code == status.HTTP_200_OK

    # 2. get_diagnosis_report_by_practice dict
    mock_diagnosis_service.get_diagnosis_report_by_practice.return_value = fake_report_dict
    res_get_p = client.get(f"/practices/{practice_id}/diagnosis")
    assert res_get_p.status_code == status.HTTP_200_OK

    # 3. get_diagnosis_report dict
    mock_diagnosis_service.get_diagnosis_report.return_value = fake_report_dict
    res_get_r = client.get(f"/diagnosis/reports/{report_id}")
    assert res_get_r.status_code == status.HTTP_200_OK

    # 4. get_user_mastery_overview dict
    mock_diagnosis_service.get_user_mastery_overview.return_value = fake_overview_dict
    res_ov = client.get("/mastery")
    assert res_ov.status_code == status.HTTP_200_OK

    # 5. get_knowledge_mastery dict
    mock_diagnosis_service.get_knowledge_mastery.return_value = fake_summary_dict
    res_kp = client.get(f"/mastery/{kp_id}")
    assert res_kp.status_code == status.HTTP_200_OK
