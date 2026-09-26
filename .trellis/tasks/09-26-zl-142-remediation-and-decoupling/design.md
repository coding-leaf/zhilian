# Technical Design: ZL-142 缺陷修复与架构解耦改造

## 1. 架构与边界划分 (Architecture & Boundaries)
本次改造遵循“业务隔离、协议对齐、渐进落地”的设计原则，按三条清晰的技术边界解耦：
1. **资料解析领域 (Material Domain)**:
   - 边界：`backend/app/api/v1/materials.py` -> `MaterialService` -> `MaterialRepository`。
   - 依赖关系：通过 `BackgroundTasks` 或 `QueueProtocol` 解耦，重试时更新数据库实体状态，重新触发 `run_material_pipeline_background`。
2. **安全鉴权领域 (Auth Domain)**:
   - 边界：`backend/app/services/auth.py` -> `UserRepository`；前端 `login.vue` -> `request.ts`。
   - 依赖关系：严格按照 RFC 6749 JWT 规范，保证 Access Token 与 Refresh Token 的有效性。
3. **AI 图工作流领域 (LLM & Agent Graph)**:
   - 边界：`backend/app/integrations/llm/` 纯基础适配层，不依赖 Web 框架和数据库。

## 2. 详细接口与数据流契约 (Contracts & Data Flow)

### 2.1 资料重试 API 契约
- **Endpoint**: `POST /api/v1/materials/{id}/retry`
- **Request Headers**: `Authorization: Bearer <token>`
- **Response Model**: `MaterialDetailResponse` (HTTP 200 OK)
- **业务流程**:
  ```text
  Client -> API Router -> MaterialService.retry_material_pipeline(id, user_id)
                       -> Repository: 查最新版本，重置 parse_status=QUEUED, error=None
                       -> Repository: 资料 status=PENDING
                       -> DB commit
                       -> BackgroundTasks.add_task(run_material_pipeline_background)
                       -> 返回最新 MaterialDetailResponse
  ```

### 2.2 确定性与双模鉴权数据流
- **开发/测试环境**:
  - `code == "dev_code"` -> `openid = "wx_dev_deterministic_user"`
  - `code.startswith(("dev_", "mock_"))` -> `openid = f"wx_dev_{code}"`
- **生产环境 (配置了 wechat_app_id/secret)**:
  - 调用 `https://api.weixin.qq.com/sns/jscode2session` 置换真实 openid。
- **前端防御**:
  - 遇到异常时直接提示 Toast，禁止写入 `mock_access_token_`，避免 401 拦截器重试雪崩。

### 2.3 LangGraph Tool Calling 契约
- **Schema-as-Tool**:
  ```python
  def pydantic_to_tool_schema(
      model: type[BaseModel],
      name: str = "submit_structured_output",
  ) -> dict[str, Any]:
      return {
          "type": "function",
          "function": {
              "name": name,
              "description": (model.__doc__ or "").strip() or f"Submit structured data for {name}",
              "parameters": model.model_json_schema(),
          },
      }
  ```
- **StateGraph 节点升级**:
  - `call_model_node`: 若传入 `response_model`，注入 `tools` 并强制 `tool_choice={"type": "function", "function": {"name": "submit_structured_output"}}`。
  - `validate_output_node`: 优先解析 `raw_response.tool_calls[0].arguments`，向下兼容普通纯文本。
  - `repair_prompt_node`: 携带工具调用失败的 Tool Error 消息重新请求大模型。

## 3. 兼容性与回滚策略 (Compatibility & Rollback)
- **向后兼容**:
  - `agent_graph.py` 保留 Markdown 代码块提取逻辑作为降级回退，如果大模型未命中 Tool 调用，仍能安全解析文本 JSON。
  - 微信鉴权完全保留现有测试用例兼容性。
- **回滚机制**:
  - 各模块独立提交，若某层（如前端 UI）需要微调，不影响底层重试 API 与 AI 图引擎。
