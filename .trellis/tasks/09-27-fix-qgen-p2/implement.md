# 执行计划：QGEN 切片 P2 修复

## 前置条件

- 任务：`09-27-fix-qgen-p2`（父任务：`09-27-fullstack-bug-audit-and-fix`）。
- 契约权威与技术设计：详见 `design.md`。
- 问题根因与切片审计：详见 `.trellis/tasks/archive/2026-09/09-27-read-only-bug-audit/research/slice-QGEN.md`。

---

## 执行清单（有序）

### Step 1 — 失败回归测试（红）
- [ ] 1.1 后端：在 `test_question_quality.py` 新增用例 `test_conflict_cross_type_true_false_and_choice_not_conflicted`（判断题与单选题题干高度相似但在当前逻辑下被误判为冲突 → 预期通过；当前实现返回失败 → 红）。
- [ ] 1.2 后端：在 `test_question_schemas.py` 增加 `QuestionGenerateRequest(..., question_types=[])` 期望抛出 ValidationError 的断言（当前可通过 → 红）。
- [ ] 1.3 后端：在 `test_question_service.py` 增加 `GenerateQuestionsOptions(question_types=[])` 期望抛出 ValueError 的断言（当前可通过 → 红）。
- [ ] 1.4 前端：在 `materialTreeUtils.spec.ts` 中新增/修改 `validateQuestionConfig({ count: 21 })` 返回 false 的断言（当前返回 true → 红）。
- [ ] 1.5 前端：在 `QuestionConfigDrawer.spec.ts` 中断言输入 25 被 clamp 到 20、文案为 1 到 20（当前为 50 → 红）。
- [ ] 1.6 前端：在 `api/question.spec.ts` 中断言 `deleteQuestion('q_001', '原因')` 发起请求 URL 包含 `?reason=` 且不发送 body data（当前发送 body data → 红）。
- [ ] 1.7 运行测试套件，确认上述新增断言全部处于「红」状态。

### Step 2 — 后端修复实现（绿）
- [ ] 2.1 `backend/app/core/algorithms/question_quality.py`：
  - 在 `check_answer_conflict` 中判断 `candidate.question_type` 与 `existing_question.question_type` 是否同属判断题或同属选择题，跨类型时直接 `continue` 跳过答案比对（BUG-QGEN-006）。
- [ ] 2.2 `backend/app/schemas/question.py`：
  - `QuestionGenerateRequest.question_types` 添加 `min_length=1` 约束及元素值枚举校验（BUG-QGEN-008）。
- [ ] 2.3 `backend/app/services/question.py`：
  - `GenerateQuestionsOptions.__post_init__` 增加 `question_types` 非空和有效性校验（BUG-QGEN-008）。
- [ ] 2.4 `backend/app/api/v1/questions.py`：
  - `delete_question` 路由参数增加读取可选 Request Body 作为 reason 的兜底（BUG-QGEN-003）。
- [ ] 2.5 运行后端对应单元测试确认转绿。

### Step 3 — 前端修复实现（绿）
- [ ] 3.1 `miniprogram/src/subpackages/material/utils/tree.ts`：
  - `validateQuestionConfig` 上限校验由 50 修改为 20，文案更新为 `出题数量必须在 1 到 20 题之间`（BUG-QGEN-002）。
- [ ] 3.2 `miniprogram/src/subpackages/material/components/QuestionConfigDrawer.vue`：
  - 界面提示文案改为 `单次支持生成 1 到 20 道题目`；
  - `clampCount` 上限收敛为 20；
  - 加号按钮禁用条件改为 `questionCount >= 20`（BUG-QGEN-002）。
- [ ] 3.3 `miniprogram/src/api/question.ts`：
  - 修改 `deleteQuestion` 实现，将 `reason` 格式化为 query string 追加到 URL，DELETE 不传 data（BUG-QGEN-003）。
- [ ] 3.4 `miniprogram/src/types/question.ts`：
  - 更新 `QuestionQualityCheck` 接口定义，对齐后端 `QuestionQualityCheckResponse`（BUG-QGEN-004）。
- [ ] 3.5 `miniprogram/src/subpackages/material/pages/questions/index.vue`：
  - 在 `handleDeleteQuestion` 删除成功后，重置分页并重新拉取第一页数据 `loadQuestions(true)`，防止 offset 跳题（BUG-QGEN-005）。
- [ ] 3.6 运行前端对应单元测试确认转绿。

### Step 4 — 全量门禁校验与收尾
- [ ] 4.1 后端全套门禁：
  - `uv run ruff format --check .`
  - `uv run ruff check .`
  - `uv run mypy app`
  - `uv run lint-imports`
  - `uv run pytest tests`
- [ ] 4.2 前端全套门禁：
  - `pnpm run lint`
  - `pnpm run type-check`
  - `pnpm run test:unit`
- [ ] 4.3 确认所有回归测试与既有测试均通过，无 warning/error，关闭 BUG-QGEN-002、003、004、005、006、008。

---

## 验证命令

```bash
# 后端（workdir=backend）
uv run ruff format --check . && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run pytest tests

# 前端（workdir=miniprogram）
pnpm run lint && pnpm run type-check && pnpm run test:unit
```

---

## 评审门禁

- **Gate A（红绿反转）**：Step 1 的 6 个 bug 对应测试先出现明确断言失败（红），在 Step 2 & Step 3 实现后转绿。
- **Gate B（跨层一致性）**：出题上限前后端同为 20；删除 reason 前端以 query 发送，后端 query+body 兼容并成功入审计表；质检类型与后端 schema 完全一致。
- **Gate C（质量全绿）**：后端 5 项工具链全绿，前端 3 项门禁全绿，无 `any`，无 import-linter 违例。

---

## 回滚点

- 所有改动均遵循兼容性设计原则：
  - 若需回滚 QGEN-002，仅需还原前端 `QuestionConfigDrawer.vue` 与 `tree.ts` 中对 20 的限制；
  - 若需回滚 QGEN-003，后端由于保留双向兼容，前端单文件 revert 即可；
  - 若需回滚 QGEN-004，前端字段含有可选兼容别名，无破坏性；
  - 若需回滚 QGEN-005、006、008，均为单一函数级变更，单文件 revert 即可。
