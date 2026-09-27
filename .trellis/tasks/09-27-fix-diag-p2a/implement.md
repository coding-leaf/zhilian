# 执行计划：DIAG 切片 P2-A 修复（009-015）

## 前置

- 任务目标：清零 DIAG 切片 7 条 P2 功能与跨层契约缺陷（BUG-DIAG-009 至 BUG-DIAG-015）。
- 契约权威与技术设计：参考 `prd.md` 与 `design.md`。
- 上游审计证据：`.trellis/tasks/archive/2026-09/09-27-read-only-bug-audit/research/slice-DIAG.md`。

---

## 执行清单（有序）

### Step 1 — 失败回归测试（红）
- [ ] 1.1 后端：在 `tests/unit/schemas/test_diagnosis_schemas.py` 增加用例：
  - 断言 `UserMasteryOverviewResponse.model_validate(UserMasteryOverviewDTO(...))` 后 `mastered_count == proficient_count` 且 `learning_count == basic_count`（当前恒为 0，必红）。
  - 断言 `DeleteWrongRecordResponse` 实例包含 `removed is True` 且 `success is True`。
- [ ] 1.2 后端：在 `tests/unit/api/test_diagnosis_router.py` 增加用例：
  - 断言 `GET /api/v1/wrong-records?question_type=single_choice` 会按快照题型过滤并返回正确 `items` 与 `total`。
  - 断言 `GET /api/v1/wrong-records?error_type=incomplete_expression` 会在仓储层进行真实总数与分页统计。
- [ ] 1.3 后端：在 `tests/unit/repositories/test_diagnosis_repo.py` 增加用例：
  - 测试按 `material_id` 过滤错题时，当错题数较多时分页能够准确返回且 `count_wrong_records` 统计真实总数，无 1000 截断限制。
- [ ] 1.4 前端：在 `tests/unit/report/reportDetailPage.spec.ts` 增加用例：
  - 断言进入报告详情页仅发起 1 次报告数据请求与 1 次练习详情请求（当前 onLoad 与 onMounted 双重调用，必红）。
- [ ] 1.5 前端：在 `tests/unit/report/wrongBookPage.spec.ts` 增加用例：
  - 断言在 `WrongRecordFilterBar` 点击重置时，父组件仅触发 1 次 `loadData`。
- [ ] 1.6 运行测试确认新增断言呈现红态（FAIL）。

### Step 2 — 后端 DTO 与契约修复（DIAG-009、DIAG-013）
- [ ] 2.1 修改 `backend/app/schemas/diagnosis.py`：
  - 在 `UserMasteryOverviewResponse._sync_after` 中补充 `mastered_count <-> proficient_count` 及 `basic_count <-> learning_count` 双向同步。
  - 在 `DeleteWrongRecordResponse` 中添加附加可选字段 `removed: bool = Field(default=True, description="是否成功移除")`。
- [ ] 2.2 验证 Step 1.1 的 Schema 测试转绿。

### Step 3 — 后端仓储与服务层多维过滤下推（DIAG-010、DIAG-011、DIAG-012）
- [ ] 3.1 修改 `backend/app/repositories/diagnosis.py`：
  - `list_wrong_records` 和 `count_wrong_records` 增加 `material_id`、`error_type`、`question_type` 可选入参。
  - 当传入 `material_id` 时，通过关联 `KnowledgePoint` 进行 SQL 级别过滤。
  - 当传入 `question_type` 时，通过题目快照中的 `question_type` 字段进行过滤。
  - 当传入 `error_type` 时，在 SQL 条件中进行精确过滤。
- [ ] 3.2 修改 `backend/app/services/diagnosis.py`：
  - `list_wrong_records` 接收 `error_type` 和 `question_type`，并将 `material_id` 过滤下推至仓储层，彻底移除 `limit=1000` 内存硬编码截断。
- [ ] 3.3 修改 `backend/app/api/v1/diagnosis.py`：
  - `list_wrong_records` 路由声明 `question_type` Query 参数。
  - 将 `error_type` 映射与标准化后透传至 Service，移除 API 层后置的 Python 列表切片过滤。
- [ ] 3.4 验证 Step 1.2 与 Step 1.3 的 API 与仓储测试转绿。

### Step 4 — 前端枚举对齐与接口类型更新（DIAG-010、DIAG-013）
- [ ] 4.1 修改 `miniprogram/src/types/report.ts` 与 `miniprogram/src/api/diagnosis.ts`：
  - 更新 `deleteWrongRecord` 响应类型包含 `removed: boolean` 和 `success?: boolean`。
  - 完善 `WrongRecordQueryParams` 支持 `question_type` 与标准 `error_type`。
- [ ] 4.2 修改 `miniprogram/src/subpackages/report/components/WrongRecordFilterBar.vue`：
  - 将错误类型的枚举值对齐为 `incomplete_expression` 与 `question_misreading`。
- [ ] 4.3 修改 `miniprogram/src/subpackages/report/utils/wrongBookFormat.ts`：
  - 增强 `getErrorTypeInfo` 支持新枚举，并对旧缩写 `incomplete` 与 `deviation` 进行兼容映射。

### Step 5 — 前端生命周期与事件双触发修复（DIAG-014、DIAG-015）
- [ ] 5.1 修改 `miniprogram/src/subpackages/report/pages/detail/index.vue`：
  - 增加请求防重标志（如 `hasLoaded`），统一 `onLoad` 与 `onMounted` 的加载时机，确保单次进入仅加载 1 次。
- [ ] 5.2 修改 `miniprogram/src/subpackages/report/components/WrongRecordFilterBar.vue` 与 `wrong-book/index.vue`：
  - 统一重置事件流，避免重置操作同时触发 `reset` 与 `filter-change` 导致父组件重复调用 `loadData`。
- [ ] 5.3 验证 Step 1.4 与 Step 1.5 的前端测试转绿。

### Step 6 — 全量门禁校验与收尾
- [ ] 6.1 后端全套质量门禁检查：
  - `uv run ruff format --check .`
  - `uv run ruff check .`
  - `uv run mypy app`
  - `uv run lint-imports`
  - `uv run pytest tests`
- [ ] 6.2 前端全套质量门禁检查：
  - `pnpm run lint`
  - `pnpm run type-check`
  - `pnpm run test:unit`
- [ ] 6.3 确认所有 7 条 Bug 均得到完整修复与测试覆盖。

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
