"""大语言模型适配器与图编排工厂模块。

严格遵循 AGENTS.md 规范：
- 工厂集中分发并控制实例化参数；
- 默认支持 Fake 模式，隔离网络套接字；
- 遵循 8 个缩写白名单。
"""

from typing import Any

from app.core.errors import LLMError
from app.integrations.llm.agent_graph import build_structured_agent_graph
from app.integrations.llm.fake import FakeLLMAdapter
from app.integrations.llm.openai import OpenAICompatibleLLMAdapter
from app.integrations.llm.protocol import LLMProtocol


def create_llm_adapter(
    adapter_type: str = "fake",
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str = "qwen-max",
    timeout: float = 30.0,
    max_retries: int = 3,
    client: Any | None = None,
    retry_delay_base: float = 0.5,
) -> LLMProtocol:
    """创建并初始化大语言模型适配器实例。

    Args:
        adapter_type: 适配器类型，可选 "fake", "openai", "dashscope", "deepseek", "siliconflow"。
        api_key: 模型服务凭证 Key (生产适配器必填)。
        base_url: 接口基础 URL。
        model: 模型名称。
        timeout: 默认超时时间（秒）。
        max_retries: 最大重试次数。
        client: 可选外部注入的 HTTP 客户端实例。
        retry_delay_base: 退避重试基数（秒）。

    Returns:
        LLMProtocol: 统一接口适配器实例。

    Raises:
        LLMError: 适配器类型未知或参数校验失败。
    """
    adapter_type_lower = adapter_type.lower()
    if adapter_type_lower == "fake":
        return FakeLLMAdapter()

    if adapter_type_lower in ("openai", "dashscope", "deepseek", "siliconflow"):
        if not api_key:
            raise LLMError(f"适配器类型 '{adapter_type}' 需要提供有效的 api_key")

        effective_base_url = base_url
        if effective_base_url is None:
            if adapter_type_lower == "dashscope":
                effective_base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
            elif adapter_type_lower == "deepseek":
                effective_base_url = "https://api.deepseek.com/v1"
            elif adapter_type_lower == "siliconflow":
                effective_base_url = "https://api.siliconflow.cn/v1"

        return OpenAICompatibleLLMAdapter(
            api_key=api_key,
            base_url=effective_base_url,
            model=model,
            timeout=timeout,
            max_retries=max_retries,
            client=client,
            retry_delay_base=retry_delay_base,
        )

    raise LLMError(f"未知的 LLM 适配器类型: '{adapter_type}'")


def create_structured_agent_graph(adapter: LLMProtocol) -> Any:
    """构建并绑定指定适配器的结构化 Agent 执行图。

    Args:
        adapter: 大语言模型适配器实例。

    Returns:
        CompiledStateGraph: 编译就绪的 LangGraph 执行引擎。
    """
    return build_structured_agent_graph(adapter=adapter)


__all__ = [
    "create_llm_adapter",
    "create_structured_agent_graph",
]
