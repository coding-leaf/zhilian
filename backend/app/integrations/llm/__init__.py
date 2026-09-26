"""大语言模型网关适配器与 LangGraph 编排引擎模块。

严格遵循 AGENTS.md 规范：
- 通过 Protocol 抽象接口与外部大模型提供商解耦；
- 基于 LangGraph StateGraph 实现结构化输出自愈与图编排；
- 遵循 8 个缩写白名单 (api, id, url, ocr, llm, db, config, env)；
- __all__ 导出列表严格遵循 ASCII 字典序排序。
"""

from app.integrations.llm.agent_graph import (
    AgentWorkflowState,
    build_structured_agent_graph,
    call_model_node,
    decide_after_validation,
    fallback_node,
    pydantic_to_tool_schema,
    repair_prompt_node,
    run_structured_agent_workflow,
    validate_output_node,
)
from app.integrations.llm.factory import (
    create_llm_adapter,
    create_structured_agent_graph,
)
from app.integrations.llm.fake import FakeLLMAdapter
from app.integrations.llm.openai import OpenAICompatibleLLMAdapter
from app.integrations.llm.protocol import (
    LLMMessage,
    LLMOptions,
    LLMProtocol,
    LLMResponse,
    LLMToolCall,
    LLMUsage,
)

__all__ = [
    "AgentWorkflowState",
    "FakeLLMAdapter",
    "LLMMessage",
    "LLMOptions",
    "LLMProtocol",
    "LLMResponse",
    "LLMToolCall",
    "LLMUsage",
    "OpenAICompatibleLLMAdapter",
    "build_structured_agent_graph",
    "call_model_node",
    "create_llm_adapter",
    "create_structured_agent_graph",
    "decide_after_validation",
    "fallback_node",
    "pydantic_to_tool_schema",
    "repair_prompt_node",
    "run_structured_agent_workflow",
    "validate_output_node",
]
