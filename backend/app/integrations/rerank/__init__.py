"""智练重排（Rerank）适配器包。"""

from app.integrations.rerank.factory import create_rerank_adapter
from app.integrations.rerank.fake import FakeRerankAdapter
from app.integrations.rerank.protocol import RerankItem, RerankProtocol
from app.integrations.rerank.siliconflow import SiliconFlowRerankAdapter

__all__ = [
    "FakeRerankAdapter",
    "RerankItem",
    "RerankProtocol",
    "SiliconFlowRerankAdapter",
    "create_rerank_adapter",
]
