# Design: 多选考点生效

## 1. 边界与影响面

| 层 | 文件 | 改动 |
|---|---|---|
| Schema | `backend/app/schemas/question.py` | `QuestionGenerateRequest` 增 `knowledge_point_ids: list[UUID] = []`；`QuestionGenerateResponse` 增 `knowledge_point_ids: list[UUID] = []` |
| Service | `backend/app/services/question.py` | 新增编排方法 `generate_questions_for_knowledge_points(...)`；复用现有 `generate_questions` |
| API | `backend/app/api/v1/questions.py` | 路由按 `knowledge_point_ids` 选择单/多编排；聚合响应 |
| 前端类型 | `miniprogram/src/types/question.ts` | `QuestionGenerateRequest` 增可选 `knowledge_point_ids` |
| 前端组件 | `miniprogram/src/subpackages/material/components/QuestionConfigDrawer.vue` | 提交传全部已选考点 |

不触碰：数据库表结构、既有单考点语义、其它 REST 端点。

## 2. 请求契约

```jsonc
POST /api/v1/questions/generate
{
  "material_id": "...",
  "version_id": "...",              // 可选
  "knowledge_point_id": "...",      // 保留：单考点（向后兼容）
  "knowledge_point_ids": ["...","..."], // 新增：多考点（可选）
  "count": 6,
  "difficulty": 3,
  "question_types": ["single_choice","..."],
  "max_retries": 2
}
```

- 解析优先级：`knowledge_point_ids` 非空 → 多考点；否则用 `knowledge_point_id`（单）。
- 若两者都为空 → 现有校验失败（400）。
- 若 `knowledge_point_ids` 只有一个元素 → 走单考点路径（等价）。

## 3. 题量分配（Count Distribution）

- `n = len(knowledge_point_ids)`，`total = options.count`。
- `base = total // n`，`rem = total % n`；前 `rem` 个考点各 `base+1` 题，其余各 `base` 题。
- 下限保护：每考点 `>= 1` 题。若 `total < n`，则每考点 1 题（实际总数 = n），并在结果/日志标注 `requested_count` 与 `actual_total`。
- 分配规则写入 service 私有纯函数 `distribute_count(total, n) -> list[int]`（可单测，放 `app/core/algorithms` 或 service 内纯函数）。

## 4. 聚合结果（Aggregation）

- 逐个考点调用现有 `generate_questions(user_id, material_id, version_id, knowledge_point_id=kp, options=per_kp_options)`。
- 聚合：
  - `qualified_questions` / `pending_questions`：按调用顺序拼接（每题自带 `knowledge_point_id`）。
  - `quality_checks`：拼接。
  - `total_generated`：求和；`qualified_count`/`pending_count`：求和；`retry_count`：求和。
  - `knowledge_point_id`（旧字段）：取第一个考点（兼容）。
  - `knowledge_point_ids`（新字段）：全部考点。
  - `batch_id`：新建一个批次 ID（或沿用首个批次），`material_id`/`version_id`：取对齐后的版本。
- 返回类型：新增 `MultiKnowledgePointGenerationResult`（或复用 `QuestionGenerationResult` 并扩展），需保证 API 层字段映射清晰。

## 5. 错误语义（不改现有异常）

- 任一考点不存在/越权 → 抛 `KnowledgeNotFoundError`（40007）。
- 某考点无有效切片 → 抛 `MissingSourceSnippetError`（40003）。
- 取舍：**fail-fast**（不做“跳过失败考点继续”的静默降级），与单考点语义一致；如需部分成功，另立任务。

## 6. 兼容性与回滚

- 兼容：请求/响应均为**新增可选字段**；旧客户端不传 `knowledge_point_ids` → 行为与现在完全一致。
- 回滚：移除新增字段与多考点分支即可；无 DB 迁移。

## 7. 测试策略

- 纯函数单测：`distribute_count`（均分、余数、total<n 下限）。
- 服务单测：2~3 个考点 → 断言调用次数、题量分配、聚合字段、每题 `knowledge_point_id` 覆盖集合。
- API 单测：多考点请求返回 `knowledge_point_ids` 与聚合题目；旧单考点请求响应结构不回归。
- 真实链路（可选）：CLI 扩展或直接脚本，验证多考点覆盖。

## 8. 前端联动

- `QuestionConfigDrawer` 提交 payload：`knowledge_point_ids: props.selectedKnowledgeIds`（保持 `knowledge_point_id` = 首个以兼容）。
- UI 提示：显示「已选 N 个考点，共 M 题」，并在 `total < N` 时提示每考点至少 1 题。
