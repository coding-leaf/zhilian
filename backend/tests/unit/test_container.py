"""应用装配容器单元测试 (AppContainer)。

覆盖用例:
- UT-CTR-01: AppContainer 完整装配与 8 大领域服务获取 (create / create_from_settings)
- UT-CTR-02: AppContainer 数据库会话事务上下文管理 (get_session / get_db_session)
- UT-CTR-03: AppContainer 启动与优雅停机生命周期 (startup / shutdown)
- UT-CTR-04: AppContainer 多组件健康检查结构化响应 (check_health)
"""

import contextlib

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.container import AppContainer
from app.core.config import AppSettings, DatabaseSettings, StorageSettings
from app.integrations.container import ProviderRegistry
from app.services.auth import AuthService
from app.services.diagnosis import DiagnosisService
from app.services.grading import GradingService
from app.services.knowledge import KnowledgeService
from app.services.material import MaterialService
from app.services.practice import PracticeService
from app.services.question import QuestionService


def test_app_container_create_and_services() -> None:
    """测试 AppContainer.create 能正确组装 Session 工厂与 8 个领域服务。"""
    settings = AppSettings(db=DatabaseSettings(db_url="sqlite:///:memory:"))
    registry = ProviderRegistry.create_default(settings)

    container = AppContainer.create(settings=settings, registry=registry)

    # 1. 验证 Session 工厂装配
    assert container.session_factory is not None
    assert container.engine is not None
    assert container.providers is registry
    assert container.registry is registry

    # 2. 验证 8 大领域服务纯工厂方法 (传入独立 Session 产出绑定该 Session 的独立实例)
    with container.get_session() as custom_session:
        mat_svc = container.create_material_service(custom_session)
        assert isinstance(mat_svc, MaterialService)
        assert mat_svc.session is custom_session

        auth_svc = container.create_auth_service(custom_session)
        assert isinstance(auth_svc, AuthService)
        assert auth_svc.session is custom_session

        user_svc = container.create_user_service(custom_session)
        assert isinstance(user_svc, AuthService)
        assert user_svc.session is custom_session

        know_svc = container.create_knowledge_service(custom_session)
        assert isinstance(know_svc, KnowledgeService)
        assert know_svc.session is custom_session

        ques_svc = container.create_question_service(custom_session)
        assert isinstance(ques_svc, QuestionService)
        assert ques_svc.session is custom_session

        prac_svc = container.create_practice_service(custom_session)
        assert isinstance(prac_svc, PracticeService)
        assert prac_svc.session is custom_session

        grad_svc = container.create_grading_service(custom_session)
        assert isinstance(grad_svc, GradingService)
        assert grad_svc.session is custom_session

        diag_svc = container.create_diagnosis_service(custom_session)
        assert isinstance(diag_svc, DiagnosisService)
        assert diag_svc.session is custom_session

    # 3. 验证兼容性 get_*_service 方法委托
    with container.get_session() as compat_session:
        assert isinstance(container.get_material_service(compat_session), MaterialService)
        assert isinstance(container.get_auth_service(compat_session), AuthService)
        assert isinstance(container.get_user_service(compat_session), AuthService)
        assert isinstance(container.get_knowledge_service(compat_session), KnowledgeService)
        assert isinstance(container.get_question_service(compat_session), QuestionService)
        assert isinstance(container.get_practice_service(compat_session), PracticeService)
        assert isinstance(container.get_grading_service(compat_session), GradingService)
        assert isinstance(container.get_diagnosis_service(compat_session), DiagnosisService)


def test_app_container_get_session_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    """测试 get_session 数据库事务上下文管理器与异常回滚机制。"""
    settings = AppSettings(db=DatabaseSettings(db_url="sqlite:///:memory:"))
    container = AppContainer.create(settings=settings)

    # 1. 正常使用 get_session 上下文
    closed: list[bool] = []
    with container.get_session() as session:
        assert isinstance(session, Session)
        result = session.execute(text("SELECT 1")).scalar()
        assert result == 1
        original_close = session.close

        def track_close() -> None:
            closed.append(True)
            original_close()

        monkeypatch.setattr(session, "close", track_close)
    # 退出上下文后 session 应当已被关闭
    assert len(closed) == 1

    # 2. 上下文抛出异常触发 rollback 并且关闭 session
    rolled_back: list[bool] = []
    closed_err: list[bool] = []
    try:
        with container.get_session() as session_err:
            original_rollback = session_err.rollback
            original_close_err = session_err.close

            def track_rollback() -> None:
                rolled_back.append(True)
                original_rollback()

            def track_close_err() -> None:
                closed_err.append(True)
                original_close_err()

            monkeypatch.setattr(session_err, "rollback", track_rollback)
            monkeypatch.setattr(session_err, "close", track_close_err)
            session_err.execute(text("SELECT 1"))
            raise RuntimeError("模拟业务异常")
    except RuntimeError:
        pass
    assert len(rolled_back) == 1
    assert len(closed_err) == 1

    # 3. get_db_session 生成器兼容测试
    gen = container.get_db_session()
    sess_from_gen = next(gen)
    assert isinstance(sess_from_gen, Session)
    closed_gen: list[bool] = []
    orig_close_gen = sess_from_gen.close

    def track_close_gen() -> None:
        closed_gen.append(True)
        orig_close_gen()

    monkeypatch.setattr(sess_from_gen, "close", track_close_gen)

    # 模拟请求生命周期结束关闭生成器
    with contextlib.suppress(StopIteration):
        next(gen)
    assert len(closed_gen) == 1


@pytest.mark.asyncio
async def test_app_container_lifecycle() -> None:
    """测试 AppContainer 启动与优雅停机生命周期。"""
    settings = AppSettings(db=DatabaseSettings(db_url="sqlite:///:memory:"))
    container = AppContainer.create(settings=settings)

    # 1. 启动容器 (握手连通性与确保存储桶)
    await container.startup()

    # 2. 停机回收 (释放注册中心适配器与连接池)
    await container.shutdown()


@pytest.mark.asyncio
async def test_app_container_check_health() -> None:
    """测试 AppContainer.check_health 多组件健康检查结构。"""
    settings = AppSettings(
        env="development",
        db=DatabaseSettings(db_url="sqlite:///:memory:"),
        storage=StorageSettings(provider="memory", bucket_name="zhilian-materials"),
    )
    container = AppContainer.create(settings=settings)

    # 1. 验证支持同步直接调用
    health_sync = container.check_health()
    assert health_sync["status"] == "ok"
    assert health_sync["app"] == "ZhiLian"
    assert health_sync["environment"] == "development"
    assert health_sync["database"]["status"] == "connected"
    assert health_sync["database"]["dialect"] == "sqlite"
    assert health_sync["storage"]["provider"] == "memory"
    assert health_sync["storage"]["bucket"] == "zhilian-materials"
    assert health_sync["providers"]["llm"] == "fake"
    assert health_sync["providers"]["ocr"] == "fake"
    assert health_sync["providers"]["queue"] == "memory"

    # 2. 验证支持异步 await 调用
    health_async = await container.check_health()
    assert health_async["status"] == "ok"
    assert health_async["database"]["status"] == "connected"
