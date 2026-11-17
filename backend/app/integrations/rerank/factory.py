"""重排适配器工厂：fake / siliconflow（及 openai-compatible 别名）。"""

from typing import Any

from app.core.errors import SearchError
from app.integrations.rerank.fake import FakeRerankAdapter
from app.integrations.rerank.protocol import RerankProtocol
from app.integrations.rerank.siliconflow import SiliconFlowRerankAdapter

_REMOTE_TYPES = ("siliconflow", "openai-compatible", "openai_compatible", "openai")


def create_rerank_adapter(
    adapter_type: str = "fake",
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str = "BAAI/bge-reranker-v2-m3",
    timeout: float = 15.0,
    max_retries: int = 2,
    client: Any | None = None,
) -> RerankProtocol:
    """根据类型与配置创建重排适配器。

    Args:
        adapter_type: "fake" / "siliconflow" / "openai-compatible"（别名）。
        api_key: 非 fake 类型必填。
        base_url: 接口基础 URL，None 使用 SiliconFlow 默认地址。
        model: 重排模型名称。
        timeout: 超时（秒）。
        max_retries: 最大重试次数。
        client: 可选注入 HTTP 客户端。

    Returns:
        RerankProtocol: 重排适配器。

    Raises:
        SearchError: 缺少 api_key 或类型不受支持。
    """
    normalized = adapter_type.strip().lower()
    if normalized == "fake":
        return FakeRerankAdapter()
    if normalized in _REMOTE_TYPES:
        if not api_key or not api_key.strip():
            raise SearchError("重排适配器必须提供 api_key")
        return SiliconFlowRerankAdapter(
            api_key=api_key,
            base_url=base_url or "https://api.siliconflow.cn/v1",
            model=model,
            timeout=timeout,
            max_retries=max_retries,
            client=client,
        )
    raise SearchError(f"不支持的重排适配器类型: {adapter_type}")


__all__ = ["create_rerank_adapter"]
