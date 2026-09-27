# 执行计划：PRAC 切片 P0+P1 修复

## 前置

- 任务：`09-27-fix-prac-p0p1`（父：`09-27-fullstack-bug-audit-and-fix`）。
- 依赖：无前置子任务。上游审计已归档。
- 权威契约：见 `design.md` §2；证据：归档 `archive/2026-09/09-27-read-only-bug-audit/research/slice-PRAC.md`。

## 执行清单（有序）

### Step 1 — 建立失败回归（红）
- [ ] 1.1 新增/改造前端测试夹具为真实后端契约（`items[].question_snapshot`、选项 `content`），见 `design.md` §3.1。
- [ ] 1.2 写断言：适配后 `questions` 非空、`options[0].text` 来自 `content`（PRAC-001/002）。
- [ ] 1.3 写断言：同 practiceId 幂等键复用 + 成功后清理（PRAC-003）。
- [ ] 1.4 写断言：Storage 抛错时 store 不丢、远端同步仍调度（PRAC-004）。
- [ ] 1.5 运行 `pnpm run test:unit`，确认新增断言**失败**（红）。

### Step 2 — 实现 PRAC-001 + PRAC-002（适配层）
- [ ] 2.1 新增 `src/api/adapters/practice.ts`，按 `design.md` §3.1 映射表实现 `adaptPracticeItem` / `adaptPracticeSession`。
- [ ] 2.2 `src/api/practice.ts` 的 `createPractice`/`fetchPracticeSession` 接入适配。
- [ ] 2.3 `src/types/practice.ts` 增补可选 `items`（原始透传）。
- [ ] 2.4 确认 `usePracticeSession.ts`、`ContinuePracticeBar.vue` 无需各自特判。

### Step 3 — 实现 PRAC-003（幂等键）
- [ ] 3.1 新增 `src/subpackages/practice/utils/submitKey.ts`（`getOrCreateSubmitKey` / `clearSubmitKey`，含写入 try/catch 降级）。
- [ ] 3.2 `pages/session/index.vue` 交卷改用持久化 key；成功/终态后 `clearSubmitKey`。

### Step 4 — 实现 PRAC-004（写降级）
- [ ] 4.1 `utils/draft.ts` 写入包 try/catch，超限降级不抛。
- [ ] 4.2 `usePracticeSession.ts` 保证降级后远端同步仍被调度、store 状态不变。

### Step 5 — 转绿与单切片自检
- [ ] 5.1 `pnpm run test:unit` 全部转绿（含原有用例不回归）。
- [ ] 5.2 `pnpm run lint`、`pnpm run type-check` 通过。
- [ ] 5.3 逐条对照 `bug-ledger.md` BUG-PRAC-001/002/003/004 关闭。

### Step 6 — 质量门禁（全工具链）
- [ ] 6.1 前端：`pnpm run lint` + `pnpm run type-check` + `pnpm run test:unit`。
- [ ] 6.2 后端（无改动，确认不退化）：`uv run ruff format --check .` + `ruff check .` + `mypy app` + `lint-imports` + `pytest`。

## 验证命令

```bash
# 前端（workdir=miniprogram）
pnpm run lint && pnpm run type-check && pnpm run test:unit
# 后端（workdir=backend）
uv run ruff format --check . && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run pytest tests
```

## 评审门禁

- Gate A（实现后）：5 条回归断言先红后绿。
- Gate B（提交前）：前端三项 + 后端五项全绿；派发 `trellis-check` 复核跨层契约与规范。

## 回滚点

- 适配层为独立新增模块，移除接入即可回滚。
- PRAC-003/004 局部改动，可独立回退。
- 若门禁暴露后端契约另有别名冲突 → 回到 `design.md` §2 复核，不擅改前端类型规避。
