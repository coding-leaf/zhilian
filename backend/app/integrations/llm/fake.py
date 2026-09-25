"""大语言模型纯内存假适配器实现模块。

严格遵循 AGENTS.md 规范：
- 专为单元测试与离线环境设计，零外部套接字连接；
- 内部基于 threading.Lock 保障多线程并发安全；
- 基于消息哈希生成确定性补全结果；
- 支持预设回答映射、预设结构化数据绑定、模拟时延与故障注入；
- 绝密脱敏展示，严禁输出具体交互文本。
"""

import hashlib
import threading
import time
from collections.abc import Sequence
from typing import TypeVar, cast

from pydantic import BaseModel

from app.integrations.llm.agent_graph import run_structured_agent_workflow
from app.integrations.llm.protocol import (
    LLMMessage,
    LLMOptions,
    LLMProtocol,
    LLMResponse,
    LLMUsage,
)

T = TypeVar("T", bound=BaseModel)


class FakeLLMAdapter(LLMProtocol):
    """纯内存假大语言模型适配器。"""

    def __init__(self) -> None:
        """初始化假大模型适配器。"""
        self._lock = threading.Lock()
        self._canned_responses: dict[str, str | LLMResponse] = {}
        self._canned_structured: dict[type[BaseModel], BaseModel] = {}
        self._fault_injections: dict[str, Exception] = {}
        self._latency_seconds: float = 0.0

    def set_canned_response(self, match_key: str, response: str | LLMResponse) -> None:
        """预置指定关键词或提示词的文本响应。

        Args:
            match_key: 匹配关键词或提示文本。
            response: 预设返回的字符串或 LLMResponse 对象。
        """
        with self._lock:
            self._canned_responses[match_key] = response

    def set_canned_structured_response(self, response_model: type[T], data: T) -> None:
        """针对指定 Pydantic 模型类绑定固定结构化对象。

        Args:
            response_model: 绑定的 Pydantic 模型类型。
            data: 预置返回的强类型模型实例。
        """
        with self._lock:
            self._canned_structured[response_model] = data

    def set_latency(self, seconds: float) -> None:
        """设置模拟网络调用时延。

        Args:
            seconds: 延迟秒数。
        """
        with self._lock:
            self._latency_seconds = max(0.0, seconds)

    def set_fault_injection(self, key: str, exception: Exception) -> None:
        """注入指定匹配键触发的模拟异常。

        Args:
            key: 匹配键（如 "generate", "structured", "all" 或 Prompt 关键词）。
            exception: 待抛出的异常实例。
        """
        with self._lock:
            self._fault_injections[key] = exception

    def reset(self) -> None:
        """重置所有预置文本、结构化数据、模拟时延与故障注入。"""
        with self._lock:
            self._canned_responses.clear()
            self._canned_structured.clear()
            self._fault_injections.clear()
            self._latency_seconds = 0.0

    def _check_latency_and_faults(
        self,
        call_type: str,
        messages: Sequence[LLMMessage],
    ) -> None:
        """检查并执行时延与故障注入。"""
        with self._lock:
            latency = self._latency_seconds
            injections = dict(self._fault_injections)

        if latency > 0:
            time.sleep(latency)

        if not injections:
            return

        for fault_key, exc in injections.items():
            if fault_key in ("all", call_type):
                raise exc
            if any(fault_key in msg.content for msg in messages):
                raise exc

    def _generate_deterministic_content(self, messages: Sequence[LLMMessage]) -> str:
        """基于消息序列最后一条内容的摘要生成确定性回答。"""
        last_content = messages[-1].content if messages else ""
        digest = hashlib.sha256(last_content.encode("utf-8")).hexdigest()
        return f"Fake deterministic response [{digest[:12]}]"

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
        self._check_latency_and_faults("generate", messages)

        model_name = options.model if options and options.model is not None else "qwen-max"

        with self._lock:
            canned = dict(self._canned_responses)

        # 优先匹配最新上下文消息中的预设回答
        for msg in reversed(messages):
            for match_key, resp in canned.items():
                if match_key in msg.content:
                    if isinstance(resp, LLMResponse):
                        return resp
                    return LLMResponse(
                        content=resp,
                        usage=LLMUsage(
                            prompt_tokens=len(str(messages)) // 4,
                            completion_tokens=len(resp) // 4,
                            total_tokens=(len(str(messages)) + len(resp)) // 4,
                        ),
                        model=model_name,
                        duration_ms=1.0,
                    )

        # 默认确定性返回
        content = self._generate_deterministic_content(messages)
        return LLMResponse(
            content=content,
            usage=LLMUsage(
                prompt_tokens=10,
                completion_tokens=10,
                total_tokens=20,
            ),
            model=model_name,
            duration_ms=1.0,
        )

    def generate_structured(
        self,
        messages: Sequence[LLMMessage],
        response_model: type[T],
        options: LLMOptions | None = None,
    ) -> tuple[T, LLMResponse]:
        """执行强类型结构化补全。

        优先返回通过 set_canned_structured_response 预置的模型对象；
        若未命中预置对象，则通过 LangGraph 结构化 Agent 状态图执行生成、校验与自愈。

        Args:
            messages: 上下文消息序列。
            response_model: 期望反序列化并校验的 Pydantic 模型类。
            options: 可选调用配置选项。

        Returns:
            tuple[T, LLMResponse]: 结构化模型对象与模型响应。
        """
        self._check_latency_and_faults("generate_structured", messages)

        model_name = options.model if options and options.model is not None else "qwen-max"

        with self._lock:
            if response_model in self._canned_structured:
                instance = cast(T, self._canned_structured[response_model])
                json_content = instance.model_dump_json()
                response = LLMResponse(
                    content=json_content,
                    usage=LLMUsage(
                        prompt_tokens=20,
                        completion_tokens=20,
                        total_tokens=40,
                    ),
                    model=model_name,
                    duration_ms=1.0,
                )
                return instance, response

        return run_structured_agent_workflow(
            adapter=self,
            messages=messages,
            response_model=response_model,
            options=options,
        )

    def __repr__(self) -> str:
        """绝密脱敏表示，仅展示内部注册统计。"""
        with self._lock:
            return (
                f"FakeLLMAdapter(canned_count={len(self._canned_responses)}, "
                f"structured_count={len(self._canned_structured)}, "
                f"fault_count={len(self._fault_injections)}, "
                f"latency_seconds={self._latency_seconds})"
            )

    def __str__(self) -> str:
        return self.__repr__()


__all__ = ["FakeLLMAdapter"]
