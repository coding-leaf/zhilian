"""混合检索适配器纯内存假实现模块。

严格遵循 AGENTS.md 规范：
- 专为单元测试与无数据库环境设计，零外部套接字连接；
- 强租户隔离门禁：缺失 user_id 严厉抛出 PermissionDeniedError；
- 内部基于 threading.Lock 保障多线程并发安全；
- 支持预置结果映射、候选集配置、模拟延迟与故障注入；
- 绝密脱敏防泄露。
"""

import threading
import time
import uuid
from collections.abc import Sequence

from app.core.errors import PermissionDeniedError
from app.integrations.search.protocol import (
    SearchOptions,
    SearchProtocol,
    SearchResult,
    SearchSnippetCandidate,
)


class FakeSearchAdapter(SearchProtocol):
    """纯内存假混合检索适配器。"""

    def __init__(self) -> None:
        """初始化假检索适配器。"""
        self._lock = threading.Lock()
        self._canned_results: dict[str, SearchResult] = {}
        self._canned_candidates: list[SearchSnippetCandidate] = []
        self._fault_injections: dict[str, Exception] = {}
        self._latency_seconds: float = 0.0

    def set_canned_result(self, key: str, result: SearchResult) -> None:
        """针对特定检索 Key 预置完整 SearchResult。

        Args:
            key: 匹配键（如 query 或 "user_id:query"）。
            result: 预置结果对象。
        """
        with self._lock:
            self._canned_results[key] = result

    def set_canned_candidates(self, candidates: Sequence[SearchSnippetCandidate]) -> None:
        """设置全局默认可供检索切片候选集合。

        Args:
            candidates: 预设候选切片列表。
        """
        with self._lock:
            self._canned_candidates = list(candidates)

    def set_latency(self, seconds: float) -> None:
        """设置模拟检索时延时长。

        Args:
            seconds: 延迟秒数。
        """
        with self._lock:
            self._latency_seconds = max(0.0, seconds)

    def set_fault_injection(self, key: str, exception: Exception) -> None:
        """注入特定场景或匹配键下的模拟异常。

        Args:
            key: 故障匹配键 (如 "search", query 或 user_id 字符串)。
            exception: 待抛出异常实例。
        """
        with self._lock:
            self._fault_injections[key] = exception

    def reset(self) -> None:
        """重置所有预置结果、候选切片集、注入故障与时延。"""
        with self._lock:
            self._canned_results.clear()
            self._canned_candidates.clear()
            self._fault_injections.clear()
            self._latency_seconds = 0.0

    def search(
        self,
        query: str,
        user_id: uuid.UUID,
        material_id: uuid.UUID | None = None,
        version_id: uuid.UUID | None = None,
        options: SearchOptions | None = None,
    ) -> SearchResult:
        """执行多租户强隔离的假检索。

        Args:
            query: 用户查询文本。
            user_id: 租户用户 ID（不可为空）。
            material_id: 可选资料 ID。
            version_id: 可选版本 ID。
            options: 可选检索选项。

        Returns:
            SearchResult: 检索结果。

        Raises:
            PermissionDeniedError: user_id 缺失或为空。
        """
        if not user_id:
            raise PermissionDeniedError("user_id 不能为空")

        opts = options or SearchOptions()

        with self._lock:
            if self._latency_seconds > 0.0:
                time.sleep(self._latency_seconds)

            user_str = str(user_id)
            # 故障注入检查
            if "search" in self._fault_injections:
                raise self._fault_injections["search"]
            if query in self._fault_injections:
                raise self._fault_injections[query]
            if user_str in self._fault_injections:
                raise self._fault_injections[user_str]

            # 预置精确匹配
            compound_key = f"{user_str}:{query}"
            if compound_key in self._canned_results:
                return self._canned_results[compound_key]
            if query in self._canned_results:
                return self._canned_results[query]

            # 候选集过滤
            filtered_candidates: list[SearchSnippetCandidate] = []
            for c in self._canned_candidates:
                if material_id is not None and c.material_id != material_id:
                    continue
                if version_id is not None and c.version_id != version_id:
                    continue
                filtered_candidates.append(c)

            top_candidates = filtered_candidates[: opts.top_k]
            return SearchResult(
                query=query,
                items=top_candidates,
                total_candidates=len(filtered_candidates),
                duration_ms=self._latency_seconds * 1000.0,
            )

    def __repr__(self) -> str:
        """安全脱敏日志展示。"""
        with self._lock:
            return (
                f"FakeSearchAdapter(canned_results={len(self._canned_results)}, "
                f"canned_candidates={len(self._canned_candidates)}, "
                f"latency={self._latency_seconds})"
            )


__all__ = ["FakeSearchAdapter"]
