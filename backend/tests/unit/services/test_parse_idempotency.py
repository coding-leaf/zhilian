"""Unit tests for full-chain material parse idempotency and RQ inspection/cancellation."""

import threading
import uuid
from collections.abc import Generator
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import StorageNotFoundError
from app.integrations.embedding.fake import FakeEmbeddingAdapter
from app.integrations.idempotency.memory import MemoryIdempotencyAdapter
from app.integrations.ocr.fake import FakeOCRAdapter
from app.integrations.queue.memory import MemoryQueueAdapter
from app.integrations.queue.rq_adapter import DEFAULT_QUEUE, HIGH_QUEUE, RQQueueAdapter
from app.integrations.storage.memory import MemoryStorageAdapter
from app.models.base import Base
from app.models.material import MaterialStatus, ParseStatus
from app.services.material import MaterialService


class _FakeRedisLockClient:
    """Thread-safe in-memory Redis subset supporting SET NX EX, GET, DELETE, and Lua EVAL."""

    def __init__(self, *, raise_on_set: bool = False) -> None:
        self._lock = threading.Lock()
        self._kv: dict[str, str] = {}
        self.raise_on_set = raise_on_set
        self.set_calls: list[tuple[str, str, bool, int | None]] = []

    def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool:
        self.set_calls.append((key, value, nx, ex))
        if self.raise_on_set:
            raise RuntimeError("redis unavailable")
        with self._lock:
            if nx and key in self._kv:
                return False
            self._kv[key] = value
            return True

    def get(self, key: str) -> bytes | None:
        with self._lock:
            val = self._kv.get(key)
            return val.encode("utf-8") if val is not None else None

    def delete(self, key: str) -> int:
        with self._lock:
            return 1 if self._kv.pop(key, None) is not None else 0

    def eval(self, _script: str, _numkeys: int, key: str, token: str) -> int:
        with self._lock:
            if self._kv.get(key) == token:
                self._kv.pop(key, None)
                return 1
            return 0


class _QueueWithRedisClient(MemoryQueueAdapter):
    """MemoryQueueAdapter exposing a fake Redis `_client` plus configurable live/cancel hooks."""

    def __init__(self, redis_client: Any) -> None:
        super().__init__()
        self._client = redis_client
        self.live_override: bool | None = None
        self.cancelled_calls: list[tuple[str, dict[str, str]]] = []

    def has_live_job(self, task_name: str, match_payload: dict[str, str]) -> bool:
        if self.live_override is not None:
            return self.live_override
        return super().has_live_job(task_name, match_payload)

    def cancel_matching_jobs(self, task_name: str, match_payload: dict[str, str]) -> int:
        self.cancelled_calls.append((task_name, dict(match_payload)))
        return super().cancel_matching_jobs(task_name, match_payload)


@pytest.fixture
def session_factory(tmp_path: Any) -> Generator[sessionmaker[Session], None, None]:
    db_file = tmp_path / "parse_idempotency.db"
    engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False, "timeout": 15.0},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield factory
    engine.dispose()


def _make_material_service(
    session: Session,
    queue: MemoryQueueAdapter,
    *,
    storage: MemoryStorageAdapter | None = None,
) -> MaterialService:
    resolved_storage = storage or MemoryStorageAdapter()
    resolved_storage.ensure_bucket_exists("zhilian-materials")
    return MaterialService(
        session=session,
        storage_adapter=resolved_storage,
        ocr_adapter=FakeOCRAdapter(),
        embedding_adapter=FakeEmbeddingAdapter(),
        queue_adapter=queue,
        idempotency_adapter=MemoryIdempotencyAdapter(),
    )


def test_queue_adapter_capabilities_and_rq_live_cancel_contracts() -> None:
    """Verify supports_async_worker, has_live_job, and cancel_matching_jobs."""
    mem = MemoryQueueAdapter()
    assert mem.supports_async_worker is False

    ver_id = str(uuid.uuid4())
    other_ver_id = str(uuid.uuid4())
    t1 = mem.enqueue("parse_material_pipeline", {"version_id": ver_id, "user_id": "u1"}, "u1")
    t2 = mem.enqueue("parse_material_pipeline", {"version_id": other_ver_id, "user_id": "u1"}, "u1")
    assert mem.has_live_job("parse_material_pipeline", {"version_id": ver_id}) is True
    assert mem.cancel_matching_jobs("parse_material_pipeline", {"version_id": ver_id}) == 1
    assert mem.has_live_job("parse_material_pipeline", {"version_id": ver_id}) is False
    assert mem.get_status(t1, "u1") is not None
    assert mem.get_status(t1, "u1").status == "cancelled"  # type: ignore[union-attr]
    assert mem.has_live_job("parse_material_pipeline", {"version_id": other_ver_id}) is True
    assert mem.cancel_matching_jobs("parse_material_pipeline", {"version_id": other_ver_id}) == 1
    assert t2

    # RQQueueAdapter tests
    client = MagicMock()
    rq_adapter = RQQueueAdapter(redis_client=client)
    assert rq_adapter.supports_async_worker is True

    high_q = MagicMock()
    default_q = MagicMock()
    high_q.get_job_ids.return_value = []
    high_q.started_job_registry.get_job_ids.return_value = []
    high_q.scheduled_job_registry.get_job_ids.return_value = ["sched-1"]
    high_q.deferred_job_registry.get_job_ids.return_value = []

    default_q.get_job_ids.return_value = ["queued-1"]
    default_q.started_job_registry.get_job_ids.return_value = ["started-1"]
    default_q.scheduled_job_registry.get_job_ids.return_value = []
    default_q.deferred_job_registry.get_job_ids.return_value = ["defer-1"]

    def _queue_factory(name: str, connection: Any) -> MagicMock:
        _ = connection
        return high_q if name == HIGH_QUEUE else default_q

    sched_job = SimpleNamespace(
        id="sched-1",
        args=("parse_material_pipeline", {"version_id": ver_id}, "u1"),
        get_status=lambda: "scheduled",
    )
    queued_job = SimpleNamespace(
        id="queued-1",
        args=("parse_material_pipeline", {"version_id": ver_id}, "u1"),
        get_status=lambda: "queued",
    )
    defer_job = SimpleNamespace(
        id="defer-1",
        args=("parse_material_pipeline", {"version_id": ver_id}, "u1"),
        get_status=lambda: "deferred",
    )
    started_job = SimpleNamespace(
        id="started-1",
        args=("parse_material_pipeline", {"version_id": ver_id}, "u1"),
        get_status=lambda: "started",
    )
    other_job = SimpleNamespace(
        id="other-1",
        args=("parse_material_pipeline", {"version_id": other_ver_id}, "u1"),
        get_status=lambda: "queued",
    )

    with patch("app.integrations.queue.rq_adapter.Queue", side_effect=_queue_factory):
        # has_live_job ignores scheduled/deferred when queued & started are empty
        default_q.get_job_ids.return_value = []
        default_q.started_job_registry.get_job_ids.return_value = []
        with patch("app.integrations.queue.rq_adapter.Job.fetch_many", return_value=[]):
            assert (
                rq_adapter.has_live_job("parse_material_pipeline", {"version_id": ver_id}) is False
            )

        # has_live_job returns True when started job matches
        default_q.started_job_registry.get_job_ids.return_value = ["started-1"]
        with patch("app.integrations.queue.rq_adapter.Job.fetch_many", return_value=[started_job]):
            assert (
                rq_adapter.has_live_job("parse_material_pipeline", {"version_id": ver_id}) is True
            )

        # cancel_matching_jobs cancels queued/scheduled/deferred but NEVER started or non-matching
        default_q.get_job_ids.return_value = ["queued-1", "other-1"]
        with (
            patch(
                "app.integrations.queue.rq_adapter.Job.fetch_many",
                return_value=[sched_job, queued_job, defer_job, started_job, other_job],
            ),
            patch("app.integrations.queue.rq_adapter.cancel_job") as mock_cancel,
        ):
            cancelled = rq_adapter.cancel_matching_jobs(
                "parse_material_pipeline", {"version_id": ver_id}
            )
            assert cancelled == 3
            cancelled_ids = {call.args[0] for call in mock_cancel.call_args_list}
            assert cancelled_ids == {"sched-1", "queued-1", "defer-1"}
            assert DEFAULT_QUEUE == "zhilian"


def test_trigger_parse_dispatch_lock_and_fail_open(session_factory: sessionmaker[Session]) -> None:
    """Dispatch lock skips duplicate requests when held and fails open if Redis errors."""
    redis = _FakeRedisLockClient()
    queue = _QueueWithRedisClient(redis)

    with session_factory() as session:
        svc = _make_material_service(session, queue)
        user_id = uuid.uuid4()
        content = b"Dispatch lock idempotency test content\n\n" * 4
        mat, ver = svc.create_material(
            user_id=user_id,
            title="DispatchLock.txt",
            file_format="txt",
            file_size=len(content),
            file_content=content,
        )

        # Simulate another HTTP request holding the dispatch lock
        lock_key = f"zhilian:material:parse:dispatch:{ver.id}"
        assert redis.set(lock_key, "other-holder", nx=True, ex=10) is True
        res_locked = svc.trigger_parse(user_id=user_id, material_id=mat.id, version_id=ver.id)
        assert res_locked.id == ver.id
        assert len(queue._queue) == 0

        # Release lock; if Redis fails during SET, fail-open still allows DB CAS + enqueue
        redis.delete(lock_key)
        redis.raise_on_set = True
        res_fail_open = svc.trigger_parse(user_id=user_id, material_id=mat.id, version_id=ver.id)
        assert res_fail_open.parse_status == ParseStatus.QUEUED.value
        assert len(queue._queue) == 1


def test_trigger_parse_from_failed_cancels_scheduled_retries_and_guards_live_jobs(
    session_factory: sessionmaker[Session],
) -> None:
    """FAILED re-parse checks has_live_job first and cancels scheduled retries before enqueue."""
    redis = _FakeRedisLockClient()
    queue = _QueueWithRedisClient(redis)

    with session_factory() as session:
        svc = _make_material_service(session, queue)
        user_id = uuid.uuid4()
        content = b"Retry cancellation idempotency test\n\n" * 4
        mat, ver = svc.create_material(
            user_id=user_id,
            title="RetryCancel.txt",
            file_format="txt",
            file_size=len(content),
            file_content=content,
        )
        svc.repo.update_material_status(mat.id, user_id, MaterialStatus.FAILED.value)
        svc.repo.update_version_status(ver.id, user_id, ParseStatus.FAILED.value)
        session.commit()

        # Case 1: live queued/started job exists -> do not double enqueue
        queue.live_override = True
        res_live = svc.trigger_parse(user_id=user_id, material_id=mat.id, version_id=ver.id)
        assert res_live.parse_status == ParseStatus.FAILED.value
        assert len(queue._queue) == 0
        assert queue.cancelled_calls == []

        # Case 2: only scheduled retry exists (has_live_job=False) -> CAS + cancel + enqueue
        queue.live_override = False
        res_retry = svc.trigger_parse(user_id=user_id, material_id=mat.id, version_id=ver.id)
        assert res_retry.parse_status == ParseStatus.QUEUED.value
        assert queue.cancelled_calls == [
            ("parse_material_pipeline", {"version_id": str(ver.id)}),
        ]
        assert len(queue._queue) == 1
        assert redis.get(f"zhilian:material:parse:dispatch:{ver.id}") is None


def test_trigger_parse_concurrent_double_clicks_enqueue_once(
    session_factory: sessionmaker[Session],
) -> None:
    """Concurrent trigger_parse calls on the same version enqueue at most 1 job."""
    redis = _FakeRedisLockClient()
    queue = _QueueWithRedisClient(redis)

    with session_factory() as seed_session:
        svc = _make_material_service(seed_session, queue)
        user_id = uuid.uuid4()
        content = b"Concurrent double click parse test\n\n" * 4
        mat, ver = svc.create_material(
            user_id=user_id,
            title="DoubleClick.txt",
            file_format="txt",
            file_size=len(content),
            file_content=content,
        )

    barrier = threading.Barrier(4)
    errors: list[Exception] = []

    def _click() -> None:
        try:
            barrier.wait(timeout=3.0)
            with session_factory() as sess:
                worker_svc = _make_material_service(sess, queue)
                worker_svc.trigger_parse(user_id=user_id, material_id=mat.id, version_id=ver.id)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=_click) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    assert errors == []
    assert len(queue._queue) == 1


def test_parse_material_pipeline_execution_lock_skips_duplicate_and_releases_on_error(
    session_factory: sessionmaker[Session],
) -> None:
    """Worker path (sync=False) acquires exec lock (1800s) and releases in finally."""
    redis = _FakeRedisLockClient()
    queue = _QueueWithRedisClient(redis)
    storage = MemoryStorageAdapter()
    storage.ensure_bucket_exists("zhilian-materials")

    with session_factory() as session:
        svc = _make_material_service(session, queue, storage=storage)
        user_id = uuid.uuid4()
        content = b"Execution lock worker idempotency content\n\n" * 4
        mat, ver = svc.create_material(
            user_id=user_id,
            title="ExecLock.txt",
            file_format="txt",
            file_size=len(content),
            file_content=content,
        )
        exec_key = f"zhilian:material:parse:exec:{ver.id}"

        # 1. Held by another worker -> skip parse_material_pipeline idempotently
        assert redis.set(exec_key, "worker-1-token", nx=True, ex=1800) is True
        skipped = svc.parse_material_pipeline(
            material_id=mat.id,
            version_id=ver.id,
            user_id=user_id,
        )
        assert skipped.parse_status == ParseStatus.NOT_STARTED.value
        assert redis.get(exec_key) == b"worker-1-token"

        # 2. Release lock, inject storage failure -> exec lock acquired & released in finally
        redis.delete(exec_key)
        storage.delete_object("zhilian-materials", ver.storage_key)
        with pytest.raises(StorageNotFoundError):
            svc.parse_material_pipeline(
                material_id=mat.id,
                version_id=ver.id,
                user_id=user_id,
            )
        assert any(
            key == exec_key and nx is True and ex == 1800 for key, _val, nx, ex in redis.set_calls
        )
        assert redis.get(exec_key) is None
