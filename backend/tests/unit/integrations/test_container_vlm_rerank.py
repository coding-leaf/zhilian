"""ProviderRegistry 的 rerank / vlm 可选能力装配单元测试（离线、确定性）。"""

import asyncio

from pydantic import SecretStr

from app.core.config import AppSettings, RerankSettings, VLMSettings
from app.integrations.container import ProviderRegistry
from app.integrations.embedding.fake import FakeEmbeddingAdapter
from app.integrations.idempotency.memory import MemoryIdempotencyAdapter
from app.integrations.llm.fake import FakeLLMAdapter
from app.integrations.llm.openai import OpenAICompatibleLLMAdapter
from app.integrations.ocr.fake import FakeOCRAdapter
from app.integrations.queue.memory import MemoryQueueAdapter
from app.integrations.rerank.fake import FakeRerankAdapter
from app.integrations.rerank.protocol import RerankProtocol
from app.integrations.rerank.siliconflow import SiliconFlowRerankAdapter
from app.integrations.search.fake import FakeSearchAdapter
from app.integrations.storage.memory import MemoryStorageAdapter


def _seven() -> ProviderRegistry:
    """仅注入 7 块必备协议的 strict 注册表。"""
    return ProviderRegistry(
        llm=FakeLLMAdapter(),
        ocr=FakeOCRAdapter(),
        storage=MemoryStorageAdapter(),
        search=FakeSearchAdapter(),
        queue=MemoryQueueAdapter(),
        idempotency=MemoryIdempotencyAdapter(),
        embedding=FakeEmbeddingAdapter(),
        strict=True,
    )


class TestStrictConstruction:
    """rerank / vlm 不计入 strict 校验。"""

    def test_strict_seven_protocols_defaults_rerank_fake_vlm_none(self) -> None:
        """7 块必备协议 + strict=True 通过；rerank 缺省 Fake，vlm 为 None。"""
        registry = _seven()

        assert isinstance(registry.rerank, FakeRerankAdapter)
        assert isinstance(registry.rerank, RerankProtocol)
        assert registry.vlm is None
        registry.validate()

    def test_explicit_rerank_and_vlm_kept(self) -> None:
        """构造时显式传入的 rerank / vlm 原样保留。"""
        rerank = FakeRerankAdapter()
        vlm = FakeLLMAdapter()
        registry = ProviderRegistry(
            llm=FakeLLMAdapter(),
            ocr=FakeOCRAdapter(),
            storage=MemoryStorageAdapter(),
            search=FakeSearchAdapter(),
            queue=MemoryQueueAdapter(),
            idempotency=MemoryIdempotencyAdapter(),
            embedding=FakeEmbeddingAdapter(),
            rerank=rerank,
            vlm=vlm,
            strict=True,
        )

        assert registry.rerank is rerank
        assert registry.vlm is vlm

    def test_empty_registry_has_rerank_but_no_vlm(self) -> None:
        """空注册表访问 rerank / vlm 不抛异常。"""
        registry = ProviderRegistry.create_empty()

        assert isinstance(registry.rerank, FakeRerankAdapter)
        assert registry.vlm is None


class TestRegister:
    """register_rerank / register_vlm。"""

    def test_register_rerank_and_vlm_chain(self) -> None:
        """链式注册并可覆盖、可清空 vlm。"""
        registry = _seven()
        rerank = FakeRerankAdapter()
        vlm = FakeLLMAdapter()

        returned = registry.register_rerank(rerank).register_vlm(vlm)

        assert returned is registry
        assert registry.rerank is rerank
        assert registry.vlm is vlm

        assert registry.register_vlm(None) is registry
        assert registry.vlm is None

    def test_property_setters(self) -> None:
        """属性 setter 与 register_* 等价。"""
        registry = _seven()
        rerank = FakeRerankAdapter()
        vlm = FakeLLMAdapter()

        registry.rerank = rerank
        registry.vlm = vlm

        assert registry.rerank is rerank
        assert registry.vlm is vlm


class TestCreateDefault:
    """create_default 仅在 enabled 时装配真实 rerank / vlm。"""

    def test_defaults_are_offline(self) -> None:
        """默认配置：rerank=Fake，vlm=None。"""
        registry = ProviderRegistry.create_default(AppSettings())

        assert isinstance(registry.rerank, FakeRerankAdapter)
        assert registry.vlm is None

    def test_rerank_provider_ignored_when_disabled(self) -> None:
        """enabled=False 时即便 provider=siliconflow 且无 key，也走 Fake（不抛错）。"""
        settings = AppSettings(rerank=RerankSettings(enabled=False, provider="siliconflow"))

        registry = ProviderRegistry.create_default(settings)

        assert isinstance(registry.rerank, FakeRerankAdapter)

    def test_rerank_enabled_siliconflow(self) -> None:
        """enabled=True + siliconflow + key → SiliconFlowRerankAdapter。"""
        settings = AppSettings(
            rerank=RerankSettings(
                enabled=True,
                provider="siliconflow",
                api_key=SecretStr("sk-rerank"),
                model="BAAI/bge-reranker-v2-m3",
            )
        )

        registry = ProviderRegistry.create_default(settings)

        assert isinstance(registry.rerank, SiliconFlowRerankAdapter)

    def test_rerank_enabled_with_fake_provider_stays_fake(self) -> None:
        """enabled=True 但 provider=fake 仍为 Fake。"""
        settings = AppSettings(rerank=RerankSettings(enabled=True, provider="fake"))

        assert isinstance(ProviderRegistry.create_default(settings).rerank, FakeRerankAdapter)

    def test_vlm_enabled_siliconflow(self) -> None:
        """vlm enabled + siliconflow + key → OpenAI 兼容适配器（默认官方地址）。"""
        settings = AppSettings(
            vlm=VLMSettings(enabled=True, provider="siliconflow", api_key=SecretStr("sk-vlm"))
        )

        registry = ProviderRegistry.create_default(settings)

        assert isinstance(registry.vlm, OpenAICompatibleLLMAdapter)
        assert registry.vlm.base_url == "https://api.siliconflow.cn/v1"
        assert registry.vlm.model == "Qwen/Qwen2.5-VL-7B-Instruct"

    def test_vlm_enabled_without_key_degrades_to_none(self) -> None:
        """vlm enabled 但缺 key → None，不阻断装配。"""
        settings = AppSettings(vlm=VLMSettings(enabled=True, provider="siliconflow"))

        assert ProviderRegistry.create_default(settings).vlm is None

    def test_vlm_disabled_with_key_is_none(self) -> None:
        """vlm 未启用时即便有 key 也为 None。"""
        settings = AppSettings(
            vlm=VLMSettings(enabled=False, provider="siliconflow", api_key=SecretStr("sk-vlm"))
        )

        assert ProviderRegistry.create_default(settings).vlm is None


class TestShutdown:
    """shutdown 覆盖 rerank / vlm。"""

    def test_shutdown_closes_vlm_and_rerank(self) -> None:
        """带 close 的 vlm / rerank 适配器在 shutdown 时被关闭。"""
        closed: list[str] = []

        class ClosableRerank(FakeRerankAdapter):
            def close(self) -> None:
                closed.append("rerank")

        class ClosableVLM(FakeLLMAdapter):
            def close(self) -> None:
                closed.append("vlm")

        registry = _seven().register_rerank(ClosableRerank()).register_vlm(ClosableVLM())

        asyncio.run(registry.shutdown())

        assert sorted(closed) == ["rerank", "vlm"]

    def test_shutdown_tolerates_missing_vlm(self) -> None:
        """vlm 为 None 时 shutdown 正常完成。"""
        asyncio.run(_seven().shutdown())
