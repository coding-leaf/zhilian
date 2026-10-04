"""Unit tests supplement: app/services/practice.py TIMEOUT status and edge cases.

补测目标：覆盖 P1 状态机迁移与幂等重派路径中未覆盖分支（采用 mock 策略，避免繁重的实体装配）。
- `retry_grading` 拒绝非 `partially_queued` 状态的练习（L1299-1315）
- `submit_practice` 在缺 dto/practice_id/idempotency_key 时参数校验（L1020-1022）
- `retry_grading` 在实体消失后的兜底
- 状态跃迁成功后并发删除导致的 rollback 防御（评审 BUG-02 修复）
"""

import uuid
from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.core.errors import (
    IdempotencyConflictError,
    PracticeNotFoundError,
    PracticeStatusError,
    QueueError,
)
from app.integrations.idempotency.memory import MemoryIdempotencyAdapter
from app.integrations.queue.memory import MemoryQueueAdapter
from app.models.practice import Practice, PracticeStatus


def _make_practice_service_stub(
    *,
    practice: Practice | None = None,
    session: MagicMock | None = None,
    queue: MagicMock | None = None,
) -> tuple[Any, Any]:
    """构造轻量 PracticeService 桩，返回 (service, repo_mock)。

    BUG-FIX: 提取共用桩工厂，避免 5 个 _make_service* 重复实现（评审 PR4-05）。
    当 practice=None 时：repo.get_practice_by_id 返回 None（模拟实体不存在）。
    """
    from app.services.practice import PracticeService

    service = PracticeService.__new__(PracticeService)
    service.session = session or MagicMock()
    service.queue = queue if queue is not None else MemoryQueueAdapter()
    service.practice_repo = MagicMock()
    service.practice_repo.get_practice_by_id.return_value = practice  # 显式 None 或实体
    return service, service.practice_repo


class TestSubmitPracticeParamValidation:
    """`submit_practice` 在缺少必填参数时的参数校验（L1020-1022）。

    通过桩化 repository 与 idempotency 校验器，使被测函数在最早阶段触发
    参数校验失败，避免复杂的实体装配。
    """

    def test_submit_practice_without_dto_and_keys_raises_value_error(self) -> None:
        """不传 dto 且不传 practice_id/idempotency_key 时必须抛 ValueError。"""
        service, _ = _make_practice_service_stub()

        with pytest.raises(ValueError) as exc_info:
            service.submit_practice(user_id=uuid.uuid4())
        assert "practice_id" in str(exc_info.value)
        assert "idempotency_key" in str(exc_info.value)

    def test_submit_practice_without_dto_with_only_practice_id_raises(self) -> None:
        """仅传 practice_id 时必须抛 ValueError（双参数绑定校验）。"""
        service, _ = _make_practice_service_stub()

        with pytest.raises(ValueError):
            service.submit_practice(
                user_id=uuid.uuid4(),
                practice_id=uuid.uuid4(),
            )

    def test_submit_practice_without_dto_with_only_key_raises(self) -> None:
        """仅传 idempotency_key 时必须抛 ValueError。"""
        service, _ = _make_practice_service_stub()

        with pytest.raises(ValueError):
            service.submit_practice(
                user_id=uuid.uuid4(),
                idempotency_key="some-key",
            )


def _sample_datetime() -> Any:
    """返回用于 completed_at 的 UTC 时间样本。"""
    from datetime import UTC, datetime

    return datetime(2026, 10, 1, tzinfo=UTC)


class TestRetryGradingStatusGuard:
    """`retry_grading` 拒绝非 `partially_queued` 状态的练习（L1299-1315）。

    BUG-FIX: 评审 PR4-04 要求补全 PAUSED / SUBMITTED 状态拦截；用 parametrize 合并 6 状态用例。
    """

    @pytest.mark.parametrize(
        ("status_value", "completed_at"),
        [
            (PracticeStatus.TIMEOUT.value, None),
            (PracticeStatus.NOT_STARTED.value, None),
            (PracticeStatus.IN_PROGRESS.value, None),
            (PracticeStatus.PAUSED.value, None),
            (PracticeStatus.SUBMITTED.value, None),
            (PracticeStatus.COMPLETED.value, _sample_datetime()),
        ],
    )
    def test_retry_grading_rejects_non_partially_graded_status(
        self, status_value: str, completed_at: Any
    ) -> None:
        """非 partially_graded 状态：retry_grading 必须抛 PracticeStatusError，绝不入队。

        覆盖 6 种非法状态：TIMEOUT / NOT_STARTED / IN_PROGRESS / PAUSED / SUBMITTED / COMPLETED。
        """
        practice = Practice(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            status=status_value,
            completed_at=completed_at,
        )
        service, repo = _make_practice_service_stub(practice=practice)

        with pytest.raises(PracticeStatusError) as exc_info:
            service.retry_grading(practice.user_id, practice.id)
        # 错误消息必须非空且明确
        assert exc_info.value.message, f"错误消息不能为空: {status_value}"
        # error_code 必须为 40011（统一错误码）
        assert exc_info.value.error_code == 40011
        # details 必须含 status 字段便于客户端处理
        assert exc_info.value.details.get("status") == status_value
        # 队列未被入队
        assert isinstance(service.queue, MemoryQueueAdapter)
        assert len(service.queue._queue) == 0
        # 未尝试状态跃迁（避免在状态非法时无谓的 DB CAS）
        repo.try_transition_status.assert_not_called()


def _sample_datetime() -> Any:
    """返回用于 completed_at 的 UTC 时间样本。"""
    from datetime import UTC, datetime

    return datetime(2026, 10, 1, tzinfo=UTC)


class TestRetryGradingNotFoundGuard:
    """`retry_grading` 在实体不存在时的兜底（L1292-1296）。"""

    def test_retry_grading_raises_not_found_when_practice_missing(self) -> None:
        """练习不存在时 retry_grading 必须抛 PracticeNotFoundError，绝不静默。"""
        service, _ = _make_practice_service_stub(practice=None)
        user_id = uuid.uuid4()
        practice_id = uuid.uuid4()

        with pytest.raises(PracticeNotFoundError) as exc_info:
            service.retry_grading(user_id, practice_id)
        assert "练习不存在" in exc_info.value.message or str(practice_id) in str(
            exc_info.value.details
        )
        # 队列未被入队
        assert isinstance(service.queue, MemoryQueueAdapter)
        assert len(service.queue._queue) == 0


class TestRetryGradingRaceCondition:
    """`retry_grading` 并发场景：状态跃迁失败的兜底（L1326-1330）。"""

    def test_retry_grading_rejects_concurrent_second_trigger(self) -> None:
        """并发场景：状态跃迁失败时 retry_grading 必须抛 PracticeStatusError，绝不入队。"""
        practice = Practice(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            status=PracticeStatus.PARTIALLY_GRADED.value,
            completed_at=None,
        )
        service, repo = _make_practice_service_stub(practice=practice)
        # 模拟并发第二次请求：状态跃迁失败（行已被前一个请求改走）
        repo.try_transition_status.return_value = False

        with pytest.raises(PracticeStatusError) as exc_info:
            service.retry_grading(practice.user_id, practice.id)
        # 错误消息必须提示「已在重试中」
        assert "重试" in exc_info.value.message
        # 队列未被入队（关键：并发场景下不会重复派发）
        assert isinstance(service.queue, MemoryQueueAdapter)
        assert len(service.queue._queue) == 0


class TestRetryGradingQueueFailureRollback:
    """`retry_grading` 入队失败时必须回滚状态（L1317-1344）。

    BUG-FIX: 评审 PR4-03 要求改用 QueueError 而非 RuntimeError，
    锁定生产真实异常路径。retry_grading 现已收紧到 except (QueueError, SQLAlchemyError)。
    """

    def test_rolls_back_status_when_queue_enqueue_fails_with_queue_error(self) -> None:
        """queue.enqueue 抛 QueueError 时：必须 rollback，且包装为 PracticeStatusError。"""
        practice = Practice(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            status=PracticeStatus.PARTIALLY_GRADED.value,
            completed_at=None,
        )
        # 用真实 MemoryQueueAdapter + fault_injection 模拟生产路径
        queue = MemoryQueueAdapter()
        queue.set_fault_injection("enqueue", QueueError("redis down"))
        service, repo = _make_practice_service_stub(practice=practice, queue=queue)
        repo.try_transition_status.return_value = True

        # 入队失败必须抛包装后的 PracticeStatusError（带 reason 详情）
        with pytest.raises(PracticeStatusError) as exc_info:
            service.retry_grading(practice.user_id, practice.id)
        assert exc_info.value.error_code == 40011
        assert "redis down" in exc_info.value.details.get("reason", "")

        # 关键断言：session.rollback 必须被调用（防「永久判题中」）
        service.session.rollback.assert_called_once()

        queue.set_fault_injection("enqueue", None)


class TestRetryGradingNotFoundAfterTransition:
    """评审 BUG-02 修复回归：`retry_grading` 状态跃迁后实体消失防御。

    之前 retry_grading 在 try/except 外做 `get_practice_by_id`，实体消失时抛错无 rollback。
    修复后：状态跃迁 commit 后再做二次校验，查询过程若抛 SQLAlchemyError 则 rollback
    并包装为 NotFoundError；查询返回 None 时也明确返回 NotFoundError。
    """

    def test_retry_grading_returns_not_found_when_practice_disappears_after_transition(
        self,
    ) -> None:
        """状态跃迁成功后实体消失：必须抛 NotFoundError。"""
        practice = Practice(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            status=PracticeStatus.PARTIALLY_GRADED.value,
            completed_at=None,
        )
        service, repo = _make_practice_service_stub(practice=practice)
        repo.try_transition_status.return_value = True

        # 第二次调用 get_practice_by_id 返回 None（实体消失）
        repo.get_practice_by_id.side_effect = [practice, None]

        with pytest.raises(PracticeNotFoundError):
            service.retry_grading(practice.user_id, practice.id)

    def test_retry_grading_rolls_back_when_get_practice_raises_sqlalchemy_error(
        self,
    ) -> None:
        """状态跃迁后查询实体抛 SQLAlchemyError：必须 rollback + 包装 NotFoundError。"""
        from sqlalchemy.exc import OperationalError

        practice = Practice(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            status=PracticeStatus.PARTIALLY_GRADED.value,
            completed_at=None,
        )
        service, repo = _make_practice_service_stub(practice=practice)
        repo.try_transition_status.return_value = True
        # 第二次调用抛 OperationalError（典型 DB 连接丢失场景）
        repo.get_practice_by_id.side_effect = [practice, OperationalError("conn lost", None, None)]

        with pytest.raises(PracticeNotFoundError) as exc_info:
            service.retry_grading(practice.user_id, practice.id)
        # 必须包含原始 SQLAlchemyError 原因，便于诊断
        assert "conn lost" in exc_info.value.details.get("reason", "")
        # rollback 必须被调用
        service.session.rollback.assert_called()


class TestStrongIdempotencyReplay:
    """强幂等并发锁：同 idempotency_key 第二次提交应抛 IdempotencyConflictError。"""

    def test_idempotency_lock_raises_conflict_on_duplicate_key(self) -> None:
        """idempotency.acquire_lock 在已占用 key 上必须抛 IdempotencyConflictError。"""
        adapter = MemoryIdempotencyAdapter()

        adapter.acquire_lock(key="key-1", user_id="user-A")
        with pytest.raises(IdempotencyConflictError) as exc_info:
            adapter.acquire_lock(key="key-1", user_id="user-A")
        assert exc_info.value.error_code == 30017

    def test_different_keys_do_not_conflict(self) -> None:
        """不同 idempotency_key 之间互不冲突。"""
        adapter = MemoryIdempotencyAdapter()

        adapter.acquire_lock(key="key-A", user_id="user-A")
        adapter.acquire_lock(key="key-B", user_id="user-A")

        with pytest.raises(IdempotencyConflictError):
            adapter.acquire_lock(key="key-A", user_id="user-A")


@pytest.fixture
def session() -> Generator[Any, None, None]:
    """兼容 pytest 收集需要的 session 参数。"""
    yield MagicMock()
