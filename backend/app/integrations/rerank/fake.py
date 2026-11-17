"""确定性离线重排假实现：基于查询词元重叠率，零网络、零随机。"""

from collections.abc import Sequence

from app.core.algorithms.search import tokenize_text
from app.integrations.rerank.protocol import RerankItem, RerankProtocol


class FakeRerankAdapter(RerankProtocol):
    """词元重叠打分的确定性重排器。

    得分 = 命中的去重查询词元数 / 去重查询词元总数，天然落在 [0, 1]；
    同分按输入下标升序保证稳定。
    """

    def rerank(
        self,
        query: str,
        documents: Sequence[str],
        *,
        top_n: int | None = None,
    ) -> list[RerankItem]:
        """对 documents 做词元重叠重排。

        Args:
            query: 查询文本。
            documents: 候选文档序列。
            top_n: 仅返回前 top_n 条（<=0 返回空列表）。

        Returns:
            list[RerankItem]: 相关度降序结果。
        """
        if not documents:
            return []
        query_tokens = set(tokenize_text(query))
        scored: list[RerankItem] = []
        for index, document in enumerate(documents):
            if query_tokens:
                hits = len(query_tokens & set(tokenize_text(document)))
                score = hits / len(query_tokens)
            else:
                score = 0.0
            scored.append(RerankItem(index=index, relevance_score=score))
        scored.sort(key=lambda item: (-item.relevance_score, item.index))
        if top_n is not None:
            return scored[: max(top_n, 0)]
        return scored

    def __repr__(self) -> str:
        return "FakeRerankAdapter()"


__all__ = ["FakeRerankAdapter"]
