# 修复 GRADE 切片 P1：重批同步语义与待重判呈现

## Goal

修复审计清单 GRADE 切片 2 条 P1：重批实际同步完成但前后端仍按“待重判”呈现；以及 pending_regrade 题因缺少判题状态字段被当作“判错”显示。

## 需求来源

上游审计 `09-27-read-only-bug-audit`（已归档）`research/slice-GRADE.md`：

| ID | 级别 | 层 | 一句话 |
|---|---|---|---|
| BUG-GRADE-001 | P1 | cross-layer | 重批在请求内同步完成并写 `status=success`，前端却忽略响应硬编码 `pending_regrade`、不更新分数 |
| BUG-GRADE-002 | P1 | cross-layer | LLM 失败降级 pending_regrade 时 `item.score=0.0`，练习项 DTO 无判题状态字段，前端按 score 判级显示“判错” |

## Requirements

### 功能要求
1. **GRADE-001**：明确重判为**同步**语义。
   - 后端 `RegradeResponse.status` 反映真实终态（成功 = `success`），并**回传新分数**（`score`）；路由仅透传服务返回记录，不硬编码 `pending_regrade`。
   - 前端读取重判响应：`status === 'success'` 时用返回 `score` 就地更新该题分数与判级（`graded`），不再一律置 `pending_regrade`。
2. **GRADE-002**：为练习项提供**可判定的判题状态**，使“待重判”不再落为“判错”。
   - 后端练习项 DTO 新增**附加可选** `grading_status`，取值 `unanswered | pending_regrade | graded`（由 `is_answered`/`score` 判定）。
   - 后端降级为 pending_regrade 时，`AttemptItem.score` 置 `null`（未定分）而非 `0.0`，使“待判定”成为唯一可判信号。
   - 前端判级优先使用 `grading_status`，`pending_regrade`/`unanswered` 直接命中对应状态；`graded` 或缺失时再回退到既有 score 阈值逻辑。

### 约束
- 契约权威：后端 `schemas/practice.py`（`PracticeItemDetailResponse`）、`schemas/grading.py`（`RegradeResponse`）。
- 新增字段一律**附加可选**，默认值保持旧行为，历史响应不破坏。
- `AttemptItem.score` 汇总口径 `sum(it.score or 0.0)` 已容忍 `None`，不得改动其语义。
- 无 `any`；守后端分层与 import-linter；前端测试夹具字段名逐字取自后端。
- 不弱化既有测试；前后端门禁全绿。

### 不在范围内
- GRADE 其余 P2（`BUG-GRADE-003…013, 016`）→ 后续 P2 批次。
- 错题本 `question_snapshot.options` 的 `content/text` 漂移 → DIAG 切片（B6）。

## Acceptance Criteria

- [ ] **GRADE-001**：`POST /api/v1/grading/regrade` 成功返回 `status="success"` 且 `score` 为新分（回归：修复前 mock/真实路径为 `pending_regrade`，修复后为 `success`）。
- [ ] **GRADE-001**：前端重判成功后该题分数文本更新为新分、状态不再停留在“待重新判题”（回归断言）。
- [ ] **GRADE-002**：降级 pending_regrade 后 `AttemptItem.score is None`（回归：修复前为 `0.0`），且练习项 DTO `grading_status == "pending_regrade"`。
- [ ] **GRADE-002**：`grading_status` 判定：`unanswered`（未作答）/`pending_regrade`（已答未判分）/`graded`（已判分）三态正确。
- [ ] **GRADE-002**：前端 `getGradingStatusInfo` 对 `grading_status='pending_regrade'` 返回“待重新判题”，对 `grading_status='unanswered'` 返回“未作答”，对 `graded` 回退 score 阈值。
- [ ] 后端门禁全绿：`ruff format --check`、`ruff check`、`mypy app`、`lint-imports`、`pytest`。
- [ ] 前端门禁全绿：`pnpm run lint`、`type-check`、`test:unit`。
- [ ] 逐条关闭 `bug-ledger.md` BUG-GRADE-001/002。

## Notes

- 父任务：`09-27-fullstack-bug-audit-and-fix`；依赖：无前置子任务。
- 完整证据见归档 `archive/2026-09/09-27-read-only-bug-audit/research/slice-GRADE.md`。
