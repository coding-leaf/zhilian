# 修复 DIAG 错题本 P1：分页总数/攻克切换/作答回显/继续练习

## Goal

修复审计清单 DIAG 切片错题本侧 4 条 P1：错题列表 `total` 失真导致分页卡死、取消攻克无效、错题不显示用户作答、一键巩固练习必 422。

## 需求来源

上游审计 `09-27-read-only-bug-audit`（已归档）`research/slice-DIAG.md`：

| ID | 级别 | 层 | 一句话 |
|---|---|---|---|
| BUG-DIAG-003 | P1 | backend | 错题列表接口 `total = len(items)`（当前页条数）→ 首页满页时 `hasMore=false`，后续页永不可达 |
| BUG-DIAG-004 | P1 | cross-layer | 前端发 `{is_mastered:false}`，后端 master 端点无请求体、恒置已掌握 → 取消攻克无效 |
| BUG-DIAG-005 | P1 | cross-layer | `WrongRecordItemResponse` 无 `user_answer` → 卡片“您的作答”恒显示“未作答” |
| BUG-DIAG-006 | P1 | cross-layer | 一键巩固传非法 `source_type='wrong_record'` 且 `material_id` 缺失 → 后端 422 |

## Requirements

### 功能要求
1. **DIAG-003**：错题列表返回**真实总数**。仓储新增 `count_wrong_records`（同过滤条件）；服务 `list_wrong_records` 返回 `(items, total)`；路由用真实 total 组装响应。
2. **DIAG-004**：`POST /wrong-records/{id}/master` 接受**可选请求体** `{is_mastered?}`；缺省 `True`（向后兼容）；`false` 时清空 `is_mastered`/`mastered_at`。
3. **DIAG-005**：`WrongRecordItemResponse` 新增 `user_answer`，由实体 `last_wrong_answer` 映射下发（含 ORM `from_attributes` 路径）。
4. **DIAG-006**：后端允许 `source_type='wrong_record'`（`VALID_PRACTICE_SOURCE_TYPES` + `PracticeSourceType`）；`material_id` 改为**可选**，缺省时由命中的题目资料解析；前端在无可用知识点时禁用继续练习入口。

### 约束
- 后端为契约真源；新增字段/入参一律**附加可选**，默认行为不变。
- `master` 缺省行为（无 body）必须保持“置为已攻克”。
- 前端无 `any`；守后端分层与 import-linter；夹具字段名逐字取自后端。
- 不弱化既有测试；前后端门禁全绿。

### 不在范围内
- DIAG P2：`error_type` 下推与枚举对齐（010）、题型过滤（011）、1000 上限（012）、删除响应字段（013）、重复请求（014/015）、store 陈旧弱点点（016）、草稿字段（017）、继续练习幂等头（018）、报告生成幂等（019）、排序（020）、潜伏类型（021）、空态（022）。
- 刻意不改：`list_wrong_records` 的 `limit=1000` 内存过滤（DIAG-012，P2）。

## Acceptance Criteria

- [ ] **DIAG-003**：错题列表 `total` 为真实总数（> 当前页条数）；首页满页时 `hasMore` 为真、可翻页（回归：修复前 `total=len(items)`）。
- [ ] **DIAG-004**：`is_mastered=false` 后实体与响应均为 `false` 且 `mastered_at=None`；无 body 时置 `true`（向后兼容）。
- [ ] **DIAG-005**：错题响应含 `user_answer` 等于实体 `last_wrong_answer`。
- [ ] **DIAG-006**：`source_type='wrong_record'` + 无 `material_id` 的继续练习返回 200 并创建练习；`material_id` 由题目解析；旧 `weakness`/`normal` 路径零回归。
- [ ] 后端门禁全绿：`ruff format --check`、`ruff check`、`mypy app`、`lint-imports`、`pytest`。
- [ ] 前端门禁全绿：`pnpm run lint`、`type-check`、`test:unit`。
- [ ] 逐条关闭 `bug-ledger.md` BUG-DIAG-003/004/005/006。

## Notes

- 父任务：`09-27-fullstack-bug-audit-and-fix`；前置：`09-27-fix-diag-read-p1`（已归档，弱点点数据修复使报告页继续练习可用）。
- 证据见归档 `archive/2026-09/09-27-read-only-bug-audit/research/slice-DIAG.md`。
