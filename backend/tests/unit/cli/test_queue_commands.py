"""`queue stalled` 只读滞留巡检子命令单元测试（sqlite 内存库，零联网）。

覆盖：
- 无滞留记录时退出码 0；
- 长期停留在 `submitted` 的练习 / 解析中间态的资料版本被检出，退出码 2 并给出恢复入口；
- 阈值内的新鲜记录不被误报；
- 巡检命令不得回写任何业务状态。
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.cli.errors import EXIT_OK
from app.cli.main import main
from app.container import AppContainer
from app.core.config import get_settings
from app.integrations.container import ProviderRegistry
from app.models.base import Base
from app.models.material import Material, MaterialStatus, MaterialVersion, ParseStatus
from app.models.practice import Practice, PracticeStatus


@pytest.fixture
def cli_container(monkeypatch: pytest.MonkeyPatch) -> AppContainer:
    """构建离线共享容器（内存 SQLite + fake/memory Provider）。"""
    settings = get_settings()
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    registry = ProviderRegistry.create_default(settings=settings, session_factory=session_factory)
    container = AppContainer(
        settings=settings,
        engine=engine,
        session_factory=session_factory,
        providers=registry,
    )

    def _create(cls: type[AppContainer], **kwargs: Any) -> AppContainer:
        return container

    monkeypatch.setattr(AppContainer, "create", classmethod(_create))
    return container


def _run(capsys: pytest.CaptureFixture[str], argv: list[str]) -> tuple[int, dict[str, Any]]:
    code = main(argv)
    out = capsys.readouterr().out.strip()
    payload = json.loads(out) if out else {}
    return code, payload


def _normalize_id(value: str) -> str:
    """归一化 UUID 文本：SQLite 原生查询返回无连字符的十六进制串。"""
    return value.replace("-", "").lower()


def _seed_stalled_practice(container: AppContainer, minutes_ago: int) -> uuid.UUID:
    """写入一条停留在 submitted 且已超过阈值的练习。"""
    user_id = uuid.uuid4()
    practice_id = uuid.uuid4()
    with container.get_session() as session:
        session.add(
            Practice(
                id=practice_id,
                user_id=user_id,
                title="滞留判题练习",
                status=PracticeStatus.SUBMITTED.value,
                source_type="normal",
                question_count=2,
                knowledge_point_ids=[],
                ordered_question_ids=[],
                submitted_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
            )
        )
        session.commit()
    return practice_id


def _seed_stalled_version(container: AppContainer, minutes_ago: int) -> uuid.UUID:
    """写入一条停留在解析中间态且已超过阈值的资料版本。"""
    user_id = uuid.uuid4()
    material_id = uuid.uuid4()
    version_id = uuid.uuid4()
    with container.get_session() as session:
        session.add(
            Material(
                id=material_id,
                user_id=user_id,
                title="滞留解析讲义.pdf",
                file_format="pdf",
                file_size=1024,
                status=MaterialStatus.PARSING.value,
            )
        )
        version = MaterialVersion(
            id=version_id,
            material_id=material_id,
            user_id=user_id,
            version_number=1,
            storage_key="raw/stalled.pdf",
            content_hash="hash_stalled",
            parse_status=ParseStatus.PARSING_DOC.value,
        )
        session.add(version)
        session.flush()
        version.updated_at = datetime.now(UTC) - timedelta(minutes=minutes_ago)
        session.commit()
    return version_id


def test_queue_stalled_reports_no_stall_on_empty_database(
    cli_container: AppContainer,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """空库巡检必须返回退出码 0 与 total=0，不得伪造滞留记录。"""
    code, payload = _run(capsys, ["queue", "stalled", "--json"])

    assert code == EXIT_OK
    assert payload["command"] == "queue.stalled"
    assert payload["total"] == 0
    assert payload["status"] == "ok"
    assert payload["stalled_practices"] == []
    assert payload["stalled_versions"] == []


def test_queue_stalled_detects_and_points_to_user_recovery_entry(
    cli_container: AppContainer,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """超过阈值的判题/解析记录必须被检出，并给出用户可操作的恢复入口。"""
    practice_id = _seed_stalled_practice(cli_container, minutes_ago=60)
    version_id = _seed_stalled_version(cli_container, minutes_ago=60)

    code, payload = _run(
        capsys,
        ["queue", "stalled", "--older-than-minutes", "15", "--json"],
    )

    assert code == 2
    assert payload["total"] == 2
    assert payload["status"] == "stalled"
    assert _normalize_id(payload["stalled_practices"][0]["practice_id"]) == _normalize_id(
        str(practice_id)
    )
    assert payload["stalled_practices"][0]["action"] == "POST /practices/{id}/regrade"
    assert _normalize_id(payload["stalled_versions"][0]["version_id"]) == _normalize_id(
        str(version_id)
    )
    assert payload["stalled_versions"][0]["parse_status"] == ParseStatus.PARSING_DOC.value
    assert payload["stalled_versions"][0]["action"] == "POST /materials/{id}/retry"


def test_queue_stalled_ignores_records_within_threshold(
    cli_container: AppContainer,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """阈值内的新鲜记录不得被误报为滞留。"""
    _seed_stalled_practice(cli_container, minutes_ago=1)
    _seed_stalled_version(cli_container, minutes_ago=1)

    code, payload = _run(
        capsys,
        ["queue", "stalled", "--older-than-minutes", "15", "--json"],
    )

    assert code == EXIT_OK
    assert payload["total"] == 0


def test_queue_stalled_never_mutates_business_state(
    cli_container: AppContainer,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """巡检必须只读：不得改写练习状态或版本解析状态。"""
    practice_id = _seed_stalled_practice(cli_container, minutes_ago=60)
    version_id = _seed_stalled_version(cli_container, minutes_ago=60)

    _run(capsys, ["queue", "stalled", "--json"])

    with cli_container.get_session() as session:
        practice = (
            session.execute(select(Practice).where(Practice.id == practice_id)).scalars().one()
        )
        version = (
            session.execute(select(MaterialVersion).where(MaterialVersion.id == version_id))
            .scalars()
            .one()
        )

    assert practice.status == PracticeStatus.SUBMITTED.value
    assert practice.completed_at is None
    assert version.parse_status == ParseStatus.PARSING_DOC.value
