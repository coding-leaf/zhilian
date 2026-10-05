"""CLI 子命令处理器补测（M1-001 薄弱模块，mock 直测）。

覆盖目标（2026-10-04 权威口径下未覆盖行）：
- `app/cli/commands/grading.py`：`grading grade` / `diagnosis report` 成功输出；
- `app/cli/commands/db.py`：`db upgrade` / `db reset --yes` 成功路径；
- `app/cli/commands/practice.py`：`_parse_question_ids` / `_load_answers` 校验与三个 handler；
- `app/cli/commands/question.py`：`_first_knowledge_point_id` / `_parse_types` 与两个 handler；
- `app/cli/commands/material.py`：`_read_file` / `_resolve_target_version` 边界、
  `parse / status / tree` 成功与失败归因路径。

策略：处理器为纯编排函数，这里以显式 Fake 上下文 + Mock 服务直测，
覆盖成功路径与参数校验分支；完整链路另有 `test_smoke_offline.py` 端到端兜底。
"""

import argparse
import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.cli.commands.db import handle_reset, handle_upgrade
from app.cli.commands.grading import handle_diagnosis_report, handle_grade
from app.cli.commands.material import (
    _count_and_flatten,
    _parse_failure,
    _read_file,
    _resolve_target_version,
    handle_parse,
    handle_status,
    handle_tree,
)
from app.cli.commands.practice import (
    _load_answers,
    _parse_question_ids,
    handle_answer,
    handle_create,
    handle_submit,
)
from app.cli.commands.question import (
    _first_knowledge_point_id,
    _parse_types,
    handle_generate,
    handle_list,
)
from app.cli.errors import EXIT_ASSERTION, EXIT_OK, EXIT_RUNTIME, CliError
from app.cli.report import Reporter
from app.core.errors import AppError
from app.models.material import ParseStatus


class _FakeContext:
    """最小 CliContext 替身：container 为 Mock，provider 门禁恒通过。"""

    def __init__(self, container: Any) -> None:
        self.container = container
        self.db_url = "sqlite://"
        self.settings = SimpleNamespace()

    def assert_real_providers(self, require_ocr: bool = False) -> list[Any]:
        return []


def _container_with_session() -> MagicMock:
    container = MagicMock()
    container.get_session.return_value.__enter__.return_value = MagicMock()
    return container


class TestGradingHandlers:
    """`grading grade` 与 `diagnosis report`。"""

    def test_handle_grade_success_emits_summary(self, capsys: pytest.CaptureFixture[str]) -> None:
        """判题成功必须输出 practice_status / total_score / graded_items。"""
        practice_id = uuid.uuid4()
        summary = SimpleNamespace(
            practice_id=practice_id,
            status="graded",
            total_score=80.0,
            max_score=100.0,
            total_items=5,
            graded_items=5,
            pending_regrade_count=0,
        )
        container = _container_with_session()
        container.create_grading_service.return_value.grade_practice_submission.return_value = (
            summary
        )
        args = argparse.Namespace(user_id=str(uuid.uuid4()), practice_id=str(practice_id))

        code = handle_grade(args, _FakeContext(container), Reporter(json_mode=True))

        assert code == EXIT_OK
        payload = json.loads(capsys.readouterr().out)
        assert payload["command"] == "grading grade"
        assert payload["practice_status"] == "graded"
        assert payload["graded_items"] == 5

    def test_handle_diagnosis_report_success_emits_counts(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """诊断报告成功必须输出弱项/退步/建议计数（None 归一为 0）。"""
        report = SimpleNamespace(
            id=uuid.uuid4(),
            practice_id=uuid.uuid4(),
            score_rate=0.6,
            total_questions=10,
            unanswered_count=1,
            wrong_count=3,
            pending_regrade_count=0,
            weak_knowledge_points=[{"k": 1}],
            regressed_knowledge_points=None,
            actionable_suggestions=[{"s": 1}, {"s": 2}],
        )
        container = _container_with_session()
        container.create_diagnosis_service.return_value.generate_diagnosis_report.return_value = (
            report
        )
        args = argparse.Namespace(user_id=str(uuid.uuid4()), practice_id=str(report.practice_id))

        code = handle_diagnosis_report(args, _FakeContext(container), Reporter(json_mode=True))

        assert code == EXIT_OK
        payload = json.loads(capsys.readouterr().out)
        assert payload["command"] == "diagnosis report"
        assert payload["weak_knowledge_point_count"] == 1
        assert payload["regressed_knowledge_point_count"] == 0
        assert payload["suggestion_count"] == 2


class TestDbHandlers:
    """`db upgrade` 与 `db reset`（Alembic 命令以 monkeypatch 替身）。"""

    def test_handle_upgrade_invokes_alembic_and_emits_revision(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """upgrade 必须调用 alembic upgrade head 并输出脱敏后的 revision。"""
        calls: list[tuple[Any, str]] = []
        monkeypatch.setattr("app.cli.commands.db._configure_alembic", lambda url: "alembic-config")
        monkeypatch.setattr(
            "app.cli.commands.db.command.upgrade",
            lambda config, revision: calls.append((config, revision)),
        )
        context = _FakeContext(MagicMock())
        context.db_revision = lambda: "rev-head"  # type: ignore[method-assign]

        code = handle_upgrade(argparse.Namespace(), context, Reporter(json_mode=True))

        assert code == EXIT_OK
        assert calls == [("alembic-config", "head")]
        payload = json.loads(capsys.readouterr().out)
        assert payload["revision"] == "rev-head"
        assert payload["database_url"] == "sqlite://"

    def test_handle_reset_requires_yes(self) -> None:
        """缺少 --yes 必须拒绝并抛退出码 1 的 CliError。"""
        context = _FakeContext(MagicMock())
        with pytest.raises(CliError) as exc_info:
            handle_reset(argparse.Namespace(yes=False), context, Reporter(json_mode=True))
        assert exc_info.value.exit_code == EXIT_RUNTIME
        assert "--yes" in exc_info.value.remediation

    def test_handle_reset_confirmed_runs_downgrade_then_upgrade(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """确认后必须 downgrade base -> upgrade head 并输出 revision。"""
        order: list[str] = []
        monkeypatch.setattr("app.cli.commands.db._configure_alembic", lambda url: "cfg")
        monkeypatch.setattr(
            "app.cli.commands.db.command.downgrade",
            lambda config, revision: order.append(f"down:{revision}"),
        )
        monkeypatch.setattr(
            "app.cli.commands.db.command.upgrade",
            lambda config, revision: order.append(f"up:{revision}"),
        )
        context = _FakeContext(MagicMock())
        context.db_revision = lambda: "rev-1"  # type: ignore[method-assign]

        code = handle_reset(argparse.Namespace(yes=True), context, Reporter(json_mode=True))

        assert code == EXIT_OK
        assert order == ["down:base", "up:head"]
        payload = json.loads(capsys.readouterr().out)
        assert payload["command"] == "db reset"


class TestPracticeHelpers:
    """`practice` 命令参数解析。"""

    def test_parse_question_ids_accepts_csv_with_spaces(self) -> None:
        """CSV 中的空白项被忽略，合法项全部解析。"""
        first, second = uuid.uuid4(), uuid.uuid4()
        result = _parse_question_ids(f" {first} , {second} ,")
        assert result == [first, second]

    def test_parse_question_ids_empty_raises(self) -> None:
        """全空输入必须抛退出码 2 的 CliError。"""
        with pytest.raises(CliError) as exc_info:
            _parse_question_ids(" , , ")
        assert exc_info.value.exit_code == EXIT_ASSERTION

    def test_load_answers_none_returns_empty_dict(self) -> None:
        """未传 --answers 返回空字典。"""
        assert _load_answers(None) == {}

    def test_load_answers_invalid_json_raises_with_details(self) -> None:
        """非法 JSON 必须抛 CliError 且 details 保留解析错误。"""
        with pytest.raises(CliError) as exc_info:
            _load_answers("{not-json")
        assert exc_info.value.exit_code == EXIT_ASSERTION
        assert "error" in exc_info.value.details

    def test_load_answers_non_object_raises(self) -> None:
        """JSON 数组不是合法作答映射，必须拒绝。"""
        with pytest.raises(CliError) as exc_info:
            _load_answers('["A", "B"]')
        assert exc_info.value.exit_code == EXIT_ASSERTION

    def test_load_answers_coerces_keys_and_values_to_str(self) -> None:
        """键与值统一转为字符串。"""
        result = _load_answers('{"q1": 1, "q2": true}')
        assert result == {"q1": "1", "q2": "True"}


class TestPracticeHandlers:
    """`practice create / answer / submit` 成功路径。"""

    def test_handle_create_assembles_practice_from_questions(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """create 必须以题目反推考点与资料并组卷。"""
        user_id = uuid.uuid4()
        qid1, qid2 = uuid.uuid4(), uuid.uuid4()
        knowledge_point_id = uuid.uuid4()
        material_id = uuid.uuid4()
        question = SimpleNamespace(
            knowledge_point_id=knowledge_point_id,
            material_id=material_id,
            question_type="single_choice",
        )
        container = _container_with_session()
        question_service = container.create_question_service.return_value
        question_service.get_question.return_value = question
        practice = SimpleNamespace(
            id=uuid.uuid4(),
            material_id=material_id,
            status="in_progress",
            question_count=2,
            ordered_question_ids=[str(qid1), str(qid2)],
        )
        container.create_practice_service.return_value.create_practice.return_value = practice
        args = argparse.Namespace(
            user_id=str(user_id),
            question_ids=f"{qid1},{qid2}",
            material_id=None,
            title="CLI 练习",
        )

        code = handle_create(args, _FakeContext(container), Reporter(json_mode=True))

        assert code == EXIT_OK
        payload = json.loads(capsys.readouterr().out)
        assert payload["practice_status"] == "in_progress"
        assert payload["ordered_question_ids"] == [str(qid1), str(qid2)]

    def test_handle_answer_saves_and_reports_item(self, capsys: pytest.CaptureFixture[str]) -> None:
        """answer 暂存后必须输出 attempt_item_id 与 is_answered。"""
        item = SimpleNamespace(id=uuid.uuid4(), is_answered=True)
        container = _container_with_session()
        container.create_practice_service.return_value.save_answer.return_value = item
        args = argparse.Namespace(
            user_id=str(uuid.uuid4()),
            practice_id=str(uuid.uuid4()),
            question_id=str(uuid.uuid4()),
            answer="A",
        )

        code = handle_answer(args, _FakeContext(container), Reporter(json_mode=True))

        assert code == EXIT_OK
        payload = json.loads(capsys.readouterr().out)
        assert payload["attempt_item_id"] == str(item.id)
        assert payload["is_answered"] is True

    def test_handle_submit_saves_batch_answers_before_submitting(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """submit 必须先逐题暂存批量作答，再交卷。"""
        user_id = uuid.uuid4()
        practice_id = uuid.uuid4()
        qid = uuid.uuid4()
        container = _container_with_session()
        practice_service = container.create_practice_service.return_value
        practice_service.submit_practice.return_value = SimpleNamespace(
            practice_id=practice_id,
            task_id="task-1",
            status="submitted",
            total_questions=1,
            answered_questions=1,
            unanswered_count=0,
            submitted_at="2026-10-04T20:00:00+08:00",
        )
        container = _container_with_session()
        container.create_practice_service.return_value = practice_service
        args = argparse.Namespace(
            user_id=str(user_id),
            practice_id=str(practice_id),
            answers=json.dumps({str(qid): "B"}),
        )

        code = handle_submit(args, _FakeContext(container), Reporter(json_mode=True))

        assert code == EXIT_OK
        practice_service.save_answer.assert_called_once()
        assert practice_service.save_answer.call_args.args[0] == user_id
        assert practice_service.save_answer.call_args.kwargs["practice_id"] == practice_id
        assert practice_service.save_answer.call_args.kwargs["user_answer"] == "B"
        payload = json.loads(capsys.readouterr().out)
        assert payload["task_id"] == "task-1"


class TestQuestionHelpers:
    """`question` 命令的辅助函数。"""

    def test_first_knowledge_point_id_prefers_deepest_leaf(self) -> None:
        """有 children 时深度优先取叶子节点 id。"""
        roots = [
            {"id": "root-1", "children": [{"id": "leaf-1", "children": []}]},
            {"id": "root-2"},
        ]
        assert _first_knowledge_point_id(roots) == "leaf-1"

    def test_first_knowledge_point_id_skips_nodes_without_id(self) -> None:
        """节点无 id 时跳过，取后续可用 id。"""
        roots: list[dict[str, Any]] = [{"children": []}, {"id": None}, {"id": "usable"}]
        assert _first_knowledge_point_id(roots) == "usable"

    def test_first_knowledge_point_id_returns_none_for_empty_tree(self) -> None:
        """空树返回 None。"""
        assert _first_knowledge_point_id([]) is None

    def test_parse_types_none_and_blank_return_none(self) -> None:
        """未传或全空白时返回 None（交由服务默认值处理）。"""
        assert _parse_types(None) is None
        assert _parse_types(" , ") is None

    def test_parse_types_returns_tuple(self) -> None:
        """合法 CSV 返回去空白元组。"""
        assert _parse_types("single_choice, multiple_choice") == (
            "single_choice",
            "multiple_choice",
        )


class TestQuestionHandlers:
    """`question generate / list` 成功与失败路径。"""

    def test_handle_generate_success_emits_question_ids(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """生成成功必须输出 batch 与合格题目 id 列表。"""
        knowledge_point_id = uuid.uuid4()
        question_id = uuid.uuid4()
        container = _container_with_session()
        container.create_knowledge_service.return_value.get_knowledge_tree.return_value = [
            {"id": str(knowledge_point_id)}
        ]
        container.create_question_service.return_value.generate_questions.return_value = (
            SimpleNamespace(
                material_id=uuid.uuid4(),
                version_id=uuid.uuid4(),
                knowledge_point_id=knowledge_point_id,
                batch_id="batch-1",
                total_generated=3,
                qualified_questions=[SimpleNamespace(id=question_id)],
                pending_questions=[],
            )
        )
        args = argparse.Namespace(
            user_id=str(uuid.uuid4()),
            material_id=str(uuid.uuid4()),
            version_id=None,
            knowledge_point_id=None,
            types=None,
            count=5,
        )

        code = handle_generate(args, _FakeContext(container), Reporter(json_mode=True))

        assert code == EXIT_OK
        payload = json.loads(capsys.readouterr().out)
        assert payload["question_ids"] == [str(question_id)]
        assert payload["qualified_count"] == 1

    def test_handle_generate_empty_tree_raises(
        self,
    ) -> None:
        """知识树为空且未显式给考点时必须抛出退出码 2。"""
        container = _container_with_session()
        container.create_knowledge_service.return_value.get_knowledge_tree.return_value = []
        args = argparse.Namespace(
            user_id=str(uuid.uuid4()),
            material_id=str(uuid.uuid4()),
            version_id=None,
            knowledge_point_id=None,
            types=None,
            count=5,
        )
        with pytest.raises(CliError) as exc_info:
            handle_generate(args, _FakeContext(container), Reporter(json_mode=True))
        assert exc_info.value.exit_code == EXIT_ASSERTION

    def test_handle_generate_no_qualified_questions_raises(self) -> None:
        """生成结果无合格题目时必须抛出退出码 2 并保留批次信息。"""
        container = _container_with_session()
        container.create_knowledge_service.return_value.get_knowledge_tree.return_value = [
            {"id": str(uuid.uuid4())}
        ]
        container.create_question_service.return_value.generate_questions.return_value = (
            SimpleNamespace(
                material_id=uuid.uuid4(),
                version_id=uuid.uuid4(),
                knowledge_point_id=uuid.uuid4(),
                batch_id="batch-2",
                total_generated=3,
                qualified_questions=[],
                pending_questions=[],
            )
        )
        args = argparse.Namespace(
            user_id=str(uuid.uuid4()),
            material_id=str(uuid.uuid4()),
            version_id=None,
            knowledge_point_id=None,
            types=None,
            count=5,
        )
        with pytest.raises(CliError) as exc_info:
            handle_generate(args, _FakeContext(container), Reporter(json_mode=True))
        assert exc_info.value.exit_code == EXIT_ASSERTION
        assert exc_info.value.details["batch_id"] == "batch-2"

    def test_handle_generate_uses_explicit_knowledge_point(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """显式 --knowledge-point-id 时必须跳过知识树查询。"""
        knowledge_point_id = uuid.uuid4()
        container = _container_with_session()
        container.create_question_service.return_value.generate_questions.return_value = (
            SimpleNamespace(
                material_id=uuid.uuid4(),
                version_id=uuid.uuid4(),
                knowledge_point_id=knowledge_point_id,
                batch_id="batch-3",
                total_generated=1,
                qualified_questions=[SimpleNamespace(id=uuid.uuid4())],
                pending_questions=[],
            )
        )
        args = argparse.Namespace(
            user_id=str(uuid.uuid4()),
            material_id=str(uuid.uuid4()),
            version_id=str(uuid.uuid4()),
            knowledge_point_id=str(knowledge_point_id),
            types="single_choice",
            count=1,
        )

        code = handle_generate(args, _FakeContext(container), Reporter(json_mode=True))

        assert code == EXIT_OK
        container.create_knowledge_service.return_value.get_knowledge_tree.assert_not_called()

    def test_handle_list_emits_question_summaries(self, capsys: pytest.CaptureFixture[str]) -> None:
        """list 必须输出题目摘要（含 status/stem）与总数。"""
        question = SimpleNamespace(
            id=uuid.uuid4(),
            knowledge_point_id=uuid.uuid4(),
            question_type="single_choice",
            status="ready",
            difficulty="easy",
            stem="题干",
        )
        container = _container_with_session()
        container.create_question_service.return_value.list_questions.return_value = (
            [question],
            1,
        )
        args = argparse.Namespace(user_id=str(uuid.uuid4()), material_id=str(uuid.uuid4()))

        code = handle_list(args, _FakeContext(container), Reporter(json_mode=True))

        assert code == EXIT_OK
        payload = json.loads(capsys.readouterr().out)
        assert payload["total"] == 1
        assert payload["questions"][0]["stem"] == "题干"


class TestMaterialHelpers:
    """`material` 命令的文件读取与版本解析。"""

    def test_read_file_success_returns_bytes(self, tmp_path: Path) -> None:
        """存在文件返回原始字节。"""
        target = tmp_path / "notes.txt"
        target.write_text("讲义内容", encoding="utf-8")
        assert _read_file(str(target)) == "讲义内容".encode()

    def test_read_file_missing_raises(self, tmp_path: Path) -> None:
        """文件不存在抛退出码 2 的 CliError。"""
        with pytest.raises(CliError) as exc_info:
            _read_file(str(tmp_path / "missing.txt"))
        assert exc_info.value.exit_code == EXIT_ASSERTION
        assert "资料文件不存在" in exc_info.value.message

    def test_read_file_os_error_normalized(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """读取抛 OSError 归一化为 CliError（details 保留底层错误）。"""
        target = tmp_path / "locked.txt"
        target.write_text("内容", encoding="utf-8")

        def _raise(self: Path) -> bytes:
            raise OSError("device not ready")

        monkeypatch.setattr(Path, "read_bytes", _raise)
        with pytest.raises(CliError) as exc_info:
            _read_file(str(target))
        assert exc_info.value.exit_code == EXIT_ASSERTION
        assert exc_info.value.details["error"] == "device not ready"

    def test_resolve_target_version_defaults_to_latest(self) -> None:
        """未指定 version_id 时返回列表首个（最新）版本。"""
        latest = SimpleNamespace(id=uuid.uuid4())
        service = MagicMock()
        service.list_material_versions.return_value = [latest, SimpleNamespace(id=uuid.uuid4())]

        result = _resolve_target_version(service, uuid.uuid4(), uuid.uuid4(), None)

        assert result is latest

    def test_resolve_target_version_finds_specified(self) -> None:
        """指定 version_id 时精确匹配返回。"""
        target = SimpleNamespace(id=uuid.uuid4())
        service = MagicMock()
        service.list_material_versions.return_value = [SimpleNamespace(id=uuid.uuid4()), target]

        result = _resolve_target_version(service, uuid.uuid4(), uuid.uuid4(), target.id)

        assert result is target

    def test_resolve_target_version_empty_raises(self) -> None:
        """无任何版本时抛 CliError（提示核对 --material-id）。"""
        service = MagicMock()
        service.list_material_versions.return_value = []

        with pytest.raises(CliError) as exc_info:
            _resolve_target_version(service, uuid.uuid4(), uuid.uuid4(), None)

        assert exc_info.value.exit_code == EXIT_ASSERTION
        assert "不存在可用版本" in exc_info.value.message

    def test_resolve_target_version_mismatch_raises(self) -> None:
        """指定版本不在列表中时抛 CliError（提示核对 --version-id）。"""
        service = MagicMock()
        service.list_material_versions.return_value = [SimpleNamespace(id=uuid.uuid4())]

        with pytest.raises(CliError) as exc_info:
            _resolve_target_version(service, uuid.uuid4(), uuid.uuid4(), uuid.uuid4())

        assert exc_info.value.exit_code == EXIT_ASSERTION
        assert "--version-id" in (exc_info.value.remediation or "")


class TestMaterialHandlers:
    """`material parse / status / tree` 成功与失败路径。"""

    def test_handle_parse_success_emits_ready_state(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """解析完成且终态 READY 时输出 ok 与版本状态。"""
        version = SimpleNamespace(
            id=uuid.uuid4(), parse_status=ParseStatus.READY.value, is_active=True
        )
        container = _container_with_session()
        service = container.create_material_service.return_value
        service.list_material_versions.return_value = [version]
        args = argparse.Namespace(
            user_id=str(uuid.uuid4()), material_id=str(uuid.uuid4()), version_id=None
        )

        code = handle_parse(args, _FakeContext(container), Reporter(json_mode=True))

        assert code == EXIT_OK
        service.parse_material_pipeline.assert_called_once()
        payload = json.loads(capsys.readouterr().out)
        assert payload["parse_status"] == ParseStatus.READY.value

    def test_handle_parse_not_ready_raises_with_failure_details(self) -> None:
        """终态非 READY 时抛 CliError 并携带 failed_stage/error_message。"""
        failed_version = SimpleNamespace(
            id=uuid.uuid4(),
            parse_status="failed",
            failed_stage="ocr",
            error_message="ocr provider 超时",
        )
        container = _container_with_session()
        service = container.create_material_service.return_value
        service.list_material_versions.return_value = [failed_version]
        args = argparse.Namespace(
            user_id=str(uuid.uuid4()), material_id=str(uuid.uuid4()), version_id=None
        )

        with pytest.raises(CliError) as exc_info:
            handle_parse(args, _FakeContext(container), Reporter(json_mode=True))

        assert exc_info.value.exit_code == EXIT_ASSERTION
        assert exc_info.value.details["failed_stage"] == "ocr"
        assert exc_info.value.details["error_message"] == "ocr provider 超时"

    def test_handle_parse_app_error_maps_to_cli_error_with_stage(self) -> None:
        """解析抛 AppError 时经 _parse_failure 归因（阶段来自版本现场）。"""
        version = SimpleNamespace(id=uuid.uuid4(), parse_status="parsing")
        container = _container_with_session()
        service = container.create_material_service.return_value
        service.list_material_versions.return_value = [version]
        service.parse_material_pipeline.side_effect = AppError(error_code=30010, message="解析炸了")
        service.repo.get_version_by_id.return_value = SimpleNamespace(
            failed_stage="chunking", error_message="chunk 失败", parse_status="failed"
        )
        args = argparse.Namespace(
            user_id=str(uuid.uuid4()), material_id=str(uuid.uuid4()), version_id=None
        )

        with pytest.raises(CliError) as exc_info:
            handle_parse(args, _FakeContext(container), Reporter(json_mode=True))

        assert exc_info.value.exit_code == EXIT_ASSERTION
        assert exc_info.value.details["error_code"] == 30010
        assert exc_info.value.details["failed_stage"] == "chunking"

    def test_parse_failure_without_version_falls_back_to_exc_message(self) -> None:
        """版本现场缺失时 details 退化为异常消息（不伪造阶段信息）。"""
        service = MagicMock()
        service.repo.get_version_by_id.return_value = None
        exc = AppError(error_code=30011, message="流水线崩溃")

        error = _parse_failure(service, uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), exc)

        assert error.details["error_message"] == "流水线崩溃"
        assert "failed_stage" not in error.details

    def test_handle_status_emits_material_and_versions(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """status 必须输出资料概要 + 全部版本明细。"""
        material_id = uuid.uuid4()
        material = SimpleNamespace(
            id=material_id,
            title="线性表讲义",
            file_format="txt",
            status="ready",
            parse_status="ready",
            progress_percentage=100,
            current_version_id=None,
        )
        version = SimpleNamespace(
            id=uuid.uuid4(),
            version_number=1,
            parse_status="ready",
            failed_stage=None,
            error_message=None,
            is_active=True,
        )
        container = _container_with_session()
        service = container.create_material_service.return_value
        service.get_material_detail.return_value = material
        service.list_material_versions.return_value = [version]
        args = argparse.Namespace(user_id=str(uuid.uuid4()), material_id=str(material_id))

        code = handle_status(args, _FakeContext(container), Reporter(json_mode=True))

        assert code == EXIT_OK
        payload = json.loads(capsys.readouterr().out)
        assert payload["title"] == "线性表讲义"
        assert payload["versions"][0]["version_number"] == 1

    def test_count_and_flatten_recurses_and_skips_invalid_ids(self) -> None:
        """递归统计节点并扁平化合法 id；非法 id 计入数量但不入列表。"""
        count, ids = _count_and_flatten(
            [
                {"id": "kp-1", "children": [{"children": [{"id": "kp-2"}]}]},
                {"no_id": True},
            ]
        )
        assert count == 4
        assert ids == ["kp-1", "kp-2"]

    def test_handle_tree_emits_flattened_ids(self, capsys: pytest.CaptureFixture[str]) -> None:
        """tree 必须输出节点总数与扁平化 id 列表并保留原树。"""
        roots = [{"id": "kp-1", "children": [{"id": "kp-2", "children": []}]}]
        container = _container_with_session()
        container.create_knowledge_service.return_value.get_knowledge_tree.return_value = roots
        args = argparse.Namespace(
            user_id=str(uuid.uuid4()), material_id=str(uuid.uuid4()), version_id=None
        )

        code = handle_tree(args, _FakeContext(container), Reporter(json_mode=True))

        assert code == EXIT_OK
        payload = json.loads(capsys.readouterr().out)
        assert payload["point_count"] == 2
        assert payload["knowledge_point_ids"] == ["kp-1", "kp-2"]
        assert payload["tree"] == roots
