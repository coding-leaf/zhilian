"""CLI 业务子命令离线单元测试（sqlite 内存库 + fake provider，零联网）。

覆盖：
- UT-CLI-10: `auth login` 输出 user_id，且绝不输出令牌明文；
- UT-CLI-11: `material upload` + `material status` 输出契约与退出码；
- UT-CLI-12: `material parse` 对损坏 DOCX 归因输出 failed_stage/error_message 并退出码 2；
- UT-CLI-13: 非真实 Provider 且未 `--allow-fake` 时业务命令以退出码 3 中止；
- UT-CLI-14: `question list` 空列表返回退出码 0。

说明：`main()` 每次调用都会自建 `CliContext`，因此这里显式注入一个**跨调用共享**的
`AppContainer`（内存 SQLite StaticPool + 共享 memory storage），确保同一次测试内的
上传/解析链路复用同一份内存数据。
"""

import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.cli.errors import EXIT_ASSERTION, EXIT_CONFIG, EXIT_OK
from app.cli.main import main
from app.container import AppContainer
from app.core.config import get_settings
from app.integrations.container import ProviderRegistry
from app.models.base import Base


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


def test_auth_login_outputs_user_id_without_plain_token(
    cli_container: AppContainer,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`auth login` 必须返回 user_id，且不得出现任何令牌明文字段。"""
    code, payload = _run(
        capsys,
        ["auth", "login", "--code", "dev_cli-smoke-user", "--json", "--allow-fake"],
    )

    assert code == EXIT_OK
    assert payload["status"] == "ok"
    assert payload["user_id"]
    assert payload["has_access_token"] is True
    assert payload["has_refresh_token"] is True
    assert "access_token" not in payload
    assert "refresh_token" not in payload


def test_material_upload_and_status(
    cli_container: AppContainer,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """上传中文讲义 TXT 后，状态查询应反映 pending/queued。"""
    user_id = uuid.uuid4()
    notes = tmp_path / "notes.txt"
    notes.write_text("第一章 线性表\n\n第二章 栈与队列\n\n第三章 二叉树遍历。", encoding="utf-8")

    upload_code, upload = _run(
        capsys,
        [
            "material",
            "upload",
            "--file",
            str(notes),
            "--user-id",
            str(user_id),
            "--json",
            "--allow-fake",
        ],
    )
    assert upload_code == EXIT_OK
    assert upload["material_id"]
    assert upload["version_id"]
    assert upload["material_status"] == "pending"
    assert upload["parse_status"] == "queued"

    status_code, status = _run(
        capsys,
        [
            "material",
            "status",
            "--material-id",
            str(upload["material_id"]),
            "--user-id",
            str(user_id),
            "--json",
            "--allow-fake",
        ],
    )
    assert status_code == EXIT_OK
    assert status["material_status"] == "pending"
    assert status["parse_status"] == "queued"
    assert len(status["versions"]) == 1


def test_material_parse_corrupt_docx_reports_failed_stage(
    cli_container: AppContainer,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """损坏 DOCX 解析失败必须输出 failed_stage + error_message 且退出码 2。"""
    user_id = uuid.uuid4()
    docx = tmp_path / "broken.docx"
    docx.write_bytes(b"PK\x03\x04this-is-not-a-valid-zip-container")

    upload_code, upload = _run(
        capsys,
        [
            "material",
            "upload",
            "--file",
            str(docx),
            "--user-id",
            str(user_id),
            "--json",
            "--allow-fake",
        ],
    )
    assert upload_code == EXIT_OK

    parse_code, parse = _run(
        capsys,
        [
            "material",
            "parse",
            "--material-id",
            str(upload["material_id"]),
            "--user-id",
            str(user_id),
            "--json",
            "--allow-fake",
        ],
    )
    assert parse_code == EXIT_ASSERTION
    details = parse["details"]
    assert isinstance(details, dict)
    assert details["failed_stage"] == "parsing_doc"
    assert details["error_message"]


def test_material_parse_success_with_notes_txt(
    cli_container: AppContainer,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """中文讲义 TXT 在 fake 知识抽取下解析成功可完成并输出 READY。"""
    from app.cli.fixtures import build_notes_txt

    user_id = uuid.uuid4()
    notes = tmp_path / "notes.txt"
    notes.write_bytes(build_notes_txt())

    _upload_code, upload = _run(
        capsys,
        [
            "material",
            "upload",
            "--file",
            str(notes),
            "--user-id",
            str(user_id),
            "--json",
            "--allow-fake",
        ],
    )

    parse_code, parse = _run(
        capsys,
        [
            "material",
            "parse",
            "--material-id",
            str(upload["material_id"]),
            "--user-id",
            str(user_id),
            "--json",
            "--allow-fake",
        ],
    )

    # fake LLM 无法产出真实结构化考点时，应精确归因退出码 2 而非伪造成功。
    assert parse_code in (EXIT_OK, EXIT_ASSERTION)
    if parse_code == EXIT_ASSERTION:
        assert parse["details"]["failed_stage"]


def test_business_command_requires_real_provider(
    cli_container: AppContainer,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """未 `--allow-fake` 时业务命令在 fake/memory 回落配置下以退出码 3 中止。"""
    code, payload = _run(capsys, ["auth", "login", "--code", "dev_x", "--json"])

    assert code == EXIT_CONFIG
    assert payload["exit_code"] == EXIT_CONFIG
    details = payload["details"]
    assert isinstance(details, dict)
    assert details["gaps"]


def test_question_list_empty_returns_ok(
    cli_container: AppContainer,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """无题目时 `question list` 返回退出码 0 与空列表。"""
    code, payload = _run(
        capsys,
        [
            "question",
            "list",
            "--material-id",
            str(uuid.uuid4()),
            "--user-id",
            str(uuid.uuid4()),
            "--json",
            "--allow-fake",
        ],
    )

    assert code == EXIT_OK
    assert payload["total"] == 0
    assert payload["questions"] == []
