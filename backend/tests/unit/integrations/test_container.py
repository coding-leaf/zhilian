"""外部能力注册中心单元测试 (ProviderRegistry)。

覆盖用例:
- UT-REG-01: ProviderRegistry 默认装配与协议分发 (create_default / create_from_settings)
- UT-REG-02: 自定义适配器注册覆盖 (register_*)
- UT-REG-03: 未注册协议防御性断言与校验
- UT-REG-04: ProviderRegistry 异步优雅停机 (shutdown)
"""

import pytest

from app.core.config import AppSettings
from app.integrations.container import ProviderRegistry
from app.integrations.embedding.fake import FakeEmbeddingAdapter
from app.integrations.embedding.protocol import EmbeddingProtocol
from app.integrations.idempotency.memory import MemoryIdempotencyAdapter
from app.integrations.idempotency.protocol import IdempotencyProtocol
from app.integrations.llm.fake import FakeLLMAdapter
from app.integrations.llm.protocol import LLMProtocol
from app.integrations.ocr.baidu import BaiduOCRAdapter
from app.integrations.ocr.fake import FakeOCRAdapter
from app.integrations.ocr.protocol import OCRProtocol
from app.integrations.queue.memory import MemoryQueueAdapter
from app.integrations.queue.protocol import QueueProtocol
from app.integrations.search.fake import FakeSearchAdapter
from app.integrations.search.protocol import SearchProtocol
from app.integrations.storage.memory import MemoryStorageAdapter
from app.integrations.storage.protocol import StorageProtocol


def test_provider_registry_create_default() -> None:
    """测试通过 create_default 依据配置成功装配 7 块默认协议实例。"""
    settings = AppSettings()
    registry = ProviderRegistry.create_default(settings)

    # 1. 验证 7 块协议实例均非空且符合各自 Protocol 协议契约
    assert isinstance(registry.llm, LLMProtocol)
    assert isinstance(registry.ocr, OCRProtocol)
    assert isinstance(registry.storage, StorageProtocol)
    assert isinstance(registry.search, SearchProtocol)
    assert isinstance(registry.queue, QueueProtocol)
    assert isinstance(registry.idempotency, IdempotencyProtocol)
    assert isinstance(registry.embedding, EmbeddingProtocol)

    # 2. 默认模式下确认为 Fake/Memory 或当前环境配置实现
    if settings.llm.provider == "fake":
        assert isinstance(registry.llm, FakeLLMAdapter)
    else:
        assert isinstance(registry.llm, LLMProtocol)

    if settings.ocr.provider == "baidu":
        assert isinstance(registry.ocr, BaiduOCRAdapter)
    else:
        assert isinstance(registry.ocr, FakeOCRAdapter)

    if settings.storage.provider == "memory":
        assert isinstance(registry.storage, MemoryStorageAdapter)
    else:
        assert isinstance(registry.storage, StorageProtocol)
    assert isinstance(registry.search, FakeSearchAdapter)
    assert isinstance(registry.queue, MemoryQueueAdapter)
    assert isinstance(registry.idempotency, MemoryIdempotencyAdapter)
    assert isinstance(registry.embedding, FakeEmbeddingAdapter)

    # 3. 验证 create_from_settings 契约兼容
    registry_alt = ProviderRegistry.create_from_settings(settings)
    assert isinstance(registry_alt.llm, LLMProtocol)
    assert isinstance(registry_alt.storage, StorageProtocol)


def test_provider_registry_custom_overrides() -> None:
    """测试自定义注册覆盖各 Protocol 实现并支持链式调用。"""
    settings = AppSettings()
    registry = ProviderRegistry.create_default(settings)

    custom_llm = FakeLLMAdapter()
    custom_ocr = FakeOCRAdapter()
    custom_storage = MemoryStorageAdapter()
    custom_search = FakeSearchAdapter()
    custom_queue = MemoryQueueAdapter()
    custom_idempotency = MemoryIdempotencyAdapter()
    custom_embedding = FakeEmbeddingAdapter()

    # 链式调用覆盖注册
    returned = (
        registry.register_llm(custom_llm)
        .register_ocr(custom_ocr)
        .register_storage(custom_storage)
        .register_search(custom_search)
        .register_queue(custom_queue)
        .register_idempotency(custom_idempotency)
        .register_embedding(custom_embedding)
    )

    assert returned is registry
    assert registry.llm is custom_llm
    assert registry.ocr is custom_ocr
    assert registry.storage is custom_storage
    assert registry.search is custom_search
    assert registry.queue is custom_queue
    assert registry.idempotency is custom_idempotency
    assert registry.embedding is custom_embedding


def test_provider_registry_unregistered_protocol_assertion() -> None:
    """测试未注册协议时的防御性断言与校验异常拦截。"""
    # 1. 尝试以缺省/None 构造未初始化的空注册表时，访问属性抛出防御性异常
    partial_registry = ProviderRegistry.create_empty()

    with pytest.raises(ValueError, match="未注册的大语言模型协议"):
        _ = partial_registry.llm

    with pytest.raises(ValueError, match="未注册的光学字符识别协议"):
        _ = partial_registry.ocr

    with pytest.raises(ValueError, match="未注册的对象存储协议"):
        _ = partial_registry.storage

    with pytest.raises(ValueError, match="未注册的检索协议"):
        _ = partial_registry.search

    with pytest.raises(ValueError, match="未注册的任务队列协议"):
        _ = partial_registry.queue

    with pytest.raises(ValueError, match="未注册的幂等拦截协议"):
        _ = partial_registry.idempotency

    with pytest.raises(ValueError, match="未注册的向量化协议"):
        _ = partial_registry.embedding

    # 2. 调用 validate() 时如存在缺失协议抛出 ValueError
    with pytest.raises(ValueError, match="缺少未注册的基础设施协议适配器"):
        partial_registry.validate()

    # 3. 构造函数在 strict=True 模式下直接拦截 None 注入
    with pytest.raises(ValueError, match="缺少未注册的基础设施协议适配器"):
        ProviderRegistry(
            llm=None,
            ocr=None,
            storage=None,
            search=None,
            queue=None,
            idempotency=None,
            embedding=None,
            strict=True,
        )


@pytest.mark.asyncio
async def test_provider_registry_shutdown() -> None:
    """测试 ProviderRegistry 异步优雅停机回收。"""
    settings = AppSettings()
    registry = ProviderRegistry.create_default(settings)

    # 验证 shutdown 调用无异常
    await registry.shutdown()
