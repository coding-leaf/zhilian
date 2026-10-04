"""CLI `doctor` 与 `CliContext` 补测（M1-001 薄弱模块）。

覆盖目标（2026-10-04 权威口径下未覆盖行）：
- `app/cli/commands/doctor.py`：`--require-real` 的 3/4/0 三种退出码分支；
- `app/cli/context.py`：`require_ocr` 缺口分支、storage 密钥缺失分支、
  `_probe_database/_probe_redis/_probe_minio` 失败归因、`db_revision` 取值与异常兜底。

纪律：零外部网络（socket/redis 均以 monkeypatch 替身），不触发真实探测。
"""

import argparse
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.cli.commands.doctor import handle as doctor_handle
from app.cli.context import CliContext, Gap
from app.cli.errors import EXIT_CONFIG, EXIT_INFRA, EXIT_OK
from app.cli.report import Reporter


def _settings_stub(**overrides: Any) -> SimpleNamespace:
    """构造全部合规的配置替身，可按需覆盖单个域。"""
    settings = SimpleNamespace(
        llm=SimpleNamespace(provider="openai", api_key="sk-llm"),
        embedding=SimpleNamespace(provider="openai", api_key="sk-emb"),
        search=SimpleNamespace(provider="pgvector"),
        storage=SimpleNamespace(
            provider="minio",
            access_key="ak",
            secret_key="sk",  # noqa: S106 - 测试假密钥
            endpoint_url="http://minio.local:9000",
        ),
        db=SimpleNamespace(db_url="postgresql+psycopg://u:p@h:5432/db"),
        redis=SimpleNamespace(redis_url="redis://localhost:6379/0"),
        ocr=SimpleNamespace(provider="tencent", effective_api_key="ocr-key"),
        env="test",
    )
    for key, value in overrides.items():
        setattr(settings, key, value)
    return settings


def _context(settings: SimpleNamespace, container: Any = None) -> CliContext:
    return CliContext(settings, allow_fake=False, container=container or MagicMock())


class _DoctorContext:
    """doctor 处理器的最小上下文替身。"""

    allow_fake = False

    def __init__(self, gaps: list[Gap], infra: dict[str, dict[str, Any]]) -> None:
        self.settings = SimpleNamespace(env="test")
        self.db_url = "sqlite:///doctor.db"
        self._gaps = gaps
        self._infra = infra

    def assert_real_providers(self, require_ocr: bool = False) -> list[Gap]:
        return self._gaps

    def probe_infra(self) -> dict[str, dict[str, Any]]:
        return self._infra

    def provider_matrix(self) -> dict[str, Any]:
        return {"llm": {"provider": "fake", "configured": False}}

    def db_revision(self) -> str | None:
        return "rev-1"


_A_GAP = Gap(
    component="llm",
    env_key="ZHILIAN_LLM__PROVIDER",
    expected="openai",
    actual="fake",
    remediation="配置真实 LLM Provider。",
)


class TestDoctorHandler:
    """`doctor --require-real` 的退出码契约。"""

    def test_gaps_present_returns_exit_config(self, capsys: pytest.CaptureFixture[str]) -> None:
        """存在配置缺口时返回 EXIT_CONFIG(3)。"""
        context = _DoctorContext([_A_GAP], {"database": {"reachable": True}})
        code = doctor_handle(
            argparse.Namespace(require_real=True),
            context,
            Reporter(json_mode=False),  # type: ignore[arg-type]
        )
        assert code == EXIT_CONFIG
        assert "配置缺口" in capsys.readouterr().out

    def test_unreachable_infra_returns_exit_infra(self, capsys: pytest.CaptureFixture[str]) -> None:
        """无缺口但基础设施不可达时返回 EXIT_INFRA(4) 并列出中文组件名。"""
        context = _DoctorContext(
            [],
            {
                "database": {"reachable": True},
                "redis": {"reachable": False, "detail": "down"},
            },
        )
        code = doctor_handle(
            argparse.Namespace(require_real=True),
            context,
            Reporter(json_mode=False),  # type: ignore[arg-type]
        )
        assert code == EXIT_INFRA
        assert "Redis" in capsys.readouterr().out

    def test_all_green_returns_ok(self) -> None:
        """全部合规时返回 EXIT_OK。"""
        context = _DoctorContext([], {"database": {"reachable": True}})
        code = doctor_handle(
            argparse.Namespace(require_real=True),
            context,
            Reporter(json_mode=True),  # type: ignore[arg-type]
        )
        assert code == EXIT_OK

    def test_without_require_real_always_ok(self, capsys: pytest.CaptureFixture[str]) -> None:
        """未要求真实链路时即使有缺口也只报告（退出码 0）+ status=degraded。"""
        context = _DoctorContext([_A_GAP], {"database": {"reachable": False}})
        code = doctor_handle(
            argparse.Namespace(require_real=False),
            context,
            Reporter(json_mode=True),  # type: ignore[arg-type]
        )
        assert code == EXIT_OK


class TestAssertRealProvidersBoundaries:
    """`assert_real_providers` 的 OCR 与 storage 缺口分支。"""

    def test_require_ocr_with_fake_provider_reports_gap(self) -> None:
        """require_ocr 且 OCR 为 fake 时必须产生 ocr 缺口。"""
        settings = _settings_stub(ocr=SimpleNamespace(provider="fake", effective_api_key="k"))
        gaps = _context(settings).assert_real_providers(require_ocr=True)
        assert any(gap.component == "ocr" and "PROVIDER" in gap.env_key for gap in gaps)

    def test_require_ocr_without_api_key_reports_gap(self) -> None:
        """require_ocr 且 OCR 真实 Provider 缺密钥时必须产生 API_KEY 缺口。"""
        settings = _settings_stub(ocr=SimpleNamespace(provider="tencent", effective_api_key=None))
        gaps = _context(settings).assert_real_providers(require_ocr=True)
        assert any(gap.component == "ocr" and "API_KEY" in gap.env_key for gap in gaps)

    def test_all_real_with_ocr_returns_no_gaps(self) -> None:
        """全部真实配置（含 OCR）时返回空缺口。"""
        gaps = _context(_settings_stub()).assert_real_providers(require_ocr=True)
        assert gaps == []

    def test_storage_missing_keys_reports_gap(self) -> None:
        """storage 真实 Provider 但缺密钥对时必须产生缺口。"""
        settings = _settings_stub(
            storage=SimpleNamespace(
                provider="minio",
                access_key=None,
                secret_key="sk",  # noqa: S106 - 测试假密钥
            )
        )
        gaps = _context(settings).assert_real_providers()
        assert any(gap.component == "storage" for gap in gaps)


class TestProbes:
    """`_probe_*` 与 `db_revision` 的失败归因。"""

    def test_probe_database_failure_captured(self) -> None:
        """数据库连接失败时返回 reachable=False 与错误详情。"""
        container = MagicMock()
        container.engine.connect.side_effect = OSError("connection refused")
        result = _context(_settings_stub(), container)._probe_database()
        assert result["reachable"] is False
        assert "connection refused" in result["detail"]

    def test_probe_redis_failure_captured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Redis ping 失败时返回 reachable=False。"""
        client = MagicMock()
        client.ping.side_effect = ConnectionError("redis down")
        monkeypatch.setattr("app.cli.context.redis.from_url", lambda *a, **k: client)
        result = _context(_settings_stub())._probe_redis()
        assert result["reachable"] is False
        assert "redis down" in result["detail"]

    def test_probe_minio_missing_endpoint(self) -> None:
        """storage 未配置端点时返回 reachable=False（不发起连接）。"""
        settings = _settings_stub(storage=SimpleNamespace(provider="minio", endpoint_url=None))
        result = _context(settings)._probe_minio()
        assert result["reachable"] is False
        assert "endpoint_url" in result["detail"]

    def test_probe_minio_connection_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """TCP 连接失败时返回 reachable=False（socket 以替身拦截）。"""

        def _boom(address: tuple[str, int], timeout: float = 0.5) -> Any:
            raise OSError("connection refused")

        monkeypatch.setattr("app.cli.context.socket.create_connection", _boom)
        result = _context(_settings_stub())._probe_minio()
        assert result["reachable"] is False
        assert "connection refused" in result["detail"]

    def test_db_revision_returns_value(self) -> None:
        """正常读取迁移版本号返回字符串。"""
        container = MagicMock()
        execute = container.engine.connect.return_value.__enter__.return_value.execute
        execute.return_value.scalar.return_value = "rev-9"
        assert _context(_settings_stub(), container).db_revision() == "rev-9"

    def test_db_revision_returns_none_when_empty(self) -> None:
        """alembic_version 表为空时返回 None。"""
        container = MagicMock()
        execute = container.engine.connect.return_value.__enter__.return_value.execute
        execute.return_value.scalar.return_value = None
        assert _context(_settings_stub(), container).db_revision() is None

    def test_db_revision_returns_none_on_error(self) -> None:
        """连接异常时兜底返回 None。"""
        container = MagicMock()
        container.engine.connect.side_effect = OSError("db down")
        assert _context(_settings_stub(), container).db_revision() is None
