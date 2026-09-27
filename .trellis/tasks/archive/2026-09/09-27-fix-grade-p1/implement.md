# 执行计划：GRADE 切片 P1 修复

## 前置

- 任务：`09-27-fix-grade-p1`（父：`09-27-fullstack-bug-audit-and-fix`）。
- 权威契约见 `design.md` §3；证据见归档 `archive/2026-09/09-27-read-only-bug-audit/research/slice-GRADE.md`。

## 执行清单（有序）

### Step 1 — 失败回归（红）
- [ ] 1.1 后端：`test_grading_service.py` 在 `test_subjective_ai_timeout_fallback_to_pending_regrade` 增加 `assert item_sub.score is None`（当前 0.0 → 红）。
- [ ] 1.2 后端：`test_practice_schemas.py` 新增 `grading_status` 三态断言（unanswered / pending_regrade / graded）。
- [ ] 1.3 后端：`test_grading_router.py::test_regrade_success` mock 记录改 `status="success", score=新分`，断言 `data["status"]=="success"`、`data["score"]==新分`、message 含“完成”；`test_practice_grading_flow.py` 同步。
- [ ] 1.4 前端：`reportFormat.spec.ts` 新增 `grading_status` 优先级用例；`gradingModals.spec.ts` 断言 success 事件含 `status`/`score`；`reportDetailPage.spec.ts` 断言重判成功后分数文本更新。
- [ ] 1.5 运行测试确认新增断言红。

### Step 2 — GRADE-002 实现
- [ ] 2.1 `grading.py::_build_pending_regrade_record`：`item.score = None`（记录 score 保持 0.0）。
- [ ] 2.2 `schemas/practice.py::PracticeItemDetailResponse`：新增 `grading_status` 字段 + validator 计算 + field_names 追加。
- [ ] 2.3 前端 `types/report.ts` / `types/practice.ts` 增加 `grading_status?`。
- [ ] 2.4 `reportFormat.ts::getGradingStatusInfo` 按 design §3.3 优先 `grading_status`。
- [ ] 2.5 `GradingResultList.vue::getStatus` 传入 `grading_status`；`canSelfGrade` 兼容 pending。

### Step 3 — GRADE-001 实现
- [ ] 3.1 `schemas/grading.py::RegradeResponse`：`status` 默认 `success`，新增 `score`/`is_final`，message 语义更新。
- [ ] 3.2 `api/v1/grading.py::regrade`：透传 `status`/`score`/`is_final`，message 改“重新判题已完成”。
- [ ] 3.3 前端 `diagnosis.ts::requestRegrade` 响应类型加 `score`。
- [ ] 3.4 `RegradeModal.vue`：success 事件携带 `status`/`score`；toast 改“重新判题已完成”。
- [ ] 3.5 `detail/index.vue::onRegradeSuccess`：按 payload 回填分数/状态。

### Step 4 — 全门禁
- [ ] 4.1 后端：`uv run ruff format --check .` + `ruff check .` + `mypy app` + `lint-imports` + `pytest`。
- [ ] 4.2 前端：`pnpm run lint` + `pnpm run type-check` + `pnpm run test:unit`。
- [ ] 4.3 逐条关闭 BUG-GRADE-001/002。

## 验证命令

```bash
# 后端（workdir=backend）
uv run ruff format --check . && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run pytest tests
# 前端（workdir=miniprogram）
pnpm run lint && pnpm run type-check && pnpm run test:unit
```

## 评审门禁

- Gate A：4 组回归断言先红后绿。
- Gate B：后端五项 + 前端三项全绿；派发 `trellis-check` 复核契约、状态机与兼容性。

## 回滚点

- `grading_status`/`score`/`is_final` 均为附加可选，移除即回滚。
- `item.score=None` 单行可复位为 `0.0`。
- `RegradeResponse.status` 默认值复位为 `pending_regrade`。
