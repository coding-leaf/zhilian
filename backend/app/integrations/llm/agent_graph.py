"""基于 LangGraph StateGraph 的结构化 Agent 状态机引擎。

严格遵循 AGENTS.md 规范：
- 基于 LangGraph StateGraph 显式建模结构化自愈全生命周期；
- 状态流转无副作用，单次自愈严格受控 (retry_count == 0 允许重试，>=1 阻断)；
- 绝密脱敏防泄露，杜绝在状态与异常中泄露私密文本；
- 零 Web 框架与数据库依赖。
"""

import json
import re
from collections.abc import Sequence
from typing import Any, Literal, TypedDict, cast

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from app.core.errors import LLMResponseFormatError
from app.integrations.llm.protocol import (
    LLMMessage,
    LLMOptions,
    LLMProtocol,
    LLMResponse,
)


class AgentWorkflowState(TypedDict, total=False):
    """LangGraph 状态机流转上下文状态。"""

    messages: list[LLMMessage]
    options: LLMOptions | None
    response_model: type[BaseModel]
    adapter: LLMProtocol
    raw_response: LLMResponse | None
    parsed_data: Any | None
    retry_count: int
    error_message: str | None
    status: Literal["pending", "success", "failed"]


def pydantic_to_tool_schema(
    model: type[BaseModel],
    name: str = "submit_structured_output",
) -> dict[str, Any]:
    """将 Pydantic 模型自动转为 OpenAPI function schema。"""
    description = (model.__doc__ or "").strip() or f"Submit structured data for {name}"
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": model.model_json_schema(),
        },
    }


def call_model_node(
    state: AgentWorkflowState,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """节点 1: 注入 Schema-as-Tool 配置并调用底层适配器生成结果。

    若指定了 response_model，自动生成 OpenAPI Tool 规范并注入 options.tools 与 tool_choice。

    Args:
        state: 当前状态图上下文。
        config: 可选 RunnableConfig。

    Returns:
        dict[str, Any]: 更新后的 raw_response 字段。
    """
    adapter = state.get("adapter")
    if adapter is None:
        raise ValueError("AgentWorkflowState 中未指定有效 adapter")
    messages = state.get("messages", [])
    current_options = state.get("options")
    response_model = state.get("response_model")

    effective_options = current_options
    if response_model is not None:
        tool_schema = pydantic_to_tool_schema(response_model)
        tool_name = tool_schema["function"]["name"]
        tools = [tool_schema]
        tool_choice: str | dict[str, Any] = {"type": "function", "function": {"name": tool_name}}

        if current_options is not None:
            effective_options = LLMOptions(
                model=current_options.model,
                temperature=current_options.temperature,
                max_tokens=current_options.max_tokens,
                timeout=current_options.timeout,
                response_format=current_options.response_format,
                tools=current_options.tools or tools,
                tool_choice=current_options.tool_choice or tool_choice,
            )
        else:
            effective_options = LLMOptions(
                tools=tools,
                tool_choice=tool_choice,
            )

    response = adapter.generate(messages, effective_options)
    return {"raw_response": response}


def validate_output_node(
    state: AgentWorkflowState,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """节点 2: 优先解析 Tool Call 参数，兼容文本与 Markdown JSON 反序列化校验。

    Args:
        state: 当前状态图上下文。
        config: 可选 RunnableConfig。

    Returns:
        dict[str, Any]: 校验成功或失败的状态更新字典。
    """
    raw_response = state.get("raw_response")
    if raw_response is None:
        return {
            "parsed_data": None,
            "status": "failed",
            "error_message": "未获取到模型原始响应",
        }

    response_model = state.get("response_model")
    if response_model is None:
        return {
            "parsed_data": None,
            "status": "failed",
            "error_message": "未指定 response_model",
        }

    content_str = ""
    # 优先解析 raw_response.tool_calls[0].arguments，向下兼容普通纯文本与 Markdown
    if raw_response.tool_calls and len(raw_response.tool_calls) > 0:
        first_tool = raw_response.tool_calls[0]
        content_str = first_tool.arguments.strip()

    if not content_str:
        content_str = raw_response.content.strip()

    # 提取 Markdown 代码块中的 JSON 内容（若存在多个代码块，默认优先匹配首个有效 JSON 块）
    markdown_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", content_str)
    if markdown_match:
        content_str = markdown_match.group(1).strip()

    try:
        json_data = json.loads(content_str)
        parsed_obj = response_model.model_validate(json_data)
        return {
            "parsed_data": parsed_obj,
            "status": "success",
            "error_message": None,
        }
    except Exception as err:
        return {
            "parsed_data": None,
            "error_message": str(err),
        }


def decide_after_validation(
    state: AgentWorkflowState,
) -> Literal["repair_prompt_node", "fallback_node", "__end__"]:
    """条件边决策函数: 判断是否自愈重试、阻断降级或正常结束。

    Args:
        state: 当前状态图上下文。

    Returns:
        Literal["repair_prompt_node", "fallback_node", "__end__"]: 下一步流转目标。
    """
    if state.get("parsed_data") is not None:
        return "__end__"

    if state.get("retry_count", 0) == 0:
        return "repair_prompt_node"

    return "fallback_node"


def repair_prompt_node(
    state: AgentWorkflowState,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """节点 3: 构造并追加自愈修复上下文提示词。

    Args:
        state: 当前状态图上下文。
        config: 可选 RunnableConfig。

    Returns:
        dict[str, Any]: 递增 retry_count 与追加诊断提示词后的消息列表。
    """
    retry_count = state.get("retry_count", 0) + 1
    current_messages = list(state.get("messages", []))
    raw_response = state.get("raw_response")
    raw_content = ""
    if raw_response:
        if raw_response.tool_calls and len(raw_response.tool_calls) > 0:
            raw_content = raw_response.tool_calls[0].arguments
        else:
            raw_content = raw_response.content
    error_message = state.get("error_message") or "Unknown validation error"

    current_messages.append(LLMMessage(role="assistant", content=raw_content or "{}"))
    current_messages.append(
        LLMMessage(
            role="user",
            content=(
                f"Your previous response failed validation: {error_message}. "
                "Please correct the output and return strictly valid JSON conforming to the schema."
            ),
        )
    )

    return {
        "retry_count": retry_count,
        "messages": current_messages,
    }


def fallback_node(
    state: AgentWorkflowState,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """节点 4: 记录最终失败状态，准备阻断或降级。

    Args:
        state: 当前状态图上下文。
        config: 可选 RunnableConfig。

    Returns:
        dict[str, Any]: 置 status="failed"。
    """
    return {"status": "failed"}


def build_structured_agent_graph(adapter: LLMProtocol | None = None) -> Any:
    """构建并编译基于 LangGraph StateGraph 的标准状态图。

    Args:
        adapter: 可选预先绑定的模型适配器。若提供，则在调用缺省时作为默认适配器。

    Returns:
        CompiledStateGraph: 编译就绪的图执行引擎。
    """

    # 包装 call_model_node 支持预绑 adapter
    def _call_model(
        state: AgentWorkflowState,
        config: RunnableConfig | None = None,
    ) -> dict[str, Any]:
        if "adapter" not in state or state["adapter"] is None:
            if adapter is None:
                raise ValueError("AgentWorkflowState 中未指定 adapter 且图未预绑 adapter")
            state["adapter"] = adapter
        return call_model_node(state, config)

    workflow = StateGraph(AgentWorkflowState)
    workflow.add_node("call_model_node", _call_model)
    workflow.add_node("validate_output_node", validate_output_node)
    workflow.add_node("repair_prompt_node", repair_prompt_node)
    workflow.add_node("fallback_node", fallback_node)

    workflow.add_edge(START, "call_model_node")
    workflow.add_edge("call_model_node", "validate_output_node")
    workflow.add_conditional_edges(
        "validate_output_node",
        decide_after_validation,
        {
            "__end__": END,
            "repair_prompt_node": "repair_prompt_node",
            "fallback_node": "fallback_node",
        },
    )
    workflow.add_edge("repair_prompt_node", "call_model_node")
    workflow.add_edge("fallback_node", END)

    return workflow.compile()


def run_structured_agent_workflow[T: BaseModel](
    adapter: LLMProtocol,
    messages: Sequence[LLMMessage],
    response_model: type[T],
    options: LLMOptions | None = None,
) -> tuple[T, LLMResponse]:
    """执行强类型结构化 Agent 工作流。

    Args:
        adapter: 大模型适配器实现。
        messages: 上下文对话消息。
        response_model: 期望校验转换的 Pydantic 模型类。
        options: 可选调用配置。

    Returns:
        tuple[T, LLMResponse]: 校验成功的模型实例与模型响应对象。

    Raises:
        LLMResponseFormatError: 校验自愈失败抛出 (30014, 502)。
    """
    graph = build_structured_agent_graph(adapter=adapter)
    initial_state: AgentWorkflowState = {
        "messages": list(messages),
        "options": options,
        "response_model": response_model,
        "adapter": adapter,
        "raw_response": None,
        "parsed_data": None,
        "retry_count": 0,
        "error_message": None,
        "status": "pending",
    }

    result = graph.invoke(initial_state)

    if result.get("status") == "success" and result.get("parsed_data") is not None:
        return cast(T, result["parsed_data"]), cast(LLMResponse, result["raw_response"])

    error_detail = result.get("error_message") or "输出格式不符合 Schema 规范且自愈失败"
    last_content = ""
    if result.get("raw_response"):
        last_content = result["raw_response"].content[:200]

    raise LLMResponseFormatError(
        f"结构化 Agent 状态图校验自愈失败: {error_detail}",
        details={
            "retry_count": result.get("retry_count", 0),
            "last_content_preview": last_content,
        },
    )


__all__ = [
    "AgentWorkflowState",
    "build_structured_agent_graph",
    "call_model_node",
    "decide_after_validation",
    "fallback_node",
    "pydantic_to_tool_schema",
    "repair_prompt_node",
    "run_structured_agent_workflow",
    "validate_output_node",
]
