# Implementation Plan: ZL-142 缺陷修复与架构解耦改造

## Ordered Checklist

- [ ] **Step 1: 资料解析重试后端与服务层实现 (Milestone 1)**
  - 在 `backend/app/repositories/material.py` 增加 `get_latest_version` 方法。
  - 在 `backend/app/services/material.py` 实现 `retry_material_pipeline`，并在 `create_material` 中针对 `FAILED` 状态同哈希版本实现存储复用与重调度。
  - 在 `backend/app/api/v1/materials.py` 暴露 `POST /{id}/retry` 端点。
  - 编写并执行单元测试：`uv run pytest tests/unit/services/test_material_service.py tests/unit/api/test_material_router.py`。

- [ ] **Step 2: 微信双模鉴权与前端登录异常修复 (Milestone 2)**
  - 在 `backend/app/services/auth.py` 实现双模 OpenID 解析（含 `dev_code` 确定性账号与官方 `jscode2session` 置换）。
  - 在 `miniprogram/src/pages/auth/login.vue` 移除伪造假 Token 逻辑，完善错误捕获与提示。
  - 编写并执行测试：`uv run pytest tests/unit/services/test_auth_service.py` 及 `pnpm --dir miniprogram test:unit`。

- [ ] **Step 3: 资料失败态前端交互与就地重试 (Milestone 3)**
  - 在 `miniprogram/src/api/material.ts` 增加 `retryMaterial` 请求方法。
  - 在 `miniprogram/src/subpackages/material/components/MaterialCard.vue` 增加失败重试按钮与事件派发。
  - 在 `miniprogram/src/subpackages/material/pages/detail/index.vue` 和 `list/index.vue` 处理重试逻辑与状态自愈。
  - 运行前端单测与类型检查：`pnpm --dir miniprogram lint && pnpm --dir miniprogram type-check && pnpm --dir miniprogram test:unit`。

- [ ] **Step 4: LangGraph 原生 Tool Calling 升级与图状态自愈 (Milestone 4)**
  - 更新 `backend/app/integrations/llm/protocol.py` 支持 `tools`, `tool_choice`, `tool_calls`。
  - 更新 `backend/app/integrations/llm/openai.py` 和 `fake.py` 适配工具调用入参和响应解析。
  - 升级 `backend/app/integrations/llm/agent_graph.py` 的 `pydantic_to_tool_schema` 与节点处理逻辑。
  - 编写并执行测试：`uv run pytest tests/unit/integrations/llm/`。

- [ ] **Step 5: 全局质量门禁复验 (Final Verification)**
  - 后端：`uv run ruff check .`、`uv run ruff format --check .`、`uv run mypy app`、`uv run pytest`。
  - 前端：`pnpm --dir miniprogram lint`、`pnpm --dir miniprogram type-check`、`pnpm --dir miniprogram test:unit`。

## Verification Commands
```bash
# 后端质检
cd backend
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest

# 前端质检
cd ../miniprogram
pnpm run lint
pnpm run type-check
pnpm run test:unit
```
