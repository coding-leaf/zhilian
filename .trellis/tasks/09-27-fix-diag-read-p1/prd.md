# 修复 DIAG 读侧 P1：报告契约与掌握度

## Goal

修复审计清单 DIAG 切片读侧 4 条 P1：诊断报告字段名/主分数契约错位、掌握度全景在缺省资料时恒零、退步 `score_delta` 符号反向导致退步徽章反向。

## 需求来源

上游审计 `09-27-read-only-bug-audit`（已归档）`research/slice-DIAG.md`：

| ID | 级别 | 层 | 一句话 |
|---|---|---|---|
| BUG-DIAG-001 | P1 | cross-layer | 后端下发 `weak_knowledge_points`，前端只读 `weak_points` → 薄弱知识点卡片永不渲染 |
| BUG-DIAG-002 | P1 | cross-layer | 后端无 `overall_score`/`mastery_rate` → 综合得分恒 0、掌握档恒 unlearned |
| BUG-DIAG-007 | P1 | cross-layer | `fetchMasteryOverview()` 不传 `material_id` → 仓储按 `material_id IS NULL` 查询（列 NOT NULL）→ 全景恒 0 |
| BUG-DIAG-008 | P1 | cross-layer | 后端 `score_delta = previous - current`（退步为正），前端按负数判退步 → 退步徽章反向 |

## Requirements

### 功能要求
1. **DIAG-001/002（报告契约）**：新增前端**诊断报告适配层**，把后端响应归一为前端 `DiagnosisReport`：
   - `weak_points` ← `weak_knowledge_points`（保留已归一值，幂等）。
   - `overall_score` ← 后端缺失时由 `score_rate * 100` 取整推导。
   - `mastery_rate` ← 后端缺失时由 `mastery_after`（缺省回落 `score_rate`）`* 100` 取整推导。
2. **DIAG-007（掌握度全景缺省资料）**：`get_user_mastery_overview` 的 `material_id` 支持 `None`；为空时聚合该用户**全部**知识点与其掌握度记录（非 `material_id IS NULL`）。
3. **DIAG-008（退步符号统一）**：统一为 `score_delta = current_score - previous_score`（**负数 = 退步**），`is_regressed = score_delta <= -threshold`；与我方 `RegressedKnowledgeItemDTO`（负数=退步）及前端 `formatScoreDelta`（负数=退步）一致。

### 约束
- 字段新增/推导一律**附加兼容**：后端已提供的值不得被覆盖；前端适配幂等（已含 `weak_points`/`overall_score`/`mastery_rate` 的旧夹具仍通过）。
- 后端为契约真源；适配集中在一处（`src/api/adapters/diagnosis.ts`），禁止各组件各自映射。
- 无 `any`；守后端分层与 import-linter；前端夹具字段名逐字取自后端。
- 不弱化既有测试；前后端门禁全绿。

### 不在范围内
- DIAG P2（003~006、009~022）→ 后续批次（其中 003~006 归入 `fix-diag-wrongbook-p1`）。
- `reportStore.setReport` 陈旧 `weakPoints` 未清空（DIAG-016 P2）。

## Acceptance Criteria

- [ ] **DIAG-001**：适配层把后端 `weak_knowledge_points` 归一为 `weak_points`（回归：后端形态夹具 → 卡片有数据）。
- [ ] **DIAG-002**：后端缺 `overall_score`/`mastery_rate` 时由 `score_rate`/`mastery_after` 推导出非零值；`masteryTier` 随之为正确档位。
- [ ] **DIAG-007**：`material_id=None` 的全景聚合返回该用户全部知识点计数（非全 0）；带 `material_id` 行为不变（零回归）。
- [ ] **DIAG-008**：退步点 `score_delta` 为负且 `is_regressed` 为真；提升为正值且 `is_regressed` 为假；前端 `formatScoreDelta` 显示“退步”徽章。
- [ ] 后端门禁全绿：`ruff format --check`、`ruff check`、`mypy app`、`lint-imports`、`pytest`。
- [ ] 前端门禁全绿：`pnpm run lint`、`type-check`、`test:unit`。
- [ ] 逐条关闭 `bug-ledger.md` BUG-DIAG-001/002/007/008。

## Notes

- 父任务：`09-27-fullstack-bug-audit-and-fix`；依赖：无前置子任务。
- 证据见归档 `archive/2026-09/09-27-read-only-bug-audit/research/slice-DIAG.md`。
- 同批错题本修复见后续 `09-27-fix-diag-wrongbook-p1`。
