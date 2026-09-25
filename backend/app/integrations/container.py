"""外部基础设施协议适配器注册中心。

严格遵循 AGENTS.md 架构分层规范：
- 属于 app/integrations 适配层，绝对禁止反向导入 app.services 或 app.repositories；
- 集中统一分发并持有 7 块协议实例 (LLM, OCR, Storage, Search, Queue, Idempotency, Embedding)；
- 提供生命周期关闭钩子 (shutdown)。
"""

import asyncio
from typing import Any

from app.core.config import AppSettings, get_settings
from app.integrations.embedding.factory import create_embedding_adapter
from app.integrations.embedding.protocol import EmbeddingProtocol
from app.integrations.idempotency.factory import create_idempotency_adapter
from app.integrations.idempotency.protocol import IdempotencyProtocol
from app.integrations.llm.factory import create_llm_adapter
from app.integrations.llm.protocol import LLMProtocol
from app.integrations.ocr.factory import create_ocr_adapter
from app.integrations.ocr.protocol import OCRProtocol
from app.integrations.queue.factory import create_queue_adapter
from app.integrations.queue.protocol import QueueProtocol
from app.integrations.search.factory import create_search_adapter
from app.integrations.search.protocol import SearchProtocol
from app.integrations.storage.factory import create_storage_adapter
from app.integrations.storage.protocol import StorageProtocol


class ProviderRegistry:
    """外部基础设施协议适配器统一注册表。

    管理大模型、OCR、存储、检索、任务队列、幂等控制与向量化 7 块 Protocol 适配器。
    支持不可变默认装配、测试时动态覆盖注入与统一生命周期资源释放。
    """

    def __init__(
        self,
        llm: LLMProtocol | None = None,
        ocr: OCRProtocol | None = None,
        storage: StorageProtocol | None = None,
        search: SearchProtocol | None = None,
        queue: QueueProtocol | None = None,
        idempotency: IdempotencyProtocol | None = None,
        embedding: EmbeddingProtocol | None = None,
        *,
        strict: bool = False,
    ) -> None:
        """初始化基础设施适配器注册中心。

        Args:
            llm: 大语言模型协议适配器。
            ocr: 光学字符识别协议适配器。
            storage: 对象存储协议适配器。
            search: 检索协议适配器。
            queue: 任务队列协议适配器。
            idempotency: 幂等拦截协议适配器。
            embedding: 向量化协议适配器。
            strict: 是否在构造时强制验证所有协议均已就绪。

        Raises:
            ValueError: strict 为 True 且存在未就绪的协议适配器。
        """
        self._llm = llm
        self._ocr = ocr
        self._storage = storage
        self._search = search
        self._queue = queue
        self._idempotency = idempotency
        self._embedding = embedding

        if strict:
            self.validate()

    @property
    def llm(self) -> LLMProtocol:
        """获取大语言模型协议适配器。

        Returns:
            LLMProtocol: 大语言模型适配器实例。

        Raises:
            ValueError: 适配器尚未注册。
        """
        if self._llm is None:
            raise ValueError("未注册的大语言模型协议 (llm adapter is not registered)")
        return self._llm

    @llm.setter
    def llm(self, adapter: LLMProtocol) -> None:
        self._llm = adapter

    @property
    def ocr(self) -> OCRProtocol:
        """获取光学字符识别协议适配器。

        Returns:
            OCRProtocol: OCR 适配器实例。

        Raises:
            ValueError: 适配器尚未注册。
        """
        if self._ocr is None:
            raise ValueError("未注册的光学字符识别协议 (ocr adapter is not registered)")
        return self._ocr

    @ocr.setter
    def ocr(self, adapter: OCRProtocol) -> None:
        self._ocr = adapter

    @property
    def storage(self) -> StorageProtocol:
        """获取对象存储协议适配器。

        Returns:
            StorageProtocol: 存储适配器实例。

        Raises:
            ValueError: 适配器尚未注册。
        """
        if self._storage is None:
            raise ValueError("未注册的对象存储协议 (storage adapter is not registered)")
        return self._storage

    @storage.setter
    def storage(self, adapter: StorageProtocol) -> None:
        self._storage = adapter

    @property
    def search(self) -> SearchProtocol:
        """获取检索协议适配器。

        Returns:
            SearchProtocol: 检索适配器实例。

        Raises:
            ValueError: 适配器尚未注册。
        """
        if self._search is None:
            raise ValueError("未注册的检索协议 (search adapter is not registered)")
        return self._search

    @search.setter
    def search(self, adapter: SearchProtocol) -> None:
        self._search = adapter

    @property
    def queue(self) -> QueueProtocol:
        """获取任务队列协议适配器。

        Returns:
            QueueProtocol: 任务队列适配器实例。

        Raises:
            ValueError: 适配器尚未注册。
        """
        if self._queue is None:
            raise ValueError("未注册的任务队列协议 (queue adapter is not registered)")
        return self._queue

    @queue.setter
    def queue(self, adapter: QueueProtocol) -> None:
        self._queue = adapter

    @property
    def idempotency(self) -> IdempotencyProtocol:
        """获取幂等拦截协议适配器。

        Returns:
            IdempotencyProtocol: 幂等适配器实例。

        Raises:
            ValueError: 适配器尚未注册。
        """
        if self._idempotency is None:
            raise ValueError("未注册的幂等拦截协议 (idempotency adapter is not registered)")
        return self._idempotency

    @idempotency.setter
    def idempotency(self, adapter: IdempotencyProtocol) -> None:
        self._idempotency = adapter

    @property
    def embedding(self) -> EmbeddingProtocol:
        """获取向量化协议适配器。

        Returns:
            EmbeddingProtocol: 向量化适配器实例。

        Raises:
            ValueError: 适配器尚未注册。
        """
        if self._embedding is None:
            raise ValueError("未注册的向量化协议 (embedding adapter is not registered)")
        return self._embedding

    @embedding.setter
    def embedding(self, adapter: EmbeddingProtocol) -> None:
        self._embedding = adapter

    def register_llm(self, adapter: LLMProtocol) -> "ProviderRegistry":
        """注册或覆盖大语言模型适配器。"""
        self.llm = adapter
        return self

    def register_ocr(self, adapter: OCRProtocol) -> "ProviderRegistry":
        """注册或覆盖 OCR 适配器。"""
        self.ocr = adapter
        return self

    def register_storage(self, adapter: StorageProtocol) -> "ProviderRegistry":
        """注册或覆盖对象存储适配器。"""
        self.storage = adapter
        return self

    def register_search(self, adapter: SearchProtocol) -> "ProviderRegistry":
        """注册或覆盖检索适配器。"""
        self.search = adapter
        return self

    def register_queue(self, adapter: QueueProtocol) -> "ProviderRegistry":
        """注册或覆盖任务队列适配器。"""
        self.queue = adapter
        return self

    def register_idempotency(self, adapter: IdempotencyProtocol) -> "ProviderRegistry":
        """注册或覆盖幂等拦截适配器。"""
        self.idempotency = adapter
        return self

    def register_embedding(self, adapter: EmbeddingProtocol) -> "ProviderRegistry":
        """注册或覆盖向量化适配器。"""
        self.embedding = adapter
        return self

    def validate(self) -> None:
        """验证所有 7 块协议适配器均已就绪。

        Raises:
            ValueError: 存在尚未注册的协议适配器。
        """
        missing: list[str] = []
        for name in ("llm", "ocr", "storage", "search", "queue", "idempotency", "embedding"):
            if getattr(self, f"_{name}", None) is None:
                missing.append(name)
        if missing:
            raise ValueError(
                f"ProviderRegistry 缺少未注册的基础设施协议适配器: {', '.join(missing)}"
            )

    @classmethod
    def create_empty(cls) -> "ProviderRegistry":
        """创建未装配任何协议适配器的空注册中心。

        Returns:
            ProviderRegistry: 空注册中心实例。
        """
        return cls(strict=False)

    @classmethod
    def create_default(
        cls,
        settings: AppSettings | None = None,
        session_factory: Any | None = None,
    ) -> "ProviderRegistry":
        """根据全局或指定配置生产符合 Protocol 契约的全套默认适配器。

        Args:
            settings: 应用强类型配置，缺省自动从环境加载单例。
            session_factory: 可选传入的 SQLAlchemy 会话工厂（供混合检索适配器）。

        Returns:
            ProviderRegistry: 已就绪的基础设施适配器注册中心。
        """
        if settings is None:
            settings = get_settings()

        llm_api_key = (
            settings.llm.api_key.get_secret_value() if settings.llm.api_key is not None else None
        )
        llm = create_llm_adapter(
            adapter_type=settings.llm.provider,
            api_key=llm_api_key,
            base_url=settings.llm.base_url,
            model=settings.llm.model,
            timeout=settings.llm.timeout,
            max_retries=settings.llm.max_retries,
        )

        ocr_api_key = (
            settings.ocr.effective_api_key.get_secret_value()
            if settings.ocr.effective_api_key is not None
            else None
        )
        ocr_secret_key = (
            settings.ocr.secret_key.get_secret_value()
            if settings.ocr.secret_key is not None
            else None
        )
        ocr = create_ocr_adapter(
            adapter_type=settings.ocr.provider,
            api_key=ocr_api_key,
            secret_id=ocr_api_key,
            secret_key=ocr_secret_key,
            region=settings.ocr.region,
            endpoint=settings.ocr.endpoint,
            timeout=settings.ocr.timeout,
            max_retries=settings.ocr.max_retries,
        )

        storage_access_key = (
            settings.storage.access_key.get_secret_value()
            if settings.storage.access_key is not None
            else None
        )
        storage_secret_key = (
            settings.storage.secret_key.get_secret_value()
            if settings.storage.secret_key is not None
            else None
        )
        storage = create_storage_adapter(
            storage_type=settings.storage.provider,
            endpoint_url=settings.storage.endpoint_url,
            access_key=storage_access_key,
            secret_key=storage_secret_key,
            region_name=settings.storage.region,
            secure=settings.storage.use_ssl,
        )

        embedding_api_key = (
            settings.embedding.api_key.get_secret_value()
            if settings.embedding.api_key is not None
            else None
        )
        embedding = create_embedding_adapter(
            adapter_type=settings.embedding.provider,
            api_key=embedding_api_key,
            base_url=settings.embedding.base_url,
            model=settings.embedding.model,
            dimensions=settings.embedding.dimension,
            timeout=settings.embedding.timeout,
            max_retries=settings.embedding.max_retries,
        )

        search = create_search_adapter(
            adapter_type=settings.search.provider,
            session_factory=session_factory,
            embedding_adapter=embedding,
        )

        queue_redis_url = settings.redis.redis_url if settings.queue.provider == "redis" else None
        queue = create_queue_adapter(
            adapter_type=settings.queue.provider,
            redis_url=queue_redis_url,
            immediate_mode=settings.queue.immediate_mode,
        )

        idempotency_redis_url = (
            settings.redis.redis_url if settings.idempotency.provider == "redis" else None
        )
        idempotency = create_idempotency_adapter(
            adapter_type=settings.idempotency.provider,
            redis_url=idempotency_redis_url,
        )

        return cls(
            llm=llm,
            ocr=ocr,
            storage=storage,
            search=search,
            queue=queue,
            idempotency=idempotency,
            embedding=embedding,
            strict=True,
        )

    @classmethod
    def create_from_settings(
        cls,
        settings: AppSettings,
        session_factory: Any | None = None,
    ) -> "ProviderRegistry":
        """兼容从强类型配置创建注册中心契约。"""
        return cls.create_default(settings=settings, session_factory=session_factory)

    async def shutdown(self) -> None:
        """清理外部适配器网络连接池与后台运行句柄。"""
        for adapter in (
            self._llm,
            self._ocr,
            self._storage,
            self._search,
            self._queue,
            self._idempotency,
            self._embedding,
        ):
            if adapter is None:
                continue
            shutdown_fn = getattr(adapter, "shutdown", None)
            if callable(shutdown_fn):
                if asyncio.iscoroutinefunction(shutdown_fn):
                    await shutdown_fn()
                else:
                    shutdown_fn()
                continue

            aclose_fn = getattr(adapter, "aclose", None)
            if callable(aclose_fn):
                res = aclose_fn()
                if asyncio.iscoroutine(res):
                    await res
                continue

            close_fn = getattr(adapter, "close", None)
            if callable(close_fn):
                if asyncio.iscoroutinefunction(close_fn):
                    await close_fn()
                else:
                    close_fn()


__all__ = ["ProviderRegistry"]
