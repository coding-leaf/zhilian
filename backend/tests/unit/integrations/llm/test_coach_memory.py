"""CoachSessionMemory 离线测试：滑动窗口 / TTL / LRU / 截断 / Redis 路径与降级。"""

import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.integrations.llm import coach_memory as cm
from app.integrations.llm.coach_memory import CoachSessionMemory, CoachTurn


class Clock:
    """可控的 time.monotonic 替身。"""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    fake = Clock()
    monkeypatch.setattr(cm, "time", SimpleNamespace(monotonic=fake))
    return fake


class DictRedis:
    """字典实现的 Redis 鸭子类型客户端，记录 ex 参数。"""

    def __init__(self, *, bytes_mode: bool = False) -> None:
        self.store: dict[str, Any] = {}
        self.ex: dict[str, int | None] = {}
        self.bytes_mode = bytes_mode

    def get(self, key: str) -> Any:
        value = self.store.get(key)
        if value is not None and self.bytes_mode:
            return value.encode("utf-8")
        return value

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value
        self.ex[key] = ex

    def delete(self, key: str) -> None:
        self.store.pop(key, None)


class TestInMemory:
    def test_roundtrip_and_empty_load(self) -> None:
        memory = CoachSessionMemory()
        assert memory.max_turns == 12
        assert memory.load("t") == []
        memory.append("t", "问题1", "回答1")
        memory.append("t", "问题2", "回答2")
        assert memory.load("t") == [CoachTurn("问题1", "回答1"), CoachTurn("问题2", "回答2")]

    def test_sliding_window_keeps_last_twelve(self) -> None:
        memory = CoachSessionMemory()
        for i in range(16):
            memory.append("t", f"q{i}", f"a{i}")
        turns = memory.load("t")
        assert [t.user for t in turns] == [f"q{i}" for i in range(4, 16)]

    def test_custom_max_turns_and_validation(self) -> None:
        memory = CoachSessionMemory(max_turns=2)
        for i in range(5):
            memory.append("t", f"q{i}", f"a{i}")
        assert [t.user for t in memory.load("t")] == ["q3", "q4"]
        with pytest.raises(ValueError, match="max_turns"):
            CoachSessionMemory(max_turns=0)

    @pytest.mark.parametrize(
        ("user", "assistant"), [("", "a"), ("q", ""), ("  ", "a"), ("q", " \n")]
    )
    def test_empty_turn_ignored(self, user: str, assistant: str) -> None:
        memory = CoachSessionMemory()
        memory.append("t", user, assistant)
        assert memory.load("t") == []

    def test_truncation_and_strip(self) -> None:
        memory = CoachSessionMemory()
        memory.append("t", "  " + "问" * 700 + "  ", "答" * 1100)
        (turn,) = memory.load("t")
        assert turn.user == "问" * 600
        assert turn.assistant == "答" * 1000

    def test_ttl_expiry(self, clock: Clock) -> None:
        memory = CoachSessionMemory(ttl_seconds=60)
        memory.append("t", "q", "a")
        clock.now += 59
        assert len(memory.load("t")) == 1
        clock.now += 2
        assert memory.load("t") == []
        # 过期条目被真正移除，之后追加从零开始
        memory.append("t", "q2", "a2")
        assert [t.user for t in memory.load("t")] == ["q2"]

    def test_load_does_not_extend_ttl_but_append_refreshes(self, clock: Clock) -> None:
        memory = CoachSessionMemory(ttl_seconds=60)
        memory.append("t", "q1", "a1")
        clock.now += 40
        memory.append("t", "q2", "a2")  # 重置 TTL
        clock.now += 40
        assert len(memory.load("t")) == 2

    def test_lru_eviction(self) -> None:
        memory = CoachSessionMemory(max_local_threads=2)
        memory.append("a", "q", "a")
        memory.append("b", "q", "a")
        memory.load("a")  # a 变为最近使用
        memory.append("c", "q", "a")  # 淘汰最久未用的 b
        assert memory.load("b") == []
        assert len(memory.load("a")) == 1
        assert len(memory.load("c")) == 1

    def test_threads_isolated_and_clear(self) -> None:
        memory = CoachSessionMemory()
        memory.append("u1:s:t", "q1", "a1")
        memory.append("u2:s:t", "q2", "a2")
        memory.clear("u1:s:t")
        assert memory.load("u1:s:t") == []
        assert [t.user for t in memory.load("u2:s:t")] == ["q2"]
        memory.clear("missing")  # 不存在也不抛错


class TestRedisPath:
    def test_roundtrip_stores_json_with_ttl_and_prefix(self) -> None:
        redis = DictRedis()
        memory = CoachSessionMemory(redis_client=redis, ttl_seconds=120)
        memory.append("t", "问", "答")
        key = "zhilian:coach:memory:t"
        assert key in redis.store
        assert redis.ex[key] == 120
        assert json.loads(redis.store[key]) == [{"user": "问", "assistant": "答"}]
        assert memory.load("t") == [CoachTurn("问", "答")]
        # Redis 成功时不写进程内缓存
        assert "t" not in memory._local

    def test_bytes_values_decoded(self) -> None:
        redis = DictRedis(bytes_mode=True)
        memory = CoachSessionMemory(redis_client=redis)
        memory.append("t", "问", "答")
        memory.append("t", "问2", "答2")
        assert [t.user for t in memory.load("t")] == ["问", "问2"]

    def test_window_applies_on_load_of_oversized_payload(self) -> None:
        redis = DictRedis()
        payload = [{"user": f"q{i}", "assistant": f"a{i}"} for i in range(16)]
        redis.store["zhilian:coach:memory:t"] = json.dumps(payload)
        memory = CoachSessionMemory(redis_client=redis)
        assert [t.user for t in memory.load("t")] == [f"q{i}" for i in range(4, 16)]

    def test_non_list_and_malformed_items(self) -> None:
        redis = DictRedis()
        memory = CoachSessionMemory(redis_client=redis)
        redis.store["zhilian:coach:memory:t"] = json.dumps({"user": "x"})
        assert memory.load("t") == []
        redis.store["zhilian:coach:memory:t"] = json.dumps(
            [{"user": "ok", "assistant": "ok"}, {"user": "missing"}, "junk", 3]
        )
        assert memory.load("t") == [CoachTurn("ok", "ok")]

    def test_corrupted_json_degrades_without_raising(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        redis = DictRedis()
        redis.store["zhilian:coach:memory:t"] = "{not json"
        memory = CoachSessionMemory(redis_client=redis)
        assert memory.load("t") == []  # 降级到（空的）内存
        assert "degraded" in caplog.text
        assert "not json" not in caplog.text

    def test_redis_errors_degrade_to_memory(self, caplog: pytest.LogCaptureFixture) -> None:
        class Broken:
            def get(self, key: str) -> Any:
                raise ConnectionError("secret-host")

            def set(self, key: str, value: str, ex: int | None = None) -> None:
                raise ConnectionError("secret-host")

            def delete(self, key: str) -> None:
                raise ConnectionError("secret-host")

        memory = CoachSessionMemory(redis_client=Broken())
        memory.append("t", "问", "答")  # 保存失败 -> 写入进程内
        assert memory.load("t") == [CoachTurn("问", "答")]  # 读取失败 -> 回落进程内
        memory.clear("t")  # delete 失败也不抛错
        assert memory.load("t") == []
        assert "ConnectionError" in caplog.text
        assert "secret-host" not in caplog.text
        assert "问" not in caplog.text

    def test_clear_removes_redis_key(self) -> None:
        redis = DictRedis()
        memory = CoachSessionMemory(redis_client=redis)
        memory.append("t", "问", "答")
        memory.clear("t")
        assert redis.store == {}
        assert memory.load("t") == []

    def test_clear_without_delete_method(self) -> None:
        class NoDelete:
            def get(self, key: str) -> Any:
                return None

            def set(self, key: str, value: str, ex: int | None = None) -> None:
                return None

        memory = CoachSessionMemory(redis_client=NoDelete())
        memory.clear("t")  # 无 delete 能力时静默
