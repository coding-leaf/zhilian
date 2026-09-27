"""FastAPI 应用生命周期 (Lifespan)、健康检查与容器依赖供给单元测试。

验证遵循 AGENTS.md 规范与 spec.md 架构契约：
- UT-LIFE-01: FastAPI Lifespan 启动预热正确初始化 AppContainer 并挂载至 app.state.container；
- Lifespan 退出时触发 container.shutdown() 优雅释放资源；
- GET /health 返回结构化健康就绪状态（兼容 ok/healthy），核心组件异常时返回降级状态；
- 各 API 依赖项无需手动 dependency_overrides 即可由 app.state.container 自动供给。
"""

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request
from starlette.testclient import TestClient

from app.api.deps.auth import get_auth_service
from app.api.deps.diagnosis import get_diagnosis_service
from app.api.deps.grading import get_grading_service
from app.api.deps.knowledge import get_knowledge_service
from app.api.deps.material import get_material_service
from app.api.deps.practice import get_practice_service
from app.api.deps.question import get_question_service
from app.api.deps.user import get_user_service
from app.container import AppContainer
from app.main import app, get_container
from app.services.auth import AuthService
from app.services.diagnosis import DiagnosisService
from app.services.grading import GradingService
from app.services.knowledge import KnowledgeService
from app.services.material import MaterialService
from app.services.practice import PracticeService
from app.services.question import QuestionService


@pytest.fixture(autouse=True)
def clean_dependency_overrides() -> Generator[None, None, None]:
    """在每个测试用例前后保持 dependency_overrides 独立干净。"""
    original_overrides = dict(app.dependency_overrides)
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()
    app.dependency_overrides.update(original_overrides)


def test_lifespan_startup_and_shutdown() -> None:
    """测试 lifespan 启动时正确创建并挂载 AppContainer，退出时触发优雅停机。"""
    mock_container = MagicMock(spec=AppContainer)
    mock_container.startup = AsyncMock()
    mock_container.shutdown = AsyncMock()
    mock_container.check_health.return_value = {
        "status": "ok",
        "app": "ZhiLian",
        "environment": "test",
        "database": {"status": "connected", "dialect": "sqlite"},
        "storage": {"provider": "memory", "bucket": "zhilian-materials"},
        "providers": {
            "llm": "fake",
            "ocr": "fake",
            "embedding": "fake",
            "search": "fake",
            "queue": "memory",
        },
    }

    with (
        patch.object(
            AppContainer, "create_from_settings", return_value=mock_container
        ) as mock_create,
        TestClient(app),
    ):
        mock_create.assert_called_once()
        mock_container.startup.assert_awaited_once()
        assert hasattr(app.state, "container")
        assert app.state.container is mock_container

    mock_container.shutdown.assert_awaited_once()


def test_health_check_endpoint_healthy() -> None:
    """测试 GET /health 在服务正常时返回 200 及多组件结构化状态信息。"""
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") in ("ok", "healthy")
        assert data.get("app") == "ZhiLian"
        assert "database" in data
        assert "storage" in data
        assert "providers" in data


def test_health_check_endpoint_degraded_when_db_down() -> None:
    """测试 GET /health 在核心数据库断开时返回 503 与降级状态。"""
    mock_container = MagicMock(spec=AppContainer)
    mock_container.startup = AsyncMock()
    mock_container.shutdown = AsyncMock()
    mock_container.check_health.return_value = {
        "status": "degraded",
        "app": "ZhiLian",
        "environment": "test",
        "database": {"status": "disconnected", "error": "connection refused"},
        "storage": {"provider": "memory", "bucket": "zhilian-materials"},
        "providers": {
            "llm": "fake",
            "ocr": "fake",
            "embedding": "fake",
            "search": "fake",
            "queue": "memory",
        },
    }

    with (
        patch.object(AppContainer, "create_from_settings", return_value=mock_container),
        TestClient(app) as client,
    ):
        response = client.get("/health")
        assert response.status_code == 503
        data = response.json()
        assert data.get("status") == "degraded"
        assert data["database"]["status"] == "disconnected"


def test_deps_supply_services_from_container_without_overrides() -> None:
    """测试各 API 依赖项在 lifespan 运行时无需手动 overrides 即可由 container 自动供给。"""
    with TestClient(app):
        container = app.state.container
        assert container is not None

        # 模拟 Request 上下文
        fake_request = MagicMock(spec=Request)
        fake_request.app = app

        auth_service_gen = get_auth_service(fake_request)
        auth_svc = next(auth_service_gen)
        assert isinstance(auth_svc, AuthService)
        auth_service_gen.close()

        user_service_gen = get_user_service(fake_request)
        user_svc = next(user_service_gen)
        assert isinstance(user_svc, AuthService)
        user_service_gen.close()

        mat_svc = get_material_service(fake_request)
        assert isinstance(mat_svc, MaterialService)

        know_svc = get_knowledge_service(fake_request)
        assert isinstance(know_svc, KnowledgeService)

        quest_svc = get_question_service(fake_request)
        assert isinstance(quest_svc, QuestionService)

        prac_svc = get_practice_service(fake_request)
        assert isinstance(prac_svc, PracticeService)

        grad_svc = get_grading_service(fake_request)
        assert isinstance(grad_svc, GradingService)

        diag_svc = get_diagnosis_service(fake_request)
        assert isinstance(diag_svc, DiagnosisService)


def test_get_container_helper() -> None:
    """测试 get_container 辅助函数在有/无容器时的行为。"""
    fake_request = MagicMock(spec=Request)

    # 容器未挂载时抛出运行时异常
    fake_request.app.state = MagicMock()
    del fake_request.app.state.container
    with pytest.raises(RuntimeError, match="应用装配容器未初始化"):
        get_container(fake_request)

    # 容器正常挂载时返回该实例
    dummy_container = MagicMock(spec=AppContainer)
    fake_request.app.state.container = dummy_container
    assert get_container(fake_request) is dummy_container


def test_deps_raise_not_implemented_when_no_container() -> None:
    """测试当缺少 container 且未设置 overrides 时依赖函数抛出清晰的 NotImplementedError。"""
    fake_request = MagicMock(spec=Request)
    fake_request.app.state = MagicMock(spec=[])  # 无 container 属性

    with pytest.raises(NotImplementedError):
        get_material_service(fake_request)

    with pytest.raises(NotImplementedError):
        get_knowledge_service(fake_request)

    with pytest.raises(NotImplementedError):
        next(get_auth_service(fake_request))

    with pytest.raises(NotImplementedError):
        next(get_user_service(fake_request))
