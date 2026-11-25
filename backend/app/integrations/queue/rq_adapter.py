"""RQ-backed implementation of the application task queue contract."""

import logging
import uuid
from datetime import timedelta
from typing import Any

from redis import Redis
from rq import Callback, Queue, Retry, cancel_job
from rq.exceptions import NoSuchJobError
from rq.job import Job

from app.core.config import RedisSettings
from app.core.errors import PermissionDeniedError, QueueError
from app.integrations.queue.protocol import REGISTERED_TASK_NAMES, QueueProtocol, TaskResult
from app.integrations.redis_client import build_redis_client, close_redis_client, mask_redis_url

logger = logging.getLogger(__name__)

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
        redis_settings: RedisSettings | None = None,
        socket_timeout: float | None = None,
        max_connections: int | None = None,
        retry_limit: int = 3,
        job_timeout: int = 1800,
    ) -> None:
        resolved_url = redis_url or (redis_settings.redis_url if redis_settings else None)
        self._url = mask_redis_url(resolved_url)
        self._client = redis_client or build_redis_client(
            redis_url=redis_url,
            settings=redis_settings,
            socket_timeout=socket_timeout,
            max_connections=max_connections,
            decode_responses=False,
        )
        self._retry_limit = max(0, retry_limit)
        self._job_timeout = job_timeout

    def close(self) -> None:
        """Close the Redis client and disconnect its connection pool."""
        close_redis_client(self._client)

    def ping(self) -> bool:
        """Probe Redis connectivity for health checks."""
        return bool(self._client.ping())

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

    @property
    def supports_async_worker(self) -> bool:
        """RQ 队列由独立后台 Worker 进程消费，支持非阻塞异步投递。"""
        return True

    @staticmethod
    def _job_matches(job: Job | None, task_name: str, match_payload: dict[str, str]) -> bool:
        if job is None:
            return False
        raw_args = job.args if isinstance(job.args, (list, tuple)) else []
        if len(raw_args) < 2 or raw_args[0] != task_name or not isinstance(raw_args[1], dict):
            return False
        return all(
            str(raw_args[1].get(key, "")) == str(value) for key, value in match_payload.items()
        )

    def _any_job_matches(
        self,
        job_ids: list[str],
        task_name: str,
        match_payload: dict[str, str],
    ) -> bool:
        if not job_ids:
            return False
        jobs = Job.fetch_many(list(dict.fromkeys(job_ids)), connection=self._client)
        return any(self._job_matches(job, task_name, match_payload) for job in jobs)

    @staticmethod
    def _is_started_job(job: Job | None, started_ids: set[str]) -> bool:
        if job is None:
            return False
        job_id = getattr(job, "id", None)
        if job_id is not None and str(job_id) in started_ids:
            return True
        get_status_fn = getattr(job, "get_status", None)
        if callable(get_status_fn):
            raw_status = get_status_fn()
            status_val = getattr(raw_status, "value", raw_status)
            if str(status_val) == "started":
                return True
        return False

    def has_active_job(self, task_name: str, match_payload: dict[str, str]) -> bool | None:
        """检查 RQ 队列与活跃注册表中是否存在匹配指定载荷的进行中任务。"""
        try:
            job_ids: list[str] = []
            for queue_name in (HIGH_QUEUE, DEFAULT_QUEUE):
                queue = Queue(queue_name, connection=self._client)
                job_ids.extend(queue.get_job_ids())
                job_ids.extend(queue.started_job_registry.get_job_ids())
                job_ids.extend(queue.scheduled_job_registry.get_job_ids())
                job_ids.extend(queue.deferred_job_registry.get_job_ids())
            return self._any_job_matches(job_ids, task_name, match_payload)
        except Exception:
            return None

    def has_live_job(self, task_name: str, match_payload: dict[str, str]) -> bool | None:
        """仅检查 queued 与 started 任务（忽略 scheduled 延迟退避重试）。"""
        try:
            job_ids: list[str] = []
            for queue_name in (HIGH_QUEUE, DEFAULT_QUEUE):
                queue = Queue(queue_name, connection=self._client)
                job_ids.extend(queue.get_job_ids())
                job_ids.extend(queue.started_job_registry.get_job_ids())
            return self._any_job_matches(job_ids, task_name, match_payload)
        except Exception:
            return None

    def cancel_matching_jobs(self, task_name: str, match_payload: dict[str, str]) -> int:
        """取消 HIGH_QUEUE 与 DEFAULT_QUEUE 中匹配的排队/延迟/挂起任务（不强杀 started）。"""
        try:
            job_ids: list[str] = []
            started_ids: set[str] = set()
            for queue_name in (HIGH_QUEUE, DEFAULT_QUEUE):
                queue = Queue(queue_name, connection=self._client)
                job_ids.extend(queue.get_job_ids())
                job_ids.extend(queue.scheduled_job_registry.get_job_ids())
                job_ids.extend(queue.deferred_job_registry.get_job_ids())
                started_ids.update(str(jid) for jid in queue.started_job_registry.get_job_ids())
            if not job_ids:
                return 0
            jobs = Job.fetch_many(list(dict.fromkeys(job_ids)), connection=self._client)
        except Exception as exc:
            logger.warning("inspect matching RQ jobs failed: %s", str(exc)[:160])
            return 0

        cancelled = 0
        for job in jobs:
            if not self._job_matches(job, task_name, match_payload):
                continue
            if self._is_started_job(job, started_ids):
                continue
            job_id = getattr(job, "id", None)
            if job_id is None:
                continue
            try:
                cancel_job(str(job_id), connection=self._client)
                cancelled += 1
            except NoSuchJobError:
                continue
            except Exception as exc:
                logger.warning("cancel matching RQ job %s failed: %s", job_id, str(exc)[:160])
        return cancelled

    def __repr__(self) -> str:
        return f"<RQQueueAdapter url={self._url}>"
