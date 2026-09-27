# 修复 QGEN 切片 P2（002-006, 008）

## Goal

修复只读审计清单 QGEN 切片 6 条 P2 缺陷：出题数量上限前后端契约对齐、题目删除原因参数位置修正、质检记录前端类型与后端对齐、列表删除后加载更多跳题修复、客观题题干相似答案冲突跨题型误判修复、生成题目请求模型空题型非空校验。

## 需求来源

上游审计 `09-27-read-only-bug-audit`（已归档）`research/slice-QGEN.md`：

| ID | 级别 | 层 | 现象一句话 |
|---|---|---|---|
| BUG-QGEN-002 | P2 | cross-layer | 出题数量上限前后端不一致（前端 50 / 后端 20），用户输入 21~50 必然被后端 422 拒绝 |
| BUG-QGEN-003 | P2 | cross-layer | 删除原因以请求体发送，后端按 Query 读取（原因未传参，审计记录丢失） |
| BUG-QGEN-004 | P2 | cross-layer | 质检记录前端类型字段（rule_code/passed/message）与后端响应（check_type/is_passed/reason 等）不一致 |
| BUG-QGEN-005 | P2 | frontend | offset 分页 + 本地删除后直接按 page+1「加载更多」会跳过前移的题目 |
| BUG-QGEN-006 | P2 | backend | 判断题（布尔）与选择题（集合）题干相似时，归一化答案因跨类型比较永不相等被误判为冲突一票否决 |
| BUG-QGEN-008 | P2 | backend | `QuestionGenerateRequest` 允许空 `question_types: []` 通过校验，服务端提示词失去题型约束 |

## Requirements

### 功能要求

1. **BUG-QGEN-002（出题数量上限对齐）**：
   - 契约权威以**后端为准（1~20 题）**。LLM 出题单次单考点 token/生成耗时敏感，20 题已是当前后端与算法层经过压测的安全硬上限。
   - 前端 `QuestionConfigDrawer.vue` 界面文案更新为 `单次支持生成 1 到 20 道题目`，步进器和输入框截断 `clampCount` 上限改为 20，`+` 按钮在 `>= 20` 时禁用。
   - 前端 `validateQuestionConfig` 校验上限由 50 调整为 20，错误文案统一为 `出题数量必须在 1 到 20 题之间`。
2. **BUG-QGEN-003（删除原因参数传递）**：
   - 前端 `deleteQuestion` 接口契约修正：将 `reason` 作为 Query Parameter 拼接到请求 URL 中（如 `/api/v1/questions/${questionId}?reason=...`），DELETE 请求体不发送冗余 data。
   - 后端 `api/v1/questions.py` 保留 `reason: Query(...)` 参数；同时后端做向后防御性兼容：若 Query 未提供 `reason` 且请求体含有 JSON `{"reason": "..."}` 时，亦可兜底读取（保持健壮性）。
3. **BUG-QGEN-004（质检记录前端类型契约对齐）**：
   - 前端 `QuestionQualityCheck`（`miniprogram/src/types/question.ts`）字段对齐后端 `QuestionQualityCheckResponse`（`schemas/question.py`）：
     - `id?: string`
     - `question_id?: string`
     - `batch_id?: string`
     - `check_type: string`
     - `is_passed: boolean`
     - `reason?: string | null`
     - `similarity_score?: number | null`
     - `check_metadata?: Record<string, unknown>`
     - `created_at?: string`
   - 为向前兼容保留可选废弃别名字段（`rule_code?: string`、`passed?: boolean`、`message?: string`），确保类型平滑过渡。
4. **BUG-QGEN-005（offset 分页删除后加载更多）**：
   - 在题目列表页（`pages/questions/index.vue`），当用户确认并成功删除某道题目后，不仅在本地移除该项与更新 `total`，同时触发基于当前已加载数量重置或就地按当前 offset 补齐/刷新当前列表（或在用户触发下一次「加载更多」时依据当前实际已加载有效列表长度向后端换算 `offset`，请求真实偏移量，而不是简单 `page += 1`）。
   - 本方案采用最稳健且符合既有无限滚动 UX 的策略：
     - 用户在第 K 页删除某题目后，重新从第 1 页静默拉取当前已加载深度（`offset=0, limit=listData.length`）或删除成功后重新刷新列表，保证后端前移的数据能够无缝补入，且不破坏现有分页位置。
5. **BUG-QGEN-006（客观题跨题型答案冲突误判修复）**：
   - 算法函数 `check_answer_conflict`（`backend/app/core/algorithms/question_quality.py`）中，当候选题与已有题题干相似度达到冲突阈值（`>= conflict_vector_threshold`，默认 0.88）时：
     - **仅当两道题目属于兼容题型/同一答案域**时才进行答案归一化比对与冲突拦截。
     - 若候选为判断题（`true_false`），只有当参考题也是判断题（`true_false`）时才比对；
     - 若候选为选择题（`single_choice` / `multiple_choice`），只有当参考题也是选择题时才比对；
     - 判断题与选择题之间答案域不兼容，不触发答案冲突拦截，跳过冲突比较。
6. **BUG-QGEN-008（请求模型空题型校验）**：
   - 后端 `QuestionGenerateRequest`（`schemas/question.py`）：对 `question_types: list[str]` 增加校验，禁止空列表（`min_length=1`），并校验列表中每一项必须属于有效 `QuestionType` 枚举值。
   - 后端 `GenerateQuestionsOptions`（`services/question.py`）：在 `__post_init__` 中校验 `self.question_types` 非空（`len(self.question_types) >= 1`）且所有元素合法。

### 约束
- 契约权威：后端 `schemas/question.py`。前端所有字段名和约束逐字取自后端。
- 新增/调整字段保持兼容与类型收敛，无 `any`。
- 守分层规范与 import-linter 规则。
- 不弱化既有测试用例，所有新增或修改测试先红后绿。
- 前后端全量门禁必须全绿。

### 不在范围内
- BUG-QGEN-001（选项 content/text 契约，P1，已在 `09-27-fix-qgen-p1` 中修复）。
- BUG-QGEN-007（多考点生成事务原子性，P1，属于独立批次）。
- 错题本相关 snapshot 问题（属于 DIAG/PRAC 切片）。

## Acceptance Criteria

- [ ] **QGEN-002**：前端 `validateQuestionConfig({ count: 21 })` 返回 `valid: false` 且提示 `1 到 20 题`；抽屉 `clampCount(50)` 截断为 20；文案与步进器最大值更新为 20。
- [ ] **QGEN-003**：前端 `deleteQuestion(id, '原因')` 发起请求 URL 携带 `?reason=%E5%8E%9F%E5%9B%A0`；后端删除接口在 Query 传参或 body 传参时均能正确将原因落库至审计日志（`QuestionAuditLog.reason`）。
- [ ] **QGEN-004**：前端 `QuestionQualityCheck` 类型完全对齐后端字段名（`check_type`, `is_passed`, `reason`, `similarity_score`, `check_metadata`），编译无错误。
- [ ] **QGEN-005**：在题目列表页面删除某项后，后续翻页加载不会跳过前移的题目，分页状态与后端完全一致。
- [ ] **QGEN-006**：单选题与判断题题干即便相似度为 1.0（如都以某判断命题为题干但一为判断一为选择），`check_answer_conflict` 返回 `is_valid: True`，不会因跨题型比较答案而误判冲突。同为判断题答案相反、或同为选择题答案不同且相似度 >= 0.88 时仍正确判冲突。
- [ ] **QGEN-008**：`QuestionGenerateRequest(material_id=..., knowledge_point_id=..., question_types=[])` 抛出验证错误；`GenerateQuestionsOptions(question_types=[])` 抛出 `ValueError`。
- [ ] 后端门禁全绿：`ruff format --check`、`ruff check`、`mypy app`、`lint-imports`、`pytest`。
- [ ] 前端门禁全绿：`pnpm run lint`、`pnpm run type-check`、`pnpm run test:unit`。

## Notes

- 6 条 P2 全部经 HEAD 代码客观查验，全部确证存在，无误报或失效条目。
- 契约权威说明：QGEN-002 以后端 1~20 题为准；QGEN-003 前端改 query、后端兼容 query+body；QGEN-004 前端对齐后端字段名。
