"""`smoke` 子命令离线编排单元测试（内存 SQLite + fake provider，零联网）。

覆盖用例：
- UT-SMOKE-01：fake 配置且未 `--allow-fake` 时以退出码 3 于 preflight 中止，绝不执行任何业务；
- UT-SMOKE-02：基础设施不可达时以退出码 4 于 preflight 中止，并指出不可达组件；
- UT-SMOKE-03：`--allow-fake` 下编排逐阶段运行，解析断言失败返回退出码 2 且精确归因；
- UT-SMOKE-04：`--allow-fake` + 预置结构化 LLM 响应时全链路 11 阶段全绿，退出码 0。

说明：`main()` 每次调用都会自建 `CliContext`，这里显式注入一个跨调用共享的
`AppContainer`（内存 SQLite StaticPool + memory storage + fake provider），
以复用同一份内存数据；LLM 通过 `FakeLLMAdapter` 预置结构化响应实现确定性闭环。
"""

import json
from collections.abc import Iterator
from typing import Any, cast

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.cli.context import CliContext
from app.cli.errors import EXIT_ASSERTION, EXIT_CONFIG, EXIT_INFRA, EXIT_OK
from app.cli.main import main
from app.container import AppContainer
from app.core.config import get_settings
from app.integrations.container import ProviderRegistry
from app.integrations.llm.fake import FakeLLMAdapter
from app.models.base import Base
from app.models.question import QuestionType
from app.services.grading import LLMGradingOutput
from app.services.knowledge import (
    ExtractedKnowledgeItem,
    KnowledgeExtractionOutput,
)
from app.services.question import (
    LLMGeneratedQuestionItem,
    LLMQuestionBatchOutput,
    LLMQuestionOptionItem,
)


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


def _seed_full_chain_llm(container: AppContainer) -> None:
    """向 fake LLM 预置能通过质检门禁的结构化知识点、题目与判题响应。"""
    llm = cast(FakeLLMAdapter, container.providers.llm)

    knowledge = KnowledgeExtractionOutput(
        knowledge_points=[
            ExtractedKnowledgeItem(
                temp_id="kp_1",
                parent_temp_id=None,
                name="线性表",
                description="顺序存储使用连续内存",
                level=1,
                chapter_title="第一章 线性表",
                source_snippet_indices=[0],
            ),
            ExtractedKnowledgeItem(
                temp_id="kp_2",
                parent_temp_id="kp_1",
                name="栈与队列",
                description="后进先出",
                level=2,
                chapter_title="第二章 栈与队列",
                source_snippet_indices=[2],
            ),
            ExtractedKnowledgeItem(
                temp_id="kp_3",
                parent_temp_id="kp_2",
                name="二叉树",
                description="前序遍历按",
                level=3,
                chapter_title="第三章 树与二叉树",
                source_snippet_indices=[3],
            ),
        ]
    )
    llm.set_canned_response("你是一个专业的考纲分析与知识图谱构建专家", knowledge.model_dump_json())

    questions = LLMQuestionBatchOutput(
        questions=[
            LLMGeneratedQuestionItem(
                question_type=QuestionType.SINGLE_CHOICE.value,
                stem="二叉树每个结点最多有两个子结点？",
                options=[
                    LLMQuestionOptionItem(key="A", content="正确"),
                    LLMQuestionOptionItem(key="B", content="错误"),
                    LLMQuestionOptionItem(key="C", content="部分正确"),
                    LLMQuestionOptionItem(key="D", content="无法判断"),
                ],
                answer="A",
                analysis="二叉树每个结点最多有两个子结点。",
                difficulty=3,
                source_snippet_index=0,
            ),
            LLMGeneratedQuestionItem(
                question_type=QuestionType.MULTIPLE_CHOICE.value,
                stem="前序遍历按“根、左、右”访问？",
                options=[
                    LLMQuestionOptionItem(key="A", content="前序遍历先访问根"),
                    LLMQuestionOptionItem(key="B", content="前序遍历再访问左子树"),
                    LLMQuestionOptionItem(key="C", content="中序遍历先访问根"),
                ],
                answer="A,B",
                analysis="前序遍历按根、左、右的顺序访问。",
                difficulty=3,
                source_snippet_index=0,
            ),
            LLMGeneratedQuestionItem(
                question_type=QuestionType.SHORT_ANSWER.value,
                stem="平衡二叉树通过旋转维持树高平衡？",
                options=[],
                answer="平衡二叉树通过旋转维持树高平衡。",
                analysis="平衡二叉树通过旋转维持树高平衡。",
                difficulty=3,
                source_snippet_index=0,
            ),
        ]
    )
    llm.set_canned_response("你是一名资深教育命题专家", questions.model_dump_json())
    llm.set_canned_structured_response(
        LLMGradingOutput,
        LLMGradingOutput(score=8.0, confidence=0.92, feedback="回答准确，要点清晰"),
    )


def test_smoke_config_gap_stops_before_business(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """未 `--allow-fake` 时 preflight 以退出码 3 中止，且不执行任何业务阶段。"""
    code, payload = _run(capsys, ["smoke", "--json"])

    assert code == EXIT_CONFIG
    assert payload["status"] == "failed"
    assert payload["failed_stage"] == "preflight"
    assert payload["exit_code"] == EXIT_CONFIG
    assert payload["entities"] == {}
    assert [stage["name"] for stage in payload["stages"]] == ["preflight"]
    components = {gap["component"] for gap in payload["details"]["gaps"]}
    assert {"llm", "embedding", "search", "storage", "database"} <= components


def test_smoke_infra_unreachable_exits_4(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """基础设施不可达时以退出码 4 中止，并指出不可达组件。"""
    monkeypatch.setattr(CliContext, "assert_real_providers", lambda self, require_ocr=False: [])
    monkeypatch.setattr(
        CliContext,
        "probe_infra",
        lambda self: {
            "database": {"reachable": False, "detail": "connection refused"},
            "redis": {"reachable": True, "detail": "ping ok"},
            "minio": {"reachable": True, "detail": "tcp open"},
        },
    )

    code, payload = _run(capsys, ["smoke", "--json"])

    assert code == EXIT_INFRA
    assert payload["failed_stage"] == "preflight"
    assert payload["entities"] == {}
    assert "database" in payload["details"]["unreachable"]


def test_smoke_allow_fake_reports_failed_stage(
    cli_container: AppContainer,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--allow-fake` 下编排逐阶段运行，解析断言失败精确归因并返回退出码 2。"""
    code, payload = _run(capsys, ["smoke", "--json", "--allow-fake"])

    assert code == EXIT_ASSERTION
    assert payload["status"] == "failed"
    assert payload["failed_stage"] == "parse"
    assert payload["exit_code"] == EXIT_ASSERTION
    assert payload["error"]
    assert payload["entities"]["user_id"]
    assert payload["entities"]["material_id"]
    stage_names = [stage["name"] for stage in payload["stages"]]
    assert stage_names == ["preflight", "login", "import", "parse"]
    failed = payload["stages"][-1]
    assert failed["status"] == "failed"
    assert failed["error"]


def test_smoke_offline_full_chain_success(
    cli_container: AppContainer,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """预置结构化 LLM 响应后，全链路 11 阶段全绿并返回退出码 0。"""
    _seed_full_chain_llm(cli_container)

    code, payload = _run(capsys, ["smoke", "--json", "--allow-fake"])

    assert code == EXIT_OK, json.dumps(payload, ensure_ascii=False)
    assert payload["status"] == "ok"
    assert payload["exit_code"] == EXIT_OK
    assert "failed_stage" not in payload
    assert payload["ocr_leg"] == "skipped"

    stage_names = [stage["name"] for stage in payload["stages"]]
    assert stage_names == [
        "preflight",
        "login",
        "import",
        "parse",
        "snippets",
        "tree",
        "questions",
        "practice",
        "grading",
        "report",
        "summary",
    ]
    assert all(stage["status"] == "ok" for stage in payload["stages"])

    entities = payload["entities"]
    assert entities["user_id"]
    assert entities["material_id"]
    assert entities["version_id"]
    assert entities["knowledge_point_id"]
    assert entities["practice_id"]
    assert entities["report_id"]
    assert entities["parse_status"] == "ready"
    assert entities["snippet_count"] > 0
    assert entities["question_count"] > 0
