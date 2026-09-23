"""向量化适配器模块单元测试套件。

严格遵循 AGENTS.md 规范：
- 零真实外部网络连接，使用 Mock/Fake 隔离测试；
- 覆盖 Fake、OpenAI 适配器、工厂函数及数据契约；
- 行覆盖率与分支覆盖率门禁 >= 90%。
"""

import concurrent.futures
import math
from unittest.mock import MagicMock

import httpx
import pytest

from app.core.errors import (
    EmbeddingAuthError,
    EmbeddingError,
    EmbeddingTimeoutError,
)
from app.integrations.embedding import (
    EmbeddingOptions,
    EmbeddingProtocol,
    EmbeddingResult,
    FakeEmbeddingAdapter,
    OpenAICompatibleEmbeddingAdapter,
    create_embedding_adapter,
)


class TestEmbeddingContracts:
    """数据模型与参数契约测试。"""

    def test_embedding_options_validation(self) -> None:
        """测试配置选项校验。"""
        opts = EmbeddingOptions(model="test-model", dimensions=512, timeout=10.0)
        assert opts.model == "test-model"
        assert opts.dimensions == 512
        assert opts.timeout == 10.0

        with pytest.raises(ValueError, match="dimensions must be greater than 0"):
            EmbeddingOptions(dimensions=0)

        with pytest.raises(ValueError, match="timeout must be greater than 0"):
            EmbeddingOptions(timeout=-1.0)

    def test_embedding_result_immutability(self) -> None:
        """测试返回结果数据模型元组冻结转换。"""
        res = EmbeddingResult(vector=[0.1, 0.2, 0.3], tokens=10, duration_ms=5.0)
        assert isinstance(res.vector, tuple)
        assert res.tokens == 10
        assert res.duration_ms == 5.0


class TestFakeEmbeddingAdapter:
    """Fake 向量化适配器测试。"""

    def test_fake_embedding_deterministic_1024(self) -> None:
        """测试确定性 1024 维生成与 L2 模长归一化。"""
        adapter = FakeEmbeddingAdapter()
        assert isinstance(adapter, EmbeddingProtocol)

        vec1 = adapter.embed_query("智练自主学习平台")
        vec2 = adapter.embed_query("智练自主学习平台")
        vec3 = adapter.embed_query("其他不同文本内容")

        assert len(vec1) == 1024
        assert vec1 == vec2
        assert vec1 != vec3

        norm = math.sqrt(sum(x * x for x in vec1))
        assert math.isclose(norm, 1.0, rel_tol=1e-5)

    def test_fake_embedding_documents_batch(self) -> None:
        """测试批量文档编码。"""
        adapter = FakeEmbeddingAdapter()
        docs = ["第一段内容", "第二段内容", "第三段内容"]
        vectors = adapter.embed_documents(docs)

        assert len(vectors) == 3
        for v in vectors:
            assert len(v) == 1024
            norm = math.sqrt(sum(x * x for x in v))
            assert math.isclose(norm, 1.0, rel_tol=1e-5)

    def test_fake_embedding_canned_vector(self) -> None:
        """测试预置返回向量支持。"""
        adapter = FakeEmbeddingAdapter()
        canned = [0.05] * 1024
        adapter.set_canned_vector("测试预置", canned)

        res = adapter.embed_query("测试预置")
        assert res == canned

        batch_res = adapter.embed_documents(["测试预置", "普通文本"])
        assert batch_res[0] == canned
        assert batch_res[1] != canned

    def test_fake_embedding_latency_and_fault(self) -> None:
        """测试模拟时延与故障注入。"""
        adapter = FakeEmbeddingAdapter()
        adapter.set_latency(0.01)

        # 针对 query 注入
        adapter.set_fault_injection("query", EmbeddingTimeoutError("模拟超时"))
        with pytest.raises(EmbeddingTimeoutError, match="模拟超时"):
            adapter.embed_query("任何查询")

        adapter.reset()
        res = adapter.embed_query("重置后正常")
        assert len(res) == 1024

        # 针对特定 query 注入
        adapter.set_fault_injection("特定查询文本", EmbeddingError("特定查询错误"))
        with pytest.raises(EmbeddingError, match="特定查询错误"):
            adapter.embed_query("特定查询文本")

        adapter.reset()

        # 针对 documents 批量注入
        adapter.set_fault_injection("documents", EmbeddingError("模拟批量故障"))
        with pytest.raises(EmbeddingError, match="模拟批量故障"):
            adapter.embed_documents(["文档1"])

        adapter.reset()

        # 针对特定单文档注入
        adapter.set_fault_injection("故障文档", EmbeddingError("特定文档错误"))
        with pytest.raises(EmbeddingError, match="特定文档错误"):
            adapter.embed_documents(["正常文档", "故障文档"])

    def test_fake_embedding_thread_safety(self) -> None:
        """测试多线程高并发下的并发安全。"""
        adapter = FakeEmbeddingAdapter()
        texts = [f"并发文本-{i}" for i in range(20)]

        def _worker(t: str) -> list[float]:
            return adapter.embed_query(t)

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(_worker, t) for t in texts]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        assert len(results) == 20
        for r in results:
            assert len(r) == 1024

    def test_fake_embedding_repr_safe(self) -> None:
        """测试 repr 脱敏。"""
        adapter = FakeEmbeddingAdapter()
        repr_str = repr(adapter)
        assert "canned_count=0" in repr_str

    def test_fake_embedding_zero_norm_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试全零向量下 norm <= 0.0 保底分支。"""
        adapter = FakeEmbeddingAdapter()
        monkeypatch.setattr("random.Random.uniform", lambda self, a, b: 0.0)
        vec = adapter._generate_deterministic_vector("测试零向量", dimensions=16)
        assert vec[0] == 1.0
        assert all(x == 0.0 for x in vec[1:])


class TestOpenAICompatibleEmbeddingAdapter:
    """生产级 OpenAI 兼容适配器测试。"""

    def test_openai_init_validation(self) -> None:
        """测试初始化参数校验。"""
        with pytest.raises(EmbeddingAuthError, match="api_key 不能为空"):
            OpenAICompatibleEmbeddingAdapter(api_key="")

        with pytest.raises(EmbeddingError, match="timeout 必须大于 0"):
            OpenAICompatibleEmbeddingAdapter(api_key="sk-test", timeout=-1.0)

        with pytest.raises(EmbeddingError, match="max_retries 不能小于 0"):
            OpenAICompatibleEmbeddingAdapter(api_key="sk-test", max_retries=-1)

        with pytest.raises(EmbeddingError, match="dimensions 必须大于 0"):
            OpenAICompatibleEmbeddingAdapter(api_key="sk-test", dimensions=0)

    def test_openai_repr_masks_api_key(self) -> None:
        """测试 api_key 绝对脱敏红线。"""
        adapter = OpenAICompatibleEmbeddingAdapter(
            api_key="sk-secret-token-1234567890",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        repr_str = repr(adapter)
        str_str = str(adapter)
        assert "sk-secret-token-1234567890" not in repr_str
        assert "api_key='******'" in repr_str
        assert "api_key='******'" in str_str

    def test_openai_embed_query_success(self) -> None:
        """测试正常查询向量化成功流转。"""
        mock_client = MagicMock()
        fake_vector = [0.1] * 1024
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [{"embedding": fake_vector, "index": 0}],
        }
        mock_client.post.return_value = mock_response

        adapter = OpenAICompatibleEmbeddingAdapter(
            api_key="sk-test",
            client=mock_client,
            retry_delay_base=0.001,
        )

        vec = adapter.embed_query("你好")
        assert vec == fake_vector
        mock_client.post.assert_called_once()

    def test_openai_embed_documents_batch_success(self) -> None:
        """测试批量文档向量化成功流转。"""
        mock_client = MagicMock()
        fake_vec1 = [0.1] * 1024
        fake_vec2 = [0.2] * 1024
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"embedding": fake_vec2, "index": 1},
                {"embedding": fake_vec1, "index": 0},
            ],
        }
        mock_client.post.return_value = mock_response

        adapter = OpenAICompatibleEmbeddingAdapter(
            api_key="sk-test",
            client=mock_client,
            retry_delay_base=0.001,
        )

        assert adapter.embed_documents([]) == []
        vectors = adapter.embed_documents(["文档1", "文档2"])
        assert len(vectors) == 2
        assert vectors[0] == fake_vec1
        assert vectors[1] == fake_vec2

    def test_openai_auth_error_no_retry(self) -> None:
        """测试 401 立即抛出 EmbeddingAuthError，不进行重试。"""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_client.post.return_value = mock_response

        adapter = OpenAICompatibleEmbeddingAdapter(
            api_key="sk-invalid",
            client=mock_client,
            max_retries=3,
            retry_delay_base=0.001,
        )

        with pytest.raises(EmbeddingAuthError, match="认证失败"):
            adapter.embed_query("测试")

        assert mock_client.post.call_count == 1

    def test_openai_retry_on_429_then_success(self) -> None:
        """测试 429 频率限制指数退避重试并最终成功。"""
        mock_client = MagicMock()
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.text = "Rate limit reached"

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {"data": [{"embedding": [0.3] * 1024}]}

        mock_client.post.side_effect = [resp_429, resp_200]

        adapter = OpenAICompatibleEmbeddingAdapter(
            api_key="sk-test",
            client=mock_client,
            max_retries=2,
            retry_delay_base=0.001,
        )

        vec = adapter.embed_query("测试")
        assert len(vec) == 1024
        assert mock_client.post.call_count == 2

    def test_openai_retry_exhausted_raises_error(self) -> None:
        """测试 500 持续错误直至重试耗尽。"""
        mock_client = MagicMock()
        resp_500 = MagicMock()
        resp_500.status_code = 500
        resp_500.text = "Internal Server Error"
        mock_client.post.return_value = resp_500

        adapter = OpenAICompatibleEmbeddingAdapter(
            api_key="sk-test",
            client=mock_client,
            max_retries=2,
            retry_delay_base=0.001,
        )

        with pytest.raises(EmbeddingError, match="向量化服务暂时不可用"):
            adapter.embed_query("测试")

        assert mock_client.post.call_count == 3

    def test_openai_timeout_mapped_to_app_error(self) -> None:
        """测试 httpx.TimeoutException 映射为 EmbeddingTimeoutError。"""
        mock_client = MagicMock()
        mock_client.post.side_effect = httpx.TimeoutException("Read timed out")

        adapter = OpenAICompatibleEmbeddingAdapter(
            api_key="sk-test",
            client=mock_client,
            max_retries=1,
            retry_delay_base=0.001,
        )

        with pytest.raises(EmbeddingTimeoutError, match="向量化服务调用超时"):
            adapter.embed_query("测试")

    def test_openai_request_error_mapped_to_embedding_error(self) -> None:
        """测试网络连接错误映射。"""
        mock_client = MagicMock()
        mock_client.post.side_effect = httpx.RequestError("Connection failed")

        adapter = OpenAICompatibleEmbeddingAdapter(
            api_key="sk-test",
            client=mock_client,
            max_retries=1,
            retry_delay_base=0.001,
        )

        with pytest.raises(EmbeddingError, match="向量化网络请求异常"):
            adapter.embed_query("测试")

    def test_openai_bad_request_error(self) -> None:
        """测试 400 等其他客户端错误转译。"""
        mock_client = MagicMock()
        resp_400 = MagicMock()
        resp_400.status_code = 400
        resp_400.text = "Bad Request"
        mock_client.post.return_value = resp_400

        adapter = OpenAICompatibleEmbeddingAdapter(
            api_key="sk-test",
            client=mock_client,
            max_retries=0,
        )
        with pytest.raises(EmbeddingError, match="返回异常状态码: 400"):
            adapter.embed_query("测试")

    def test_openai_invalid_json_and_dimension_mismatch(self) -> None:
        """测试反序列化失败与维度不匹配异常拦截。"""
        mock_client = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.side_effect = ValueError("Invalid JSON")
        mock_client.post.return_value = resp

        adapter = OpenAICompatibleEmbeddingAdapter(
            api_key="sk-test",
            client=mock_client,
            max_retries=0,
        )

        with pytest.raises(EmbeddingError, match="反序列化失败"):
            adapter.embed_query("测试")

        # 缺少 embedding 字段
        resp.json.side_effect = None
        resp.json.return_value = {"data": [{}]}
        with pytest.raises(EmbeddingError, match="未包含 embedding 数据"):
            adapter.embed_query("测试")

        # 维度不匹配
        resp.json.return_value = {"data": [{"embedding": [0.1] * 512}]}
        with pytest.raises(EmbeddingError, match="向量维度不匹配"):
            adapter.embed_query("测试")

        # 批量数量不匹配
        resp.json.return_value = {"data": [{"embedding": [0.1] * 1024}]}
        with pytest.raises(EmbeddingError, match="向量返回数量不匹配"):
            adapter.embed_documents(["文1", "文2"])

        # 批量其中一项维度不匹配
        resp.json.return_value = {
            "data": [
                {"embedding": [0.1] * 1024, "index": 0},
                {"embedding": [0.1] * 512, "index": 1},
            ]
        }
        with pytest.raises(EmbeddingError, match="向量维度不匹配"):
            adapter.embed_documents(["文1", "文2"])

    def test_openai_default_client_init(self) -> None:
        """测试未注入客户端时的懒加载客户端构造。"""
        adapter = OpenAICompatibleEmbeddingAdapter(api_key="sk-test")
        client = adapter._get_client()
        assert isinstance(client, httpx.Client)
        assert client.timeout.read == 20.0


class TestEmbeddingFactory:
    """工厂函数测试。"""

    def test_create_embedding_adapter(self) -> None:
        """测试不同类型适配器创建分发。"""
        fake = create_embedding_adapter("fake")
        assert isinstance(fake, FakeEmbeddingAdapter)

        openai = create_embedding_adapter("openai", api_key="sk-test")
        assert isinstance(openai, OpenAICompatibleEmbeddingAdapter)

        dashscope = create_embedding_adapter("dashscope", api_key="sk-test")
        assert isinstance(dashscope, OpenAICompatibleEmbeddingAdapter)

        with pytest.raises(EmbeddingAuthError, match="必须提供 api_key"):
            create_embedding_adapter("openai")

        with pytest.raises(EmbeddingError, match="不支持的向量化适配器类型"):
            create_embedding_adapter("unknown_provider")
