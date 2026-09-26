"""`doctor` 子命令离线单元测试 (sqlite + fake provider，零联网)。

覆盖用例:
- UT-CLI-01: fake 配置下 `doctor --require-real` 返回 EXIT_CONFIG(3) 且含缺口清单。
- UT-CLI-02: 非 `--require-real` 仅报告，返回 EXIT_OK(0)。
- UT-CLI-03: `--allow-fake` 跳过真实 Provider 校验并返回 EXIT_OK(0)。
- UT-CLI-04: 输出严格脱敏，绝不泄漏 API Key / 连接串密码。
- UT-CLI-05: `main([...])` 全局参数可置于子命令之后（argparse 契约）。
"""

import json
from collections.abc import Iterator

import pytest

from app.cli.context import CliContext
from app.cli.errors import EXIT_CONFIG, EXIT_OK
from app.cli.main import main
from app.core.config import get_settings


@pytest.fixture(autouse=True)
def _fake_provider_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """将全链路 Provider 回落为 fake/memory 并指向内存 SQLite，清除配置缓存。"""
    monkeypatch.setenv("ZHILIAN_LLM__PROVIDER", "fake")
    monkeypatch.setenv("ZHILIAN_EMBEDDING__PROVIDER", "fake")
    monkeypatch.setenv("ZHILIAN_SEARCH__PROVIDER", "fake")
    monkeypatch.setenv("ZHILIAN_STORAGE__PROVIDER", "memory")
    monkeypatch.setenv("ZHILIAN_QUEUE__PROVIDER", "memory")
    monkeypatch.setenv("ZHILIAN_IDEMPOTENCY__PROVIDER", "memory")
    monkeypatch.setenv("ZHILIAN_DB__DB_URL", "sqlite:///:memory:")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_doctor_require_real_exits_with_config_gaps(capsys: pytest.CaptureFixture[str]) -> None:
    """fake 配置下 `doctor --require-real` 必须以退出码 3 中止并列出缺口。"""
    code = main(["doctor", "--require-real", "--json"])

    assert code == EXIT_CONFIG
    payload = json.loads(capsys.readouterr().out)
    assert payload["require_real"] is True
    assert payload["allow_fake"] is False

    gaps = payload["gaps"]
    components = {gap["component"] for gap in gaps}
    assert {"llm", "embedding", "search", "storage", "database"} <= components
    assert all(gap["env_key"] and gap["expected"] for gap in gaps)
    assert all("actual" in gap for gap in gaps)


def test_doctor_without_require_real_reports_only(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """非 `--require-real` 时仅报告，退出码恒为 0。"""
    code = main(["doctor", "--json"])

    assert code == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["require_real"] is False
    assert payload["providers"]["llm"]["provider"] == "fake"
    assert payload["providers"]["search"]["provider"] == "fake"
    assert payload["gaps"]


def test_doctor_allow_fake_skips_real_validation(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--allow-fake` 跳过真实 Provider 校验并返回 0，且缺口清单为空。"""
    code = main(["doctor", "--allow-fake", "--json"])

    assert code == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["allow_fake"] is True
    assert payload["gaps"] == []


def test_assert_real_providers_allow_fake_returns_empty() -> None:
    """`allow_fake=True` 时真实链路校验直接放行（仅测试用）。"""
    context = CliContext.create(allow_fake=True)
    assert context.assert_real_providers() == []


def test_doctor_output_redacts_secrets(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """输出必须脱敏：API Key / Secret / 连接串密码均不得出现明文。"""
    monkeypatch.setenv("ZHILIAN_LLM__PROVIDER", "openai")
    monkeypatch.setenv("ZHILIAN_LLM__API_KEY", "cli-test-llm-secret")
    monkeypatch.setenv("ZHILIAN_EMBEDDING__PROVIDER", "openai")
    monkeypatch.setenv("ZHILIAN_EMBEDDING__API_KEY", "cli-test-embedding-secret")
    monkeypatch.setenv("ZHILIAN_SEARCH__PROVIDER", "pgvector")
    monkeypatch.setenv("ZHILIAN_STORAGE__PROVIDER", "minio")
    monkeypatch.setenv("ZHILIAN_STORAGE__ACCESS_KEY", "cli-test-access-key")
    monkeypatch.setenv("ZHILIAN_STORAGE__SECRET_KEY", "cli-test-storage-secret")
    monkeypatch.setenv(
        "ZHILIAN_DB__DB_URL",
        "postgresql+psycopg://cli_user:cli-db-password@localhost:5432/cli_db",
    )
    get_settings.cache_clear()

    code = main(["doctor", "--json"])

    assert code == EXIT_OK
    out = capsys.readouterr().out
    for secret in (
        "cli-test-llm-secret",
        "cli-test-embedding-secret",
        "cli-test-access-key",
        "cli-test-storage-secret",
        "cli-db-password",
    ):
        assert secret not in out

    payload = json.loads(out)
    assert payload["providers"]["llm"]["api_key_configured"] is True
    assert payload["providers"]["storage"]["secret_key_configured"] is True
    database_url = payload["settings"]["database_url"]
    assert "***" in database_url
    assert database_url.endswith("@localhost:5432/cli_db")
