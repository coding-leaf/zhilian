"""智练混合检索适配器包。

严格遵循 AGENTS.md 规范：
- 通过 Protocol 抽象接口解耦业务与底层向量检索实现；
- 缩写白名单仅限 8 个；
- __all__ 严格维持 ASCII 字典序。
"""

from app.integrations.search.factory import create_search_adapter
from app.integrations.search.fake import FakeSearchAdapter
from app.integrations.search.pgvector import PgvectorHybridSearchAdapter
from app.integrations.search.protocol import (
    SearchOptions,
    SearchProtocol,
    SearchResult,
    SearchSnippetCandidate,
)

__all__ = [
    "FakeSearchAdapter",
    "PgvectorHybridSearchAdapter",
    "SearchOptions",
    "SearchProtocol",
    "SearchResult",
    "SearchSnippetCandidate",
    "create_search_adapter",
]
