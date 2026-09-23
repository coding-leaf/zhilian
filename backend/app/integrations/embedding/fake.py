"""向量化适配器纯内存假实现模块。

严格遵循 AGENTS.md 规范：
- 专为单元测试与无网络环境设计，零外部套接字连接；
- 内部基于 threading.Lock 保障多线程并发安全；
- 基于文本 SHA-256 摘要种子生成确定性 1024 维 L2 归一化向量；
- 支持预置向量映射、模拟延迟与异常注入；
- 绝密脱敏防泄露。
"""

import hashlib
import math
import random
import threading
import time
from collections.abc import Sequence

from app.integrations.embedding.protocol import (
    EmbeddingOptions,
    EmbeddingProtocol,
)


class FakeEmbeddingAdapter(EmbeddingProtocol):
    """纯内存假向量化适配器实现。"""

    def __init__(self) -> None:
        """初始化假向量化适配器。"""
        self._lock = threading.Lock()
        self._canned_vectors: dict[str, list[float]] = {}
        self._fault_injections: dict[str, Exception] = {}
        self._latency_seconds: float = 0.0

    def set_canned_vector(self, text: str, vector: Sequence[float]) -> None:
        """针对指定文本预置特定的返回向量。

        Args:
            text: 匹配文本键。
            vector: 预置的 1024 维向量序列。
        """
        with self._lock:
            self._canned_vectors[text] = list(vector)

    def set_latency(self, seconds: float) -> None:
        """设置模拟网络调用延迟时长。

        Args:
            seconds: 延迟秒数。
        """
        with self._lock:
            self._latency_seconds = max(0.0, seconds)

    def set_fault_injection(self, key: str, exception: Exception) -> None:
        """注入指定场景或文本匹配时抛出的模拟异常。

        Args:
            key: 故障匹配键 (如 "query", "documents" 或具体文本)。
            exception: 待抛出的异常实例。
        """
        with self._lock:
            self._fault_injections[key] = exception

    def reset(self) -> None:
        """重置所有预置结果、注入故障与模拟时延。"""
        with self._lock:
            self._canned_vectors.clear()
            self._fault_injections.clear()
            self._latency_seconds = 0.0

    def _generate_deterministic_vector(self, text: str, dimensions: int = 1024) -> list[float]:
        """基于文本的 SHA-256 哈希确定性生成 L2 归一化伪随机浮点向量。

        Args:
            text: 输入文本。
            dimensions: 向量目标维度，默认 1024。

        Returns:
            list[float]: L2 模长为 1.0 的确定性浮点向量。
        """
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        seed_int = int(digest[:16], 16)
        rng = random.Random(seed_int)  # noqa: S311

        raw = [rng.uniform(-1.0, 1.0) for _ in range(dimensions)]
        norm = math.sqrt(sum(x * x for x in raw))
        if norm <= 0.0:
            return [1.0] + [0.0] * (dimensions - 1)
        return [x / norm for x in raw]

    def embed_query(
        self,
        text: str,
        options: EmbeddingOptions | None = None,
    ) -> list[float]:
        """将单个查询文本编码为 1024 维定长浮点向量。

        Args:
            text: 待编码文本。
            options: 可选的模型与调用配置。

        Returns:
            list[float]: 1024 维浮点向量。
        """
        dimensions = options.dimensions if options else 1024

        with self._lock:
            if self._latency_seconds > 0.0:
                time.sleep(self._latency_seconds)

            # 故障注入拦截
            if "query" in self._fault_injections:
                raise self._fault_injections["query"]
            if text in self._fault_injections:
                raise self._fault_injections[text]

            # 预置返回拦截
            if text in self._canned_vectors:
                return list(self._canned_vectors[text])

        return self._generate_deterministic_vector(text, dimensions)

    def embed_documents(
        self,
        texts: Sequence[str],
        options: EmbeddingOptions | None = None,
    ) -> list[list[float]]:
        """批量将多个文档文本编码为 1024 维定长浮点向量列表。

        Args:
            texts: 待编码的文档文本序列。
            options: 可选的模型与调用配置。

        Returns:
            list[list[float]]: 包含等量 1024 维向量的列表。
        """
        dimensions = options.dimensions if options else 1024

        with self._lock:
            if self._latency_seconds > 0.0:
                time.sleep(self._latency_seconds)

            if "documents" in self._fault_injections:
                raise self._fault_injections["documents"]

        results: list[list[float]] = []
        for text in texts:
            with self._lock:
                if text in self._fault_injections:
                    raise self._fault_injections[text]
                if text in self._canned_vectors:
                    results.append(list(self._canned_vectors[text]))
                    continue
            results.append(self._generate_deterministic_vector(text, dimensions))

        return results

    def __repr__(self) -> str:
        """安全脱敏日志展示，严禁打印向量值或文本内容。"""
        with self._lock:
            return (
                f"FakeEmbeddingAdapter(canned_count={len(self._canned_vectors)}, "
                f"latency={self._latency_seconds})"
            )


__all__ = ["FakeEmbeddingAdapter"]
