# 题库区块：执行计划

## 前置检查（开工前必做）

- [ ] `python ./.trellis/scripts/task.py current` 确认活动任务是本任务。
- [ ] 读 `spec/backend/database-guidelines.md`（聚合查询、N+1、分页约定）与
      `spec/frontend/state-management.md`（composable 与 store 的边界）。
- [ ] `git grep -n "batches" backend/app/api/v1/questions.py` 确认**尚无**同名路由。
- [ ] 确认 `Question` 模型有 `is_deleted` 与 `status` 两列可参与聚合（`app/models/question.py`）。

## 后端

### 1. 仓储聚合查询（`app/repositories/question.py`）

- [ ] `list_question_batches(user_id, *, limit, offset)` → 按 `batch_id` 分组的
      `(batch_id, question_count, available_count, created_at)`，按 `min(created_at)` 倒序。
- [ ] `count_question_batches(user_id)` → 与上者**同 WHERE** 的真实全量批次数。
- [ ] `list_batch_sources(user_id, batch_ids)` → 只针对本页 batch_id 的
      `(batch_id, material_id, material_title, folder_id, folder_name)` 去重集合。
- [ ] 三条查询都带 `user_id` 过滤 + 排除软删除题目。
- [ ] `available_count` 用 `sum(case when status = ... then 1 else 0 end)`（两库通用），
      不用 `FILTER`。
- [ ] 来源查询用 `LEFT JOIN material_folders`，且**用 `LEFT JOIN materials`**：
      资料已删时保留批次来源位，由装配层给可读降级标签，不得因 JOIN 丢批次。

### 2. Schema（`app/schemas/question.py`）

- [ ] 新增 `QuestionBatchSourceDTO`（material_id / material_title / folder_id / folder_name）。
- [ ] 新增 `QuestionBatchSummaryResponse`（`batch_id: str | None`、
      `question_count`、`available_count`、`pending_review_count`、`created_at`、`sources`）。
- [ ] 新增 `QuestionBatchListResponse`（`items` / `total` / `limit` / `offset`），
      形状与既有 `QuestionListResponse` 对齐。
- [ ] `batch_id` 必须是 `str | None`：历史题目可空，**不得伪造 ID**。

### 3. Service 装配（`app/services/question.py`）

- [ ] `list_question_batches(...)`：调 1、2 两条查询 → 再用 3 一次性装配来源。
- [ ] `pending_review_count = question_count - available_count`。
- [ ] **禁止逐批次查来源**（N+1）。

### 4. 路由（`app/api/v1/questions.py`）

- [ ] ⚠️ **新路由必须注册在 `:198` 的 `"/questions/{id}"` 之前**。
      放错位置的症状是 `/questions/batches` 被 `{id}` 捕获并因 UUID 解析失败返回 422，
      不是错误匹配。**这条要单独写一个回归断言**（见第 5 步）。
- [ ] 查询参数 `page` / `page_size` 与既有 `list_questions` 同约定（`page_size` 上限 100）。

### 5. 后端测试

- [ ] 路由顺序回归：`GET /questions/batches` 返回 200 且响应含 `items`/`total`
      （**不是** 422）——这是能拦住第 4 步放错位置的那条断言。
- [ ] 分页：`total` 为真实批次数，与 `items` 分页一致。
- [ ] `batch_id IS NULL` 的历史题目**出现在结果里**，题量计入。
- [ ] 跨资料批次（一个 `batch_id` 对多 `material_id`）：`sources` 返回多条，
      且不重复、不丢。
- [ ] 租户隔离：另一用户的批次不出现。
- [ ] 软删除题目不计入 `question_count`。
- [ ] 来源已删除时批次仍返回，`sources` 给出可读降级值。

**后端验证命令**

```bash
cd backend && uv run ruff format --check . && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run pytest tests --cov=app --cov-branch --cov-fail-under=80
```

## 前端

### 6. 契约层

- [ ] `src/types/index.ts` 只增**归一化后的 view 类型**（`QuestionBatchSummary` / `BatchSource` /
      题目行类型）；`Wire*` 原始载荷类型按 `spec/frontend/type-safety.md` **定义在 adapter 文件内**，
      **不得进 `types/index.ts`**。
- [ ] `src/api/adapters/` 增适配函数（与 `adaptQuestion` 同址），在适配器里归一化字段，
      **不在组件里断言 payload**。
- [ ] `src/api/index.ts` 增 `apiListQuestionBatches(params)`。

### 7. 纯函数（`src/utils/questionBatch.ts`）——**TDD，先写用例**

- [ ] `miniprogram/tests/questionBatch.spec.ts` 先写失败用例，覆盖：
  - [ ] 三态判定：全选 / 半选 / 未选，含「整批选中后取消一题」→ `partial`。
  - [ ] 已选题数：`whole` 批次用 `availableCount` 减去 `unpicked`，加上 `picked`；
        **断言它与「实际会进入练习的题数」恒等**（对应 PRD AC-9）。
  - [ ] `describeBatchLabel` 的四条来源分支：单资料 / 多资料同课程 / 多资料跨课程 / 来源已删除。
  - [ ] `batchId === null`（未分批）能参与三态判定与计数——**这是 AC-5 的实现前提**，
        类型上必须允许 `null` 进 Map/Set（哨兵或 `string | null` 键）。
  - [ ] 只勾 `pending_review` 时计数为 0（决策 4：待审核不可选）。
- [ ] 再写实现使其通过。

### 8. Composable（`src/pages/review/composables/useQuestionBank.ts`）

- [ ] `loadBatches`：分页加载，写 `isLoading` / `loadError`。
- [ ] `expandBatch(batchId)`：按需拉该批次题目，**仅在展开时触发**。
- [ ] `toggleBatch` / `toggleQuestion`：维护 `whole` / `picked` / `unpicked`。
- [ ] `startPractice()`：解析选中题目的 available ID 集合 → 校验解析数 == 显示数
      → `apiCreatePractice({ title, question_ids, question_count })` → 跳作答页。
- [ ] ⚠️ **必须显式传 `question_count = 计划题数`**。后端 `question_count` 默认 10 且
      显式题目路径按它切片（`app/services/practice.py:473`），不传就静默砍到 10 题。
      见 PRD F3 的更正块。
- [ ] **超过 50 题**（`question_count` 是 `ge=1, le=50`）：先告知再按 50 创建，不得静默截断。
- [ ] 解析数 ≠ 显示数（竞态，**任一方向**）：**必须告知并让用户确认**，不得静默按差额创建。
- [ ] 连点「立即开练」必须只创建一条练习（在途标志守卫；该路径没有幂等键）。
- [ ] 失败走 `RequestError` / `RequestErrorKind` 分类，暴露可重试动作。
- [ ] `tests/questionBank.spec.ts` 覆盖：展开按需（未展开不发题目请求）、
      勾选状态跨展开/收起保持、开练解析数校验、**显式传 `question_count`（变异验证）**、
      **超 50 题先告知**、**连点只创建一条**、**末页空页收掉「加载更多」**。

### 9. 组件与挂载

- [ ] `src/pages/review/components/` 增批次行与题目行组件（沿用 `.paper-card` 风格，
      参考既有 `WrongRecordCard.vue`）。
- [ ] 三态视觉可区分（全选/半选/未选）。
- [ ] `pending_review` 题目显示「待审核」徽标且不可勾选。
- [ ] 加载中 / 空 / 失败三态可区分，失败态带重试。
- [ ] 挂载点由父任务 `09-29-question-bank-tab` 提供（本任务**不改页面骨架**）。
- [ ] 每题预留动作位（供 `09-29-manual-wrong-mark` 挂「记入错题」）——
      **本任务只留位，不实现动作**。

### 10. 需求 2：核对出题页显示批次

- [ ] `src/subpackages/material/pages/questions/index.vue` 渲染本次生成的批次信息。
- [ ] **import 第 7 步的同一个 `describeBatchLabel`**，不得另写口径。
- [ ] 加一条用例或断言，证明两处用的是同一函数（防止将来被复制成第二份）。

### 11. 门禁

```bash
task verify   # 后端 + 前端
```

- [ ] `task verify-frontend` 全绿（eslint / vue-tsc / vitest）。
- [ ] 既有 11 个 spec 文件零回归。

## 风险点与回滚

| 风险 | 症状 | 处理 |
| --- | --- | --- |
| 路由注册在 `:198` 之后 | `/questions/batches` 返回 422 | 第 5 步已有专门断言拦住；调整注册位置 |
| `available_count` 用 `FILTER` | SQLite 下报语法错（测试库先炸） | 改用 `sum(case when ...)` |
| `batch_id` 为 `null` 被 Set 吞掉 | 未分批题目在界面上消失（静默丢数据） | 纯函数用例专门覆盖 `null` 键 |
| `whole` 批次的 ID 解析放在渲染路径 | 违反 AC-7，退化成全量预取 | 只在 `startPractice` 内解析 |
| 解析数少于显示数 | 用户数着题目对不上 | 开练前显式确认，不静默创建 |
| 核对页复制了标签逻辑 | 两页说的「同一个批次」不一致 | 强制 import 同一纯函数 + 断言 |

**回滚**：本任务纯新增（新接口 + 新组件 + 新 composable + 新纯函数）。
回滚 = 撤掉这些文件与父任务挂载点的那一行，**无数据变更、无迁移、无需回滚数据库**。
