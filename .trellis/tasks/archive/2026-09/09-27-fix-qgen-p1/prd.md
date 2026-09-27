# 修复 QGEN 切片 P1：选项契约与多考点原子性

## Goal

修复审计清单 QGEN 切片 2 条 P1：客观题选项字段契约错位导致选项正文渲染为空，以及多考点生成逐考点提交导致中途失败遗留部分题目（非原子）。

## 需求来源

上游审计 `09-27-read-only-bug-audit`（已归档）`research/slice-QGEN.md`：

| ID | 级别 | 层 | 一句话 |
|---|---|---|---|
| BUG-QGEN-001 | P1 | cross-layer | 后端选项 `{key, content}` vs 前端 `{key, text}` → 题目卡片/审核编辑抽屉选项正文为空 |
| BUG-QGEN-007 | P1 | backend | `generate_questions_for_knowledge_points` 逐考点调用各自 `commit()`；第 N 个失败时前 N-1 个已入库，用户见失败但数据部分落库 |

## Requirements

### 功能要求
1. **QGEN-001**：前端在 **api 适配层**把题目响应的选项 `content` 归一为 `text`，供 `QuestionCard`/审核/编辑等既有消费点渲染；对 `options` 入参（更新请求）把 `text` 归一为后端 `content`。契约以后端 schema（`options` 元素 `{key, content}`）为准，消费点不各写映射。
   - 覆盖三个响应路径：题目列表 `fetchQuestionList`、题目详情 `fetchQuestionDetail`、出题生成 `generateQuestions`（其 `qualified_questions`/`pending_questions` 内嵌 `QuestionDetailResponse.options`）。
2. **QGEN-007**：多考点编排改为**单事务原子**——所有考点在同一个外层事务内提交，任一考点失败则整批回滚，不遗留部分题目。保持单考点路径行为不变。

### 约束
- 契约权威：后端 `schemas/question.py`（`options: list[dict[str,Any]]`，元素 `{key, content}`；`QuestionUpdateRequest.options` 同）。
- 与 B1（PRAC 同根因）适配策略一致：前端集中归一，禁止各组件各自映射。
- 前端测试夹具字段名必须逐字取自真实后端模型（`content`），消除双侧夹具漂移。
- 不弱化既有测试；无 `any`；守后端分层与 import-linter。
- `generate_questions` 公共签名仅**追加**可选参数，默认行为不变（单考点零回归）。

### 不在范围内
- QGEN 其余 P2（`BUG-QGEN-002…006, 008`）→ 后续 P2 批次。
- P2-002（前端上限 50 vs 后端 20）等参数一致性。

## Acceptance Criteria

- [ ] **QGEN-001**：回归——以真实后端结构（`options[].content`）为夹具，断言适配后题目 `options[0].text` 等于 `content` 值；覆盖列表 / 详情 / 生成响应三条路径。修复前红、修复后绿。
- [ ] **QGEN-001**：`updateQuestion` 发送前把 `text` 映射回 `content`（回归断言请求体字段）。
- [ ] **QGEN-007**：回归——多考点中某考点抛 `MissingSourceSnippetError` 时，库中**无**任何本批次题目（回滚）；全成功时全部落库（单次提交）。
- [ ] **QGEN-007**：单考点 `generate_questions` 默认路径行为不变（既有测试零回归）。
- [ ] 后端门禁全绿：`ruff format --check`、`ruff check`、`mypy app`、`lint-imports`、`pytest`。
- [ ] 前端门禁全绿：`pnpm run lint`、`type-check`、`test:unit`。
- [ ] 逐条关闭 `bug-ledger.md` BUG-QGEN-001/007。

## Notes

- 父任务：`09-27-fullstack-bug-audit-and-fix`；依赖：无前置子任务（B1 已为同根因建立适配先例）。
- 完整证据见归档 `archive/2026-09/09-27-read-only-bug-audit/research/slice-QGEN.md`。
