# 修复 PRAC 切片 P0+P1：练习会话与交卷

## Goal

修复审计清单 `bug-ledger.md` 中 PRAC 切片的 4 条高优先级缺陷，使练习「进入会话 → 作答 → 交卷」主流程可用、选项可读、交卷幂等、草稿不静默丢失。所有修复以回归测试 + 全工具链绿为验收。

## 需求来源

上游审计任务 `09-27-read-only-bug-audit`（已归档）的 `research/slice-PRAC.md`。本任务修复其中：

| ID | 级别 | 层 | 一句话 |
|---|---|---|---|
| BUG-PRAC-001 | P0 | cross-layer | 后端响应题目字段 `items`（`{question_snapshot}`），前端读 `res.data.questions`，无适配层 → 会话题目恒空，主流程不可用 |
| BUG-PRAC-002 | P1 | cross-layer | 选项后端 `{key, content}`，前端 `{key, text}` → 选项正文空白（被 001 掩盖） |
| BUG-PRAC-003 | P1 | frontend | 交卷幂等键每次重生成，不持久化复用 → 超时重试非幂等 |
| BUG-PRAC-004 | P1 | frontend | 草稿整写超 `MAX_STORAGE_BYTES`(20KB) 时抛错无 try/catch → 该次作答既不同步也不备份（数据丢失风险） |

## Requirements

### 功能要求
1. **PRAC-001**：前端新增响应适配，把后端 `items[].question_snapshot` 展平为前端 `PracticeQuestion[]` 并写入 store；进入练习必须能渲染题目。真实后端契约（`items`）为唯一真相源，禁止再依赖 mock 的 `questions`。
2. **PRAC-002**：适配层把选项 `content` 归一为前端消费的字段（`text`），保证单选/多选/判断选项正文可渲染。
3. **PRAC-003**：交卷幂等键在**每次练习会话内只生成一次并持久化**，在收到明确成功/明确业务终态前重试复用同一 key；成功后清理。
4. **PRAC-004**：草稿 Storage 写入失败（超限/序列化异常）必须被捕获并降级，**不得**中断后续远端同步调度，也不得丢失 store 内已作答状态。

### 约束
- 契约权威：以后端响应模型为准（见 `.trellis/spec/backend/quality-guidelines.md` 场景「Backend↔Frontend Response Field-Name Contract Pinning」）。
- 前端测试夹具字段名必须逐字取自真实后端响应模型（`items`/`content`），消除双侧夹具漂移导致的假绿。
- 不混入重构/去重（`SMELL-*` 另册）；本任务只修上述 4 条。
- 不改变后端既有对外契约（本任务为前端适配；若确需后端改动须在 design.md 说明理由）。

### 不在范围内
- PRAC 切片其余 P2 条目（`BUG-PRAC-005…017`）→ 归入后续 P2 批次。
- QGEN 切片同根因的 `BUG-QGEN-001` → 归入 QGEN 批次（B4），但适配策略须一致。

## Acceptance Criteria

- [ ] `BUG-PRAC-001`：新增/更新回归测试，断言「给定真实后端响应 `items[].question_snapshot`，store 中题目数量与内容非空」；修复前该测试失败（红），修复后通过（绿）。
- [ ] `BUG-PRAC-002`：断言选项正文来自 `content` 且可渲染非空。
- [ ] `BUG-PRAC-003`：断言同一练习多次交卷重试复用同一 `idempotency_key`；成功路径清理。
- [ ] `BUG-PRAC-004**：断言 Storage 写入抛错时不影响 store 状态且远端同步仍被调度（不抛未捕获异常）。
- [ ] 前端门禁全绿：`pnpm run lint`、`pnpm run type-check`、`pnpm run test:unit`。
- [ ] 后端门禁不退化：`uv run ruff format --check .`、`ruff check .`、`mypy app`、`lint-imports`、`pytest` 全绿（若本任务不含后端改动，须确认仍绿）。
- [ ] 前端测试中 PRAC 相关夹具改写为真实契约字段（`items`/`content`），不再使用 `questions`/`text` 自造字段。
- [ ] 逐条关闭 `bug-ledger.md` 中 BUG-PRAC-001/002/003/004。

## Notes

- 父任务：`09-27-fullstack-bug-audit-and-fix`。依赖：无前置子任务；本任务是修复链首环。
- 证据与完整字段见归档 `archive/2026-09/09-27-read-only-bug-audit/research/slice-PRAC.md`。
