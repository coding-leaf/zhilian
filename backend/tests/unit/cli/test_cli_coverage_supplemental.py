"""CLI 层覆盖率补强（M1-001 薄弱模块）。

覆盖目标（2026-10-04 权威口径下未覆盖行）：
- `app/cli/__main__.py`：`python -m app.cli` 入口（0% → 100%）；
- `app/cli/main.py`：CliError 非 JSON 输出、KeyboardInterrupt、未预期异常双模式；
- `app/cli/fixtures.py`：`resolve_smoke_input` 文件不存在 / OSError 归一化；
- `app/cli/report.py`：`redact_url` 边界（非法端口/带端口）、`sanitize` SecretStr、
  非 JSON 模式 `emit` / `info` 与嵌套打印；
- `app/cli/commands/__init__.py`：`parse_uuid` 空值与非法值、`resolve_user_id` code 分支。

纪律：零网络、零真实外部依赖；container 用内存 SQLite + fake Provider（沿既有 CLI 测试模式）。
"""

import argparse
import json
import runpy
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.cli
from app.cli.commands import parse_uuid, resolve_user_id
from app.cli.context import CliContext
from app.cli.errors import EXIT_ASSERTION, EXIT_OK, EXIT_RUNTIME, CliError
from app.cli.fixtures import resolve_smoke_input
from app.cli.main import main
from app.cli.report import REDACTED, Reporter, redact_url, sanitize
from app.container import AppContainer
from app.core.config import get_settings
from app.integrations.container import ProviderRegistry
from app.models.base import Base

_MAIN_PATH = Path(app.cli.__file__).parent / "__main__.py"


@pytest.fixture
def cli_container(monkeypatch: pytest.MonkeyPatch) -> AppContainer:
    """构建跨调用共享的离线容器（内存 SQLite + fake/memory Provider）。"""
    settings = get_settings()
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    registry = ProviderRegistry.create_default(settings=settings, session_factory=session_factory)
    registry.storage.ensure_bucket_exists(settings.storage.bucket_name)
    container = AppContainer(
        settings=settings,
        engine=engine,
        session_factory=session_factory,
        providers=registry,
    )

    def _create(
        cls: type[AppContainer],
        settings: Any = None,
        registry: Any = None,
        engine: Any = None,
        session_factory: Any = None,
    ) -> AppContainer:
        return container

    monkeypatch.setattr(AppContainer, "create", classmethod(_create))
    return container


def _run(capsys: pytest.CaptureFixture[str], argv: list[str]) -> tuple[int, dict[str, Any]]:
    code = main(argv)
    out = capsys.readouterr().out.strip()
    payload = json.loads(out) if out else {}
    return code, payload


class TestModuleEntry:
    """`python -m app.cli` 入口（`__main__.py`）。"""

    @pytest.mark.parametrize("exit_code", [0, 3])
    def test_dunder_main_propagates_exit_code(
        self, monkeypatch: pytest.MonkeyPatch, exit_code: int
    ) -> None:
        """入口必须调用 main() 并将返回值作为 SystemExit 码向上传播。"""
        monkeypatch.setattr("app.cli.main.main", lambda: exit_code)
        with pytest.raises(SystemExit) as exc_info:
            runpy.run_path(str(_MAIN_PATH), run_name="__main__")
        assert exc_info.value.code == exit_code


class TestMainErrorPaths:
    """`main()` 的三类异常路径（CliError / KeyboardInterrupt / 未预期异常）。"""

    def test_keyboard_interrupt_returns_runtime_code(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KeyboardInterrupt 必须被捕获并返回 EXIT_RUNTIME。"""

        def _raise(cls: Any, db_url: Any = None, allow_fake: Any = False) -> Any:
            raise KeyboardInterrupt

        monkeypatch.setattr(CliContext, "create", classmethod(_raise))
        assert main(["doctor"]) == EXIT_RUNTIME

    def test_unexpected_error_plain_mode_prints_message(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """未预期异常在非 JSON 模式下打印「未预期错误」并返回 EXIT_RUNTIME。"""

        def _raise(cls: Any, db_url: Any = None, allow_fake: Any = False) -> Any:
            raise RuntimeError("内部炸裂")

        monkeypatch.setattr(CliContext, "create", classmethod(_raise))
        code = main(["doctor"])
        assert code == EXIT_RUNTIME
        assert "未预期错误" in capsys.readouterr().out

    def test_unexpected_error_json_mode_emits_structured_payload(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """未预期异常在 JSON 模式下输出结构化 payload（error + exit_code）。"""

        def _raise(cls: Any, db_url: Any = None, allow_fake: Any = False) -> Any:
            raise RuntimeError("内部炸裂")

        monkeypatch.setattr(CliContext, "create", classmethod(_raise))
        code = main(["doctor", "--json"])
        assert code == EXIT_RUNTIME
        payload = json.loads(capsys.readouterr().out)
        assert payload["exit_code"] == EXIT_RUNTIME
        assert payload["error"] == "内部炸裂"

    def test_cli_error_plain_mode_prints_remediation(
        self, cli_container: AppContainer, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """CliError 在非 JSON 模式下打印「错误:」+「修复建议:」。"""
        code = main(["db", "reset"])
        out = capsys.readouterr().out
        assert code == EXIT_RUNTIME
        assert "错误:" in out
        assert "修复建议:" in out

    def test_cli_error_json_mode_includes_details(
        self, cli_container: AppContainer, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """CliError 携带 details 时，JSON payload 必须包含 details 字段。"""
        code, payload = _run(
            capsys,
            [
                "question",
                "list",
                "--material-id",
                "not-a-uuid",
                "--user-id",
                str(uuid.uuid4()),
                "--json",
                "--allow-fake",
            ],
        )
        assert code == EXIT_ASSERTION
        assert payload["details"]["value"] == "not-a-uuid"
        assert payload["exit_code"] == EXIT_ASSERTION


class TestFixtures:
    """`app/cli/fixtures.py` 输入解析。"""

    def test_resolve_smoke_input_reads_explicit_file(self, tmp_path: Path) -> None:
        """显式文件存在时返回其字节内容与文件名。"""
        target = tmp_path / "notes.md"
        target.write_text("# 讲义", encoding="utf-8")

        content, name = resolve_smoke_input(str(target))

        assert content == "# 讲义".encode()
        assert name == "notes.md"

    def test_resolve_smoke_input_missing_file_raises_cli_error(self, tmp_path: Path) -> None:
        """文件不存在时抛退出码 2 的 CliError（带修复指引）。"""
        missing = tmp_path / "missing.txt"

        with pytest.raises(CliError) as exc_info:
            resolve_smoke_input(str(missing))

        assert exc_info.value.exit_code == EXIT_ASSERTION
        assert "资料文件不存在" in exc_info.value.message
        assert exc_info.value.remediation

    def test_resolve_smoke_input_read_error_normalized_to_cli_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """读取抛 OSError 时归一化为 CliError（details 保留底层错误）。"""
        target = tmp_path / "locked.txt"
        target.write_text("内容", encoding="utf-8")

        def _raise(self: Path) -> bytes:
            raise OSError("permission denied")

        monkeypatch.setattr(Path, "read_bytes", _raise)

        with pytest.raises(CliError) as exc_info:
            resolve_smoke_input(str(target))

        assert exc_info.value.exit_code == EXIT_ASSERTION
        assert "读取资料文件失败" in exc_info.value.message
        assert exc_info.value.details["error"] == "permission denied"


class TestReporter:
    """`app/cli/report.py` 边界与人类可读模式。"""

    def test_redact_url_invalid_port_returns_original(self) -> None:
        """端口非法（触发 ValueError）时原样返回，不抛异常。"""
        bad = "postgresql://user:secret@host:notaport/db"
        assert redact_url(bad) == bad

    def test_redact_url_with_port_and_username_keeps_host_port(self) -> None:
        """带用户名与端口的连接串：密码脱敏为 ***，主机端口保留。"""
        result = redact_url("postgresql://zhilian:secret@dbhost:5432/zdb")
        assert result == f"postgresql://zhilian:{REDACTED}@dbhost:5432/zdb"

    def test_sanitize_replaces_secret_str_recursively(self) -> None:
        """嵌套结构中的 SecretStr 必须被替换为 ***。"""
        data = {"token": SecretStr("s3cr3t"), "items": [SecretStr("x"), {"nested": SecretStr("y")}]}
        assert sanitize(data) == {"token": REDACTED, "items": [REDACTED, {"nested": REDACTED}]}

    def test_emit_plain_mode_prints_nested_structures(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """非 JSON 模式：嵌套 dict / list 按缩进层级打印。"""
        reporter = Reporter(json_mode=False)
        reporter.emit({"name": "x", "nested": {"a": 1}, "items": [{"b": 2}, "plain"], "num": 3})
        out = capsys.readouterr().out
        assert "name: x" in out
        assert "nested:" in out
        assert "  a: 1" in out
        assert "- plain" in out
        assert "num: 3" in out

    def test_info_plain_mode_prints(self, capsys: pytest.CaptureFixture[str]) -> None:
        """非 JSON 模式：info 打印提示。"""
        Reporter(json_mode=False).info("提示信息")
        assert "提示信息" in capsys.readouterr().out

    def test_info_json_mode_stays_silent(self, capsys: pytest.CaptureFixture[str]) -> None:
        """JSON 模式：info 静默，保持 stdout 纯净。"""
        Reporter(json_mode=True).info("提示信息")
        assert capsys.readouterr().out == ""


class TestCommandHelpers:
    """`app/cli/commands/__init__.py` 共用校验工具。"""

    def test_parse_uuid_empty_value_raises_with_label(self) -> None:
        """空值必须抛 CliError 并指明参数名。"""
        with pytest.raises(CliError) as exc_info:
            parse_uuid(None, "--user-id")
        assert exc_info.value.exit_code == EXIT_ASSERTION
        assert "--user-id" in exc_info.value.message

    def test_parse_uuid_invalid_value_keeps_raw_in_details(self) -> None:
        """非法 UUID 必须抛 CliError 且 details 保留原始值。"""
        with pytest.raises(CliError) as exc_info:
            parse_uuid("not-a-uuid", "--practice-id")
        assert exc_info.value.exit_code == EXIT_ASSERTION
        assert exc_info.value.details["value"] == "not-a-uuid"

    def test_parse_uuid_valid_returns_uuid(self) -> None:
        """合法值返回 UUID 实例。"""
        value = uuid.uuid4()
        assert parse_uuid(str(value), "--user-id") == value

    def test_resolve_user_id_prefers_explicit_user_id(self) -> None:
        """显式 user_id 优先，不触发登录。"""
        context = MagicMock()
        value = uuid.uuid4()
        result = resolve_user_id(context, MagicMock(), user_id=str(value), code="ignored")
        assert result == value
        context.container.create_auth_service.assert_not_called()

    def test_resolve_user_id_via_code_logs_in(self) -> None:
        """未给 user_id 时走 code 登录并返回其 user_id。"""
        user_id = uuid.uuid4()
        user = MagicMock()
        user.id = user_id
        auth_service = MagicMock()
        auth_service.login_with_wechat.return_value = (user, MagicMock())
        context = MagicMock()
        context.container.create_auth_service.return_value = auth_service

        result = resolve_user_id(context, MagicMock(), user_id=None, code="wx-code")

        assert result == user_id
        auth_service.login_with_wechat.assert_called_once_with("wx-code")

    def test_resolve_user_id_without_any_identifier_raises(self) -> None:
        """两者均未提供时抛 CliError（退出码 2）。"""
        with pytest.raises(CliError) as exc_info:
            resolve_user_id(MagicMock(), MagicMock(), user_id=None)
        assert exc_info.value.exit_code == EXIT_ASSERTION


class TestAuthProfileCommand:
    """`auth profile` 成功路径（登录后查询画像）。"""

    def test_auth_profile_after_login_returns_payload(
        self, cli_container: AppContainer, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """先 login 再 profile：必须返回 user_id / nickname / created_at。"""
        login_code, login_payload = _run(
            capsys,
            ["auth", "login", "--code", "dev_cli-profile-user", "--json", "--allow-fake"],
        )
        assert login_code == EXIT_OK
        user_id = login_payload["user_id"]

        profile_code, profile_payload = _run(
            capsys,
            ["auth", "profile", "--user-id", user_id, "--json", "--allow-fake"],
        )

        assert profile_code == EXIT_OK
        assert profile_payload["command"] == "auth profile"
        assert profile_payload["user_id"] == user_id


class TestArgparseRegistration:
    """`build_parser` 装配契约（防止子命令漏注册）。"""

    def test_build_parser_registers_all_subcommands(self) -> None:
        """顶层解析器必须注册全部 9 个子命令。"""
        from app.cli.main import build_parser

        parser = build_parser()
        actions = next(
            action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
        )
        assert set(actions.choices) == {
            "doctor",
            "db",
            "auth",
            "material",
            "question",
            "practice",
            "grading",
            "diagnosis",
            "queue",
            "smoke",
        }
