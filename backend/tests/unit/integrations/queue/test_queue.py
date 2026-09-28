"""异步任务队列适配层单元测试套件。

涵盖：
- TaskMessage / TaskResult 契约校验与边界测试；
- 消息序列化与反序列化测试；
- MemoryQueueAdapter 即时模式、排队模式与优先级排序；
- 租户隔离校验（非任务创建者查询或取消抛 PermissionDeniedError）；
- 任务取消状态机流转；
- 故障注入、模拟延迟与重置能力；
- 多线程高并发入队线程安全测试；
- RedisQueueAdapter 凭据掩码脱敏与 repr 验证；
- RedisQueueAdapter 入队、状态查询、越权阻断与取消；
- RedisQueueAdapter 指数退避重试与超时/连接异常转译；
- create_queue_adapter 工厂方法分发与异常校验。
"""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.core.errors import PermissionDeniedError, QueueError, QueueTimeoutError
from app.integrations.queue import (
    MemoryQueueAdapter,
    QueueProtocol,
    RedisQueueAdapter,
    TaskMessage,
    TaskResult,
    create_queue_adapter,
    deserialize_task_message,
    serialize_task_message,
)


class TestTaskMessageAndResult:
    """TaskMessage 和 TaskResult 值对象数据契约测试。"""

    def test_task_message_valid(self) -> None:
        """测试正常构建 TaskMessage。"""
        now = datetime.now(UTC)
        msg = TaskMessage(
            task_id="task-123",
            task_name="generate_questions",
            payload={"count": 5},
            user_id="user-001",
            priority=2,
            created_at=now,
        )
        assert msg.task_id == "task-123"
        assert msg.task_name == "generate_questions"
        assert msg.payload == {"count": 5}
        assert msg.user_id == "user-001"
        assert msg.priority == 2
        assert msg.created_at == now

    def test_task_message_invalid_fields(self) -> None:
        """测试 TaskMessage 空字段与非法优先级校验。"""
        with pytest.raises(ValueError, match="task_id 不能为空"):
            TaskMessage(task_id="", task_name="task", payload={}, user_id="u1")

        with pytest.raises(ValueError, match="task_name 不能为空"):
            TaskMessage(task_id="t1", task_name="   ", payload={}, user_id="u1")

        with pytest.raises(ValueError, match="user_id 不能为空"):
            TaskMessage(task_id="t1", task_name="task", payload={}, user_id="")

        with pytest.raises(ValueError, match="priority 必须大于等于 0"):
            TaskMessage(task_id="t1", task_name="task", payload={}, user_id="u1", priority=-1)

    def test_task_result_valid_and_invalid(self) -> None:
        """测试 TaskResult 状态校验与耗时校验。"""
        valid_res = TaskResult(
            task_id="t1",
            status="success",
            result={"score": 100},
            duration_ms=45.2,
        )
        assert valid_res.status == "success"
        assert valid_res.duration_ms == 45.2

        with pytest.raises(ValueError, match="status 'unknown' 不合法"):
            TaskResult(task_id="t1", status="unknown")

        with pytest.raises(ValueError, match="duration_ms 不能为负数"):
            TaskResult(task_id="t1", status="pending", duration_ms=-1.0)

    def test_serialization_round_trip(self) -> None:
        """测试序列化与反序列化一致性。"""
        original = TaskMessage(
            task_id="t-abc",
            task_name="chunking",
            payload={"material_id": "mat-1"},
            user_id="usr-789",
            priority=5,
        )
        raw_json = serialize_task_message(original)
        restored = deserialize_task_message(raw_json)

        assert restored.task_id == original.task_id
        assert restored.task_name == original.task_name
        assert restored.payload == original.payload
        assert restored.user_id == original.user_id
        assert restored.priority == original.priority

    def test_deserialization_corrupt_data(self) -> None:
        """测试反序列化损坏数据抛出 QueueError。"""
        with pytest.raises(QueueError, match="反序列化任务消息失败"):
            deserialize_task_message("not-json-content")

        with pytest.raises(QueueError, match="反序列化任务消息失败"):
            deserialize_task_message(json.dumps({"task_id": "t1"}))


class TestMemoryQueueAdapter:
    """MemoryQueueAdapter 单元测试。"""

    def test_protocol_conformance(self) -> None:
        """验证符合 QueueProtocol。"""
        adapter = MemoryQueueAdapter()
        assert isinstance(adapter, QueueProtocol)

    def test_immediate_mode_with_handler(self) -> None:
        """测试即时模式下挂载 Handler 自动执行成功。"""
        adapter = MemoryQueueAdapter(immediate_mode=True)
        adapter.register_handler("add", lambda p: p["a"] + p["b"])

        task_id = adapter.enqueue("add", {"a": 10, "b": 20}, user_id="user-1")
        assert task_id

        status = adapter.get_status(task_id, user_id="user-1")
        assert status is not None
        assert status.status == "success"
        assert status.result == 30
        assert status.duration_ms >= 0.0

    def test_immediate_mode_handler_exception(self) -> None:
        """测试即时模式下 Handler 抛出异常被捕获为 failed。"""
        adapter = MemoryQueueAdapter(immediate_mode=True)

        def faulty_handler(p: dict) -> None:
            raise RuntimeError("Handler failed internally")

        adapter.register_handler("fail_task", faulty_handler)
        task_id = adapter.enqueue("fail_task", {}, user_id="user-1")

        status = adapter.get_status(task_id, user_id="user-1")
        assert status is not None
        assert status.status == "failed"
        assert "Handler failed internally" in str(status.error)

    def test_immediate_mode_without_handler(self) -> None:
        """测试即时模式下未挂载 Handler 默认返回 success。"""
        adapter = MemoryQueueAdapter(immediate_mode=True)
        task_id = adapter.enqueue("unregistered", {"key": "val"}, user_id="user-1")

        status = adapter.get_status(task_id, user_id="user-1")
        assert status is not None
        assert status.status == "success"
        assert status.result is None

    def test_queue_mode_and_priority(self) -> None:
        """测试排队模式与按优先级调度。"""
        adapter = MemoryQueueAdapter(immediate_mode=False)
        adapter.register_handler("echo", lambda p: p["data"])

        t1 = adapter.enqueue("echo", {"data": "low"}, user_id="u1", priority=1)
        t2 = adapter.enqueue("echo", {"data": "high"}, user_id="u1", priority=10)
        t3 = adapter.enqueue("echo", {"data": "medium"}, user_id="u1", priority=5)

        # 检查初始状态为 pending
        st1 = adapter.get_status(t1, user_id="u1")
        assert st1 is not None and st1.status == "pending"

        # 第一次 process_next 应该调度 t2 (priority 10)
        res1 = adapter.process_next()
        assert res1 is not None and res1.task_id == t2
        assert res1.result == "high"

        # 第二次调度 t3 (priority 5)
        res2 = adapter.process_next()
        assert res2 is not None and res2.task_id == t3

        # 第三次调度 t1 (priority 1)
        res3 = adapter.process_next()
        assert res3 is not None and res3.task_id == t1

        # 队列已空
        assert adapter.process_next() is None

    def test_unauthorized_access_blocked(self) -> None:
        """测试非任务所有者查询或取消抛出 PermissionDeniedError。"""
        adapter = MemoryQueueAdapter(immediate_mode=False)
        task_id = adapter.enqueue("echo", {"data": 1}, user_id="owner-user")

        # 他人查询状态
        with pytest.raises(PermissionDeniedError, match="无权访问任务"):
            adapter.get_status(task_id, user_id="attacker-user")

        # 他人取消任务
        with pytest.raises(PermissionDeniedError, match="无权取消任务"):
            adapter.cancel(task_id, user_id="attacker-user")

        # 本人查询正常
        status = adapter.get_status(task_id, user_id="owner-user")
        assert status is not None and status.status == "pending"

    def test_cancel_workflow(self) -> None:
        """测试任务取消状态流转。"""
        adapter = MemoryQueueAdapter(immediate_mode=False)
        task_id = adapter.enqueue("echo", {}, user_id="user-1")

        # 取消 pending 任务成功
        assert adapter.cancel(task_id, user_id="user-1") is True

        # 再次取消返回 False
        assert adapter.cancel(task_id, user_id="user-1") is False

        # 查看状态为 cancelled
        status = adapter.get_status(task_id, user_id="user-1")
        assert status is not None and status.status == "cancelled"

        # 不存在的任务取消返回 False
        assert adapter.cancel("non-existent-id", user_id="user-1") is False

    def test_cancel_completed_task(self) -> None:
        """测试取消已完成的任务返回 False。"""
        adapter = MemoryQueueAdapter(immediate_mode=True)
        task_id = adapter.enqueue("task", {}, user_id="u1")
        assert adapter.cancel(task_id, user_id="u1") is False

    def test_fault_injection_and_latency(self) -> None:
        """测试故障注入与延迟钩子。"""
        adapter = MemoryQueueAdapter()
        adapter.set_fault_injection("enqueue", QueueError("Disk full"))

        with pytest.raises(QueueError, match="Disk full"):
            adapter.enqueue("task", {}, user_id="u1")

        # 清除故障
        adapter.set_fault_injection("enqueue", None)
        task_id = adapter.enqueue("task", {}, user_id="u1")
        assert task_id

        # 注入 get_status 故障
        adapter.set_fault_injection("get_status", QueueError("Database timeout"))
        with pytest.raises(QueueError, match="Database timeout"):
            adapter.get_status(task_id, user_id="u1")

        # 延迟设置
        adapter.set_latency(0.001)

    def test_reset(self) -> None:
        """测试重置适配器内部状态。"""
        adapter = MemoryQueueAdapter(immediate_mode=False)
        task_id = adapter.enqueue("task", {}, user_id="u1")
        adapter.set_fault_injection("enqueue", QueueError("Simulated"))

        adapter.reset()
        assert adapter.get_status(task_id, user_id="u1") is None
        # 故障已清除，可以正常 enqueue
        new_task_id = adapter.enqueue("task", {}, user_id="u1")
        assert new_task_id

    def test_repr_desensitization(self) -> None:
        """测试 repr 脱敏输出。"""
        adapter = MemoryQueueAdapter()
        repr_str = repr(adapter)
        assert "<MemoryQueueAdapter" in repr_str
        assert "immediate_mode" in repr_str

    def test_concurrent_enqueue(self) -> None:
        """测试多线程高并发入队线程安全性。"""
        adapter = MemoryQueueAdapter(immediate_mode=False)
        total_tasks = 40

        def enqueue_task(index: int) -> str:
            return adapter.enqueue(
                task_name="concurrent_task",
                payload={"index": index},
                user_id=f"user-{index}",
                priority=index,
            )

        with ThreadPoolExecutor(max_workers=8) as executor:
            task_ids = list(executor.map(enqueue_task, range(total_tasks)))

        assert len(task_ids) == total_tasks
        assert len(set(task_ids)) == total_tasks

        for i, tid in enumerate(task_ids):
            st = adapter.get_status(tid, user_id=f"user-{i}")
            assert st is not None
            assert st.status == "pending"


class TestRedisQueueAdapter:
    """RedisQueueAdapter 单元测试（基于 Mock 客户端）。"""

    def test_protocol_conformance(self) -> None:
        """验证符合 QueueProtocol。"""
        mock_client = MagicMock()
        adapter = RedisQueueAdapter(redis_client=mock_client)
        assert isinstance(adapter, QueueProtocol)

    def test_repr_masking(self) -> None:
        """测试连接字符串密码脱敏。"""
        raw_url = "redis://:super_secret_password@127.0.0.1:6379/1"
        mock_client = MagicMock()
        adapter = RedisQueueAdapter(redis_url=raw_url, redis_client=mock_client)
        repr_str = repr(adapter)
        assert "super_secret_password" not in repr_str
        assert ":***@" in repr_str

    def test_enqueue_redis(self) -> None:
        """测试 Redis 入队逻辑。"""
        mock_client = MagicMock()
        adapter = RedisQueueAdapter(redis_client=mock_client)

        task_id = adapter.enqueue(
            task_name="material_ocr",
            payload={"image_url": "http://example.com/img.png"},
            user_id="user-123",
            task_id="task-fixed-01",
        )
        assert task_id == "task-fixed-01"
        mock_client.hset.assert_called_once()
        mock_client.lpush.assert_called_once()

    def test_get_status_redis(self) -> None:
        """测试 Redis 查询任务状态与 JSON 反序列化。"""
        mock_client = MagicMock()
        mock_client.hgetall.return_value = {
            "task_id": "t-1",
            "task_name": "material_ocr",
            "user_id": "user-123",
            "status": "success",
            "result": json.dumps({"text": "ocr result"}),
            "error": "",
            "duration_ms": "128.5",
        }
        adapter = RedisQueueAdapter(redis_client=mock_client)

        status = adapter.get_status("t-1", user_id="user-123")
        assert status is not None
        assert status.status == "success"
        assert status.result == {"text": "ocr result"}
        assert status.error is None
        assert status.duration_ms == 128.5

    def test_get_status_redis_not_found(self) -> None:
        """测试查询不存在的任务返回 None。"""
        mock_client = MagicMock()
        mock_client.hgetall.return_value = {}
        adapter = RedisQueueAdapter(redis_client=mock_client)

        assert adapter.get_status("non-existent", user_id="u1") is None

    def test_get_status_redis_unauthorized(self) -> None:
        """测试他人查询 Redis 任务抛出 PermissionDeniedError。"""
        mock_client = MagicMock()
        mock_client.hgetall.return_value = {
            "task_id": "t-1",
            "user_id": "owner-user",
            "status": "pending",
        }
        adapter = RedisQueueAdapter(redis_client=mock_client)

        with pytest.raises(PermissionDeniedError, match="无权访问任务"):
            adapter.get_status("t-1", user_id="attacker-user")

    def test_cancel_redis(self) -> None:
        """测试通过 Redis 取消 pending 任务。"""
        mock_client = MagicMock()
        mock_client.hgetall.return_value = {
            "task_id": "t-1",
            "user_id": "u1",
            "status": "pending",
        }
        adapter = RedisQueueAdapter(redis_client=mock_client)

        res = adapter.cancel("t-1", user_id="u1")
        assert res is True
        mock_client.hset.assert_called_with("task:t-1", "status", "cancelled")

    def test_cancel_redis_non_pending(self) -> None:
        """测试通过 Redis 取消已完成任务返回 False。"""
        mock_client = MagicMock()
        mock_client.hgetall.return_value = {
            "task_id": "t-1",
            "user_id": "u1",
            "status": "success",
        }
        adapter = RedisQueueAdapter(redis_client=mock_client)

        res = adapter.cancel("t-1", user_id="u1")
        assert res is False

    def test_cancel_redis_unauthorized(self) -> None:
        """测试他人取消 Redis 任务抛出 PermissionDeniedError。"""
        mock_client = MagicMock()
        mock_client.hgetall.return_value = {
            "task_id": "t-1",
            "user_id": "owner",
            "status": "pending",
        }
        adapter = RedisQueueAdapter(redis_client=mock_client)

        with pytest.raises(PermissionDeniedError, match="无权取消任务"):
            adapter.cancel("t-1", user_id="attacker")

    def test_retry_on_timeout_and_recover(self) -> None:
        """测试网络超时重试成功恢复。"""
        mock_client = MagicMock()
        # 第一次抛 TimeoutError，第二次成功
        mock_client.lpush.side_effect = [TimeoutError("Socket timeout"), 1]

        adapter = RedisQueueAdapter(redis_client=mock_client, max_retries=3)
        task_id = adapter.enqueue("task", {}, user_id="u1")
        assert task_id
        assert mock_client.lpush.call_count == 2

    def test_retry_exhausted_raises_timeout_error(self) -> None:
        """测试超时重试耗尽抛出 QueueTimeoutError。"""
        mock_client = MagicMock()
        mock_client.lpush.side_effect = TimeoutError("Timed out repeatedly")

        adapter = RedisQueueAdapter(redis_client=mock_client, max_retries=2)
        with pytest.raises(QueueTimeoutError, match="Redis 队列操作响应超时"):
            adapter.enqueue("task", {}, user_id="u1")

    def test_retry_exhausted_raises_queue_error(self) -> None:
        """测试连接故障重试耗尽抛出 QueueError。"""
        mock_client = MagicMock()
        mock_client.lpush.side_effect = ConnectionError("Connection refused")

        adapter = RedisQueueAdapter(redis_client=mock_client, max_retries=2)
        with pytest.raises(QueueError, match="Redis 队列网络异常"):
            adapter.enqueue("task", {}, user_id="u1")

    def test_bytes_decoding_and_plain_result(self) -> None:
        """测试返回原始 bytes 键值与非 JSON 字符串结果解析。"""
        mock_client = MagicMock()
        mock_client.hgetall.return_value = {
            b"task_id": b"t-bytes",
            b"task_name": b"task",
            b"user_id": b"user-bytes",
            b"status": b"success",
            b"result": b"plain text result",
            b"error": b"some warning",
            b"duration_ms": b"invalid_number",
        }
        adapter = RedisQueueAdapter(redis_client=mock_client)
        status = adapter.get_status("t-bytes", user_id="user-bytes")
        assert status is not None
        assert status.status == "success"
        assert status.result == "plain text result"
        assert status.error == "some warning"
        assert status.duration_ms == 0.0

    def test_hmset_fallback_and_cancel_fallback(self) -> None:
        """测试无 hset 方法时的 hmset 降级与 cancel bytes 处理。"""

        class LegacyClient:
            def __init__(self) -> None:
                self.data: dict[str, Any] = {}

            def hmset(self, key: str, mapping: dict[str, Any]) -> None:
                self.data[key] = mapping

            def lpush(self, key: str, val: str) -> None:
                pass

            def hgetall(self, key: str) -> dict[Any, Any]:
                return {
                    b"task_id": b"t-leg",
                    b"user_id": b"user-leg",
                    b"status": b"pending",
                }

        legacy_client = LegacyClient()
        adapter = RedisQueueAdapter(redis_client=legacy_client)
        t_id = adapter.enqueue("task", {}, user_id="user-leg", task_id="t-leg")
        assert t_id == "t-leg"

        res = adapter.cancel("t-leg", user_id="user-leg")
        assert res is True

    def test_custom_redis_timeout_and_connection_exceptions(self) -> None:
        """测试类名含 Timeout/Connection 的自定义异常转译。"""
        custom_timeout = type("CustomRedisTimeoutError", (Exception,), {})
        custom_connection = type("CustomRedisConnectionError", (Exception,), {})
        custom_general = type("CustomGeneralError", (Exception,), {})

        mock_client = MagicMock()
        mock_client.lpush.side_effect = custom_timeout("Redis timeout")
        adapter = RedisQueueAdapter(redis_client=mock_client, max_retries=1)
        with pytest.raises(QueueTimeoutError, match="Redis 队列操作响应超时"):
            adapter.enqueue("task", {}, user_id="u1")

        mock_client.lpush.side_effect = custom_connection("Connection drop")
        with pytest.raises(QueueError, match="Redis 队列网络故障"):
            adapter.enqueue("task", {}, user_id="u1")

        mock_client.lpush.side_effect = custom_general("Something bad")
        with pytest.raises(QueueError, match="Redis 队列操作失败"):
            adapter.enqueue("task", {}, user_id="u1")

    def test_redis_init_missing_module_or_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试未安装 redis 库或连接初始化失败。"""
        import sys

        monkeypatch.setitem(sys.modules, "redis", None)
        with pytest.raises(QueueError, match="未安装 redis 依赖包"):
            RedisQueueAdapter(redis_client=None)

        fake_redis = MagicMock()
        fake_redis.from_url.side_effect = RuntimeError("DNS failed")
        monkeypatch.setitem(sys.modules, "redis", fake_redis)
        with pytest.raises(QueueError, match="初始化 Redis 客户端连接失败"):
            RedisQueueAdapter(redis_client=None)


class TestQueueFactory:
    """create_queue_adapter 工厂方法测试。"""

    def test_create_memory_adapter(self) -> None:
        """测试分发 MemoryQueueAdapter。"""
        adapter = create_queue_adapter("memory", immediate_mode=True)
        assert isinstance(adapter, MemoryQueueAdapter)

    def test_create_redis_adapter(self) -> None:
        """生产 Redis provider 分发可消费的 RQ 适配器。"""
        mock_client = MagicMock()
        adapter = create_queue_adapter("redis", redis_client=mock_client)
        assert type(adapter).__name__ == "RQQueueAdapter"

    def test_create_unsupported_adapter(self) -> None:
        """测试传入不支持的适配器类型抛出 QueueError。"""
        with pytest.raises(QueueError, match="不支持的任务队列类型"):
            create_queue_adapter("rabbitmq")
