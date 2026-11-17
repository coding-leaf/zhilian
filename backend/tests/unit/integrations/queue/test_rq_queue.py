"""RQ queue dispatch and worker entry-point contracts."""

import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rq.job import JobStatus

from app.core.errors import PermissionDeniedError, QueueError
from app.integrations.queue.rq_adapter import RQQueueAdapter
from app.worker import (
    TERMINAL_FAILURE_CALLBACK,
    execute_registered_task,
    handle_job_terminal_failure,
)


def test_rq_enqueues_registered_task_only() -> None:
    client = MagicMock()
    adapter = RQQueueAdapter(redis_client=client, retry_limit=2)
    user_id = str(uuid.uuid4())
    payload = {
        "user_id": user_id,
        "material_id": str(uuid.uuid4()),
        "version_id": str(uuid.uuid4()),
    }

    with patch("app.integrations.queue.rq_adapter.Queue") as queue_class:
        task_id = adapter.enqueue("parse_material_pipeline", payload, user_id, task_id="known-id")

    assert task_id == "known-id"
    args, kwargs = queue_class.return_value.enqueue_call.call_args
    assert args == ("app.worker.execute_registered_task",)
    assert kwargs["args"] == ("parse_material_pipeline", payload, user_id)
    assert kwargs["meta"]["user_id"] == user_id
    assert kwargs["retry"].max == 2
    # 终态失败回写入口按受控模块路径注册，不反序列化任意客户端函数 (AC-9)
    assert kwargs["on_failure"].name == TERMINAL_FAILURE_CALLBACK

    with pytest.raises(QueueError, match="未注册"):
        adapter.enqueue("arbitrary_callable", payload, user_id)
    with pytest.raises(QueueError, match="用户"):
        adapter.enqueue("grading_jobs", payload, str(uuid.uuid4()))


def test_rq_status_and_cancel_enforce_task_owner() -> None:
    client = MagicMock()
    adapter = RQQueueAdapter(redis_client=client)
    job = MagicMock()
    job.meta = {"user_id": "owner"}
    job.get_status.return_value = JobStatus.QUEUED
    job.started_at = None
    job.ended_at = None

    with (
        patch("app.integrations.queue.rq_adapter.Job.fetch", return_value=job),
        patch("app.integrations.queue.rq_adapter.cancel_job") as cancel_job,
    ):
        result = adapter.get_status("job-id", "owner")
        assert result is not None and result.status == "pending"
        assert adapter.cancel("job-id", "owner") is True
        cancel_job.assert_called_once_with("job-id", connection=client)
        with pytest.raises(PermissionDeniedError):
            adapter.get_status("job-id", "other")


def test_worker_dispatches_with_fresh_session() -> None:
    user_id = uuid.uuid4()
    material_id = uuid.uuid4()
    version_id = uuid.uuid4()
    session = MagicMock()
    container = MagicMock()
    container.shutdown = AsyncMock()

    @contextmanager
    def session_context():
        yield session

    container.get_session.side_effect = session_context
    with patch("app.worker.AppContainer.create", return_value=container):
        execute_registered_task(
            "parse_material_pipeline",
            {
                "user_id": str(user_id),
                "material_id": str(material_id),
                "version_id": str(version_id),
            },
            str(user_id),
        )

    container.create_material_service.assert_called_once_with(session)
    container.create_material_service.return_value.parse_material_pipeline.assert_called_once_with(
        material_id=material_id, version_id=version_id, user_id=user_id
    )
    container.shutdown.assert_awaited_once()

    with pytest.raises(ValueError, match="未授权"):
        execute_registered_task("unknown", {"user_id": str(user_id)}, str(user_id))


def _make_job(
    *,
    task_name: str,
    payload: dict[str, str],
    user_id: str,
    should_retry: bool,
) -> SimpleNamespace:
    """构造最小 RQ 任务替身：仅暴露回调读取的 args / meta / should_retry / id。"""
    return SimpleNamespace(
        id="rq-job-1",
        args=(task_name, payload, user_id),
        meta={"user_id": user_id, "task_name": task_name},
        should_retry=should_retry,
    )


def _patch_container() -> tuple[Any, Any]:
    """打桩容器工厂，返回 (patcher 上下文, container 替身)。"""
    session = MagicMock()
    container = MagicMock()
    container.shutdown = AsyncMock()

    @contextmanager
    def session_context() -> Any:
        yield session

    container.get_session.side_effect = session_context
    return patch("app.worker.AppContainer.create", return_value=container), container


def test_terminal_failure_callback_marks_grading_recoverable() -> None:
    """重试耗尽的判题任务必须把业务记录回写为可恢复状态 (AC-9)."""
    user_id = uuid.uuid4()
    practice_id = uuid.uuid4()
    job = _make_job(
        task_name="grading_jobs",
        payload={"practice_id": str(practice_id), "user_id": str(user_id)},
        user_id=str(user_id),
        should_retry=False,
    )
    patcher, container = _patch_container()

    with patcher:
        handle_job_terminal_failure(job, MagicMock(), RuntimeError, RuntimeError("boom"), None)

    service = container.create_practice_service.return_value
    service.mark_grading_failed.assert_called_once_with(user_id, practice_id)
    container.shutdown.assert_awaited_once()


def test_terminal_failure_callback_skips_retryable_and_unknown_tasks() -> None:
    """仍会被重试的中间失败以及未知任务不得回写终态."""
    user_id = uuid.uuid4()
    practice_id = uuid.uuid4()
    patcher, container = _patch_container()

    with patcher:
        handle_job_terminal_failure(
            _make_job(
                task_name="grading_jobs",
                payload={"practice_id": str(practice_id), "user_id": str(user_id)},
                user_id=str(user_id),
                should_retry=True,
            ),
            MagicMock(),
            RuntimeError,
            RuntimeError("transient"),
            None,
        )
        handle_job_terminal_failure(
            _make_job(
                task_name="parse_material_pipeline",
                payload={"material_id": str(uuid.uuid4()), "version_id": str(uuid.uuid4())},
                user_id=str(user_id),
                should_retry=True,
            ),
            MagicMock(),
            RuntimeError,
            RuntimeError("transient parse"),
            None,
        )
        handle_job_terminal_failure(
            _make_job(
                task_name="unknown_task",
                payload={},
                user_id=str(user_id),
                should_retry=False,
            ),
            MagicMock(),
            RuntimeError,
            RuntimeError("unknown"),
            None,
        )

    container.create_practice_service.assert_not_called()
    container.create_material_service.assert_not_called()
    container.shutdown.assert_not_awaited()


def test_terminal_failure_callback_marks_orphaned_material_parse_failed() -> None:
    """重试耗尽或异常终止的资料解析任务必须兜底回写 FAILED (worker_terminated)."""
    user_id = uuid.uuid4()
    material_id = uuid.uuid4()
    version_id = uuid.uuid4()
    job = _make_job(
        task_name="parse_material_pipeline",
        payload={"material_id": str(material_id), "version_id": str(version_id)},
        user_id=str(user_id),
        should_retry=False,
    )
    patcher, container = _patch_container()

    with patcher:
        handle_job_terminal_failure(job, MagicMock(), TimeoutError, TimeoutError("timeout"), None)

    service = container.create_material_service.return_value
    service.mark_orphaned_parse_failed.assert_called_once_with(
        material_id=material_id,
        version_id=version_id,
        user_id=user_id,
        failed_stage="worker_terminated",
        error_message="后台解析任务异常终止 (TimeoutError)，请重新解析",
    )
    container.shutdown.assert_awaited_once()


def test_rq_has_active_job_inspects_queues_and_registries() -> None:
    """RQQueueAdapter.has_active_job 应检查队列与活跃注册表中的匹配任务。"""
    client = MagicMock()
    adapter = RQQueueAdapter(redis_client=client)
    version_id = str(uuid.uuid4())

    fake_queue = MagicMock()
    fake_queue.get_job_ids.return_value = ["job-1"]
    fake_queue.started_job_registry.get_job_ids.return_value = []
    fake_queue.scheduled_job_registry.get_job_ids.return_value = []
    fake_queue.deferred_job_registry.get_job_ids.return_value = []

    matching_job = SimpleNamespace(
        args=("parse_material_pipeline", {"version_id": version_id}, "u1")
    )
    with (
        patch("app.integrations.queue.rq_adapter.Queue", return_value=fake_queue),
        patch("app.integrations.queue.rq_adapter.Job.fetch_many", return_value=[matching_job]),
    ):
        assert adapter.has_active_job("parse_material_pipeline", {"version_id": version_id}) is True
        assert (
            adapter.has_active_job("parse_material_pipeline", {"version_id": str(uuid.uuid4())})
            is False
        )


def test_terminal_failure_callback_swallows_writeback_errors() -> None:
    """回写自身异常不得外溢到 RQ 的失败处理流程."""
    user_id = uuid.uuid4()
    practice_id = uuid.uuid4()
    job = _make_job(
        task_name="grading_jobs",
        payload={"practice_id": str(practice_id), "user_id": str(user_id)},
        user_id=str(user_id),
        should_retry=False,
    )
    patcher, container = _patch_container()
    container.create_practice_service.side_effect = RuntimeError("database down")

    with patcher:
        handle_job_terminal_failure(job, MagicMock(), RuntimeError, RuntimeError("boom"), None)

    container.shutdown.assert_awaited_once()
