"""大语言模型网关适配器抽象协议与数据传输模型定义模块。

严格遵循 AGENTS.md 规范：
- 通过 Protocol 抽象接口与外部大模型提供商解耦；
- 强类型不可变数据契约 (frozen dataclass)，零 Web 框架依赖；
- 遵守 8 个缩写白名单 (api, id, url, ocr, llm, db, config, env)。
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class LLMMessage:
    """对话消息数据传输对象。"""

    role: str
    content: str

    def __post_init__(self) -> None:
        """防御性参数校验。"""
        valid_roles = {"system", "user", "assistant"}
        if self.role not in valid_roles:
            raise ValueError(f"role 必须为 {valid_roles} 之一，实际为: '{self.role}'")
        if not self.content.strip():
            raise ValueError("content 不能为空字符串")


@dataclass(frozen=True)
class LLMToolCall:
    """大模型工具调用数据传输对象。"""

    id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class LLMOptions:
    """大模型调用控制选项。"""

    model: str | None = None
    temperature: float = 0.7
    max_tokens: int | None = None
    timeout: float = 30.0
    response_format: str | None = None
    tools: Sequence[dict[str, Any]] | None = None
    tool_choice: str | dict[str, Any] | None = None

    def __post_init__(self) -> None:
        """防御性参数合法性校验。"""
        if not (0.0 <= self.temperature <= 2.0):
            raise ValueError(f"temperature 必须在 [0.0, 2.0] 范围内，实际为: {self.temperature}")
        if self.timeout <= 0.0:
            raise ValueError(f"timeout 必须大于 0，实际为: {self.timeout}")
        if self.max_tokens is not None and self.max_tokens <= 0:
            raise ValueError(f"max_tokens 必须大于 0，实际为: {self.max_tokens}")


@dataclass(frozen=True)
class LLMUsage:
    """Token 消耗统计模型。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def __post_init__(self) -> None:
        """Token 数量非负防御校验。"""
        if self.prompt_tokens < 0 or self.completion_tokens < 0 or self.total_tokens < 0:
            raise ValueError("token 数量不能小于 0")


@dataclass(frozen=True)
class LLMResponse:
    """大模型调用响应数据传输对象。"""

    content: str
    usage: LLMUsage
    model: str
    duration_ms: float = 0.0
    tool_calls: Sequence[LLMToolCall] | None = None


@runtime_checkable
class LLMProtocol(Protocol):
    """大语言模型网关统一适配协议契约。"""

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

        Raises:
            LLMAuthError: 凭据无效或鉴权拒绝 (30013, 502)。
            LLMTimeoutError: 网络连接或等待超时 (30012, 504)。
            LLMError: 服务不可用或重试耗尽 (30011, 502)。
        """
        ...

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

        Raises:
            LLMResponseFormatError: JSON 解析损坏或 Schema 校验失败且自愈无效 (30014, 502)。
            LLMAuthError: 凭据鉴权拒绝 (30013, 502)。
            LLMTimeoutError: 调用响应超时 (30012, 504)。
            LLMError: 通用调用错误 (30011, 502)。
        """
        ...


__all__ = [
    "LLMMessage",
    "LLMOptions",
    "LLMProtocol",
    "LLMResponse",
    "LLMToolCall",
    "LLMUsage",
]
