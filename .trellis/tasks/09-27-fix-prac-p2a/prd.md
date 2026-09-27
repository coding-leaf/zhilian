# 修复 PRAC 切片 P2-A：状态机枚举、作答拦截、回放标记与草稿生命周期收敛

## Goal

修复审计清单 PRAC 切片 P2-A 批次共 7 条缺陷（BUG-PRAC-005 ~ BUG-PRAC-011）：补齐交卷回放响应标记、将 `paused`/`timeout` 纳入 `PracticeStatus` 规范枚举与状态机跃迁控制、收紧作答保存状态拦截、交卷后清理 store 内存中的草稿条目、收敛 `practice_drafts` 本地存储结构并消除类型强转、补充前端适配器状态映射、决定 `PracticeDetailResponse` 占位字段（`mode`/`completed_count`）的计算与落库策略。

## 需求来源

上游审计 `09-27-read-only-bug-audit`（已归档）`research/slice-PRAC.md`：

| ID | 级别 | 层 | 一句话 |
|---|---|---|---|
| BUG-PRAC-005 | P2 | backend | 幂等缓存回放分支返回结果未设置 `is_idempotent_replay=True`，API 响应恒为 `false` |
| BUG-PRAC-006 | P2 | backend | `PracticeStatus` 枚举缺少 `paused` 与 `timeout`，service 以字面量持久化且 `validate_practice_transition` 无法识别 |
| BUG-PRAC-007 | P2 | backend | `save_answer` 仅拦截 `completed` 状态，`paused`/`timeout`/`partially_graded` 仍允许保存作答，且测试仅打桩 mock |
| BUG-PRAC-008 | P2 | frontend | 交卷成功仅清 Storage 和会话未清除 `practiceStore.drafts`，返回首页仍展示已交卷练习为“最近未完成练习” |
| BUG-PRAC-009 | P2 | frontend | Storage key `practice_drafts` 存在 `AnswerDraft` 与 `PracticeDraftRecord` 双重结构与 `as unknown` 强转 |
| BUG-PRAC-010 | P2 | cross-layer | 前端状态枚举与后端状态集存在口径差异（已部分由 adapter 映射），需完善契约与双向映射 |
| BUG-PRAC-011 | P2 | backend | `PracticeDetailResponse` 中 `mode` 恒为 sequential、`completed_count` 恒为 0（ORM 未持久化/未提取） |

## Requirements

### 功能要求

1. **PRAC-005（回放标记）**：
   - `PracticeSubmissionResult` 增加 `is_idempotent_replay: bool = False` 字段。
   - `PracticeService.submit_practice` 命中幂等缓存分支（`idempotency.get_result`）构造返回值时显式设置 `is_idempotent_replay=True`；正常提交链路保持 `False`。
   - API 层 `SubmitPracticeResponse` 能如实返回 `is_idempotent_replay: True`。

2. **PRAC-006（paused / timeout 纳入状态枚举与状态机）**：
   - 后端 `PracticeStatus(StrEnum)` 补充 `PAUSED = "paused"`、`TIMEOUT = "timeout"`。
   - `validate_practice_transition` 纯函数显式支持 `PAUSED`（支持恢复至 `IN_PROGRESS`）与 `TIMEOUT`（作为终态/冻结态，不可逆）。
   - `PracticeService` 内硬编码 `"paused"` / `"timeout"` 字符串字面量替换为 `PracticeStatus.PAUSED.value` 与 `PracticeStatus.TIMEOUT.value`。

3. **PRAC-007（严密拦截非作答态作答保存）**：
   - `PracticeService.save_answer` 明确作答状态约束：仅允许处于 `NOT_STARTED`（保存时自跃迁为 `IN_PROGRESS`）或 `IN_PROGRESS` 状态保存作答；若状态为 `PAUSED`、`TIMEOUT`、`PARTIALLY_GRADED` 或 `COMPLETED`，一律抛出 `PracticeStatusError`（40011，HTTP 400）。
   - 补充 `PracticeService.save_answer` 在真实 service 下对 `PAUSED` 与 `TIMEOUT` 拦截的单元测试用例，不依赖 router 层的简单 mock。

4. **PRAC-008（交卷后彻底清除 store 内存草稿）**：
   - `practiceStore.clearSession(practiceId?: string)` 扩展为支持接收 `practiceId` 或使用当前 `sessionId`，在清理会话的同时从 `drafts.value` 字典中删除对应的 draft key（或新增专门方法 `removeDraft(practiceId: string)` 并由 `clearSession` 配合调用）。
   - 会话提交成功分支在调用 `clearDraftFromStorage` 与 `practiceStore.clearSession` 后，保证 `practiceStore.drafts` 中对应练习项被移除，首页 `extractLatestDraftPractice` 不再提取该已交卷练习。

5. **PRAC-009（收敛 Storage `practice_drafts` 契约）**：
   - 统一 Storage key `practice_drafts` 的类型定义为 `Record<string, PracticeDraftRecord>`（兼容历史仅含有 `answers` 的旧条目）。
   - `StorageDataMap` 中 `practice_drafts` 类型更新为 `Record<string, PracticeDraftRecord>`。
   - `practiceStore.syncDraftToStorage` 与 `loadDraftFromStorage` 统一适配规范的 `PracticeDraftRecord` 结构，移除 `as unknown as Record<string, never>` 等危险类型断言。

6. **PRAC-010（跨层状态枚举与映射收敛）**：
   - 校验前端 `api/adapters/practice.ts` 中的 `adaptStatus`，补充对 `timeout` 映射为 `graded`/`submitted` 或相应前端终态；
   - 统一前端 `PracticeStatus` 类型定义与后端 `PracticeStatus` 枚举的兼容性，消除状态断层。

7. **PRAC-011（详情响应 `mode` 与 `completed_count` 契约名实相符）**：
   - `completed_count`：`PracticeDetailResponse.synchronize_detail_fields` 支持根据 `items` 列表中 `is_answered is True` 的项目数动态计算（若 ORM 未直接提供）；
   - `mode`：`Practice` ORM 增加 `mode` 列（或由 `options.mode` 在创建练习时写入，`synchronize_detail_fields` 在详情/摘要中正常提取）；若保持当前 SQLite/PG 兼容无需大迁移，则在 `Practice` model 增加 `mode: Mapped[str]`，创建时落库并在 detail/summary 响应中返回用户创建时传入的模式。

### 约束
- 契约权威：后端 `schemas/practice.py`、`models/practice.py`。
- 新增/调整字段一律**附加可选、默认旧行为**，确保 API 前向后向兼容。
- 前端零 `any`，严格类型安全；守后端分层原则与 import-linter 规则。
- 前端测试夹具与 mock 字段名逐字取自后端 schema。
- 不得弱化既有测试断言，前后端门禁保持全绿。

### 不在范围内
- PRAC 其余项（BUG-PRAC-001 ~ 004, 012 ~ 017）→ 由后续切片处理。
- 判题（GRADE）、诊断（DIAG）相关流程缺陷。

## Acceptance Criteria

- [ ] **PRAC-005**：同一 idempotency_key 首次提交返回 `is_idempotent_replay: False`；二次回放提交返回 `is_idempotent_replay: True`。
- [ ] **PRAC-006**：`PracticeStatus.PAUSED` 与 `PracticeStatus.TIMEOUT` 定义在枚举中；`validate_practice_transition` 对 `PAUSED`、`TIMEOUT` 返回正确的有效跃迁/不可逆判断。
- [ ] **PRAC-007**：当练习状态为 `PAUSED`、`TIMEOUT`、`PARTIALLY_GRADED` 时，真实 `PracticeService.save_answer` 抛出 `PracticeStatusError` 并拒绝作答。
- [ ] **PRAC-008**：交卷成功后，`practiceStore.drafts` 中对应 `practiceId` 彻底清除；首页 `extractLatestDraftPractice` 返回 `null`（无其他练习时）。
- [ ] **PRAC-009**：`StorageDataMap['practice_drafts']` 统一为 `Record<string, PracticeDraftRecord>`；`draft.ts` 移除 `as unknown as Record<string, never>` 强转且单测全绿。
- [ ] **PRAC-010**：`adaptStatus` 覆盖 `timeout`、`paused`、`partially_graded` 等后端全量状态枚举。
- [ ] **PRAC-011**：创建为 `mode="random"` 的练习，详情接口返回 `mode="random"`；详情接口 `completed_count` 与实际已作答题目数一致。
- [ ] 后端门禁全绿：`ruff format --check`、`ruff check`、`mypy app`、`lint-imports`、`pytest`。
- [ ] 前端门禁全绿：`pnpm run lint`、`type-check`、`test:unit`。

## Notes

- 审计来源：`09-27-read-only-bug-audit/research/slice-PRAC.md`。
- PRAC-010 前端已存在 `api/adapters/practice.ts:adaptStatus`，主要补充 `timeout` 等新枚举值的映射。
