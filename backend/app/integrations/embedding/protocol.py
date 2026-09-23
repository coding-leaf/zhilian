"""向量化适配器抽象协议与数据模型定义模块。

严格遵循 AGENTS.md 规范：
- 通过 Protocol 抽象接口与外部供应商解耦；
- 强类型不可变模型定义，零框架业务依赖；
- 缩写白名单仅限 8 个 (api, id, url, ocr, llm, db, config, env)。
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class EmbeddingOptions:
    """向量化调用配置选项。"""

    model: str = "text-embedding-v3"
    dimensions: int = 1024
    timeout: float = 20.0

    def __post_init__(self) -> None:
        """防御性参数合法性校验。"""
        if self.dimensions <= 0:
            raise ValueError("dimensions must be greater than 0")
        if self.timeout <= 0.0:
            raise ValueError("timeout must be greater than 0")


@dataclass(frozen=True)
class EmbeddingResult:
    """单次向量化调用返回结果数据模型。"""

    vector: Sequence[float]
    tokens: int = 0
    duration_ms: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.vector, tuple):
            object.__setattr__(self, "vector", tuple(self.vector))


@runtime_checkable
class EmbeddingProtocol(Protocol):
    """向量化适配器抽象协议契约。

    定义与外部具体大模型提供商解耦的定长向量嵌入接口。
    """

    def embed_query(
        self,
        text: str,
        options: EmbeddingOptions | None = None,
    ) -> list[float]:
        """将单个查询文本编码为 1024 维定长浮点向量。

        Args:
            text: 待编码的用户检索或考点文本。
            options: 可选的模型与调用配置。

        Returns:
            list[float]: 长度为 1024 的定长浮点向量。

        Raises:
            EmbeddingError: 编码失败或服务异常。
            EmbeddingTimeoutError: 调用响应超时。
            EmbeddingAuthError: 凭据鉴权拒绝。
        """
        ...

    def embed_documents(
        self,
        texts: Sequence[str],
        options: EmbeddingOptions | None = None,
    ) -> list[list[float]]:
        """批量将多个文档文本编码为 1024 维定长浮点向量列表。

        Args:
            texts: 待编码的切片文本序列。
            options: 可选的模型与调用配置。

        Returns:
            list[list[float]]: 长度与输入一致的 1024 维浮点向量列表。

        Raises:
            EmbeddingError: 编码失败或服务异常。
            EmbeddingTimeoutError: 调用响应超时。
            EmbeddingAuthError: 凭据鉴权拒绝。
        """
        ...


__all__ = [
    "EmbeddingOptions",
    "EmbeddingProtocol",
    "EmbeddingResult",
]
