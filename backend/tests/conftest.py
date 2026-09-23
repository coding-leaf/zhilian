"""Pytest global configuration and fixtures.

Enforces zero-network policy during automated unit testing as mandated by AGENTS.md.
"""

import socket

import pytest


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
