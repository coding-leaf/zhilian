"""重排（Rerank）适配器抽象协议与数据模型。

- 通过 Protocol 抽象接口，支持 Fake 与 SiliconFlow 生产实现无缝切换；
- 重排只改变候选顺序与得分，不得抛出业务异常阻断问答主链路（适配器内部降级）。
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class RerankItem:
    """单个文档的重排结果。

    Attributes:
        index: 文档在输入 documents 序列中的下标。
        relevance_score: 相关度得分，范围 [0, 1]。
    """

    index: int
    relevance_score: float


@runtime_checkable
class RerankProtocol(Protocol):
    """重排适配器抽象协议。"""

    def rerank(
        self,
        query: str,
        documents: Sequence[str],
        *,
        top_n: int | None = None,
    ) -> list[RerankItem]:
        """按与 query 的相关度对 documents 重排。

        Args:
            query: 查询文本。
            documents: 候选文档文本序列。
            top_n: 仅返回前 top_n 条；None 表示全部返回。

        Returns:
            list[RerankItem]: 按 relevance_score 降序排列（同分按 index 升序），
                得分位于 [0, 1]，index 对应输入顺序。空 documents 返回 []。
        """
        ...


__all__ = ["RerankItem", "RerankProtocol"]
