"""基于 pgvector 与 BM25 的混合语义检索适配器实现。

严格遵循 AGENTS.md 规范：
- 强租户隔离门禁：必须携带并校验 user_id，严防水平越权；
- 两阶段检索编排：向量粗排 (Top 20) + BM25 关键词精排 + 排序融合 + 截断 (Top 4)；
- 数据库方言自适应：PostgreSQL 下利用 HNSW <=> 排序，SQLite 单测环境下纯函数平滑回退；
- 绝密脱敏防泄露：严禁在日志中打印文档切片内容。
"""

import time
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.algorithms.search import (
    compute_bm25_score,
    cosine_similarity,
    reciprocal_rank_fusion,
    tokenize_text,
    weighted_score_fusion,
)
from app.core.errors import (
    AppError,
    EmbeddingError,
    PermissionDeniedError,
    SearchError,
)
from app.integrations.embedding.protocol import EmbeddingProtocol
from app.integrations.search.protocol import (
    SearchOptions,
    SearchProtocol,
    SearchResult,
    SearchSnippetCandidate,
)
from app.models.material import MaterialSnippet


class PgvectorHybridSearchAdapter(SearchProtocol):
    """基于 pgvector 与 BM25 的混合检索执行器。"""

    def __init__(
        self,
        session_factory: sessionmaker[Session] | Any,
        embedding_adapter: EmbeddingProtocol,
    ) -> None:
        """初始化混合检索适配器。

        Args:
            session_factory: 数据库会话工厂生成器。
            embedding_adapter: 向量化适配器实例。
        """
        self._session_factory = session_factory
        self._embedding_adapter = embedding_adapter

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
        if not user_id:
            raise PermissionDeniedError("user_id 不能为空")

        search_options = options or SearchOptions()
        start_time = time.perf_counter()

        try:
            # 步骤 1: 向量化查询文本
            query_vector = self._embedding_adapter.embed_query(query)
            if not query_vector:
                raise EmbeddingError("生成查询向量结果为空")

            # 步骤 2: 数据库向量粗排 Top 20 (强制租户隔离)
            snippets: list[MaterialSnippet] = []
            with self._session_factory() as session:
                is_sqlite = session.bind is not None and session.bind.dialect.name == "sqlite"

                stmt = select(MaterialSnippet).where(MaterialSnippet.user_id == user_id)
                if material_id is not None:
                    stmt = stmt.where(MaterialSnippet.material_id == material_id)
                if version_id is not None:
                    stmt = stmt.where(MaterialSnippet.version_id == version_id)

                if is_sqlite:
                    # SQLite 单元测试环境下回退为纯函数计算余弦相似度粗排
                    sqlite_candidates: list[MaterialSnippet] = list(session.scalars(stmt).all())
                    scored_candidates = sorted(
                        sqlite_candidates,
                        key=lambda s: (
                            cosine_similarity(query_vector, s.embedding) if s.embedding else 0.0
                        ),
                        reverse=True,
                    )
                    snippets = scored_candidates[: search_options.vector_top_k]
                else:
                    # PostgreSQL 生产环境下使用 pgvector 余弦距离运算符 <=>
                    stmt = stmt.order_by(
                        MaterialSnippet.embedding.cosine_distance(query_vector).asc()
                    ).limit(search_options.vector_top_k)
                    snippets = list(session.scalars(stmt).all())

            # 若未召回任何切片候选集，直接返回空结果
            if not snippets:
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                return SearchResult(
                    query=query,
                    items=(),
                    total_candidates=0,
                    duration_ms=duration_ms,
                )

            # 步骤 3: 关键词 BM25 细粒度打分
            query_tokens = tokenize_text(query)
            all_doc_tokens: list[list[str]] = [tokenize_text(s.content) for s in snippets]
            total_docs = len(snippets)
            doc_lengths = [len(tokens) for tokens in all_doc_tokens]
            avg_doc_len = sum(doc_lengths) / total_docs if total_docs > 0 else 1.0

            # 统计词元文档频次
            doc_frequencies: dict[str, int] = {}
            for tokens in all_doc_tokens:
                for token in set(tokens):
                    doc_frequencies[token] = doc_frequencies.get(token, 0) + 1

            snippet_vector_scores: dict[str, float] = {}
            snippet_bm25_scores: dict[str, float] = {}
            snippet_map: dict[str, MaterialSnippet] = {}

            for s, tokens, d_len in zip(snippets, all_doc_tokens, doc_lengths, strict=False):
                sid_str = str(s.id)
                snippet_map[sid_str] = s
                # 计算向量相似度得分
                vec_score = cosine_similarity(query_vector, s.embedding) if s.embedding else 0.0
                snippet_vector_scores[sid_str] = vec_score

                # 计算 BM25 得分
                bm25_score = compute_bm25_score(
                    query_tokens=query_tokens,
                    doc_tokens=tokens,
                    doc_length=d_len,
                    avg_doc_length=avg_doc_len,
                    doc_frequencies=doc_frequencies,
                    total_docs=total_docs,
                )
                snippet_bm25_scores[sid_str] = bm25_score

            # 确定各通道名次 (1-indexed，原地优化字典取值，避免高频二次查找)
            sorted_vec_ids = sorted(
                snippet_vector_scores,
                key=snippet_vector_scores.__getitem__,
                reverse=True,
            )
            vec_ranks = {sid: rank for rank, sid in enumerate(sorted_vec_ids, start=1)}

            sorted_bm25_ids = sorted(
                snippet_bm25_scores,
                key=snippet_bm25_scores.__getitem__,
                reverse=True,
            )
            bm25_ranks = {sid: rank for rank, sid in enumerate(sorted_bm25_ids, start=1)}

            # 步骤 4: 排名 / 打分融合
            if search_options.fusion_method == "rrf":
                fused = reciprocal_rank_fusion(
                    [sorted_vec_ids, sorted_bm25_ids],
                    k=search_options.rrf_k,
                    weights=[search_options.vector_weight, search_options.keyword_weight],
                )
            else:
                fused = weighted_score_fusion(
                    vector_scores=snippet_vector_scores,
                    keyword_scores=snippet_bm25_scores,
                    vector_weight=search_options.vector_weight,
                    keyword_weight=search_options.keyword_weight,
                )

            # 步骤 5: 截断取 Top K
            top_fused = fused[: search_options.top_k]
            candidates: list[SearchSnippetCandidate] = []

            for sid_str, final_score in top_fused:
                snippet = snippet_map[sid_str]
                candidate = SearchSnippetCandidate(
                    snippet_id=snippet.id,
                    material_id=snippet.material_id,
                    version_id=snippet.version_id,
                    content=snippet.content,
                    chapter_title=snippet.chapter_title,
                    source_info=snippet.source_info,
                    vector_score=snippet_vector_scores[sid_str],
                    bm25_score=snippet_bm25_scores[sid_str],
                    final_score=final_score,
                    vector_rank=vec_ranks.get(sid_str),
                    bm25_rank=bm25_ranks.get(sid_str),
                )
                candidates.append(candidate)

            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return SearchResult(
                query=query,
                items=candidates,
                total_candidates=total_docs,
                duration_ms=duration_ms,
            )

        except AppError:
            raise
        except Exception as exc:
            raise SearchError(f"混合检索执行异常: {exc}") from exc

    def __repr__(self) -> str:
        """安全脱敏日志展示。"""
        return f"<PgvectorHybridSearchAdapter embedding={self._embedding_adapter!r}>"


__all__ = ["PgvectorHybridSearchAdapter"]
