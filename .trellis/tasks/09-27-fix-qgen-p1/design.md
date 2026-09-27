# 修复设计：QGEN 切片 P1

## 1. 边界与原则

- 契约权威：后端 `schemas/question.py`；选项元素真名 `{key, content}`。
- 适配集中一处（前端 api 层），与 B1 PRAC 同根因采用一致策略。
- QGEN-007 后端只改提交边界，不改变业务语义；单考点零回归。

## 2. 真实契约（已核实）

### 选项（QGEN-001）
- 后端：`LLMQuestionOptionItem{key, content}`（`services/question.py:134-139`）；`convert_llm_items_to_candidates` `opt.model_dump()` 落库/响应保持 `content`（`:564`）；`QuestionDetailResponse.options: list[dict[str,Any]]`（`schemas/question.py:76`）；`QuestionUpdateRequest.options: list[dict[str,Any]]`（`:158`）。
- 响应内嵌点：`QuestionListResponse.items`、`QuestionGenerateResponse.qualified_questions/pending_questions`（均 `QuestionDetailResponse`）。
- 前端：`types/question.ts:9-12` `QuestionOption{key,text}`；`QuestionCard.vue:14` 绑定 `option.text`；`QuestionOption` 亦用于 `QuestionUpdateRequest.options`。
- 后端夹具用 `content`（`tests/unit/services/test_question_service.py:362` 等），前端夹具用 `text`（`tests/unit/components/QuestionCard.spec.ts:14-17`）→ 双侧各自漂移、同时通过。

### 多考点提交（QGEN-007）
- `generate_questions`（`services/question.py:733`）：内部 `with self.session.begin_nested():` 落库后 `self.session.commit()`（`:1002-1013`）。
- `generate_questions_for_knowledge_points`（`:1048-1146`）：循环逐考点调用 `generate_questions` → 每个考点各自 commit；无跨考点事务。

## 3. 方案设计

### 3.1 QGEN-001（frontend，新增适配层）
新增 `miniprogram/src/api/adapters/question.ts`：

```ts
// 契约权威：后端 QuestionDetailResponse.options 元素为 {key, content}
export function adaptQuestionItem(raw: RawQuestion): QuestionItem
export function adaptQuestionPage(raw: RawPage<RawQuestion>): PageResult<QuestionItem>
export function adaptGenerateResponse(raw: RawGenerateResponse): QuestionGenerateResponse
export function toQuestionUpdatePayload(payload: QuestionUpdateRequest): RawQuestionUpdatePayload
```

映射规则：
- 选项：`{ key, text: opt.content ?? opt.text ?? '' }`（兼容旧 mock）。
- 其余字段原样透传。
- 更新入参：`options` 由 `{key, text}` 映射为 `{key, content}`（`content: o.content ?? o.text ?? ''`）。

集成点（`src/api/question.ts`）：
- `fetchQuestionList` → `adaptQuestionPage`。
- `fetchQuestionDetail` → `adaptQuestionItem`。
- `generateQuestions` → `adaptGenerateResponse`。
- `updateQuestion` → 发送前 `toQuestionUpdatePayload`。

消费点（`QuestionCard`/审核/编辑）保持读 `option.text`，无需改动。

**测试夹具改造**：前端题目夹具改用真实后端结构（`options[].content`）；新增断言适配后 `options[0].text === content 值`。

### 3.2 QGEN-007（backend，提交边界原子化）
- `generate_questions` 追加可选关键字 `defer_commit: bool = False`：
  ```python
  try:
      with self.session.begin_nested():
          saved_questions = self.question_repo.batch_create_questions(all_entities, user_id)
          saved_checks = self.question_repo.batch_create_quality_checks(all_quality_checks, user_id)
      if not defer_commit:
          self.session.commit()
  except Exception:
      self.session.rollback()
      raise
  ```
  默认 `False` → 单考点路径行为不变。
- `generate_questions_for_knowledge_points` 改为单事务：
  ```python
  try:
      for kp_id, kp_count in zip(...):
          result = self.generate_questions(..., defer_commit=True)
          ...聚合...
      self.session.commit()            # 全部成功一次性提交
  except Exception:
      self.session.rollback()          # 任一失败整批回滚
      raise
  ```
- 语义：任一考点失败（`MissingSourceSnippetError` 等）→ 整批不入库；全成 → 单次提交。保持 fail-fast，不静默降级。
- 说明：内层在落库异常时已 `rollback()`；外层对「检索/校验类」早期异常同样 `rollback()`，确保原子。

## 4. 影响面与兼容

| 文件 | 变更 |
|---|---|
| `miniprogram/src/api/adapters/question.ts` | 新增适配/归一 |
| `miniprogram/src/api/question.ts` | 四个函数接入适配 |
| `miniprogram/src/types/question.ts` | 如需补 `Raw*` 类型（可选原始透传） |
| `miniprogram/tests/unit/api/question.spec.ts`、`tests/unit/components/QuestionCard.spec.ts`、`tests/unit/pages/questionList.spec.ts` | 夹具改真实契约 + 回归 |
| `backend/app/services/question.py` | `defer_commit` + 多考点单事务 |
| `backend/tests/unit/services/test_question_multi_kp.py` | 原子性回归 |
| `backend/tests/unit/services/test_question_service.py` | 单考点零回归确认 |

- 兼容：`defer_commit` 默认 `False`，单考点零回归；前端适配层为新增，消费点不变。
- 风险：多考点改为单事务后，事务时长随考点数增长（可接受，题目量有上限）；若仓储内部有独立 commit 需排查（`batch_create_*` 应为 flush-only）。

## 5. 验证 & 回归

先红后绿断言：
1. 列表/详情/生成三路径：真实 `options[].content` → 适配后 `text` 非空。
2. `updateQuestion` 请求体选项为 `content`。
3. 多考点第二考点失败 → 库中 0 条本批次题目；全成功 → 全部落库。
4. 单考点 `generate_questions` 行为不变。

门禁：后端五项 + 前端三项全绿。

## 6. 回滚点

- 前端适配层为独立新增模块，移除接入即回滚。
- `defer_commit` 默认关闭，等价旧行为；多考点单事务可回退为逐提交（会复现原子性缺陷）。
