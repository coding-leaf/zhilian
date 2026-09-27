# 执行计划：QGEN 切片 P1 修复

## 前置

- 任务：`09-27-fix-qgen-p1`（父：`09-27-fullstack-bug-audit-and-fix`）。
- 权威契约见 `design.md` §2；证据见归档 `archive/2026-09/09-27-read-only-bug-audit/research/slice-QGEN.md`。

## 执行清单（有序）

### Step 1 — 失败回归（红）
- [ ] 1.1 前端：题目夹具改真实后端结构（`options[].content`）；断言列表/详情/生成三路径适配后 `options[0].text` 非空。
- [ ] 1.2 前端：断言 `updateQuestion` 请求体选项字段为 `content`。
- [ ] 1.3 后端：多考点第二考点失败 → 库中 0 条本批次题目。
- [ ] 1.4 运行测试确认新增断言红。

### Step 2 — QGEN-001 实现（前端适配层）
- [ ] 2.1 新增 `src/api/adapters/question.ts`（`adaptQuestionItem/Page/GenerateResponse`、`toQuestionUpdatePayload`）。
- [ ] 2.2 `src/api/question.ts` 四个函数接入适配。
- [ ] 2.3 确认 `QuestionCard`/审核/编辑无需改动。
- [ ] 2.4 前端测试转绿。

### Step 3 — QGEN-007 实现（后端原子提交）
- [ ] 3.1 `generate_questions` 增 `defer_commit: bool = False`，落库块据此决定是否 commit。
- [ ] 3.2 `generate_questions_for_knowledge_points` 循环传 `defer_commit=True`，外层单次 commit / 失败整批 rollback。
- [ ] 3.3 后端测试转绿；单考点零回归。

### Step 4 — 全门禁
- [ ] 4.1 后端：`uv run ruff format --check .` + `ruff check .` + `mypy app` + `lint-imports` + `pytest`。
- [ ] 4.2 前端：`pnpm run lint` + `pnpm run type-check` + `pnpm run test:unit`。
- [ ] 4.3 逐条关闭 BUG-QGEN-001/007。

## 验证命令

```bash
# 后端（workdir=backend）
uv run ruff format --check . && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run pytest tests
# 前端（workdir=miniprogram）
pnpm run lint && pnpm run type-check && pnpm run test:unit
```

## 评审门禁

- Gate A：4 组回归断言先红后绿。
- Gate B：后端五项 + 前端三项全绿；派发 `trellis-check` 复核契约与事务边界。

## 回滚点

- 前端适配层为新增模块，移除接入即回滚。
- `defer_commit` 默认关闭，等价旧行为。
