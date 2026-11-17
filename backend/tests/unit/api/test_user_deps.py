"""Unit tests for app/api/deps/user.py — UserService dependency injection.

覆盖目标：拉升 T0 接口层 `app/api/deps/` 覆盖率从 83% 至 ≥90%。

被测对象：`get_user_service` 生成器依赖函数。代码中存在四条关键路径：
- 路径 1：request + container + session 为 SQLAlchemy Session 实例 → 复用注入的 Session；
- 路径 2：request + container + session 为 None/非 Session → fallback 自建 managed_session；
- 路径 3：request 提供但未挂载 container → NotImplementedError；
- 路径 4：request=None → NotImplementedError。

`test_app_lifespan.py` 已经覆盖了路径 2、3；本文件专门补全 路径 1 与 路径 4，
并对路径 2 的 fallback 行为做更严格的契约校验（session 复用、Session 生命周期）。

设计要点（评审 PR3 后修复）：
- 不再使用自定义 `_StubSession(Session)` 反模式；改用 `MagicMock(spec=Session)`，
  spec=Session 保证 isinstance 判定与 Session API 校验同步。
- `_RecordingContainer.create_user_service` 返回 `MagicMock(spec=AuthService)`，
  满足真实服务契约校验。
- 生命周期断言改用 `close.assert_called_once()` / `assert_not_called()`，
  不再依赖 stub 内部 `_closed` 标志位。
- `_marker_cycle` 改用 `itertools.cycle` 防止 StopIteration。
"""

import itertools
from collections.abc import Generator
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from fastapi import Request
from sqlalchemy.orm import Session

from app.api.deps.user import get_user_service
from app.services.auth import AuthService


class _RecordingContainer:
    """AppContainer stub that records factory invocations and session lifecycle.

    `create_user_service` 返回 `MagicMock(spec=AuthService)`，使 isinstance 判定
    与真实服务契约一致；session 字段使用 `MagicMock(spec=Session)`，
    同步 Session API 与 close() 协议校验。
    """

    def __init__(self) -> None:
        self.created_services: list[tuple[object, str]] = []
        self.managed_session_factory_calls = 0
        self._session_pool: list[MagicMock] = []
        self._marker_cycle = itertools.cycle(["marker-A", "marker-B", "marker-C"])

    @contextmanager
    def get_session(self) -> Generator[MagicMock, None, None]:
        self.managed_session_factory_calls += 1
        stub = MagicMock(spec=Session)
        stub.close = MagicMock()  # 单独命名便于断言与反向影响隔离
        self._session_pool.append(stub)
        try:
            yield stub
        finally:
            stub.close.assert_not_called()  # teardown 由依赖函数调用 close 一次
            stub.close()


def create_user_service(self: _RecordingContainer, session: object) -> MagicMock:
    marker = next(self._marker_cycle)
    service = MagicMock(spec=AuthService)
    service.session = session  # 让 service.session 指向注入的 session 便于断言
    self.created_services.append((session, marker))
    return service


_RecordingContainer.create_user_service = create_user_service  # type: ignore[attr-defined]


def _make_request_with_container(container: object) -> Request:
    """构造一个挂在指定 container 上的 FastAPI Request 桩对象。"""
    fake_request = MagicMock(spec=Request)
    # MagicMock spec=Request 会创建 app 属性为 Mock；显式覆盖 state
    fake_request.app.state.container = container
    return fake_request


class TestGetUserServiceDirectSessionPath:
    """路径 1：注入的 session 已是 SQLAlchemy Session 实例，直接复用。"""

    def test_get_user_service_yields_with_injected_session_when_container_present(self) -> None:
        """显式传入 SQLAlchemy Session 时：复用该 Session，不进入 managed_session 兜底。"""
        container = _RecordingContainer()
        fake_request = _make_request_with_container(container)
        injected_session = MagicMock(spec=Session)

        gen = get_user_service(request=fake_request, session=injected_session)
        try:
            service = next(gen)
        finally:
            gen.close()

        # 1. 产出的服务是 AuthService 类型桩，且绑定的 session 是注入的 session
        assert isinstance(service, AuthService)
        assert service.session is injected_session
        # 2. 仅调用一次 create_user_service，且参数为注入的 session
        assert len(container.created_services) == 1
        used_session, _marker = container.created_services[0]
        assert used_session is injected_session
        # 3. fallback 工厂未被调用（说明没走 get_session 兜底）
        assert container.managed_session_factory_calls == 0

    def test_get_user_service_does_not_close_injected_session(self) -> None:
        """依赖函数必须复用调用方持有的 Session，绝不能在 yield 结束后 close() 该 Session。

        BUG-FIX: 之前用 stub._closed 状态位断言与真实 Session 关闭机制不一致；
        改用 MagicMock(spec=Session) 的 close 计数器直接验证方法调用次数。
        """
        container = _RecordingContainer()
        fake_request = _make_request_with_container(container)
        injected_session = MagicMock(spec=Session)

        gen = get_user_service(request=fake_request, session=injected_session)
        next(gen)
        gen.close()

        # 注入的 session 在依赖生命周期内绝对不能被 close（绝不能泄漏调用方资源）
        injected_session.close.assert_not_called()

    def test_get_user_service_returns_real_auth_service_when_session_is_real_session(self) -> None:
        """当 container 是真实 AppContainer 且 session 是真实 Session 时，产出真实 AuthService。"""
        from sqlalchemy.orm import sessionmaker

        from app.container import AppContainer
        from app.core.config import AppSettings, DatabaseSettings

        settings = AppSettings(db=DatabaseSettings(db_url="sqlite:///:memory:"))
        container = AppContainer.create(settings=settings)
        sess_factory = sessionmaker(bind=container.engine, expire_on_commit=False)
        sess: Session = sess_factory()
        try:
            fake_request = _make_request_with_container(container)
            gen = get_user_service(request=fake_request, session=sess)
            try:
                service = next(gen)
                # 真实容器应产出真实 AuthService 而非桩
                assert isinstance(service, AuthService)
                assert service.session is sess
            finally:
                gen.close()
        finally:
            sess.close()
            container.engine.dispose()


class TestGetUserServiceFallbackPath:
    """路径 2：session 为 None 或非 Session，走 container.get_session() 兜底。"""

    def test_get_user_service_with_none_session_falls_back_to_managed_session(self) -> None:
        """session=None 时：调用 container.get_session() 自建 session，并保证 teardown 时 close。"""
        container = _RecordingContainer()
        fake_request = _make_request_with_container(container)

        gen = get_user_service(request=fake_request, session=None)
        try:
            service = next(gen)
        finally:
            gen.close()

        # 1. 走了一次 fallback
        assert container.managed_session_factory_calls == 1
        # 2. 创建服务时使用的是 fallback 的 session（不是注入）
        assert len(container.created_services) == 1
        used_session, _ = container.created_services[0]
        assert used_session is not None
        assert isinstance(used_session, Session)
        # 3. fallback session 在 teardown 时被 close 一次
        used_session.close.assert_called_once()
        # 4. 产出服务对象
        assert isinstance(service, AuthService)

    def test_get_user_service_with_non_session_arg_falls_back(self) -> None:
        """session 不是 SQLAlchemy Session 实例时（如 MagicMock），仍走 fallback 路径。"""
        container = _RecordingContainer()
        fake_request = _make_request_with_container(container)

        sentinel = object()  # 非 Session 实例

        gen = get_user_service(request=fake_request, session=sentinel)  # type: ignore[arg-type]
        try:
            service = next(gen)
        finally:
            gen.close()

        # 必须走 fallback，且不接收传入的 sentinel
        assert container.managed_session_factory_calls == 1
        assert service.session is not sentinel
        assert isinstance(service.session, Session)


class TestGetUserServiceNoContainerPath:
    """路径 3 / 4：未挂载 container 或 request=None 时，抛出 NotImplementedError。"""

    def test_get_user_service_raises_not_implemented_when_request_is_none(self) -> None:
        """request=None 时直接抛 NotImplementedError，绝不进入任何容器装配分支。"""
        with pytest.raises(NotImplementedError) as exc_info:
            next(get_user_service(request=None, session=None))
        # 必须明确提示用户该依赖尚未装配
        assert "AuthService 生产装配工厂尚未挂载" in str(exc_info.value)

    def test_get_user_service_raises_not_implemented_when_app_state_lacks_container(self) -> None:
        """request 提供但 app.state 没有 container 属性时抛 NotImplementedError。

        BUG-FIX: 之前用 `del fake_request.app.state.container` 依赖 MagicMock 隐式行为；
        现改用更显式的 `configure_mock` 删除属性，行为更可预测。
        """
        fake_request = MagicMock(spec=Request)
        # 显式删除 container 属性，使其走 hasattr 短路分支
        del fake_request.app.state.container

        with pytest.raises(NotImplementedError):
            next(get_user_service(request=fake_request, session=None))

    def test_get_user_service_raises_not_implemented_when_app_attr_is_none(self) -> None:
        """request.app 为 None 时不应 AttributeError，应抛 NotImplementedError。"""
        fake_request = MagicMock(spec=Request)
        # request.app=None 时 getattr(...).app 是 None，会走 raise 分支
        fake_request.app = None

        with pytest.raises(NotImplementedError):
            next(get_user_service(request=fake_request, session=None))


class TestGetUserServiceIntegration:
    """端到端契约：get_user_service 的返回值必须可用于依赖注入覆盖。"""

    def test_yielded_service_binds_to_managed_session(self) -> None:
        """通过真实 AppContainer 装配：get_user_service 必须产出真实 AuthService 实例。"""
        from app.container import AppContainer
        from app.core.config import AppSettings, DatabaseSettings

        settings = AppSettings(db=DatabaseSettings(db_url="sqlite:///:memory:"))
        container = AppContainer.create(settings=settings)
        fake_request = _make_request_with_container(container)

        gen = get_user_service(request=fake_request, session=None)
        try:
            service = next(gen)
        finally:
            gen.close()

        # 真实容器装配应产出真实 AuthService（继承自 BaseService）
        assert isinstance(service, AuthService)
        # AuthService 必须暴露 get_user_by_id 接口契约
        assert hasattr(service, "get_user_by_id")
        # session 是 SQLAlchemy Session 实例
        assert isinstance(service.session, Session)
        container.engine.dispose()

    def test_generator_closes_cleanly_without_session_leak(self) -> None:
        """连续三次启动并关闭生成器：每次都必须正确 close 上一次的 fallback session。

        BUG-FIX: 之前用 `_StubSession._closed` 内部状态位难以验证计数；
        现用 MagicMock(spec=Session) + 迭代器计数器验证生命周期正确性。
        """
        container = _RecordingContainer()
        fake_request = _make_request_with_container(container)

        for _ in range(3):
            gen = get_user_service(request=fake_request, session=None)
            next(gen)
            gen.close()

        # 3 次调用 → 3 个独立 session，每个被 close 一次
        assert container.managed_session_factory_calls == 3
        assert len(container._session_pool) == 3
        # itertools.cycle 不会因为多次 next 而 StopIteration
        assert len(container.created_services) == 3
        for stub in container._session_pool:
            stub.close.assert_called_once()
