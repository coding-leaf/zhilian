# 执行计划：DIAG 切片 P2-A 修复（009-015）

## 前置

- 任务目标：清零 DIAG 切片 7 条 P2 功能与跨层契约缺陷（BUG-DIAG-009 至 BUG-DIAG-015）。
- 契约权威与技术设计：参考 `prd.md` 与 `design.md`。
- 上游审计证据：`.trellis/tasks/archive/2026-09/09-27-read-only-bug-audit/research/slice-DIAG.md`。

---

## 执行清单（有序）

### Step 1 — 失败回归测试（红）
- [x] 1.1 后端：在 `tests/unit/schemas/test_diagnosis_schemas.py` 增加用例：
  - 断言 `UserMasteryOverviewResponse.model_validate(UserMasteryOverviewDTO(...))` 后 `mastered_count == proficient_count` 且 `learning_count == basic_count`。
  - 断言 `DeleteWrongRecordResponse` 实例包含 `removed is True` 且 `success is True`。
- [x] 1.2 后端：在 `tests/unit/api/test_diagnosis_router.py` 增加用例：
  - 断言 `GET /api/v1/wrong-records` 将 `question_type` 与 `error_type` 透传 Service；路由层不再后置过滤。
- [x] 1.3 后端：在 `tests/unit/repositories/test_diagnosis_repo.py` 增加用例：
  - 测试按 `material_id` + `error_type` + `question_type` 过滤，以及 1005 条错题下 `count_wrong_records` 与分页无 1000 截断。
- [x] 1.4 前端：在 `tests/unit/report/reportDetailPage.spec.ts` 增加用例：
  - 断言进入报告详情页仅发起 1 次报告数据请求与 1 次练习详情请求。
- [x] 1.5 前端：在 `tests/unit/report/wrongBookPage.spec.ts` 增加用例：
  - 断言在 `WrongRecordFilterBar` 点击重置时，父组件仅触发 1 次 `loadData`。
- [x] 1.6 运行测试确认新增断言呈现红态（FAIL）。

### Step 2 — 后端 DTO 与契约修复（DIAG-009、DIAG-013）
- [x] 2.1 修改 `backend/app/schemas/diagnosis.py`：
  - 在 `UserMasteryOverviewResponse._sync_after`（及 `_sync_fields` before 分支）补充 `mastered_count <-> proficient_count` 及 `basic_count <-> learning_count` 双向同步。
  - 在 `DeleteWrongRecordResponse` 中添加附加可选字段 `removed: bool = Field(default=True, ...)`。
- [x] 2.2 验证 Step 1.1 的 Schema 测试转绿。

### Step 3 — 后端仓储与服务层多维过滤下推（DIAG-010、DIAG-011、DIAG-012）
- [x] 3.1 修改 `backend/app/repositories/diagnosis.py`：
  - `list_wrong_records` 和 `count_wrong_records` 增加 `material_id`、`error_type`、`question_type` 可选入参。
  - `material_id` 通过关联 `KnowledgePoint` 进行 SQL 级别过滤。
  - `question_type` 通过 `WrongRecord.question_snapshot["question_type"].as_string()` 过滤。
  - `error_type` 在 SQL 条件中精确过滤。
- [x] 3.2 修改 `backend/app/services/diagnosis.py`：
  - `list_wrong_records` 接收并下推 `material_id`/`error_type`/`question_type`；新增 `normalize_error_type`（兼容 `incomplete`/`deviation` 简写）；彻底移除 `limit=1000` 内存硬编码截断。
- [x] 3.3 修改 `backend/app/api/v1/diagnosis.py`：
  - `list_wrong_records` 路由声明 `question_type` Query 参数，透传 `error_type`/`question_type`，移除 API 层后置 Python 列表切片过滤。
- [x] 3.4 验证 Step 1.2 与 Step 1.3 的 API 与仓储测试转绿。

### Step 4 — 前端枚举对齐与接口类型更新（DIAG-010、DIAG-013）
- [x] 4.1 修改 `miniprogram/src/types/report.ts` 与 `miniprogram/src/api/diagnosis.ts`：
  - 新增 `DeleteWrongRecordResult`（`removed: boolean; success?: boolean`）并更新 `deleteWrongRecord` 泛型。
  - `WrongErrorType` 扩展标准枚举 `incomplete_expression`/`question_misreading`。
- [x] 4.2 修改 `miniprogram/src/subpackages/report/components/WrongRecordFilterBar.vue`：
  - 错误类型枚举对齐为 `incomplete_expression` 与 `question_misreading`；题型填空值对齐为 `fill_in_blank`。
- [x] 4.3 修改 `miniprogram/src/subpackages/report/utils/wrongBookFormat.ts`：
  - `getErrorTypeInfo` 支持新枚举，并向下兼容旧缩写 `incomplete` 与 `deviation`。

### Step 5 — 前端生命周期与事件双触发修复（DIAG-014、DIAG-015）
- [x] 5.1 `miniprogram/src/subpackages/report/pages/detail/index.vue` 的 onLoad/onMounted 防重守卫已在 HEAD（`1d39896`，BUG-GRADE-006）落地；本次补充回归测试断言报告+练习详情各仅 1 次。
- [x] 5.2 修改 `WrongRecordFilterBar.vue`（移除 `emit('reset')` 与 `reset` 事件声明）与 `wrong-book/index.vue`（移除 `@reset` 监听），统一由 `filter-change` 单通道触发。
- [x] 5.3 验证 Step 1.4 与 Step 1.5 的前端测试转绿。

### Step 6 — 全量门禁校验与收尾
- [x] 6.1 后端全套质量门禁检查（全绿）：
  - `uv run ruff format --check .`（217 files already formatted）
  - `uv run ruff check .`（All checks passed）
  - `uv run mypy app`（Success: no issues found in 125 source files）
  - `uv run lint-imports`（Contracts: 5 kept, 0 broken）
  - `uv run pytest tests`（1219 passed, 1 warning）
- [x] 6.2 前端全套质量门禁检查（全绿）：
  - `pnpm run lint`（无错误）
  - `pnpm run type-check`（vue-tsc 无错误）
  - `pnpm run test:unit`（59 files / 548 tests passed）
- [x] 6.3 确认所有 7 条 Bug 均得到完整修复与测试覆盖。

---

## 验证命令

```bash
# 后端（workdir=backend）
uv run ruff format --check . && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run pytest tests

# 前端（workdir=miniprogram）
pnpm run lint && pnpm run type-check && pnpm run test:unit
```

---

## 评审门禁

- **Gate A（先红后绿）**：Step 1 编写的 5 组失败回归测试必须清晰重现缺陷，并在完成修复后转为全绿。
- **Gate B（无破坏性改动）**：既有功能与前后端现有所有测试用例保持 100% 通过，不可弱化既有断言。
- **Gate C（类型与架构）**：后端 `mypy` 与 `lint-imports` 零警告零错误，前端 TypeScript 编译与 ESLint 零错误。

---

## 回滚点

- 后端 DTO 新增字段 `removed` 为可选字段，如遇意外可直接移除。
- 若仓储层针对快照 JSONB 的跨数据库查询条件在特定测试数据库引擎引发语法差异，可回退为 SQL 兼容的纯字符串或应用层安全过滤。
- 前端生命周期防重标志位为局部状态，可安全撤回。
