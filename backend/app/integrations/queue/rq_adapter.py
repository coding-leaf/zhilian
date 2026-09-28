"""RQ-backed implementation of the application task queue contract."""

import uuid
from datetime import timedelta
from typing import Any

from redis import Redis
from rq import Callback, Queue, Retry, cancel_job
from rq.exceptions import NoSuchJobError
from rq.job import Job

from app.core.errors import PermissionDeniedError, QueueError
from app.integrations.queue.protocol import REGISTERED_TASK_NAMES, QueueProtocol, TaskResult
from app.integrations.queue.redis import _mask_redis_url

DEFAULT_QUEUE = "zhilian"
HIGH_QUEUE = "zhilian_high"
TASK_ENTRY = "app.worker.execute_registered_task"
# 失败回调按受控模块路径注册，worker 端按名称重新导入，不反序列化任意客户端函数
TERMINAL_FAILURE_CALLBACK = "app.worker.handle_job_terminal_failure"
FAILURE_CALLBACK_TIMEOUT = 60


class RQQueueAdapter(QueueProtocol):
    """Submit only registered jobs and expose tenant-checked RQ status."""

    def __init__(
        self,
        *,
        redis_url: str | None = None,
        redis_client: Redis | None = None,
        retry_limit: int = 3,
        job_timeout: int = 1800,
    ) -> None:
        self._url = _mask_redis_url(redis_url)
        self._client = redis_client or Redis.from_url(redis_url or "redis://localhost:6379/0")
        self._retry_limit = max(0, retry_limit)
        self._job_timeout = job_timeout

    def enqueue(
        self,
        task_name: str,
        payload: dict[str, Any],
        user_id: str,
        *,
        task_id: str | None = None,
        delay_seconds: int = 0,
        priority: int = 0,
    ) -> str:
        if task_name not in REGISTERED_TASK_NAMES:
            raise QueueError(f"未注册的后台任务: {task_name}")
        if payload.get("user_id") != user_id:
            raise QueueError("任务用户与载荷用户不一致")
        if delay_seconds < 0 or priority < 0:
            raise QueueError("任务延迟和优先级不得为负数")
        resolved_id = task_id or str(uuid.uuid4())
        queue = Queue(HIGH_QUEUE if priority else DEFAULT_QUEUE, connection=self._client)
        options: dict[str, Any] = {
            "job_id": resolved_id,
            "meta": {"user_id": user_id, "task_name": task_name},
            "retry": Retry(
                max=self._retry_limit,
                interval=[min(10 * 3**i, 300) for i in range(self._retry_limit)],
            )
            if self._retry_limit
            else None,
            # 重试耗尽后的终态失败回写入口（AC-9）：仅注册受控模块路径
            "on_failure": Callback(TERMINAL_FAILURE_CALLBACK, timeout=FAILURE_CALLBACK_TIMEOUT),
            "failure_ttl": 86400 * 7,
            "result_ttl": 86400,
        }
        try:
            if delay_seconds:
                queue.enqueue_in(
                    timedelta(seconds=delay_seconds),
                    TASK_ENTRY,
                    task_name,
                    payload,
                    user_id,
                    job_timeout=self._job_timeout,
                    **options,
                )
            else:
                queue.enqueue_call(
                    TASK_ENTRY,
                    args=(task_name, payload, user_id),
                    timeout=self._job_timeout,
                    **options,
                )
        except Exception as exc:
            raise QueueError("后台任务入队失败") from exc
        return resolved_id

    def _get_job(self, task_id: str, user_id: str) -> Job | None:
        try:
            job = Job.fetch(task_id, connection=self._client)
        except NoSuchJobError:
            return None
        except Exception as exc:
            raise QueueError("后台任务状态查询失败") from exc
        if job.meta.get("user_id") != user_id:
            raise PermissionDeniedError("无权访问该后台任务")
        return job

    def get_status(self, task_id: str, user_id: str) -> TaskResult | None:
        job = self._get_job(task_id, user_id)
        if job is None:
            return None
        raw_status = job.get_status().value
        status = {
            "created": "pending",
            "queued": "pending",
            "deferred": "pending",
            "scheduled": "pending",
            "started": "running",
            "finished": "success",
            "failed": "failed",
            "stopped": "failed",
            "canceled": "cancelled",
        }.get(raw_status, "pending")
        duration_ms = 0.0
        if job.started_at is not None and job.ended_at is not None:
            duration_ms = max(0.0, (job.ended_at - job.started_at).total_seconds() * 1000)
        return TaskResult(
            task_id=task_id,
            status=status,
            result=job.return_value() if status == "success" else None,
            error="后台任务执行失败" if status == "failed" else None,
            duration_ms=duration_ms,
        )

    def cancel(self, task_id: str, user_id: str) -> bool:
        job = self._get_job(task_id, user_id)
        if job is None or job.get_status().value not in {
            "created",
            "queued",
            "deferred",
            "scheduled",
        }:
            return False
        try:
            cancel_job(task_id, connection=self._client)
        except Exception as exc:
            raise QueueError("后台任务取消失败") from exc
        return True

    def __repr__(self) -> str:
        return f"<RQQueueAdapter url={self._url}>"
