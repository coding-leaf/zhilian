# 修复 DIAG 切片 P2-A（009-015）

## Goal

清零 DIAG 切片 7 条 P2 功能与跨层契约 Bug（BUG-DIAG-009 至 BUG-DIAG-015），修复掌握度 DTO 校验器字段同步失效、错题本错误类型与题型过滤后端支持与枚举对齐、错题本 material_id 过滤的 1000 条硬编码截断下推、删除错题响应契约对齐、报告页生命周期重复加载以及筛选重置双重触发。

## 需求来源

上游审计 `09-27-read-only-bug-audit`（已归档）`research/slice-DIAG.md`：

| ID | 级别 | 层 | 一句话 |
|---|---|---|---|
| BUG-DIAG-009 | P2 | cross-layer | `UserMasteryOverviewResponse.mastered_count` 与 `learning_count` 恒 0（`_sync_fields` 仅 `mode="before"` 且只处理 dict，ORM/DTO 对象进入 `from_attributes` 时未同步） |
| BUG-DIAG-010 | P2 | cross-layer | `error_type` 过滤后置于内存切片导致总数失真；前端筛选项（`incomplete`/`deviation`）与后端枚举（`incomplete_expression`/`question_misreading`）不一致 |
| BUG-DIAG-011 | P2 | cross-layer | 前端错题筛选发送 `question_type`，后端错题列表端点未声明该 Query 参数且仓储无对应快照过滤，导致题型筛选被静默忽略 |
| BUG-DIAG-012 | P2 | backend | 错题本按 `material_id` 过滤时通过内存拉取 1000 条后截断切片，超过 1000 条静默丢失且总量不准 |
| BUG-DIAG-013 | P2 | cross-layer | 删除错题响应字段不一致：前端期望 `{ id, removed, message }`，后端下发 `{ id, success, message }`，前端读 `removed` 恒为 undefined |
| BUG-DIAG-014 | P2 | frontend | 报告详情页 `onMounted` 与 `onLoad` 同时无保护调用 `loadReportData`，进入页面重复触发 2 次网络请求与竞态风险 |
| BUG-DIAG-015 | P2 | frontend | 错题筛选栏重置时同时 `emit('reset')` 与 `emitChange()`，页面两处监听均发起 `loadData(1, true)` 导致单次点击重复请求 2 次 |

## Requirements

### 功能要求

1. **DIAG-009（掌握度 DTO 档次口径同步）**：
   - 明确档次字段映射口径：`mastered_count` 对应 `proficient_count`（已精通），`learning_count` 对应 `basic_count`（学习中/基础），`weak_count` 保持一致，`unlearned_count` 保持一致。
   - 在 `UserMasteryOverviewResponse` 的 `mode="after"` 校验器（及 `before` 分支）补充 `mastered_count <-> proficient_count` 和 `basic_count -> learning_count` 同步，无论输入是 dict 还是 DTO/ORM 对象，`mastered_count` 与 `learning_count` 均正确回填。

2. **DIAG-010（错误类型过滤下推与枚举兼容）**：
   - 前端兼容对齐：前端 `WrongRecordFilterBar`、`wrongBookFormat.ts` 支持标准枚举值 `incomplete_expression` 与 `question_misreading`，并向下兼容简写 `incomplete` 与 `deviation`。
   - 后端下推过滤：`error_type` 过滤下推至 `DiagnosisService` 与 `DiagnosisRepository`，在 SQL 层 `WHERE error_type = :error_type` 过滤，并在 `count_wrong_records` 中一并计算真实总数，彻底移除 API 层的后置切片过滤。

3. **DIAG-011（题目类型过滤后端支持）**：
   - 后端路由 `GET /api/v1/wrong-records` 增加可选 Query 参数 `question_type: str | None = None`。
   - 过滤下推至仓储层：利用 JSONB 表达式 `WrongRecord.question_snapshot['question_type'].as_string() == question_type` 或数据库兼容的 JSON 提取方式过滤，并在 count 时同步生效；若数据库方言对 JSON 操作有约束，则在仓储/服务提供标准下推并保持 count 精确。

4. **DIAG-012（material_id 过滤移除 1000 条硬编码截断）**：
   - 替换 `services/diagnosis.py` 中 `limit=1000` 内存过滤逻辑。
   - 仓储层增加支持 `material_id`（通过与 `KnowledgePoint` 表 JOIN）的错题列表与真实总数统计查询，直接在数据库层实现精确分页与真实总数计算。

5. **DIAG-013（删除错题响应契约对齐）**：
   - 后端 `DeleteWrongRecordResponse` 新增附加可选字段 `removed: bool = True`，同时保留既有 `success: bool = True`。
   - 前端 `deleteWrongRecord` 的返回类型与实现保持兼容（`removed: boolean; success?: boolean`），消除潜伏字段契约分歧。

6. **DIAG-014（报告详情页生命周期加载防重）**：
   - 消除 `detail/index.vue` 中 `onMounted` 与 `onLoad` 的双重加载：以 `onLoad`（小程序标准页面传参）为主要入口，增加守卫状态或在 `onMounted` 中仅当尚未触发加载时作为兜底触发，保证单次进入页面只执行 1 次 `loadReportData`。

7. **DIAG-015（错题筛选重置双重触发修复）**：
   - 重构 `WrongRecordFilterBar.vue` 的 `handleReset`：仅由 `emitChange()` 触发 `filter-change`，或规范 `reset` 与 `filter-change` 语义；`wrong-book/index.vue` 移除重复的 `@reset` 发起请求，确保点击重置只向后端发送 1 次请求。

### 约束

- 契约权威：后端 `schemas/diagnosis.py`、`models/practice.py`。
- 新增字段一律**附加可选**，默认值保持旧行为，兼容现有客户端与历史响应。
- 严禁使用 `any`，严格遵守 TypeScript 与 mypy 类型检查。
- 严格遵守分层架构与 `import-linter` 规则，禁止逆向依赖。
- 前端测试夹具字段名逐字取自后端 DTO 定义。
- 不弱化现有测试，改动后保持全量门禁全绿通过。

### 不在范围内

- DIAG P1 缺陷（BUG-DIAG-001…008）已在上游任务完成，不重复修改。
- DIAG 其余 P2 缺陷（BUG-DIAG-016…022）留待后续批次处理。

## Acceptance Criteria

- [ ] **DIAG-009**：`UserMasteryOverviewResponse.model_validate(UserMasteryOverviewDTO(proficient_count=3, basic_count=2, weak_count=1, unlearned_count=4))` 时，响应对象中 `mastered_count == 3` 且 `learning_count == 2`。
- [ ] **DIAG-010**：`GET /api/v1/wrong-records?error_type=incomplete_expression` 能够准确命中包含该错误类型的错题；前端筛选项选择“表述不全”与“审题偏差”时向后端发送标准枚举并能被后端正确识别；SQL 查询与 count 正确包含 `error_type` 条件。
- [ ] **DIAG-011**：`GET /api/v1/wrong-records?question_type=single_choice` 能够根据题目快照中的题型过滤，返回匹配题目且 `total` 为过滤后的真实总数。
- [ ] **DIAG-012**：当错题记录超过 1000 条时，按 `material_id` 分页查询不会发生静默截断，第二页及以后的记录正常返回，且 `total` 返回与数据库实际匹配数一致。
- [ ] **DIAG-013**：`DELETE /api/v1/wrong-records/{id}` 响应 JSON 包含 `removed: true` 和 `success: true`，前端 `deleteWrongRecord(id)` 调用成功解构 `res.data.removed === true`。
- [ ] **DIAG-014**：在模拟页面加载测试中，携带 `practice_id` 进入报告详情页只发起 1 次 `fetchDiagnosisReport` 和 1 次练习详情请求，无重复网络调用。
- [ ] **DIAG-015**：在 `WrongRecordFilterBar` 点击重置时，父组件只触发 1 次 `loadData`，消除双重加载现象。
- [ ] 后端门禁全绿：`uv run ruff format --check .`、`uv run ruff check .`、`uv run mypy app`、`uv run lint-imports`、`uv run pytest tests`。
- [ ] 前端门禁全绿：`pnpm run lint`、`pnpm run type-check`、`pnpm run test:unit`。

## Notes

- 审计证据：`.trellis/tasks/archive/2026-09/09-27-read-only-bug-audit/research/slice-DIAG.md`。
- 依赖关系：无前置依赖，与已落地的 `09-27-fix-diag-read-p1` 及 `09-27-fix-diag-wrongbook-p1` 保持无缝衔接。
