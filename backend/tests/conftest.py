"""Pytest global configuration and fixtures.

Enforces zero-network policy during automated unit testing as mandated by AGENTS.md.
Also pins provider selectors to fake/memory so the suite stays deterministic and
independent of a developer's local `.env` real-provider configuration.
"""

import socket
from collections.abc import Iterator

import pytest

from app.core.config import get_settings


@pytest.fixture(autouse=True)
def block_external_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """阻断任何外部真实公网网络连接，仅允许本地环回 (127.0.0.1, localhost) 与本地 Socket."""
    original_connect = socket.socket.connect

    def guarded_connect(self: socket.socket, address: tuple[str, int] | str | bytes) -> None:
        if isinstance(address, tuple) and len(address) >= 2:
            host = address[0]
            if str(host) in {"127.0.0.1", "localhost", "::1"}:
                original_connect(self, address)
                return
        elif isinstance(address, (str, bytes)):
            original_connect(self, address)
            return

        raise RuntimeError(f"AGENTS.md 红线拦截: 单元测试严禁真实联网连接外部主机 {address!r}。")

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)


@pytest.fixture(autouse=True)
def offline_default_providers(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """固定 Provider 选择器为 fake/memory，确保测试不依赖本地 `.env` 真实配置。

    单独测试可通过在用例内 `monkeypatch.setenv` 覆写具体键来做真实链路断言。
    """
    defaults = {
        "ZHILIAN_LLM__PROVIDER": "fake",
        "ZHILIAN_OCR__PROVIDER": "fake",
        "ZHILIAN_EMBEDDING__PROVIDER": "fake",
        "ZHILIAN_SEARCH__PROVIDER": "fake",
        "ZHILIAN_STORAGE__PROVIDER": "memory",
        "ZHILIAN_QUEUE__PROVIDER": "memory",
        "ZHILIAN_IDEMPOTENCY__PROVIDER": "memory",
    }
    for key, value in defaults.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
