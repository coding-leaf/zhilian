"""FastAPI deps 层覆盖率补强（M1-001 薄弱模块）。

覆盖目标（2026-10-04 权威口径下未覆盖行）：
- `app/api/deps/container.py`：`get_container` 三分支（无 request / 无 app / 有 container）；
- `app/api/deps/db.py`：`get_db_session` 未挂载报错 + 正常 yield 与退出关闭；
- `app/api/deps/folder.py`：`get_folder_service` 三分支
  （未挂载报错 / session 注入 / session_factory 兜底）。

纪律：使用 `MagicMock(spec=Session)`（禁止自定义 stub 绕过父类初始化），
断言以「方法调用」为准（禁止依赖私有字段）。
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from app.api.deps.container import get_container
from app.api.deps.db import _db_session_generator, get_db_session
from app.api.deps.folder import get_folder_service


def _request_with_container(container: Any) -> Any:
    """构造带 app.state.container 的最小 request 替身。"""
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(container=container)))


class TestGetContainer:
    """`get_container` 三条路径。"""

    def test_returns_none_when_request_is_none(self) -> None:
        """request 为 None 时返回 None（不抛异常）。"""
        assert get_container(None) is None  # type: ignore[arg-type]

    def test_returns_none_when_app_missing(self) -> None:
        """request 无 app 属性时返回 None。"""
        assert get_container(SimpleNamespace(app=None)) is None  # type: ignore[arg-type]

    def test_returns_container_from_app_state(self) -> None:
        """正常请求上下文返回 app.state.container。"""
        container = MagicMock()
        request = _request_with_container(container)
        assert get_container(request) is container  # type: ignore[arg-type]

    def test_returns_none_when_state_has_no_container(self) -> None:
        """app.state 存在但未挂载 container 时返回 None。"""
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(container=None)))
        assert get_container(request) is None  # type: ignore[arg-type]


class TestGetDbSession:
    """`get_db_session` 生成器依赖。"""

    def test_raises_when_not_mounted(self) -> None:
        """未挂载 container 时必须抛 NotImplementedError（提醒走 overrides）。"""
        with pytest.raises(NotImplementedError):
            get_db_session(None)  # type: ignore[arg-type]

    def test_wrapped_points_to_generator_function(self) -> None:
        """`__wrapped__` 契约：必须指向生成器实现，FastAPI 才按生成器依赖清理。"""
        assert get_db_session.__wrapped__ is _db_session_generator  # type: ignore[attr-defined]

    def test_generator_yields_session_and_closes_on_exit(self) -> None:
        """正常路径：yield 来自 container.get_session 的会话，退出时随 with 关闭。"""
        injected_session = MagicMock(spec=Session)
        container = MagicMock()
        container.get_session.return_value.__enter__.return_value = injected_session
        request = _request_with_container(container)

        generator = _db_session_generator(request)  # type: ignore[arg-type]
        yielded = next(generator)

        assert yielded is injected_session
        # 生成器尚未结束，会话不应被提前关闭
        injected_session.close.assert_not_called()
        with pytest.raises(StopIteration):
            next(generator)
        # 退出 with 后 container 会话上下文已结束（由 container 负责关闭）
        container.get_session.return_value.__exit__.assert_called_once()

    def test_get_db_session_delegates_to_generator(self) -> None:
        """已挂载时 `get_db_session` 返回生成器并 yield 同一会话。"""
        injected_session = MagicMock(spec=Session)
        container = MagicMock()
        container.get_session.return_value.__enter__.return_value = injected_session
        request = _request_with_container(container)

        generator = get_db_session(request)  # type: ignore[arg-type]
        assert next(generator) is injected_session


class TestGetFolderService:
    """`get_folder_service` 三条路径。"""

    def test_raises_when_not_mounted(self) -> None:
        """未挂载 container 时必须抛 NotImplementedError。"""
        with pytest.raises(NotImplementedError):
            get_folder_service(None)  # type: ignore[arg-type]

    def test_uses_injected_session_when_provided(self) -> None:
        """传入真实 Session 实例时直接透传给服务工厂。"""
        injected_session = MagicMock(spec=Session)
        container = MagicMock()
        container.create_folder_service.return_value = "folder-service"
        request = _request_with_container(container)

        result = get_folder_service(request, injected_session)  # type: ignore[arg-type]

        assert result == "folder-service"
        container.create_folder_service.assert_called_once_with(session=injected_session)
        container.session_factory.assert_not_called()

    def test_falls_back_to_session_factory(self) -> None:
        """未注入 Session 时使用 container.session_factory() 兜底。"""
        factory_session = MagicMock(spec=Session)
        container = MagicMock()
        container.session_factory.return_value = factory_session
        container.create_folder_service.return_value = "folder-service"
        request = _request_with_container(container)

        result = get_folder_service(request, None)  # type: ignore[arg-type]

        assert result == "folder-service"
        container.create_folder_service.assert_called_once_with(session=factory_session)
