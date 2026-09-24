"""分布式幂等拦截适配层单元测试套件。

涵盖：
- IdempotencyRecord 契约与校验；
- validate_idempotency_key 纯函数格式校验与边界测试；
- MemoryIdempotencyAdapter 原子加锁、并发冲突抛 409、结果回放与异常释放；
- 50 线程高并发争抢测试（有且仅有 1 次抢占成功，其余 49 次精准返回 False）；
- 多租户命名空间严格隔离校验；
- TTL 模拟时钟过期清理测试；
- 故障注入与状态重置；
- RedisIdempotencyAdapter 凭据脱敏、SET NX EX 原子互斥、结果存取与异常转译；
- create_idempotency_adapter 工厂方法分发与参数校验。
"""

import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest

from app.core.errors import (
    AppError,
    IdempotencyConflictError,
    IdempotencyKeyInvalidError,
    PermissionDeniedError,
)
from app.integrations.idempotency import (
    IdempotencyProtocol,
    IdempotencyRecord,
    MemoryIdempotencyAdapter,
    RedisIdempotencyAdapter,
    build_idempotency_storage_key,
    create_idempotency_adapter,
    validate_idempotency_key,
)


class TestIdempotencyProtocolAndHelpers:
    """IdempotencyRecord 及纯函数辅助核测试。"""

    def test_record_valid(self) -> None:
        """测试正常构建 IdempotencyRecord。"""
        rec = IdempotencyRecord(
            key="req-001",
            user_id="user-1",
            status="LOCKED",
            result=None,
            locked_at=100.0,
            expire_at=160.0,
        )
        assert rec.key == "req-001"
        assert rec.user_id == "user-1"
        assert rec.status == "LOCKED"
        assert rec.expire_at == 160.0

    def test_record_invalid(self) -> None:
        """测试非法字段与未知状态。"""
        with pytest.raises(ValueError, match="key 不能为空"):
            IdempotencyRecord(key="", user_id="u1", status="LOCKED")

        with pytest.raises(ValueError, match="user_id 不能为空"):
            IdempotencyRecord(key="k1", user_id="  ", status="LOCKED")

        with pytest.raises(ValueError, match="status 'INVALID' 不合法"):
            IdempotencyRecord(key="k1", user_id="u1", status="INVALID")

    def test_validate_key_valid(self) -> None:
        """测试合法的幂等键。"""
        assert validate_idempotency_key("req-12345") == "req-12345"
        assert (
            validate_idempotency_key("  uuid:550e8400-e29b-41d4-a716-446655440000  ")
            == "uuid:550e8400-e29b-41d4-a716-446655440000"
        )
        assert validate_idempotency_key("key.with_under_and_dots:1") == "key.with_under_and_dots:1"

    def test_validate_key_invalid(self) -> None:
        """测试各种非法幂等键边界值。"""
        # 非字符串
        with pytest.raises(IdempotencyKeyInvalidError, match="幂等键必须为字符串"):
            validate_idempotency_key(None)  # type: ignore[arg-type]

        # 空串
        with pytest.raises(IdempotencyKeyInvalidError, match="幂等键不能为空"):
            validate_idempotency_key("   ")

        # 超长 (>128 字符)
        with pytest.raises(IdempotencyKeyInvalidError, match="幂等键长度不能超过 128 字符"):
            validate_idempotency_key("a" * 129)

        # 非法字符
        with pytest.raises(IdempotencyKeyInvalidError, match="包含非法字符"):
            validate_idempotency_key("key with spaces")

        with pytest.raises(IdempotencyKeyInvalidError, match="包含非法字符"):
            validate_idempotency_key("key/with/slashes")

        with pytest.raises(IdempotencyKeyInvalidError, match="包含非法字符"):
            validate_idempotency_key("key@at")

    def test_build_idempotency_storage_key(self) -> None:
        """测试租户存储键拼接。"""
        storage_key = build_idempotency_storage_key("usr-001", "req-xyz")
        assert storage_key == "user:usr-001:idempotency:req-xyz"


class TestMemoryIdempotencyAdapter:
    """MemoryIdempotencyAdapter 单元测试。"""

    def test_protocol_conformance(self) -> None:
        """验证符合 IdempotencyProtocol。"""
        adapter = MemoryIdempotencyAdapter()
        assert isinstance(adapter, IdempotencyProtocol)

    def test_acquire_lock_and_conflict(self) -> None:
        """测试正常加锁与并发抢占冲突。"""
        adapter = MemoryIdempotencyAdapter()

        # 首次抢占成功
        assert adapter.acquire_lock("k-001", "u-1", ttl_seconds=60) is True

        # 重复抢占，默认抛出 IdempotencyConflictError (409)
        with pytest.raises(IdempotencyConflictError, match="请求正在并发处理中"):
            adapter.acquire_lock("k-001", "u-1")

        # raise_on_conflict=False 时返回 False
        assert adapter.acquire_lock("k-001", "u-1", raise_on_conflict=False) is False

    def test_concurrent_competition_50_threads(self) -> None:
        """50 线程高并发抢占同一幂等键：有且仅有 1 次抢占成功，其余 49 次返回 False。"""
        adapter = MemoryIdempotencyAdapter()
        key = "shared-concurrent-key"
        user_id = "user-concurrent"

        def try_acquire(thread_id: int) -> bool:
            return adapter.acquire_lock(
                key=key,
                user_id=user_id,
                ttl_seconds=60,
                raise_on_conflict=False,
            )

        with ThreadPoolExecutor(max_workers=20) as executor:
            results = list(executor.map(try_acquire, range(50)))

        success_count = sum(1 for r in results if r is True)
        fail_count = sum(1 for r in results if r is False)

        assert success_count == 1
        assert fail_count == 49

    def test_set_and_get_result(self) -> None:
        """测试完成处理后持久化结果与响应回放。"""
        adapter = MemoryIdempotencyAdapter()
        key = "k-done"
        user_id = "user-100"

        adapter.acquire_lock(key, user_id)
        # 未完成前查询结果为 None
        assert adapter.get_result(key, user_id) is None

        # 写入结果快照
        mock_response = {"practice_id": "p-1", "score": 95}
        adapter.set_result(key, user_id, mock_response, ttl_seconds=3600)

        # 命中缓存结果
        cached = adapter.get_result(key, user_id)
        assert cached == mock_response

        # 已完成后再次尝试加锁抛 409
        with pytest.raises(IdempotencyConflictError):
            adapter.acquire_lock(key, user_id)

    def test_release_lock_allows_retry(self) -> None:
        """测试业务异常释放锁后允许重新加锁重试。"""
        adapter = MemoryIdempotencyAdapter()
        key = "k-retry"
        user_id = "user-100"

        adapter.acquire_lock(key, user_id)
        # 主动释放锁
        adapter.release_lock(key, user_id)

        # 再次抢占成功
        assert adapter.acquire_lock(key, user_id) is True

    def test_tenant_isolation(self) -> None:
        """测试不同租户使用相同幂等键相互隔离。"""
        adapter = MemoryIdempotencyAdapter()
        key = "same-business-id"

        # 用户 A 加锁成功
        assert adapter.acquire_lock(key, user_id="tenant-A") is True
        # 用户 B 加锁同一键同样成功（独立租户命名空间）
        assert adapter.acquire_lock(key, user_id="tenant-B") is True

        adapter.set_result(key, user_id="tenant-A", response_data={"from": "A"})
        adapter.set_result(key, user_id="tenant-B", response_data={"from": "B"})

        assert adapter.get_result(key, user_id="tenant-A") == {"from": "A"}
        assert adapter.get_result(key, user_id="tenant-B") == {"from": "B"}

    def test_permission_denied_defensive_check(self) -> None:
        """测试记录存在但归属 user_id 不一致时的防御阻断。"""
        adapter = MemoryIdempotencyAdapter()
        storage_key = build_idempotency_storage_key("tenant-A", "key-sec")
        adapter._records[storage_key] = IdempotencyRecord(
            key="key-sec",
            user_id="other-user",
            status="LOCKED",
            expire_at=9999999999.0,
        )

        with pytest.raises(PermissionDeniedError, match="无权操作幂等键"):
            adapter.acquire_lock("key-sec", user_id="tenant-A")

        with pytest.raises(PermissionDeniedError, match="无权操作幂等键"):
            adapter.set_result("key-sec", user_id="tenant-A", response_data={})

        with pytest.raises(PermissionDeniedError, match="无权访问幂等键"):
            adapter.get_result("key-sec", user_id="tenant-A")

        with pytest.raises(PermissionDeniedError, match="无权释放幂等键"):
            adapter.release_lock("key-sec", user_id="tenant-A")

    def test_ttl_expiration_with_mock_clock(self) -> None:
        """测试模拟时钟前进导致 TTL 过期失效与重新加锁。"""
        adapter = MemoryIdempotencyAdapter()
        current_time = 1000.0

        adapter.set_clock(lambda: current_time)

        # 加锁 60 秒 (expire_at = 1060.0)
        assert adapter.acquire_lock("k-exp", "u-1", ttl_seconds=60) is True

        # 时钟前进 30 秒，仍处于锁期
        current_time = 1030.0
        assert adapter.acquire_lock("k-exp", "u-1", raise_on_conflict=False) is False

        # 时钟前进到 1061 秒，锁已物理过期，允许新抢占
        current_time = 1061.0
        assert adapter.acquire_lock("k-exp", "u-1") is True

    def test_result_ttl_expiration(self) -> None:
        """测试结果快照到达 TTL 后过期返回 None。"""
        adapter = MemoryIdempotencyAdapter()
        current_time = 2000.0
        adapter.set_clock(lambda: current_time)

        adapter.acquire_lock("k-res-exp", "u-1")
        adapter.set_result("k-res-exp", "u-1", {"ok": True}, ttl_seconds=100)

        # 50 秒后仍有效
        current_time = 2050.0
        assert adapter.get_result("k-res-exp", "u-1") == {"ok": True}

        # 101 秒后已过期
        current_time = 2101.0
        assert adapter.get_result("k-res-exp", "u-1") is None

    def test_fault_injection(self) -> None:
        """测试故障注入。"""
        adapter = MemoryIdempotencyAdapter()
        adapter.set_fault_injection("acquire_lock", AppError(message="Lock driver crash"))

        with pytest.raises(AppError, match="Lock driver crash"):
            adapter.acquire_lock("k1", "u1")

        adapter.set_fault_injection("acquire_lock", None)
        assert adapter.acquire_lock("k1", "u1") is True

    def test_reset(self) -> None:
        """测试重置适配器。"""
        adapter = MemoryIdempotencyAdapter()
        adapter.acquire_lock("k1", "u1")
        adapter.reset()

        # 重置后应无记录，能再次加锁
        assert adapter.acquire_lock("k1", "u1") is True

    def test_repr_desensitization(self) -> None:
        """测试 repr 输出脱敏。"""
        adapter = MemoryIdempotencyAdapter()
        assert "<MemoryIdempotencyAdapter active_records=0>" in repr(adapter)

    def test_empty_user_id_validation(self) -> None:
        """测试各方法传入空 user_id 校验。"""
        adapter = MemoryIdempotencyAdapter()
        with pytest.raises(ValueError, match="user_id 不能为空"):
            adapter.acquire_lock("k1", "   ")

        with pytest.raises(ValueError, match="user_id 不能为空"):
            adapter.set_result("k1", "", {})

        with pytest.raises(ValueError, match="user_id 不能为空"):
            adapter.get_result("k1", "")

        with pytest.raises(ValueError, match="user_id 不能为空"):
            adapter.release_lock("k1", "")


class TestRedisIdempotencyAdapter:
    """RedisIdempotencyAdapter 单元测试（基于 Mock 客户端）。"""

    def test_protocol_conformance(self) -> None:
        """验证符合 IdempotencyProtocol。"""
        mock_client = MagicMock()
        adapter = RedisIdempotencyAdapter(redis_client=mock_client)
        assert isinstance(adapter, IdempotencyProtocol)

    def test_repr_masking(self) -> None:
        """测试连接密码掩码脱敏。"""
        mock_client = MagicMock()
        adapter = RedisIdempotencyAdapter(
            redis_url="redis://:pass12345@127.0.0.1:6379/2",
            redis_client=mock_client,
        )
        repr_str = repr(adapter)
        assert "pass12345" not in repr_str
        assert ":***@" in repr_str

    def test_acquire_lock_success(self) -> None:
        """测试通过 Redis SET NX EX 成功抢占。"""
        mock_client = MagicMock()
        mock_client.exists.return_value = False
        mock_client.set.return_value = True

        adapter = RedisIdempotencyAdapter(redis_client=mock_client)
        res = adapter.acquire_lock("req-01", "user-1", ttl_seconds=60)
        assert res is True
        mock_client.set.assert_called_with(
            "user:user-1:idempotency:req-01:lock",
            "LOCKED",
            nx=True,
            ex=60,
        )

    def test_acquire_lock_conflict_raises_409(self) -> None:
        """测试 Redis 锁已被抢占抛出 IdempotencyConflictError。"""
        mock_client = MagicMock()
        mock_client.exists.return_value = False
        mock_client.set.return_value = None  # NX 争抢失败

        adapter = RedisIdempotencyAdapter(redis_client=mock_client)
        with pytest.raises(IdempotencyConflictError, match="请求正在并发处理中"):
            adapter.acquire_lock("req-01", "user-1")

    def test_acquire_lock_when_result_already_exists(self) -> None:
        """测试结果快照已存在时加锁直接判定冲突。"""
        mock_client = MagicMock()
        mock_client.exists.return_value = True

        adapter = RedisIdempotencyAdapter(redis_client=mock_client)
        with pytest.raises(IdempotencyConflictError, match="请求正在并发处理中"):
            adapter.acquire_lock("req-01", "user-1")

    def test_acquire_lock_conflict_no_raise(self) -> None:
        """测试 raise_on_conflict=False 时返回 False。"""
        mock_client = MagicMock()
        mock_client.exists.return_value = False
        mock_client.set.return_value = None

        adapter = RedisIdempotencyAdapter(redis_client=mock_client)
        assert adapter.acquire_lock("req-01", "user-1", raise_on_conflict=False) is False

    def test_set_result_redis(self) -> None:
        """测试 Redis 保存结果快照并释放 lock。"""
        mock_client = MagicMock()
        adapter = RedisIdempotencyAdapter(redis_client=mock_client)

        adapter.set_result(
            "req-01",
            "user-1",
            {"status": "ok"},
            ttl_seconds=86400,
        )
        mock_client.set.assert_called_with(
            "user:user-1:idempotency:req-01:result",
            json.dumps({"status": "ok"}),
            ex=86400,
        )
        mock_client.delete.assert_called_with("user:user-1:idempotency:req-01:lock")

    def test_get_result_redis(self) -> None:
        """测试从 Redis 查询结果快照。"""
        mock_client = MagicMock()
        mock_client.get.return_value = json.dumps({"token": "xyz"})

        adapter = RedisIdempotencyAdapter(redis_client=mock_client)
        res = adapter.get_result("req-01", "user-1")
        assert res == {"token": "xyz"}

    def test_get_result_redis_not_found(self) -> None:
        """测试未命中结果快照返回 None。"""
        mock_client = MagicMock()
        mock_client.get.return_value = None

        adapter = RedisIdempotencyAdapter(redis_client=mock_client)
        assert adapter.get_result("req-01", "user-1") is None

    def test_release_lock_redis(self) -> None:
        """测试主动释放 Redis 锁。"""
        mock_client = MagicMock()
        adapter = RedisIdempotencyAdapter(redis_client=mock_client)

        adapter.release_lock("req-01", "user-1")
        mock_client.delete.assert_called_with("user:user-1:idempotency:req-01:lock")

    def test_redis_operation_failure_mapped(self) -> None:
        """测试 Redis 底层抛出异常被转译为 AppError。"""
        mock_client = MagicMock()
        mock_client.exists.side_effect = RuntimeError("Redis connection broken")

        adapter = RedisIdempotencyAdapter(redis_client=mock_client)
        with pytest.raises(AppError, match="Redis 幂等锁抢占失败"):
            adapter.acquire_lock("req-01", "user-1")

    def test_redis_empty_user_id_validation(self) -> None:
        """测试 Redis 适配器传入空 user_id 校验。"""
        mock_client = MagicMock()
        adapter = RedisIdempotencyAdapter(redis_client=mock_client)

        with pytest.raises(ValueError, match="user_id 不能为空"):
            adapter.acquire_lock("k1", " ")

        with pytest.raises(ValueError, match="user_id 不能为空"):
            adapter.set_result("k1", "", {})

        with pytest.raises(ValueError, match="user_id 不能为空"):
            adapter.get_result("k1", "")

        with pytest.raises(ValueError, match="user_id 不能为空"):
            adapter.release_lock("k1", "")

    def test_set_result_and_release_failure_mapped(self) -> None:
        """测试 set_result 与 release_lock 异常转译为 AppError。"""
        mock_client = MagicMock()
        mock_client.set.side_effect = RuntimeError("Write failure")
        mock_client.delete.side_effect = RuntimeError("Delete failure")

        adapter = RedisIdempotencyAdapter(redis_client=mock_client)
        with pytest.raises(AppError, match="持久化幂等结果失败"):
            adapter.set_result("k1", "u1", {})

        with pytest.raises(AppError, match="释放幂等锁失败"):
            adapter.release_lock("k1", "u1")

    def test_get_result_bytes_and_non_dict_and_failure(self) -> None:
        """测试 bytes 解码、非字典 JSON 与获取异常转译。"""
        mock_client = MagicMock()
        mock_client.get.return_value = json.dumps({"key": "val"}).encode("utf-8")

        adapter = RedisIdempotencyAdapter(redis_client=mock_client)
        res = adapter.get_result("k1", "u1")
        assert res == {"key": "val"}

        # 非字典 JSON（如 JSON 字符串）返回 None
        mock_client.get.return_value = json.dumps("plain-string")
        assert adapter.get_result("k1", "u1") is None

        # 抛出异常
        mock_client.get.side_effect = RuntimeError("Network error")
        with pytest.raises(AppError, match="获取幂等结果失败"):
            adapter.get_result("k1", "u1")

    def test_redis_init_missing_or_failed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试缺少 redis 模块或初始化连接失败。"""
        import sys

        monkeypatch.setitem(sys.modules, "redis", None)
        with pytest.raises(AppError, match="未安装 redis 依赖包"):
            RedisIdempotencyAdapter(redis_client=None)

        fake_redis = MagicMock()
        fake_redis.from_url.side_effect = RuntimeError("Failed connecting")
        monkeypatch.setitem(sys.modules, "redis", fake_redis)
        with pytest.raises(AppError, match="初始化 Redis 客户端连接失败"):
            RedisIdempotencyAdapter(redis_client=None)


class TestIdempotencyFactory:
    """create_idempotency_adapter 工厂方法测试。"""

    def test_create_memory_adapter(self) -> None:
        """测试分发 MemoryIdempotencyAdapter。"""
        adapter = create_idempotency_adapter("memory")
        assert isinstance(adapter, MemoryIdempotencyAdapter)

    def test_create_redis_adapter(self) -> None:
        """测试分发 RedisIdempotencyAdapter。"""
        mock_client = MagicMock()
        adapter = create_idempotency_adapter("redis", redis_client=mock_client)
        assert isinstance(adapter, RedisIdempotencyAdapter)

    def test_create_unsupported_adapter(self) -> None:
        """测试传入不支持的适配器类型抛出 AppError。"""
        with pytest.raises(AppError, match="不支持的幂等拦截器类型"):
            create_idempotency_adapter("zookeeper")
