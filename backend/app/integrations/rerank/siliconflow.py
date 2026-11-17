"""SiliconFlow（兼容 Cohere/Jina rerank 接口）重排生产适配器。

- 同步 httpx，复用 _http_retry 的指数退避与响应状态处理；
- 绝密脱敏：api_key 不出现在 repr/日志；日志仅记录异常类名，绝不记录查询/文档文本；
- 任何失败（超时/鉴权/5xx/响应畸形）均优雅降级为“保持原序 + 中性得分”，绝不抛出。
"""

import logging
import time
from collections.abc import Sequence
from typing import Any

import httpx

from app.core.errors import SearchError
from app.integrations._http_retry import (
    RetryableAdapterError,
    handle_openai_http_response,
    managed_httpx_client,
    run_with_retry,
)
from app.integrations.rerank.protocol import RerankItem, RerankProtocol

logger = logging.getLogger(__name__)

# 降级时的最高中性得分：第 i 条得分 = 0.5 * (1 - i / n)，保持原序且严格递减、落在 (0, 0.5]。
FALLBACK_TOP_SCORE = 0.5


class SiliconFlowRerankAdapter(RerankProtocol):
    """SiliconFlow `/rerank` 重排适配器。"""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.siliconflow.cn/v1",
        model: str = "BAAI/bge-reranker-v2-m3",
        timeout: float = 15.0,
        max_retries: int = 2,
        client: Any | None = None,
        retry_delay_base: float = 0.5,
    ) -> None:
        """初始化重排适配器。

        Args:
            api_key: 服务凭证。
            base_url: 接口基础 URL。
            model: 重排模型名称。
            timeout: 单次请求超时（秒）。
            max_retries: 偶发错误重试上限。
            client: 可选注入的 HTTP 客户端（测试打桩）。
            retry_delay_base: 重试退避基数（秒）。

        Raises:
            SearchError: api_key 缺失或参数非法。
        """
        if not api_key or not api_key.strip():
            raise SearchError("重排服务 api_key 不能为空")
        if timeout <= 0.0:
            raise SearchError("重排服务 timeout 必须大于 0")
        if max_retries < 0:
            raise SearchError("重排服务 max_retries 不能小于 0")

        self.api_key = api_key.strip()
        self.base_url = (base_url or "https://api.siliconflow.cn/v1").rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay_base = retry_delay_base
        self._client = client

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        """带重试地调用 /rerank；失败抛出 SearchError（由 rerank 统一降级）。"""
        url = f"{self.base_url}/rerank"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        def _client_factory() -> httpx.Client:
            return httpx.Client(timeout=self.timeout)

        with managed_httpx_client(self._client, _client_factory) as client:

            def _attempt() -> dict[str, Any]:
                try:
                    response = client.post(url, json=payload, headers=headers)
                    return handle_openai_http_response(
                        response,
                        service_label="重排服务",
                        auth_error_cls=SearchError,
                        service_error_cls=SearchError,
                    )
                except (httpx.TimeoutException, TimeoutError) as timeout_err:
                    raise RetryableAdapterError(SearchError("重排服务调用超时")) from timeout_err
                except (httpx.RequestError, ConnectionError) as req_err:
                    raise RetryableAdapterError(SearchError("重排网络请求异常")) from req_err

            return run_with_retry(
                _attempt,
                max_retries=self.max_retries,
                retry_delay_base=self.retry_delay_base,
                sleep_fn=lambda delay: time.sleep(delay),
            )

    @staticmethod
    def _parse(data: dict[str, Any], doc_count: int) -> list[RerankItem]:
        """解析 results[].{index,relevance_score}；畸形即抛 ValueError。"""
        results = data.get("results")
        if not isinstance(results, list) or not results:
            raise ValueError("results missing")
        seen: set[int] = set()
        items: list[RerankItem] = []
        for entry in results:
            index = entry["index"]
            score = entry["relevance_score"]
            if isinstance(index, bool) or not isinstance(index, int):
                raise ValueError("bad index")
            if isinstance(score, bool) or not isinstance(score, int | float):
                raise ValueError("bad score")
            if not 0 <= index < doc_count or index in seen:
                raise ValueError("index out of range or duplicated")
            seen.add(index)
            items.append(RerankItem(index=index, relevance_score=min(1.0, max(0.0, float(score)))))
        items.sort(key=lambda item: (-item.relevance_score, item.index))
        return items

    @staticmethod
    def _fallback(doc_count: int, top_n: int) -> list[RerankItem]:
        """保持原始顺序、得分自 0.5 起严格递减的中性结果。"""
        return [
            RerankItem(index=i, relevance_score=FALLBACK_TOP_SCORE * (1.0 - i / doc_count))
            for i in range(min(top_n, doc_count))
        ]

    def rerank(
        self,
        query: str,
        documents: Sequence[str],
        *,
        top_n: int | None = None,
    ) -> list[RerankItem]:
        """调用 SiliconFlow 重排；任何错误都降级为原序 + 中性得分，绝不抛出。

        Args:
            query: 查询文本。
            documents: 候选文档序列。
            top_n: 仅返回前 top_n 条；None 表示全部。

        Returns:
            list[RerankItem]: 相关度降序结果；降级时为原序、得分自 0.5 递减。
        """
        doc_count = len(documents)
        if doc_count == 0:
            return []
        limit = doc_count if top_n is None else max(0, min(top_n, doc_count))
        if limit == 0:
            return []

        payload: dict[str, Any] = {
            "model": self.model,
            "query": query,
            "documents": list(documents),
            "top_n": limit,
            "return_documents": False,
        }
        try:
            items = self._parse(self._post(payload), doc_count)
        except Exception as exc:
            logger.warning("rerank degraded to original order: %s", type(exc).__name__)
            return self._fallback(doc_count, limit)
        return items[:limit]

    def __repr__(self) -> str:
        """安全脱敏日志展示，绝对禁止打印 api_key 明文。"""
        return (
            f"SiliconFlowRerankAdapter(model='{self.model}', base_url='{self.base_url}', "
            f"api_key='******', timeout={self.timeout})"
        )

    def __str__(self) -> str:
        return self.__repr__()


__all__ = ["FALLBACK_TOP_SCORE", "SiliconFlowRerankAdapter"]
