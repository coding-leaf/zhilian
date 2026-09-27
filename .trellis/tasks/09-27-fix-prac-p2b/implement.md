# 执行计划：PRAC 切片 P2-B 修复

## 前置

- 任务：`09-27-fix-prac-p2b`（父任务：`09-27-fullstack-bug-audit-and-fix`）。
- 需求与设计参考：`prd.md`、`design.md`。

---

## 执行清单（有序）

### Step 1 — 失败回归测试（红）
- [ ] 1.1 后端：在 `test_practice_service.py` 增加回归测试：交卷时 mock `idempotency.set_result` 抛出异常，断言主流程不崩且成功返回结果；随后的重试调用能成功回放。
- [ ] 1.2 后端：在 `test_practice_service.py` 增加多选作答保存测试，断言列表作答被保存为合法 JSON 字符串（如 `["A", "B"]`），而非 Python repr（`"['A', 'B']"`）。
- [ ] 1.3 后端：在 `test_practice_schemas.py` 增加 `PracticeDetailResponse` 的 `time_elapsed_seconds` 自动从 items 聚合求和的单测断言。
- [ ] 1.4 前端：在 `usePracticeSession.spec.ts` 中新增断言：在 `cleanupSession` 时触发未完成防抖草稿的同步；耗时计算基于真实时间差。
- [ ] 1.5 前端：在 `QuestionRenderer.spec.ts` 中断言对 `term_explanation` 和 `case_analysis` 能正确展示输入组件和对应题型标签。
- [ ] 1.6 运行测试确认新增断言失败（红）。

### Step 2 — 后端修复（PRAC-013, 015, 016）
- [ ] 2.1 `backend/app/schemas/practice.py`：
  - `PracticeDetailResponse` 添加 `time_elapsed_seconds: int = 0` 字段。
  - 在 `synchronize_detail_fields` validator 中从 items 或 attributes 聚合求和。
- [ ] 2.2 `backend/app/services/practice.py`：
  - `submit_practice`：隔离 `idempotency.set_result` 异常，避免 5xx。
  - `submit_practice`：在状态检查处支持对 `practice.submit_idempotency_key == clean_key` 的幂等回放兜底。
  - `save_answer`：在处理非字符串（如 list）作答时使用 `json.dumps(sorted(user_answer), ensure_ascii=False)`。

### Step 3 — 前端修复（PRAC-012, 014, 015, 017）
- [ ] 3.1 `miniprogram/src/types/practice.ts`：导出 `PracticeStatusChangeResult` 接口。
- [ ] 3.2 `miniprogram/src/api/practice.ts`：导出 `pausePractice` 与 `resumePractice` 函数。
- [ ] 3.3 `miniprogram/src/subpackages/practice/components/QuestionRenderer.vue`：支持 `term_explanation` 与 `case_analysis` 多行文本输入及标题映射。
- [ ] 3.4 `miniprogram/src/subpackages/practice/composables/usePracticeSession.ts`：
  - 增强 `cleanupSession`，在退出时立即 flush 未同步草稿。
  - 接入每题真实时间记录，消除 `time_spent_seconds: 1` 硬编码。
  - 增加并导出 `pauseSession` 与 `resumeSession` 控制能力。

### Step 4 — 全门禁验证（绿）
- [ ] 4.1 后端全套门禁：
  - `uv run ruff format --check .`
  - `uv run ruff check .`
  - `uv run mypy app`
  - `uv run lint-imports`
  - `uv run pytest tests`
- [ ] 4.2 前端全套门禁：
  - `pnpm run lint`
  - `pnpm run type-check`
  - `pnpm run test:unit`
- [ ] 4.3 确认所有回归测试转绿。

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

- Gate A：Step 1 编写的 5 组回归测试成功触发红测。
- Gate B：前后端门禁全量通过，无 any 引入，无 import-linter 违规。

---

## 回滚点

- `backend/app/services/practice.py` 提交逻辑复位。
- `backend/app/schemas/practice.py` 移除 `time_elapsed_seconds`。
- `miniprogram/src/api/practice.ts` 移除新加函数。
