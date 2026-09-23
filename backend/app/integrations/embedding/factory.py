"""向量化适配器工厂模块。

严格遵循 AGENTS.md 规范：
- 支持 Fake 与 OpenAI 兼容适配器按需分发构建；
- 缩写白名单限定。
"""

from typing import Any

from app.core.errors import EmbeddingAuthError, EmbeddingError
from app.integrations.embedding.fake import FakeEmbeddingAdapter
from app.integrations.embedding.openai import OpenAICompatibleEmbeddingAdapter
from app.integrations.embedding.protocol import EmbeddingProtocol


def create_embedding_adapter(
    adapter_type: str = "fake",
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str = "text-embedding-v3",
    dimensions: int = 1024,
    timeout: float = 20.0,
    max_retries: int = 3,
    client: Any | None = None,
) -> EmbeddingProtocol:
    """根据类型与配置创建向量化适配器实例。

    Args:
        adapter_type: 适配器类型 ("fake", "openai", "dashscope")。
        api_key: 大模型访问密钥 (非 fake 模式下必须提供)。
        base_url: 接口基础 URL。
        model: 模型名称。
        dimensions: 向量目标维度。
        timeout: 超时上限 (秒)。
        max_retries: 最大重试次数。
        client: 可选外部注入的 HTTP 客户端。

    Returns:
        EmbeddingProtocol: 向量化适配器实例。

    Raises:
        EmbeddingAuthError: 未提供必需的 API 凭据。
        EmbeddingError: 不支持的适配器类型。
    """
    normalized_type = adapter_type.strip().lower()
    if normalized_type == "fake":
        return FakeEmbeddingAdapter()
    if normalized_type in ("openai", "dashscope"):
        if not api_key:
            raise EmbeddingAuthError("OpenAI 兼容向量化适配器必须提供 api_key")
        return OpenAICompatibleEmbeddingAdapter(
            api_key=api_key,
            base_url=base_url,
            model=model,
            dimensions=dimensions,
            timeout=timeout,
            max_retries=max_retries,
            client=client,
        )

    raise EmbeddingError(f"不支持的向量化适配器类型: {adapter_type}")


__all__ = ["create_embedding_adapter"]
