"""OpenAI 兼容 / 通义千问 DashScope 向量化生产适配器模块。

严格遵循 AGENTS.md 规范：
- 通过 Protocol 抽象接口与外部大模型提供商解耦；
- 绝密脱敏防泄露：api_key 严禁明文打印在 repr/str 与日志中；
- 20.0s 超时控制与最多 3 次指数退避重试；
- 异常分类转译为统一业务异常体系 (30007~30009)。
"""

import time
from collections.abc import Sequence
from typing import Any, cast

import httpx

from app.core.errors import (
    EmbeddingAuthError,
    EmbeddingError,
    EmbeddingTimeoutError,
)
from app.integrations.embedding.protocol import (
    EmbeddingOptions,
    EmbeddingProtocol,
)


class OpenAICompatibleEmbeddingAdapter(EmbeddingProtocol):
    """OpenAI / DashScope 兼容向量化接口适配器。"""

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        model: str = "text-embedding-v3",
        dimensions: int = 1024,
        timeout: float = 20.0,
        max_retries: int = 3,
        client: Any | None = None,
        retry_delay_base: float = 0.5,
    ) -> None:
        """初始化向量化适配器。

        Args:
            api_key: 大模型服务凭证 Key。
            base_url: 接口基础 URL，默认通义千问兼容接入点。
            model: 向量模型名称，默认 text-embedding-v3。
            dimensions: 期望输出维度（仅用于响应校验，不随请求发送），默认 1024。
            timeout: 单次请求超时时间（秒），默认 20.0。
            max_retries: 偶发错误重试上限，默认 3。
            client: 可选外部注入的 HTTP 客户端实例（测试打桩用）。
            retry_delay_base: 重试退避基数（秒），默认 0.5。

        Raises:
            EmbeddingAuthError: api_key 缺失或为空。
            EmbeddingError: 参数校验不合法。
        """
        if not api_key or not api_key.strip():
            raise EmbeddingAuthError("api_key 不能为空")
        if timeout <= 0.0:
            raise EmbeddingError("timeout 必须大于 0")
        if max_retries < 0:
            raise EmbeddingError("max_retries 不能小于 0")
        if dimensions <= 0:
            raise EmbeddingError("dimensions 必须大于 0")

        self.api_key = api_key.strip()
        self.base_url = (base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1").rstrip(
            "/"
        )
        self.model = model
        self.dimensions = dimensions
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay_base = retry_delay_base
        self._client = client

    def _get_client(self) -> httpx.Client:
        """获取或创建 HTTP 客户端。"""
        if self._client is not None:
            return cast(httpx.Client, self._client)
        return httpx.Client(timeout=self.timeout)

    def _send_request_with_retries(self, payload: dict[str, Any]) -> dict[str, Any]:
        """带指数退避重试的 HTTP 请求发送与异常分类转译。

        Args:
            payload: 发送给 /v1/embeddings 的请求体。

        Returns:
            dict[str, Any]: 解析后的 JSON 数据。

        Raises:
            EmbeddingAuthError: 认证失败 (401/403)。
            EmbeddingTimeoutError: 超时。
            EmbeddingError: 其他业务错误或重试耗尽。
        """
        url = f"{self.base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        last_error: Exception | None = None
        client = self._get_client()

        for attempt in range(self.max_retries + 1):
            try:
                response = client.post(url, json=payload, headers=headers)

                # 401 / 403 凭据错误直接抛出，不重试
                if response.status_code in (401, 403):
                    raise EmbeddingAuthError(
                        f"向量化服务认证失败 (HTTP {response.status_code})",
                        details={"status_code": response.status_code, "body": response.text[:200]},
                    )

                # 429 频率限制或 5xx 服务端错误，触发重试
                if response.status_code == 429 or response.status_code >= 500:
                    last_error = EmbeddingError(
                        f"向量化服务暂时不可用 (HTTP {response.status_code})",
                        details={"status_code": response.status_code, "body": response.text[:200]},
                    )
                    if attempt < self.max_retries:
                        time.sleep(self.retry_delay_base * (2**attempt))
                        continue
                    raise last_error

                # 其他非 200 响应
                if response.status_code != 200:
                    raise EmbeddingError(
                        f"向量化服务返回异常状态码: {response.status_code}",
                        details={"status_code": response.status_code, "body": response.text[:200]},
                    )

                try:
                    data = response.json()
                except Exception as json_err:
                    raise EmbeddingError("向量化服务响应 JSON 反序列化失败") from json_err

                return cast(dict[str, Any], data)

            except (httpx.TimeoutException, TimeoutError) as timeout_err:
                last_error = EmbeddingTimeoutError("向量化服务调用超时")
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay_base * (2**attempt))
                    continue
                raise last_error from timeout_err

            except (httpx.RequestError, ConnectionError) as req_err:
                last_error = EmbeddingError(f"向量化网络请求异常: {req_err}")
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay_base * (2**attempt))
                    continue
                raise last_error from req_err

        if last_error:
            raise last_error
        raise EmbeddingError("向量化请求重试耗尽失败")

    def embed_query(
        self,
        text: str,
        options: EmbeddingOptions | None = None,
    ) -> list[float]:
        """将单个查询文本编码为 1024 维定长浮点向量。

        Args:
            text: 待编码文本。
            options: 可选的模型与调用配置。

        Returns:
            list[float]: 1024 维浮点向量。
        """
        model = options.model if options else self.model
        dimensions = options.dimensions if options else self.dimensions

        # 定维模型（如 bge-large-zh-v1.5）会拒收 dimensions 字段，故不随请求发送；
        # 维度契约改由下方响应校验保障（库表固定 1024 维）。
        payload = {
            "model": model,
            "input": text,
        }

        data = self._send_request_with_retries(payload)
        items = data.get("data", [])
        if not items or "embedding" not in items[0]:
            raise EmbeddingError("向量化响应未包含 embedding 数据")

        vector: list[float] = items[0]["embedding"]
        if len(vector) != dimensions:
            raise EmbeddingError(f"向量维度不匹配: 期望 {dimensions}, 实际 {len(vector)}")

        return vector

    def embed_documents(
        self,
        texts: Sequence[str],
        options: EmbeddingOptions | None = None,
    ) -> list[list[float]]:
        """批量将多个文档文本编码为 1024 维定长浮点向量列表。

        Args:
            texts: 待编码文档序列。
            options: 可选的模型与调用配置。

        Returns:
            list[list[float]]: 包含等量 1024 维向量的列表。
        """
        if not texts:
            return []

        model = options.model if options else self.model
        dimensions = options.dimensions if options else self.dimensions

        payload = {
            "model": model,
            "input": list(texts),
        }

        data = self._send_request_with_retries(payload)
        items = data.get("data", [])
        if len(items) != len(texts):
            raise EmbeddingError(f"向量返回数量不匹配: 期望 {len(texts)}, 实际 {len(items)}")

        # 按照 index 排序确保顺序一致
        sorted_items = sorted(items, key=lambda x: x.get("index", 0))
        results: list[list[float]] = []
        for item in sorted_items:
            vector: list[float] = item.get("embedding", [])
            if len(vector) != dimensions:
                raise EmbeddingError(f"向量维度不匹配: 期望 {dimensions}, 实际 {len(vector)}")
            results.append(vector)

        return results

    def __repr__(self) -> str:
        """安全脱敏日志展示，绝对禁止打印 api_key 明文。"""
        return (
            f"OpenAICompatibleEmbeddingAdapter(model='{self.model}', "
            f"dimensions={self.dimensions}, base_url='{self.base_url}', "
            f"api_key='******', timeout={self.timeout})"
        )

    def __str__(self) -> str:
        return self.__repr__()


__all__ = ["OpenAICompatibleEmbeddingAdapter"]
