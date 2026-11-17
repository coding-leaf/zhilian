"""课程助教多轮会话滑动窗口记忆 (CoachSessionMemory)。

- 仅保留最近 N 轮 (默认 6 轮) 的 (用户问题, 助教回复)，24 小时 TTL；
- 优先落 Redis（跨进程/重启可用，鸭子类型客户端：get/set），无 Redis 时降级为进程内 LRU；
- 零数据库迁移，离线单测零网络；
- 任何 Redis 故障只降级为内存，绝不阻断问答；日志只记录异常类型，从不记录会话内容。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MAX_TURNS = 6
DEFAULT_TTL_SECONDS = 24 * 3600
DEFAULT_MAX_LOCAL_THREADS = 512
_MAX_USER_CHARS = 500
_MAX_ASSISTANT_CHARS = 800
_REDIS_KEY_PREFIX = "zhilian:coach:memory:"


@dataclass(frozen=True)
class CoachTurn:
    """一轮对话：学生提问与助教回复。"""

    user: str
    assistant: str


def _truncate(text: str, limit: int) -> str:
    stripped = text.strip()
    return stripped if len(stripped) <= limit else stripped[:limit]


class CoachSessionMemory:
    """线程安全的滑动窗口会话记忆，键为调用方构造的租户隔离 thread key。"""

    def __init__(
        self,
        *,
        redis_client: Any | None = None,
        max_turns: int = DEFAULT_MAX_TURNS,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        max_local_threads: int = DEFAULT_MAX_LOCAL_THREADS,
    ) -> None:
        if max_turns <= 0:
            raise ValueError("max_turns must be greater than 0")
        self._redis = redis_client
        self._max_turns = max_turns
        self._ttl_seconds = ttl_seconds
        self._max_local_threads = max_local_threads
        self._lock = threading.Lock()
        self._local: OrderedDict[str, tuple[float, list[CoachTurn]]] = OrderedDict()

    @property
    def max_turns(self) -> int:
        """窗口保留的最大轮数。"""
        return self._max_turns

    def load(self, thread_key: str) -> list[CoachTurn]:
        """读取线程最近的对话轮次（旧 -> 新）；不存在或过期返回空列表。"""
        if self._redis is not None:
            try:
                raw = self._redis.get(self._redis_key(thread_key))
                return self._decode(raw)
            except Exception as exc:
                logger.warning("coach memory redis load degraded: %s", type(exc).__name__)
        with self._lock:
            entry = self._local.get(thread_key)
            if entry is None:
                return []
            expires_at, turns = entry
            if expires_at <= time.monotonic():
                self._local.pop(thread_key, None)
                return []
            self._local.move_to_end(thread_key)
            return list(turns)

    def append(self, thread_key: str, user: str, assistant: str) -> None:
        """追加一轮对话并裁剪到滑动窗口大小。"""
        turn = CoachTurn(
            user=_truncate(user, _MAX_USER_CHARS),
            assistant=_truncate(assistant, _MAX_ASSISTANT_CHARS),
        )
        if not turn.user or not turn.assistant:
            return
        turns = [*self.load(thread_key), turn][-self._max_turns :]
        if self._redis is not None:
            try:
                self._redis.set(
                    self._redis_key(thread_key),
                    self._encode(turns),
                    ex=self._ttl_seconds,
                )
                return
            except Exception as exc:
                logger.warning("coach memory redis save degraded: %s", type(exc).__name__)
        with self._lock:
            self._local[thread_key] = (time.monotonic() + self._ttl_seconds, turns)
            self._local.move_to_end(thread_key)
            while len(self._local) > self._max_local_threads:
                self._local.popitem(last=False)

    def clear(self, thread_key: str) -> None:
        """清除线程记忆。"""
        with self._lock:
            self._local.pop(thread_key, None)
        delete = getattr(self._redis, "delete", None)
        if callable(delete):
            try:
                delete(self._redis_key(thread_key))
            except Exception as exc:
                logger.warning("coach memory redis clear degraded: %s", type(exc).__name__)

    @staticmethod
    def _redis_key(thread_key: str) -> str:
        return f"{_REDIS_KEY_PREFIX}{thread_key}"

    @staticmethod
    def _encode(turns: list[CoachTurn]) -> str:
        return json.dumps(
            [{"user": t.user, "assistant": t.assistant} for t in turns], ensure_ascii=False
        )

    def _decode(self, raw: Any) -> list[CoachTurn]:
        if raw is None:
            return []
        text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        payload = json.loads(text)
        if not isinstance(payload, list):
            return []
        turns = [
            CoachTurn(user=str(item["user"]), assistant=str(item["assistant"]))
            for item in payload
            if isinstance(item, dict) and "user" in item and "assistant" in item
        ]
        return turns[-self._max_turns :]


__all__ = ["CoachSessionMemory", "CoachTurn"]
