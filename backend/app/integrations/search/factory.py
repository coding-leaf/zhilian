"""混合检索适配器工厂模块。

严格遵循 AGENTS.md 规范：
- 支持 Fake 与 PgvectorHybrid 适配器按需分发构建；
- 缩写白名单限定。
"""

from typing import Any

from app.core.errors import SearchError
from app.integrations.embedding.protocol import EmbeddingProtocol
from app.integrations.search.fake import FakeSearchAdapter
from app.integrations.search.pgvector import PgvectorHybridSearchAdapter
from app.integrations.search.protocol import SearchProtocol


def create_search_adapter(
    adapter_type: str = "fake",
    *,
    session_factory: Any | None = None,
    embedding_adapter: EmbeddingProtocol | None = None,
) -> SearchProtocol:
    """根据类型与依赖创建混合检索适配器实例。

    Args:
        adapter_type: 适配器类型 ("fake", "pgvector", "postgres", "hybrid")。
        session_factory: 数据库会话工厂 (pgvector 模式下必填)。
        embedding_adapter: 向量化适配器 (pgvector 模式下必填)。

    Returns:
        SearchProtocol: 混合检索适配器实例。

    Raises:
        SearchError: 依赖缺失或不支持的类型。
    """
    normalized_type = adapter_type.strip().lower()
    if normalized_type == "fake":
        return FakeSearchAdapter()

    if normalized_type in ("pgvector", "postgres", "hybrid"):
        if session_factory is None:
            raise SearchError("pgvector 混合检索适配器必须提供 session_factory")
        if embedding_adapter is None:
            raise SearchError("pgvector 混合检索适配器必须提供 embedding_adapter")
        return PgvectorHybridSearchAdapter(
            session_factory=session_factory,
            embedding_adapter=embedding_adapter,
        )

    raise SearchError(f"不支持的检索适配器类型: {adapter_type}")


__all__ = ["create_search_adapter"]
