# 执行计划：PRAC 切片 P2-A 修复

## 前置

- 任务：`09-27-fix-prac-p2a`（父任务：`09-27-fullstack-bug-audit-and-fix`）。
- 契约权威见 `design.md` §2，审计证据见归档 `archive/2026-09/09-27-read-only-bug-audit/research/slice-PRAC.md`。

## 执行清单（有序）

### Step 1 — 失败回归（红）
- [x] 1.1 后端：在 `tests/unit/services/test_practice_service.py` 中：
  - 增加交卷幂等回放测试用例，断言缓存回放时 `result.is_idempotent_replay is True`（当前无该属性 / 恒为 False → 红）。
  - 增加在真实 service 下对 `PAUSED`、`TIMEOUT`、`PARTIALLY_GRADED` 状态调用 `save_answer` 的测试用例，断言抛出 `PracticeStatusError`（当前只有 completed 拦截 → 红）。
- [x] 1.2 后端：在 `tests/unit/models/test_practice.py` 中为 `validate_practice_transition` 增加对 `PracticeStatus.PAUSED` 与 `PracticeStatus.TIMEOUT` 的跃迁测试（当前 PAUSED/TIMEOUT 未在枚举中或报 Unknown status → 红）。
- [x] 1.3 后端：在 `tests/unit/schemas/test_practice_schemas.py` 中断言：
  - 创建 mode="random" 的练习后详情返回 `mode="random"`；
  - 详情响应 `completed_count` 正确统计已答题目数。
- [x] 1.4 前端：在 `tests/unit/stores/practice.spec.ts` 中测试 `clearSession(id)` 后 `store.drafts` 中对应条目被彻底删除（当前未删除 → 红）。
- [x] 1.5 前端：在 `tests/unit/api/practiceAdapter.spec.ts` 中断言 `adaptStatus('timeout') === 'submitted'`（当前映射为 'in_progress' → 红）。
- [x] 1.6 运行测试确认新增断言失败（红）。

### Step 2 — 后端修复实现（绿）
- [x] 2.1 修改 `backend/app/models/practice.py`：
  - `PracticeStatus` 增加 `PAUSED = "paused"`、`TIMEOUT = "timeout"`；
  - `validate_practice_transition` 支持 `PAUSED` 与 `TIMEOUT`；
  - `Practice` 模型新增 `mode: Mapped[str]` 列（默认 "sequential"）。
- [x] 2.2 修改 `backend/app/services/practice.py`：
  - `PracticeSubmissionResult` 增加 `is_idempotent_replay: bool = False`；
  - `submit_practice` 回放分支传入 `is_idempotent_replay=True`；
  - `create_practice` 中将 `options.mode.value` 赋值给实体 `mode`；
  - `save_answer` 收紧拦截：非 `NOT_STARTED` 且非 `IN_PROGRESS` 时统一抛出 `PracticeStatusError`；
  - 将 service 中所有 `"paused"` / `"timeout"` 替换为 `PracticeStatus` 枚举。
- [x] 2.3 修改 `backend/app/schemas/practice.py`：
  - `synchronize_detail_fields` 支持自动根据 `items` 计算 `completed_count`。
- [x] 2.4 运行后端测试确认 Step 1.1~1.3 变绿。

### Step 3 — 前端修复实现（绿）
- [x] 3.1 修改 `miniprogram/src/types/storage.ts`：
  - `StorageDataMap['practice_drafts']` 调整为 `Record<string, PracticeDraftRecord>`。
- [x] 3.2 修改 `miniprogram/src/subpackages/practice/utils/draft.ts`：
  - 移除对 `storage.setItem` 和 `storage.getItem` 的 `as unknown as Record<string, never>` 强转，使类型原生匹配。
- [x] 3.3 修改 `miniprogram/src/stores/practiceStore.ts`：
  - 新增 `removeDraft(id: string)`；
  - `clearSession` 支持清理当前或指定练习的 `drafts.value[id]`；
  - `syncDraftToStorage` / `loadDraftFromStorage` 与规范草稿契约对齐。
- [x] 3.4 修改 `miniprogram/src/subpackages/practice/pages/session/index.vue`：
  - 交卷成功时调用 `practiceStore.clearSession(targetPracticeId)`。
- [x] 3.5 修改 `miniprogram/src/api/adapters/practice.ts`：
  - `adaptStatus` 增加对 `'timeout'` 的处理（映射为 `'submitted'`）。
- [x] 3.6 运行前端测试确认 Step 1.4~1.5 变绿。

### Step 4 — 全门禁验证
- [x] 4.1 后端门禁：
  - `uv run ruff format --check .`
  - `uv run ruff check .`
  - `uv run mypy app`
  - `uv run lint-imports`
  - `uv run pytest tests`
- [x] 4.2 前端门禁：
  - `pnpm run lint`
  - `pnpm run type-check`
  - `pnpm run test:unit`

## 验证命令

```bash
# 后端门禁 (workdir=backend)
uv run ruff format --check . && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run pytest tests

# 前端门禁 (workdir=miniprogram)
pnpm run lint && pnpm run type-check && pnpm run test:unit
```

## 评审门禁

- Gate A：失败回归测试先红后绿，精准覆盖 7 项缺陷。
- Gate B：所有后端和前端静态检查、类型检查、单元测试必须 100% 通过无 warning。
- Gate C：代码分层架构与 import-linter 规约零违反。

## 回滚点

- 若后端状态机影响既有评判流程，可快速移除 `Practice.mode` 列并复位 `PracticeStatus` 与 `save_answer` 白名单；
- 若前端 Storage 格式变更引发老版本缓存异常，可快速复位 `storage.ts` 与 `practiceStore.ts`。
