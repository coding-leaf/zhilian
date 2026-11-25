"""OpenAI 兼容 / 通义千问 DashScope 大语言模型生产适配器模块。

严格遵循 AGENTS.md 规范：
- 通过 Protocol 抽象接口与外部大模型提供商解耦；
- 绝密脱敏防泄露：api_key 严禁明文打印在 repr/str 与日志中；
- 动态超时控制与最多 3 次指数退避重试；
- 异常分类转译为统一业务异常体系 (30011~30014)；
- 结构化输出校验委托至 LangGraph Agent 状态图自愈引擎。
"""

import threading
import time
from collections.abc import Sequence
from typing import Any, TypeVar, cast

import httpx
from pydantic import BaseModel

from app.core.errors import (
    LLMAuthError,
    LLMError,
    LLMTimeoutError,
)
from app.integrations._http_retry import (
    RetryableAdapterError,
    build_httpx_client,
    handle_openai_http_response,
    run_with_retry,
)
from app.integrations.llm.agent_graph import run_structured_agent_workflow
from app.integrations.llm.protocol import (
    LLMMessage,
    LLMOptions,
    LLMProtocol,
    LLMResponse,
    LLMToolCall,
    LLMUsage,
)

T = TypeVar("T", bound=BaseModel)


def _serialize_message(message: LLMMessage) -> dict[str, Any]:
    """将 LLMMessage 序列化为 OpenAI Chat Completions 消息体。

    无图片附件时保持纯字符串 content（与既有行为完全一致）；存在 ``image_urls`` 时
    输出 OpenAI vision 兼容的内容块数组，默认 text 在前、image_url 在后，
    当 ``message.image_first`` 为 True 时将 image_url 排在 text 之前。
    """
    if not message.image_urls:
        return {"role": message.role, "content": message.content}
    image_blocks: list[dict[str, Any]] = [
        {"type": "image_url", "image_url": {"url": url}} for url in message.image_urls
    ]
    text_block: dict[str, Any] = {"type": "text", "text": message.content}
    parts = [*image_blocks, text_block] if message.image_first else [text_block, *image_blocks]
    return {"role": message.role, "content": parts}


class OpenAICompatibleLLMAdapter(LLMProtocol):
    """OpenAI / DashScope 兼容大语言模型接口适配器。"""

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        model: str = "qwen-max",
        timeout: float = 30.0,
        max_retries: int = 3,
        client: Any | None = None,
        retry_delay_base: float = 0.5,
    ) -> None:
        """初始化大语言模型适配器。

        Args:
            api_key: 大模型服务凭证 Key。
            base_url: 接口基础 URL，默认通义千问兼容接入点。
            model: 模型名称，默认 qwen-max。
            timeout: 默认超时时间（秒），默认 30.0。
            max_retries: 偶发错误重试上限，默认 3。
            client: 可选外部注入的 HTTP 客户端实例（测试打桩用）。
            retry_delay_base: 重试退避基数（秒），默认 0.5。

        Raises:
            LLMAuthError: api_key 缺失或为空。
            LLMError: 参数校验不合法。
        """
        if not api_key or not api_key.strip():
            raise LLMAuthError("api_key 不能为空")
        if timeout <= 0.0:
            raise LLMError("timeout 必须大于 0")
        if max_retries < 0:
            raise LLMError("max_retries 不能小于 0")

        self.api_key = api_key.strip()
        self.base_url = (base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1").rstrip(
            "/"
        )
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay_base = retry_delay_base
        self._client = client
        self._owned_client: httpx.Client | None = None
        self._client_lock = threading.Lock()

    def _get_client(self, effective_timeout: float | None = None) -> httpx.Client:
        """获取外部注入客户端或复用实例级持久化 httpx.Client 连接池。"""
        if self._client is not None:
            return cast(httpx.Client, self._client)
        with self._client_lock:
            if self._owned_client is None or self._owned_client.is_closed:
                resolved = effective_timeout if effective_timeout is not None else self.timeout
                self._owned_client = build_httpx_client(timeout=resolved)
            return self._owned_client

    def close(self) -> None:
        """释放实例级持久化 httpx.Client 连接池。"""
        with self._client_lock:
            client = self._owned_client
            self._owned_client = None
        if client is not None and not client.is_closed:
            client.close()

    def _send_request_with_retries(
        self,
        payload: dict[str, Any],
        effective_timeout: float,
    ) -> dict[str, Any]:
        """带指数退避重试的 HTTP 请求发送与异常分类转译。

        Args:
            payload: 发送给 /v1/chat/completions 的请求体。
            effective_timeout: 本次请求生效的超时时间。

        Returns:
            dict[str, Any]: 解析后的 JSON 字典。

        Raises:
            LLMAuthError: 认证失败 (401/403)。
            LLMTimeoutError: 超时。
            LLMError: 其他业务错误或重试耗尽。
        """
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        client = self._get_client(effective_timeout)

        def _attempt() -> dict[str, Any]:
            try:
                try:
                    response = client.post(
                        url,
                        json=payload,
                        headers=headers,
                        timeout=effective_timeout,
                    )
                except TypeError:
                    # 兼容可能不接受 timeout 参数的 Mock Client
                    response = client.post(url, json=payload, headers=headers)
                return handle_openai_http_response(
                    response,
                    service_label="大模型服务",
                    auth_error_cls=LLMAuthError,
                    service_error_cls=LLMError,
                )
            except (httpx.TimeoutException, TimeoutError) as timeout_err:
                raise RetryableAdapterError(LLMTimeoutError("大模型服务响应超时")) from timeout_err
            except (httpx.RequestError, ConnectionError) as req_err:
                raise RetryableAdapterError(
                    LLMError(f"大模型服务网络请求异常: {req_err}")
                ) from req_err

        return run_with_retry(
            _attempt,
            max_retries=self.max_retries,
            retry_delay_base=self.retry_delay_base,
            sleep_fn=lambda delay: time.sleep(delay),
        )

    def generate(
        self,
        messages: Sequence[LLMMessage],
        options: LLMOptions | None = None,
    ) -> LLMResponse:
        """执行自由文本或通用对话补全。

        Args:
            messages: 上下文消息序列。
            options: 可选调用配置选项。

        Returns:
            LLMResponse: 统一模型响应。
        """
        start_time = time.perf_counter()
        effective_timeout = (
            options.timeout
            if (options is not None and options.timeout is not None)
            else self.timeout
        )
        model_name = options.model if options and options.model is not None else self.model

        payload: dict[str, Any] = {
            "model": model_name,
            "messages": [_serialize_message(m) for m in messages],
        }
        if options:
            payload["temperature"] = options.temperature
            if options.max_tokens is not None:
                payload["max_tokens"] = options.max_tokens
            if options.response_format is not None:
                payload["response_format"] = {"type": options.response_format}
            if options.tools is not None:
                payload["tools"] = list(options.tools)
            if options.tool_choice is not None:
                payload["tool_choice"] = options.tool_choice

        data = self._send_request_with_retries(payload, effective_timeout)

        choices = data.get("choices", [])
        if not choices or not isinstance(choices, list):
            raise LLMError("大模型响应未包含有效 choices 内容")

        first_choice = choices[0]
        message_data = first_choice.get("message", {})
        content = message_data.get("content", "") or ""

        raw_tool_calls = message_data.get("tool_calls")
        tool_calls: list[LLMToolCall] | None = None
        if raw_tool_calls and isinstance(raw_tool_calls, list):
            tool_calls = []
            for tc in raw_tool_calls:
                fn = tc.get("function", {})
                tool_calls.append(
                    LLMToolCall(
                        id=str(tc.get("id", "")),
                        name=str(fn.get("name", "")),
                        arguments=str(fn.get("arguments", "")),
                    )
                )

        raw_usage = data.get("usage", {})
        usage = LLMUsage(
            prompt_tokens=raw_usage.get("prompt_tokens", 0),
            completion_tokens=raw_usage.get("completion_tokens", 0),
            total_tokens=raw_usage.get("total_tokens", 0),
        )
        duration_ms = (time.perf_counter() - start_time) * 1000.0

        return LLMResponse(
            content=content,
            usage=usage,
            model=model_name,
            duration_ms=duration_ms,
            tool_calls=tool_calls,
        )

    def generate_structured(
        self,
        messages: Sequence[LLMMessage],
        response_model: type[T],
        options: LLMOptions | None = None,
    ) -> tuple[T, LLMResponse]:
        """执行强类型结构化补全并自动完成 Pydantic 校验与单次残缺自愈。

        Args:
            messages: 上下文消息序列。
            response_model: 期望反序列化并校验的 Pydantic 模型类。
            options: 可选调用配置选项。

        Returns:
            tuple[T, LLMResponse]: 校验通过的结构化对象及完整模型响应。
        """
        return run_structured_agent_workflow(
            adapter=self,
            messages=messages,
            response_model=response_model,
            options=options,
        )

    def __repr__(self) -> str:
        """安全脱敏日志展示，绝对禁止打印 api_key 明文。"""
        return (
            f"OpenAICompatibleLLMAdapter(model='{self.model}', "
            f"base_url='{self.base_url}', api_key='******', "
            f"timeout={self.timeout}, max_retries={self.max_retries})"
        )

    def __str__(self) -> str:
        return self.__repr__()


__all__ = ["OpenAICompatibleLLMAdapter"]
