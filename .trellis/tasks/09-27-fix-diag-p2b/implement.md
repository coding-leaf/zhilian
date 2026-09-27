# 执行计划：DIAG 切片 P2-B（016-022）修复

## 前置

- 任务：`09-27-fix-diag-p2b`（父任务：`09-27-fullstack-bug-audit-and-fix`）。
- 权威设计：`design.md`；问题证据：`.trellis/tasks/archive/2026-09/09-27-read-only-bug-audit/research/slice-DIAG.md`。

## 执行清单（有序）

### Step 1 — 失败回归与断言准备（先红后绿）
- [x] 1.1 前端：在 `miniprogram/tests/unit/stores/report.spec.ts` 中新增测试用例，断言 `setReport(null)` 或传入无薄弱点的报告时，`weakPoints.value` 被正确置空（DIAG-016 红）。
- [x] 1.2 前端：在 `miniprogram/tests/unit/stores/practice.spec.ts` 与 `tests/unit/components/RecentLearningSection.spec.ts` 中新增用例，断言 `initSession` 生成的草稿包含 `total_count`/`title`/`material_id` 并能被正确展示（DIAG-017 红）。
- [x] 1.3 前端/跨层：在 `miniprogram/tests/unit/api/diagnosis.spec.ts` 断言 `continuePractice` 携带 `Idempotency-Key` 请求头（DIAG-018 红）。
- [x] 1.4 后端：在 `backend/tests/unit/api/test_practice_router.py` 与 `test_practice_service.py` 增加接收 `Idempotency-Key`、幂等回放与并发冲突的断言（DIAG-018 红）。
- [x] 1.5 后端：在 `backend/tests/unit/services/test_diagnosis_service.py` 编写并发生成报告模拟 `IntegrityError` 的测试，断言安全回查返回已有报告而不抛出 500（DIAG-019 红）。
- [x] 1.6 后端：在 `backend/tests/unit/services/test_diagnosis_service.py` 断言全景薄弱点列表 `weak_knowledge_points` 严格按掌握度升序排序（DIAG-020 红）。
- [x] 1.7 后端/前端：在 `backend/tests/unit/schemas/test_diagnosis_schemas.py` 断言 `UserMasteryOverviewResponse` 输出包含 `weak_points` 别名（DIAG-021 红）。
- [x] 1.8 前端：在 `miniprogram/tests/unit/report/reportDetailPage.spec.ts` 中断言无 pid 或空报告时渲染空态结构 `.empty-state`（DIAG-022 红）。

### Step 2 — 逐步实现各缺陷修复
- [x] 2.1 **DIAG-016**：修改 `miniprogram/src/stores/reportStore.ts::setReport`，当 `report?.weak_points` 不存在时清空 `weakPoints.value = []`。
- [x] 2.2 **DIAG-017**：
  - 更新 `miniprogram/src/types/practice.ts::AnswerDraft` 接口增加 `total_count?: number`、`title?: string`、`material_id?: string`；
  - 更新 `miniprogram/src/stores/practiceStore.ts::initSession` 将题目总数及元数据写入草稿。
- [x] 2.3 **DIAG-018**：
  - 更新 `miniprogram/src/api/diagnosis.ts::continuePractice`，使用 `Idempotency-Key` 作为 Header 键名；
  - 更新 `backend/app/schemas/practice.py::PracticeCreateRequest` 增加 `idempotency_key` 字段；
  - 更新 `backend/app/api/v1/practices.py::create_practice` 支持读取 `Idempotency-Key` 请求头。
- [x] 2.4 **DIAG-019**：在 `backend/app/services/diagnosis.py::generate_diagnosis_report` 增加捕获 `IntegrityError` 的重试回查分支，回滚事务并返回已生成的既有报告。
- [x] 2.5 **DIAG-020**：在 `backend/app/services/diagnosis.py::get_user_mastery_overview` 组装完薄弱点后，对 `weak_points_summary` 按照 `(item.mastery_score, item.knowledge_point_id)` 进行升序排序。
- [x] 2.6 **DIAG-021**：
  - 更新 `backend/app/schemas/diagnosis.py::UserMasteryOverviewResponse` 增加 `weak_points` 字段与双向同步映射；
  - 更新 `miniprogram/src/types/report.ts::KnowledgeMasterySummary` 兼容字段映射声明。
- [x] 2.7 **DIAG-022**：
  - 更新 `miniprogram/src/subpackages/report/pages/detail/index.vue` 模板，增加 `v-else` 空态展示；
  - 更新 `detail.scss` 补充空态容器与按钮样式；
  - 增加返回首页/学习中心处理逻辑。

### Step 3 — 全门禁验证
- [x] 3.1 运行所有新增单元测试，确保全部翻绿。
- [x] 3.2 后端全门禁：
  - `uv run ruff format --check .`
  - `uv run ruff check .`
  - `uv run mypy app`
  - `uv run lint-imports`
  - `uv run pytest tests`
- [x] 3.3 前端全门禁：
  - `pnpm run lint`
  - `pnpm run type-check`
  - `pnpm run test:unit`

## 验证命令

```powershell
# 后端门禁（工作目录：backend）
uv run ruff format --check . && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run pytest tests

# 前端门禁（工作目录：miniprogram）
pnpm run lint && pnpm run type-check && pnpm run test:unit
```

## 评审门禁

- **Gate A**：7 条缺陷对应的测试用例严格经历先红后绿，杜绝无断言修复。
- **Gate B**：后端五大门禁全绿，前端三大门禁全绿，无任何类型忽略（如 `@ts-ignore` / `any`）。
- **Gate C**：回归既有单元测试，保证所有存量端点与功能无退化。

## 回滚点

- 所有改动均为非侵入式的防御性补丁或接口别名兼容，回滚时仅需通过 git 检出对应源文件即可无缝还原。

## 执行结果（2026-09-27 实施记录）

- **实际测试文件路径修正**：spec 目录实际为 `stores/report.spec.ts`、`stores/practice.spec.ts`、`api/diagnosis.spec.ts`、`report/reportDetailPage.spec.ts`、`api/test_practice_router.py`、`services/test_practice_service.py`（非 implement.md 估计名）。
- **DIAG-018 服务层幂等**：`CreatePracticeOptions` 新增 `idempotency_key`；`PracticeService.create_practice` 拆为「幂等外壳 + `_assemble_and_persist_practice`」，命中已完成快照回放既有练习，未命中则 `acquire_lock` 拦截并发重复，成功后 `set_result`，失败 `release_lock`。
- **DIAG-021 偏差说明**：`KnowledgeMasterySummary` 的 `current_score`/`tier`/`sample_count` 由 design.md 的 required 调整为 optional，并新增后端权威字段 `mastery_score`/`level`/`practice_count`/`correct_count`/`knowledge_name`；理由为后端实际下发 mastery_score 系字段，保留 required 会使类型层撒谎（该接口当前无存量消费点，无回归）。
- **门禁证据**：后端 `ruff format/check`、`mypy app`、`lint-imports`（5 contracts kept）全绿，`pytest tests` **1227 passed**（exit 0）；前端 `pnpm run lint`、`pnpm run type-check`、`pnpm run test:unit` 全绿（**59 files / 556 tests passed**）。
- **DIAG-016/017/019/020/021/022** 均按 design.md 无条件实现，无 `已失效/误报` 项。
