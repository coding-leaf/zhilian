# PRD: ZL-142 缺陷修复与架构解耦改造

## 1. 目标与用户价值 (Goal & Value)
针对历史 Fall 任务 ZL-142 中暴露出的大范围强耦合修改导致系统回滚的教训，采用解耦、原子化、渐进式原则，彻底解决用户提出的三大真实使用缺陷：
1. **资料解析异常中断与重试缺失**：同文件解析失败重传无法重试、缺乏整份资料一键就地重试与自愈能力；
2. **鉴权不稳定与异常掉登录**：前端假 Token 引发 401 死循环，后端缺少稳定 dev OpenID 导致测试账号频繁分裂；
3. **LangGraph 流程与 Tool Calling 现代化**：淘汰脆弱的 Markdown 正则 JSON 截取，升级为原生 Schema-as-Tool 原生结构化调用与状态图自愈闭环。

## 2. 事实与代码锚点 (Facts & Evidence)
- **锚点 1（资料重试端点缺失）**: `backend/app/api/v1/materials.py` 仅有单页重拍路由，无 `POST /{id}/retry` 端点；`backend/app/services/material.py` 在 `create_material` 遇到 `FAILED` 状态同哈希版本时未重新调度解析。
- **锚点 2（前端登录死循环与假 Token）**: `miniprogram/src/pages/auth/login.vue:44` 在 catch 中生成 `mock_access_token_`，导致后续业务请求抛 401，被 `miniprogram/src/utils/request.ts` 捕获并在重试耗尽后强制 `reLaunch('/pages/auth/login')` 造成循环死锁。
- **锚点 3（后端微信授权与用户分裂）**: `backend/app/services/auth.py:84` 未对 `dev_code` 做确定性映射，直接拼接 `wx_{code}`，每次小程序登录产生新临时 code 导致分裂出独立的新 user_id。
- **锚点 4（LangGraph 正则耦合）**: `backend/app/integrations/llm/agent_graph.py:96` 使用 `re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", content_str)` 强依赖文本代码块，未利用 `LLMProtocol` 与 `OpenAICompatibleLLMAdapter` 的原生 Function Calling。

## 3. 功能需求 (Requirements)

### R1. 资料解析重试与异常自愈 (Material Pipeline Retry)
- **R1.1 后端重试端点**: 新增 `POST /api/v1/materials/{id}/retry`，校验租户归属，将最新版本的状态由 `FAILED` 重置为 `QUEUED`，清空 `error_message` 和 `failed_stage`，将资料状态重置为 `PENDING`，并通过 BackgroundTasks 重新拉起异步流水线。
- **R1.2 重复上传自愈**: 在 `create_material` 中，若检测到同哈希文件历史版本为 `FAILED`，复用存储 key 并将其重新激活调度，不再死锁或拒绝。
- **R1.3 前端重试交互**: `MaterialCard.vue` 与详情页在 `status === 'FAILED'` 时展示警示并提供【重试解析】操作，点击调用重试 API 并自动拉起轮询。

### R2. 鉴权长效保持与确定性会话 (Auth Session Resilience)
- **R2.1 后端确定性 OpenID & 微信接口置换**: `AuthService._resolve_wechat_openid` 支持双模。若配置微信凭据则走官方 `jscode2session`；若为本地/测试 `dev_code` 或 mock code，映射为稳定持久账号（如 `wx_dev_deterministic_user`），杜绝用户无故分裂。
- **R2.2 移除前端假 Token**: `login.vue` 彻底移除 `mock_access_token_`；登录接口失败时直接提示用户，不向 Store 存入无效令牌；确保开发环境下自动传递有效测试 code 登录。

### R3. LangGraph 原生 Tool Calling 升级 (Agent Graph Schema-as-Tool)
- **R3.1 契约支持**: `LLMOptions` 支持 `tools` 与 `tool_choice` 参数，`LLMResponse` 携带 `tool_calls`。
- **R3.2 适配器对接**: `OpenAICompatibleLLMAdapter` 支持向后端 payload 注入 tools 并解析返回的 tool_calls；`FakeLLMAdapter` 在提供 tools 时自动构造 mock tool_call。
- **R3.3 状态图自动工具化**: `agent_graph.py` 将 `response_model` 自动转为 OpenAPI function schema，优先从 `tool_calls` 提取参数验证，验证失败在图内进行 Tool Error 纠错与重试，彻底摆脱 Markdown 正则依赖。

## 4. 验收标准 (Acceptance Criteria)
- **AC1 (资料重试)**:
  - 调用 `POST /api/v1/materials/{id}/retry` 成功返回 200，资料版本状态重置为 `QUEUED` 并异步启动解析。
  - 前端资料列表卡片与详情页在失败状态下渲染【重试解析】按钮，点击后触发请求并启动状态刷新。
- **AC2 (鉴权稳定)**:
  - 携带 `dev_code` 多次登录返回同一固定 user id，历史数据可完整持久保留。
  - 前端登录失败时不写入非法 Token，阻断 401 重定向死循环。
- **AC3 (Tool Calling)**:
  - `run_structured_agent_workflow` 成功将 Pydantic 模型作为 Tool 派发并从 `tool_calls` 中成功反序列化。
  - 单元测试与端到端质检全绿：`pytest` 覆盖率与测试无损，前端 `eslint`、`vue-tsc`、`vitest` 零错误。

## 5. 非范围项 (Out of Scope)
- 不改动现有数据库核心表结构（不引入不可逆 migration）。
- 不重写前端路由骨架与 Store 核心持久化协议。
