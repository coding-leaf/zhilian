"""智练向量化适配器包。

严格遵循 AGENTS.md 规范：
- 通过 Protocol 抽象接口与外部大模型提供商解耦；
- 缩写白名单仅限 8 个；
- __all__ 严格维持 ASCII 字典序。
"""

from app.integrations.embedding.factory import create_embedding_adapter
from app.integrations.embedding.fake import FakeEmbeddingAdapter
from app.integrations.embedding.openai import OpenAICompatibleEmbeddingAdapter
from app.integrations.embedding.protocol import (
    EmbeddingOptions,
    EmbeddingProtocol,
    EmbeddingResult,
)

__all__ = [
    "EmbeddingOptions",
    "EmbeddingProtocol",
    "EmbeddingResult",
    "FakeEmbeddingAdapter",
    "OpenAICompatibleEmbeddingAdapter",
    "create_embedding_adapter",
]
