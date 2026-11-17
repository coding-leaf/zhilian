"""重排适配器测试：Fake 确定性、SiliconFlow 解析/重试/降级/脱敏、工厂（离线 MockTransport）。"""

import json
import logging
from typing import Any

import httpx
import pytest

from app.core.errors import SearchError
from app.integrations.rerank import (
    FakeRerankAdapter,
    RerankItem,
    RerankProtocol,
    SiliconFlowRerankAdapter,
    create_rerank_adapter,
)
from app.integrations.rerank.siliconflow import FALLBACK_TOP_SCORE

DOCS = ["apple banana", "牛顿第二定律 F=ma", "cherry"]


def make_client(handler: Any) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def make_adapter(handler: Any, **kwargs: Any) -> SiliconFlowRerankAdapter:
    kwargs.setdefault("retry_delay_base", 0.0)
    return SiliconFlowRerankAdapter(api_key="sk-secret", client=make_client(handler), **kwargs)


class TestFakeRerank:
    def test_overlap_ranking_scores_in_unit_range(self) -> None:
        adapter = FakeRerankAdapter()
        assert isinstance(adapter, RerankProtocol)
        items = adapter.rerank("apple cherry", DOCS)
        assert [i.index for i in items[:2]] == [0, 2]  # 各命中 1/2，按 index 稳定
        assert items[0].relevance_score == pytest.approx(0.5)
        assert items[2].relevance_score == 0.0
        assert all(0.0 <= i.relevance_score <= 1.0 for i in items)

    def test_full_match_is_one_and_top_n(self) -> None:
        items = FakeRerankAdapter().rerank("cherry", DOCS, top_n=1)
        assert items == [RerankItem(index=2, relevance_score=1.0)]

    def test_deterministic_and_edge_cases(self) -> None:
        adapter = FakeRerankAdapter()
        assert adapter.rerank("牛顿", DOCS) == adapter.rerank("牛顿", DOCS)
        assert adapter.rerank("q", []) == []
        assert adapter.rerank("!!!", DOCS) == [RerankItem(i, 0.0) for i in range(3)]
        assert adapter.rerank("cherry", DOCS, top_n=0) == []
        assert repr(adapter) == "FakeRerankAdapter()"


class TestSiliconFlowRerank:
    def test_success_request_shape_and_sorting(self) -> None:
        seen: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["auth"] = request.headers["Authorization"]
            seen["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"index": 2, "relevance_score": 0.2},
                        {"index": 1, "relevance_score": 0.9},
                        {"index": 0, "relevance_score": 1.7},  # 越界得分被钳制到 1.0
                    ]
                },
            )

        items = make_adapter(handler).rerank("q", DOCS, top_n=2)
        assert seen["url"] == "https://api.siliconflow.cn/v1/rerank"
        assert seen["auth"] == "Bearer sk-secret"
        assert seen["body"] == {
            "model": "BAAI/bge-reranker-v2-m3",
            "query": "q",
            "documents": DOCS,
            "top_n": 2,
            "return_documents": False,
        }
        assert items == [RerankItem(0, 1.0), RerankItem(1, 0.9)]

    def test_top_n_none_requests_all_and_custom_base_url(self) -> None:
        seen: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["top_n"] = json.loads(request.content)["top_n"]
            return httpx.Response(200, json={"results": [{"index": 0, "relevance_score": 0.5}]})

        make_adapter(handler, base_url="https://example.test/v1/").rerank("q", DOCS)
        assert seen == {"url": "https://example.test/v1/rerank", "top_n": 3}

    def test_empty_documents_and_zero_top_n_make_no_request(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("must not be called")

        adapter = make_adapter(handler)
        assert adapter.rerank("q", []) == []
        assert adapter.rerank("q", DOCS, top_n=0) == []

    @pytest.mark.parametrize(
        "response",
        [
            httpx.Response(401, json={"error": "bad key"}),
            httpx.Response(400, text="nope"),
            httpx.Response(200, text="not json"),
            httpx.Response(200, json={"results": []}),
            httpx.Response(200, json={"oops": 1}),
            httpx.Response(200, json={"results": [{"index": 9, "relevance_score": 0.5}]}),
            httpx.Response(
                200,
                json={
                    "results": [
                        {"index": 0, "relevance_score": 0.5},
                        {"index": 0, "relevance_score": 0.4},
                    ]
                },
            ),
            httpx.Response(200, json={"results": [{"index": 0}]}),
            httpx.Response(200, json={"results": [{"index": "0", "relevance_score": 0.5}]}),
            httpx.Response(200, json={"results": [{"index": 0, "relevance_score": "x"}]}),
        ],
    )
    def test_errors_degrade_to_original_order(
        self, response: httpx.Response, caplog: pytest.LogCaptureFixture
    ) -> None:
        adapter = make_adapter(lambda request: response)
        with caplog.at_level(logging.WARNING):
            items = adapter.rerank("secret-query", DOCS)
        assert [i.index for i in items] == [0, 1, 2]
        assert items[0].relevance_score == FALLBACK_TOP_SCORE
        scores = [i.relevance_score for i in items]
        assert scores == sorted(scores, reverse=True) and len(set(scores)) == 3
        assert all(0.0 < s <= 0.5 for s in scores)
        assert "degraded" in caplog.text
        assert "secret-query" not in caplog.text and "sk-secret" not in caplog.text
        assert DOCS[1] not in caplog.text

    def test_fallback_respects_top_n(self) -> None:
        items = make_adapter(lambda request: httpx.Response(401)).rerank("q", DOCS, top_n=2)
        assert [i.index for i in items] == [0, 1]

    def test_5xx_retried_then_succeeds(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] < 3:
                return httpx.Response(503)
            return httpx.Response(200, json={"results": [{"index": 1, "relevance_score": 0.8}]})

        items = make_adapter(handler, max_retries=2).rerank("q", DOCS)
        assert calls["n"] == 3
        assert items == [RerankItem(1, 0.8)]

    def test_retries_exhausted_degrades(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(500)

        items = make_adapter(handler, max_retries=1).rerank("q", DOCS)
        assert calls["n"] == 2
        assert [i.index for i in items] == [0, 1, 2]

    def test_auth_error_not_retried(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(403)

        make_adapter(handler, max_retries=3).rerank("q", DOCS)
        assert calls["n"] == 1

    @pytest.mark.parametrize("exc", [httpx.ReadTimeout("t"), httpx.ConnectError("c")])
    def test_network_errors_degrade(self, exc: Exception) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise exc

        items = make_adapter(handler, max_retries=1).rerank("q", DOCS)
        assert [i.index for i in items] == [0, 1, 2]

    def test_repr_masks_api_key(self) -> None:
        adapter = make_adapter(lambda request: httpx.Response(200))
        assert "sk-secret" not in repr(adapter)
        assert "sk-secret" not in str(adapter)
        assert "******" in repr(adapter)

    def test_constructor_validation(self) -> None:
        with pytest.raises(SearchError):
            SiliconFlowRerankAdapter(api_key="  ")
        with pytest.raises(SearchError):
            SiliconFlowRerankAdapter(api_key="k", timeout=0)
        with pytest.raises(SearchError):
            SiliconFlowRerankAdapter(api_key="k", max_retries=-1)

    def test_owned_client_path_degrades_without_network(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """未注入 client 时内部创建 httpx.Client；用 MockTransport 替换以保持离线。"""
        real_client = httpx.Client

        def fake_client(*args: Any, **kwargs: Any) -> httpx.Client:
            return real_client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))

        monkeypatch.setattr(httpx, "Client", fake_client)
        adapter = SiliconFlowRerankAdapter(api_key="k", max_retries=0)
        assert [i.index for i in adapter.rerank("q", DOCS)] == [0, 1, 2]


class TestFactory:
    def test_fake_default(self) -> None:
        assert isinstance(create_rerank_adapter(), FakeRerankAdapter)
        assert isinstance(create_rerank_adapter(" FAKE "), FakeRerankAdapter)

    @pytest.mark.parametrize("kind", ["siliconflow", "openai-compatible", "OpenAI"])
    def test_remote_types(self, kind: str) -> None:
        adapter = create_rerank_adapter(
            kind, api_key="k", base_url="https://x/v1", model="m", timeout=3.0, max_retries=1
        )
        assert isinstance(adapter, SiliconFlowRerankAdapter)
        assert adapter.base_url == "https://x/v1"
        assert adapter.model == "m"
        assert adapter.timeout == 3.0
        assert adapter.max_retries == 1

    def test_missing_key_and_unknown_type(self) -> None:
        with pytest.raises(SearchError, match="api_key"):
            create_rerank_adapter("siliconflow")
        with pytest.raises(SearchError, match="api_key"):
            create_rerank_adapter("siliconflow", api_key="  ")
        with pytest.raises(SearchError, match="不支持"):
            create_rerank_adapter("cohere", api_key="k")

    def test_default_base_url_when_none(self) -> None:
        adapter = create_rerank_adapter("siliconflow", api_key="k", base_url=None)
        assert isinstance(adapter, SiliconFlowRerankAdapter)
        assert adapter.base_url == "https://api.siliconflow.cn/v1"
