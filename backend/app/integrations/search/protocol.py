"""混合检索适配器抽象协议与数据模型定义模块。

严格遵循 AGENTS.md 规范：
- 通过 Protocol 抽象接口支持 Fake 与 Pgvector 生产实现无缝切换；
- 强类型不可变模型定义，多租户隔离与安全脱敏；
- 缩写白名单仅限 8 个 (api, id, url, ocr, llm, db, config, env)。
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class SearchSnippetCandidate:
    """检索命中的候选知识切片数据契约。"""

    snippet_id: uuid.UUID
    material_id: uuid.UUID
    version_id: uuid.UUID
    content: str
    chapter_title: str
    source_info: dict[str, Any]
    vector_score: float = 0.0
    bm25_score: float = 0.0
    final_score: float = 0.0
    vector_rank: int | None = None
    bm25_rank: int | None = None

    def __repr__(self) -> str:
        """安全脱敏，禁止在日志中泄露切片文本全文。"""
        return (
            f"<SearchCandidate id={self.snippet_id} score={self.final_score:.4f} "
            f"vec_rank={self.vector_rank} bm25_rank={self.bm25_rank}>"
        )


@dataclass(frozen=True)
class SearchOptions:
    """混合检索运行参数选项。"""

    top_k: int = 4
    vector_top_k: int = 20
    fusion_method: str = "rrf"  # "rrf" 或 "weighted"
    rrf_k: int = 60
    vector_weight: float = 0.7
    keyword_weight: float = 0.3

    def __post_init__(self) -> None:
        """防御性参数合法性校验。"""
        if self.top_k <= 0:
            raise ValueError("top_k must be greater than 0")
        if self.vector_top_k < self.top_k:
            raise ValueError("vector_top_k must be greater than or equal to top_k")
        if self.fusion_method not in ("rrf", "weighted"):
            raise ValueError("fusion_method must be either 'rrf' or 'weighted'")


@dataclass(frozen=True)
class SearchResult:
    """混合检索执行结果数据模型。"""

    query: str
    items: Sequence[SearchSnippetCandidate] = field(default_factory=tuple)
    total_candidates: int = 0
    duration_ms: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.items, tuple):
            object.__setattr__(self, "items", tuple(self.items))


@runtime_checkable
class SearchProtocol(Protocol):
    """混合检索适配器抽象协议。"""

    def search(
        self,
        query: str,
        user_id: uuid.UUID,
        material_id: uuid.UUID | None = None,
        version_id: uuid.UUID | None = None,
        options: SearchOptions | None = None,
    ) -> SearchResult:
        """执行多租户强隔离的混合语义检索。

        Args:
            query: 用户检索或出题考点关键词查询文本。
            user_id: 归属用户唯一标识（必须提供，严禁越权）。
            material_id: 可选的资料主键范围限定。
            version_id: 可选的资料版本标识范围限定。
            options: 可选的检索与融合配置。

        Returns:
            SearchResult: 包含 Top 4 优质切片与融合分数的结构化结果。

        Raises:
            PermissionDeniedError: user_id 缺失或为空。
            SearchError: 检索执行异常。
            EmbeddingError: 查询向量化失败。
        """
        ...


__all__ = [
    "SearchOptions",
    "SearchProtocol",
    "SearchResult",
    "SearchSnippetCandidate",
]
