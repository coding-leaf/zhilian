"""create_embedding_adapter 的 siliconflow 提供商单元测试（离线）。"""

import pytest

from app.core.errors import EmbeddingAuthError
from app.integrations.embedding.factory import create_embedding_adapter
from app.integrations.embedding.openai import OpenAICompatibleEmbeddingAdapter

SILICONFLOW_URL = "https://api.siliconflow.cn/v1"


def test_siliconflow_default_base_url() -> None:
    """siliconflow 缺省 base_url 为官方地址。"""
    adapter = create_embedding_adapter("siliconflow", api_key="sk-x")

    assert isinstance(adapter, OpenAICompatibleEmbeddingAdapter)
    assert adapter.base_url == SILICONFLOW_URL


def test_siliconflow_explicit_base_url_wins() -> None:
    """显式 base_url 优先。"""
    adapter = create_embedding_adapter(
        "siliconflow", api_key="sk-x", base_url="https://proxy.internal/v1"
    )

    assert isinstance(adapter, OpenAICompatibleEmbeddingAdapter)
    assert adapter.base_url == "https://proxy.internal/v1"


def test_siliconflow_type_is_normalized() -> None:
    """类型字符串去空白并大小写不敏感。"""
    adapter = create_embedding_adapter("  SiliconFlow ", api_key="sk-x")

    assert isinstance(adapter, OpenAICompatibleEmbeddingAdapter)
    assert adapter.base_url == SILICONFLOW_URL


@pytest.mark.parametrize("api_key", [None, ""])
def test_siliconflow_requires_api_key(api_key: str | None) -> None:
    """缺少 api_key 抛认证错误。"""
    with pytest.raises(EmbeddingAuthError):
        create_embedding_adapter("siliconflow", api_key=api_key)


def test_openai_default_base_url_not_siliconflow() -> None:
    """openai / dashscope 不套用 siliconflow 默认地址。"""
    for provider in ("openai", "dashscope"):
        adapter = create_embedding_adapter(provider, api_key="sk-x")
        assert isinstance(adapter, OpenAICompatibleEmbeddingAdapter)
        assert adapter.base_url != SILICONFLOW_URL
