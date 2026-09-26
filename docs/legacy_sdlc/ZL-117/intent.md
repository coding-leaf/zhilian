# Intent: 大语言模型网关适配器与 LangGraph 编排引擎 (LLM Gateway & Agent Graph)

- **任务编号**: ZL-117
- **提出人**: Dev
- **创建时间**: 2026-09-24 01:00
- **初始 Change Tier**: Tier 2
- **当前状态**: Accepted

---

## 1. 问题与现状背景 (Problem)
智练自主学习平台的核心业务高度依赖大语言模型 (LLM) 能力，涵盖知识点抽取建树 (FR-14)、多题型生成 6 要素与评分细则 (FR-20) 以及主观题 AI 判题与错因归因 (FR-41)：
1. **多供应商与协议耦合风险**：平台需接入主流大模型供应商（通义千问 Qwen、DeepSeek、OpenAI、SiliconFlow 等），若业务服务直接依赖具体 SDK 或 HTTP 端点，将导致厂商强绑定与架构腐化；
2. **非功能质量要求严苛 (NFR-11, NFR-26)**：不同业务场景对调用时延敏感度差异显著（如出题上限 60s、判题上限 20s、通用对话 30s）；公网调用存在偶发网络抖动与限流 (HTTP 429/5xx)，亟需统一的指数退避重试与熔断阻断；
3. **结构化输出损坏、自愈与 Agent 状态图编排诉求**：知识点树与题目均要求强类型 Pydantic Schema（JSON）。大模型输出易出现格式残缺、Markdown 标签污染或字段漏缺。传统的 Ad-hoc 过程式硬编码重试难以维护且无法适应未来多轮反思与多 Agent 拓扑，必须采用专职的图状态机引擎（**LangGraph**）建模“生成 -> 校验 -> 自愈修复重试 -> 降级阻断”的标准流转状态图，提供稳固可复用的 Agent 基础设施；
4. **单测网络隔离红线 (NFR-26)**：自动化单元测试执行严禁发起真实公网套接字请求，且需毫秒级通过，要求平台提供高保真、线程安全、支持结构化预置与故障注入的离线假实现 (Fake)，且可无缝作为 LangGraph 节点中的模型调用源；
5. **凭据安全与日志脱敏红线**：大模型 API Key 属于绝密凭证，严禁明文暴露在对象表达、控制台输出或请求日志中；提示词与输出全文禁止入日志。

## 2. 变更性质分类 (Change Archetype - 单选)
- [ ] 局部结构精简 (Local Cleanup - 仅限模块内部冗余消除，不改数据流向与全局装配)
- [x] 单模块特性演进 (Single-Module Feature - 单一模块业务增量或修复)
- [ ] 跨领域架构重构 (Cross-Domain Rewiring - 触及应用全局装配、生命周期或跨域流向，必须升 Tier 3)

## 3. 期望达成效果 (Proposed Outcome)
1. **核心依赖引入 (`backend/pyproject.toml`)**：
   - 显式登记核心依赖 `langgraph>=1.2.12` 与 `langchain-core>=1.6.4`，作为系统 Agent 图编排的统一规范基础。
2. **统一适配层与协议契约 (`backend/app/integrations/llm/protocol.py`)**：
   - 基于 `typing.Protocol` 抽象 `LLMProtocol`，彻底隔离上层业务与底层供应商；
   - 定义不可变强类型 DTO：`LLMMessage`, `LLMOptions`, `LLMUsage`, `LLMResponse`；
   - 协议原生支持作为 LangGraph 节点的模型执行体。
3. **纯内存假实现 (`backend/app/integrations/llm/fake.py`)**：
   - 实现 `FakeLLMAdapter`，零外部 I/O 与网络套接字连接；
   - 支持特定 Prompt/关键词预设回答、强类型 Pydantic 结构化响应预设；
   - 支持时延注入 (`set_latency`) 与故障注入 (`set_fault_injection`)；
   - 基于 `threading.Lock` 实现线程安全，满足单元测试并发安全与隔离要求；
   - `__repr__` 绝密脱敏。
4. **生产适配器 (`backend/app/integrations/llm/openai.py`)**：
   - 实现 `OpenAICompatibleLLMAdapter`，兼容通义千问 DashScope、DeepSeek、OpenAI、SiliconFlow 等标准 `/v1/chat/completions` API；
   - 凭据绝密掩码：`__repr__` 与 `__str__` 中强制 `api_key='******'`；
   - 超时分级与动态覆盖：支持实例级默认超时与调用级 `options.timeout` 覆盖（支持出题 60s、判题 20s）；
   - 弹性退避容灾：针对 429 限流与 5xx 错误执行最多 3 次指数退避重试；401/403 鉴权拒绝立即阻断；
   - 异常转译：底层网络与 HTTP 错误映射为系统 30011~30014 统一业务异常。
5. **基于 LangGraph StateGraph 的 Agent 状态机引擎 (`backend/app/integrations/llm/agent_graph.py`)**：
   - 使用 LangGraph `StateGraph` 统一建模结构化生成工作流；
   - 状态定义：`AgentWorkflowState`（TypedDict: `messages`, `options`, `response_model`, `adapter`, `raw_response`, `parsed_data`, `retry_count`, `error_message`, `status`）；
   - 四大节点：`call_model_node`（调用底层适配器）、`validate_output_node`（Markdown 剥离与 Pydantic 校验）、`repair_prompt_node`（单次自愈修复指令追加）、`fallback_node`（格式错误阻断与降级处理）；
   - 条件分支：通过 `add_conditional_edges` 实现单次自愈决策（首次失败 -> `repair_prompt_node` -> `call_model_node`；二次仍失败 -> `fallback_node` -> `END`；校验成功 -> `END`）；
   - 编译后的图作为通用可复用组件，为后续 ZL-120 (知识点建树)、ZL-121 (题目生成)、ZL-123 (AI 判题) 提供即插即用的图编排引擎。
6. **工厂分发与异常体系**：
   - 在 `backend/app/integrations/llm/factory.py` 提供 `create_llm_adapter` 与 `create_structured_agent_graph` 工厂函数；
   - 在 `backend/app/core/errors.py` 扩充 30011~30014 异常体系。

## 4. 波及工程分面 (Affected Architectural Layers)
- [ ] 核心领域与计算逻辑 (Domain & Core Business Logic)
- [x] 外部接口与协议入口 (Public Ingress & Controllers & Protocols)
- [ ] 数据持久化与状态存储 (Database & Storage & Schemas)
- [ ] 全局装配与应用入口 (Bootstrap & Lifecycle & Service Wiring)

## 5. 边界与硬性约束 (Constraints & Boundaries)
* **硬性技术制约**:
  - 位于 `backend/app/integrations/llm/`，单向依赖向下，**严禁反向导入 `app.services` 与 `app.repositories`**；
  - 遵守 8 个缩写白名单（`api`, `id`, `url`, `ocr`, `llm`, `db`, `config`, `env`）；
  - 绝密脱敏红线：`api_key` 严禁明文出现在 `repr`、`str` 或日志中；提示词与输出文本全文禁止进入日志；
  - 零网络隔离红线：单元测试必须在断网环境下通过，严禁外部网络连接，单测毫秒级通过；
  - 静态架构门禁校验：`python3 tooling/check_layers.py --root backend/app` 0 违规。
* **明确非目标 (Non-Goals / Out-of-Scope)**:
  - 不负责具体业务 Prompt 模板的拼装与管理（由上层业务服务 `KnowledgeService`、`QuestionService`、`GradingService` 承载）；
  - 不负责向量化检索或向量嵌入（由 `app/integrations/embedding` 承载）；
  - 不直接暴露对外 HTTP 路由（由 `app/api/v1` 承载）；
  - 不引入非必要的重量级三方封装黑盒，严格基于 LangGraph `StateGraph` 构建轻量可控的状态机。
* **完成判定条件 (Definition of Done)**:
  - `docs/sdlc/ZL-117/` 下 `intent.md`、`spec.md`、`plan.md` 齐备且通过门禁校验；
  - `backend/pyproject.toml` 登记 `langgraph>=1.2.12` 与 `langchain-core>=1.6.4`；
  - `backend/app/core/errors.py` 扩充 30011~30014 异常类并通过严格 ASCII 排序导出；
  - `backend/app/integrations/llm/` 完整实现 `protocol.py`, `fake.py`, `openai.py`, `agent_graph.py`, `factory.py`, `__init__.py`；
  - 编写适配器单测 `backend/tests/unit/integrations/llm/test_llm.py` 与 LangGraph 图单测 `backend/tests/unit/integrations/llm/test_agent_graph.py`，行覆盖率 $\ge 90\%$，分支覆盖率 $\ge 85\%$；
  - `check_layers.py`、`ruff`、`mypy` 校验全绿，0 高危中危漏洞。

## 6. 未决疑问与待探讨点 (Open Questions)
- **LangGraph Checkpointer 持久化考量**：当前单次自愈重试是否需要在节点间接入 SQLite/Postgres Checkpointer？
  - *裁决*：单次请求内的自愈重试生命周期属于短时无状态（Ephemeral）会话，直接采用纯内存状态传递，避免引入额外 DB I/O 损耗；多轮复杂规划场景预留 Checkpointer 接口。

---

## 7. 阶段准出签批 (Gate 1 Sign-off)
- [x] 场景与问题已客观复现并达成共识
- [x] 边界、非目标与约束清晰明确
- [x] 初始 Change Tier 评定合理
- **准出结论**: Accepted
- **签批人 / 日期**: Dev / 2026-09-24 01:00
