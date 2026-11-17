# 结构化输出在思考模型上不可用

## Goal

让结构化大模型调用（出题 / 知识抽取 / 判题）在**思考模式（thinking mode）模型**上可用。
当前形态是：换用 DeepSeek 官方 API 后，所有结构化调用直接 502。

## 现象（2026-09-29 用户实测）

```
[request] kind=http POST http://localhost:8000/api/v1/questions/generate
status=502 detail=大模型服务返回异常状态码: 400
```

## 根因：**已复现并定案**

### 上游真实错误

`502` 只是外层包装；上游真实报错为（本次侦察用项目自身的适配器复现取得）：

```
Thinking mode does not support this tool_choice
```

### 机制

`app/integrations/llm/agent_graph.py::call_model_node` 的 Schema-as-Tool 方案，
把 `tool_choice` **强制指定到具体函数**：

```python
tool_choice = {"type": "function", "function": {"name": tool_name}}
```

DeepSeek 的思考模式模型**拒绝一切「强制」语义的 `tool_choice`**。实测矩阵：

| `tool_choice` 取值 | deepseek-flash | deepseek-v4-pro |
| --- | --- | --- |
| `{"type":"function","function":{"name":...}}`（**项目原用法**） | **400** | **400** |
| `"required"` | **400** | — |
| `"auto"` | 200，且 `tool_calls=[emit_result]` | 200，且调用了工具 |
| 不传 | 200，且调用了工具 | — |

### 为什么现在才暴露

用户此前用的第三方中转站不校验这条约束；切到 DeepSeek 官方 API 后被其强制。
**属配置变更暴露的既有兼容性缺陷**，不是新引入的 bug。

### 附带发现

`deepseek-flash` 是**推理模型**（响应含 `reasoning_content`）。实测中
`max_tokens=8` 时 `finish_reason='length'` 且 `content` 为空——推理 token 会挤占
`max_tokens`。调用方若把 `max_tokens` 设得过小，会拿到空内容而误判为"模型没输出"。
本任务不处理，**登记为待决项**。

## Change Boundary

### In scope

- `app/integrations/llm/agent_graph.py`：默认 `tool_choice` 由「强制指定具体函数」改为 `"auto"`。
- 保留调用方经 `options.tool_choice` 显式覆盖的能力（`current_options.tool_choice or tool_choice`）。

### Out of scope

- **不改 `app/integrations/llm/openai.py`**：适配器不应替调用方改写意图。
  若将来需要「按 provider 能力降级」，应在 options 装配层做，而不是在传输层偷偷改。
- **不引入 provider 能力探测**（如按 model 名判断是否思考模型）。当前两个可用模型行为一致，
  加能力表是过早抽象；等真的出现"支持强制 tool_choice 的模型"再加。
- **不处理 `max_tokens` 与推理 token 的关系**（见上「附带发现」）。
- **不改前端**：本次 502 的前端表现（toast「生成失败」）是正确行为。

## Requirements

### R1 — 不强制 `tool_choice`

- `agent_graph` 的默认值改为 `"auto"`，`tools` 照旧注入。
- 必须写明**为何不能用强制值**（上游报错原文）与**为何 `auto` 不削弱结构化保证**，
  否则后人很容易"顺手优化"回强制。

### R2 — 结构化保证不退化

- 依据（已在代码中，无需新建）：
  1. `tools` 仍注入，模型在 `auto` 下实测仍会调用工具；
  2. `validate_output_node` 已有 `tool_calls` → 纯文本/Markdown 的向下兼容解析分支；
  3. 既有自愈重试（`retry_count == 0` 允许一次）与 `LLMResponseFormatError` 终态。
- **不得**为了让 `auto` 更"可靠"而新增 prompt 措辞约束——模型在 `auto` 下的工具调用
  是实测达成的事实，不是需要额外引导的概率事件。

## Acceptance Criteria

- [x] AC-1 上游真实错误已取得并留档（`Thinking mode does not support this tool_choice`）。
      证据：用项目自身适配器 + `run_structured_agent_workflow` 复现，异常 `details.body` 见上。
- [x] AC-2 修复后**同一条复现路径成功**：`run_structured_agent_workflow` 经 DeepSeek
      返回并解析出 2 道题目（实测输出 TCP 三次握手单选题题干）。
- [x] AC-3 `tool_choice` 的四种取值对照矩阵已实测留档（见上表），
      证明选择 `auto` 是唯一可用且不牺牲工具调用的取值。
- [x] AC-4 调用方仍可经 `options.tool_choice` 覆盖：`agent_graph` 保留
      `current_options.tool_choice or tool_choice`，既有用例
      `tests/unit/integrations/llm/test_llm.py:346`（断言显式 `tool_choice` 进入 payload）零回归。
- [x] AC-5 `ruff format` / `ruff check` / `mypy app`（strict，135 files）全绿。
- [ ] AC-6 `pytest --cov-fail-under=80` 全绿（本次改动在共享模块，必须全量跑）。
- [ ] AC-7 **端到端待用户确认**：重启后端后在开发者工具里完成一次真实生题。

## Notes

- 本次修复的触发条件是**用户切换了模型服务**。留档这条因果，避免下次换模型时
  再从「502 → 大模型服务返回异常状态码: 400」这个被吞了细节的文案开始查一遍。
- **诊断性缺口（建议单独立项）**：`LLMError` 的 `details` 里**已经带了** `status_code` 与
  `body[:200]`，但 HTTP 响应只暴露 `大模型服务返回异常状态码: 400`，
  上游的真实原因在接口层被丢掉。若这条链路把 `details` 透出，本次排查
  可以省掉「复现 + 打点」两步。本次不顺手改（涉及错误响应的对外契约）。
