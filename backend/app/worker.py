"""Restricted RQ job entry points and standalone worker process."""

import asyncio
import logging
import os
import uuid
from collections.abc import Callable
from typing import Any

from redis import Redis
from rq import Queue, SimpleWorker, Worker
from rq.job import Job

from app.container import AppContainer
from app.core.config import get_settings

if os.name == "nt":  # pragma: no cover - 平台分支，仅在 Windows 生效
    # RQ 2.12 的 `BaseRegistry.death_penalty_class` 被**硬编码**为 `UnixSignalDeathPenalty`
    # （rq/registry.py:40），绕过了 `get_default_death_penalty_class()` 的平台探测（该函数本身
    # 是会正确判断 `hasattr(signal, 'SIGALRM')` 的）。而 `clean_registries()` 构造各 Registry 时
    # 不传 override，于是必然取到这个硬编码值。
    #
    # 后果：Windows 上 registry 清理一旦遇到 abandoned job（worker 死掉时被弹出的任务），
    # 就会在失败回调里抛 `AttributeError: module 'signal' has no attribute 'SIGALRM'`；
    # 该异常从 `run_maintenance_tasks` 冒泡，**直接把 worker 打死**——而且此后每次启动都会在
    # 启动清理阶段重复崩溃，因为那个 abandoned job 还在。
    #
    # 这里按平台改回 `TimerDeathPenalty`（基于 `threading.Timer`，无平台依赖）。改基类即可覆盖
    # StartedJobRegistry / FinishedJobRegistry / FailedJobRegistry / DeferredJobRegistry 全部。
    from rq.registry import BaseRegistry
    from rq.timeouts import TimerDeathPenalty

    # mypy 依据 RQ 的类型标注推断该属性为 type[UnixSignalDeathPenalty]，此处为有意的跨平台替换。
    BaseRegistry.death_penalty_class = TimerDeathPenalty  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# RQ 失败回调入口的模块路径；仅按受控名称注册，不反序列化任意客户端函数
TERMINAL_FAILURE_CALLBACK = "app.worker.handle_job_terminal_failure"
# 失败回调自身的最长执行时间（秒），需覆盖一次短生命周期数据库事务
FAILURE_CALLBACK_TIMEOUT = 60


def _parse_material(container: AppContainer, payload: dict[str, str], user_id: uuid.UUID) -> None:
    with container.get_session() as session:
        container.create_material_service(session).parse_material_pipeline(
            material_id=uuid.UUID(payload["material_id"]),
            version_id=uuid.UUID(payload["version_id"]),
            user_id=user_id,
        )


def _grade_practice(container: AppContainer, payload: dict[str, str], user_id: uuid.UUID) -> None:
    with container.get_session() as session:
        container.create_grading_service(session).grade_practice_submission(
            practice_id=uuid.UUID(payload["practice_id"]),
            user_id=user_id,
        )


REGISTERED_TASKS: dict[str, Callable[[AppContainer, dict[str, str], uuid.UUID], None]] = {
    "parse_material_pipeline": _parse_material,
    "grading_jobs": _grade_practice,
}


def execute_registered_task(task_name: str, payload: dict[str, str], user_id: str) -> None:
    """Execute a server-owned job with a new container and database session."""
    handler = REGISTERED_TASKS.get(task_name)
    if handler is None or payload.get("user_id") != user_id:
        raise ValueError("未授权的后台任务或用户不匹配")
    container = AppContainer.create()
    try:
        handler(container, payload, uuid.UUID(user_id))
    finally:
        asyncio.run(container.shutdown())


def run_worker() -> None:
    """Consume priority and ordinary queues; scheduler activates delayed retries."""
    settings = get_settings()
    if settings.queue.provider != "redis":
        raise RuntimeError("worker 需要 ZHILIAN_QUEUE__PROVIDER=redis")
    connection = Redis.from_url(settings.redis.redis_url)
    queues = [Queue("zhilian_high", connection=connection), Queue("zhilian", connection=connection)]
    # Windows 没有 fork：`Worker.wait_for_horse` 调用 POSIX-only 的 `os.wait4`，
    # 而 `SpawnWorker` 只重写了 `fork_work_horse`、仍继承同一个 `wait_for_horse`，
    # 因此它在 Windows 上照样抛 `AttributeError: module 'os' has no attribute 'wait4'`。
    # 只有 `SimpleWorker` 派生自 `BaseWorker`、在同进程内执行任务，不触碰 fork/wait4。
    # 代价：同进程执行无法强杀超时任务，一个卡死的任务会阻塞整个 worker；
    # 解析流水线各外设调用自带超时，故接受此代价。
    worker_type = SimpleWorker if os.name == "nt" else Worker
    worker_type(queues, connection=connection).work(with_scheduler=True)


def _resolve_job_payload(job: Job) -> tuple[str, dict[str, str], str]:
    """从 RQ 任务参数中解析受控任务名、载荷与用户标识。

    Args:
        job: RQ 任务对象。

    Returns:
        tuple[str, dict[str, str], str]: (任务名, 载荷, 用户标识)；无法解析时均为空值。
    """
    raw_args = job.args if isinstance(job.args, (list, tuple)) else []
    task_name = ""
    payload: dict[str, str] = {}
    user_id = ""
    if len(raw_args) == 3:
        raw_name, raw_payload, raw_user = raw_args[0], raw_args[1], raw_args[2]
        if isinstance(raw_name, str):
            task_name = raw_name
        if isinstance(raw_payload, dict):
            payload = {str(key): str(value) for key, value in raw_payload.items()}
        if isinstance(raw_user, str):
            user_id = raw_user
    if not task_name:
        raw_meta_name = job.meta.get("task_name") if isinstance(job.meta, dict) else None
        task_name = raw_meta_name if isinstance(raw_meta_name, str) else ""
    return task_name, payload, user_id


def _mark_grading_failed(payload: dict[str, str], user_id: str) -> None:
    """以短生命周期会话回写判题任务终态失败，供用户可见并主动重试。"""
    practice_id = uuid.UUID(payload["practice_id"])
    container = AppContainer.create()
    try:
        with container.get_session() as session:
            container.create_practice_service(session).mark_grading_failed(
                uuid.UUID(user_id),
                practice_id,
            )
    finally:
        asyncio.run(container.shutdown())


def handle_job_terminal_failure(
    job: Job,
    connection: Redis,
    exc_type: type[BaseException] | None,
    exc_value: BaseException | None,
    exc_traceback: Any,
) -> None:
    """RQ 失败回调：仅在任务确定不再重试时回写可恢复的业务终态（AC-9）。

    RQ 在**每一次**失败时都会调用该回调（含仍会重试的中间失败），因此必须先用
    ``should_retry`` 判定后续是否仍会重试；只有重试已耗尽或任务被判定为终态失败时
    才回写，避免把仍在重试中的任务误标为失败。解析链路已在
    ``MaterialService.parse_material_pipeline`` / ``_enqueue_parse`` 内自行回写
    ``failed`` 终态，故此处只做运维日志；判题链路原本缺失回写，此处补齐。

    Args:
        job: 失败的 RQ 任务对象。
        connection: RQ 传给回调的 Redis 连接（本实现不使用）。
        exc_type: 失败异常类型。
        exc_value: 失败异常实例。
        exc_traceback: 失败异常回溯（RQ 在清理过期任务时传入栈帧列表）。
    """
    task_name, payload, user_id = _resolve_job_payload(job)
    exception_name = getattr(exc_type, "__name__", None) or "UnknownError"

    if getattr(job, "should_retry", False):
        logger.warning(
            "后台任务失败，RQ 将按退避策略重试: job_id=%s task=%s exception=%s",
            job.id,
            task_name or "unknown",
            exception_name,
        )
        return

    logger.error(
        "后台任务重试耗尽并进入终态失败: job_id=%s task=%s exception=%s",
        job.id,
        task_name or "unknown",
        exception_name,
    )

    if task_name != "grading_jobs" or not user_id or not payload.get("practice_id"):
        # 解析链路的失败回写由 MaterialService 内部负责，这里只保留运维日志
        return

    try:
        _mark_grading_failed(payload, user_id)
    except Exception:
        # 回写失败绝不能让 RQ 的失败处理流程抛出，仅保留可定位的运维日志
        logger.exception("判题失败状态回写异常: job_id=%s", job.id)


if __name__ == "__main__":
    run_worker()
