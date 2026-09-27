# 技术设计：QGEN 切片 P2 修复

## 1. 背景与根因分析

### BUG-QGEN-002: 出题数量上限前后端契约不一致
- **根因位置**：
  - 前端：`miniprogram/src/subpackages/material/components/QuestionConfigDrawer.vue:35, 55, 198` 与 `miniprogram/src/subpackages/material/utils/tree.ts:145-147`。代码硬编码了上限 50。
  - 后端：`backend/app/schemas/question.py:46`（`count: int = Field(default=5, ge=1, le=20)`）与 `backend/app/services/question.py:79-80`（`if self.count <= 0 or self.count > 20: raise ValueError(...)`）。
- **决定**：以**后端 1~20 题为权威准则**。出题受大模型生成窗口、耗时、网络超时（前端设为 180s）限制，单次单考点 20 题是安全合理的上限。前端统一收敛至 20 题。

### BUG-QGEN-003: 删除原因以请求体发送，后端按 Query 读取
- **根因位置**：
  - 前端：`miniprogram/src/api/question.ts:106-115`，`deleteQuestion` 调用 `request` 传入 `data: reason ? { reason } : undefined`。由于在小程序环境以及标准 REST 规范下，DELETE 请求体携带的 body 经常被代理或服务端路由忽略；
  - 后端：`backend/app/api/v1/questions.py:285` 显式声明 `reason: Annotated[str | None, Query(...)]`。后端从 Query 读取，导致前端传来的 reason 丢失。
- **决定**：
  - 前端修改：`deleteQuestion` 拼接 URL query 参数：`url: /api/v1/questions/${questionId}${reason ? \`?reason=\${encodeURIComponent(reason)}\` : ''}`，DELETE 不再传 body `data`。
  - 后端防御兼容：在 `delete_question` 路由中，若 query 中 `reason` 为空，尝试从 Request Body 中提取可选 json `reason`，保证无论是旧客户端请求体还是新客户端 query 参数均能保留删除审计原因。

### BUG-QGEN-004: 质检记录前端类型契约错位
- **根因位置**：
  - 前端：`miniprogram/src/types/question.ts:93-97` 声明为：
    ```typescript
    export interface QuestionQualityCheck {
      rule_code: string;
      passed: boolean;
      message?: string;
    }
    ```
  - 后端：`backend/app/schemas/question.py:88-101` 声明为：
    ```python
    class QuestionQualityCheckResponse(BaseModel):
        id: uuid.UUID
        question_id: uuid.UUID
        batch_id: str
        check_type: str
        is_passed: bool
        reason: str | None = None
        similarity_score: float | None = None
        check_metadata: dict[str, Any] = Field(default_factory=dict)
        created_at: datetime
    ```
- **决定**：以**后端为准**。将前端 `QuestionQualityCheck` 字段对齐后端字段（`check_type`, `is_passed`, `reason`, `similarity_score`, `check_metadata`），并提供旧字段可选别名以保持平滑兼容。

### BUG-QGEN-005: offset 分页 + 本地删除后翻页漏题
- **根因位置**：
  - `miniprogram/src/subpackages/material/pages/questions/index.vue:100-121, 146-147`。
  - 页面维护 `page` 计数（1, 2, ...），由 `pageSize = 20` 驱动。每次调用 `fetchQuestionList({ page, page_size })`，后端转换为 `offset = (page - 1) * page_size`。
  - 当第 1 页加载后（20条），用户在列表删除第 1 条，后端剩余数据整体向前移位（原第 21 条变为第 20 条）。当用户滚动到底部触发 `handleLoadMore`，`page` 变为 2，向后端请求 `offset = 20`（即原第 22 条），原第 21 条（现索引 19）被直接永久跳过。
- **决定**：
  - 修复策略：在 `questions/index.vue` 中，删除成功后刷新全量已加载数量（即重新请求已获取深度 `page: 1, page_size: listData.length` 或重新调用 `loadQuestions(true)` 刷新第 1 页），保证列表数据严格对齐后端最新偏移量与数据视图。考虑题库列表通常在单知识点下数量有限（几十条），删除后刷新第 1 页并重置分页是最健壮、无幽灵数据且符合用户操作预期的解法。

### BUG-QGEN-006: 客观题题干相似答案冲突跨题型误判
- **根因位置**：
  - `backend/app/core/algorithms/question_quality.py:609-635`（`check_answer_conflict`）与 `:346-358`（`_normalize_objective_answer`）。
  - `OBJECTIVE_QUESTION_TYPES` 包含 `single_choice`, `multiple_choice`, `true_false`。
  - 当候选题为 `true_false`，已有题为 `single_choice` 且题干相似度 `>= 0.88` 时：
    - `candidate_answer` 为布尔值（如 `True`）；
    - `existing_answer` 为选项集合（如 `frozenset({'A'})`）；
    - `candidate_answer != existing_answer` 必然成立（`True != frozenset({'A'})` 恒为真！），直接返回 `(False, "题干高度相似但客观题标准答案冲突", ...)`。
- **决定**：
  - 在 `check_answer_conflict` 的循环比较中，增加题型兼容性判断：
    - 判断题（`QuestionType.TRUE_FALSE`）只能与同为判断题（`QuestionType.TRUE_FALSE`）的已有题做答案比对；
    - 选择题（`QuestionType.SINGLE_CHOICE` 或 `QuestionType.MULTIPLE_CHOICE`）只能与同为选择题的已有题做答案比对；
    - 题型不兼容时，跳过此题的答案冲突检查（`continue`）。

### BUG-QGEN-008: 生成题目请求模型允许空题型
- **根因位置**：
  - 后端 `backend/app/schemas/question.py:48-56`：`question_types: list[str]` 仅设置了默认值，但若调用方显式传入 `question_types: []`，Pydantic 校验通过。
  - 后端 `backend/app/services/question.py:64-85`：`GenerateQuestionsOptions` 未对 `question_types` 的非空性及元素合法性进行检查。
- **决定**：
  - 在 `QuestionGenerateRequest` 中对 `question_types` 增加 `min_length=1` 约束，并通过 `field_validator` 或 `Annotated` 校验每个题型属于有效枚举（`QuestionType` 或已知枚举值集合）。
  - 在 `GenerateQuestionsOptions.__post_init__` 中增加非空校验：`if not self.question_types: raise ValueError("question_types 不能为空")`，且校验每个题型属于有效取值。

---

## 2. 契约与跨层变更设计

### 2.1 API 契约变化

#### 2.1.1 `POST /api/v1/questions/generate`
- 入参字段校验增强：
  - `count`: 维持 `ge=1, le=20`。
  - `question_types`: `list[str] = Field(..., min_length=1)`，且元素值必须在 `[e.value for e in QuestionType]` 中。若传入 `[]`，触发 Pydantic 422 校验失败。

#### 2.1.2 `DELETE /api/v1/questions/{id}`
- 前端请求形式调整：
  - 改为 `DELETE /api/v1/questions/{id}?reason=...`（不携带 Request Body）。
- 后端实现调整：
  - 优先读取 Query 中的 `reason`；
  - 若 Query 为空，异步尝试读取 Request Body 中的 `reason` 键（若存在 JSON body），保持向前兼容。

#### 2.1.3 `POST /api/v1/questions/generate` 与 `GET /materials/{id}/quality-checks` 响应中的质检结构
- 前端 `QuestionQualityCheck` 契约对齐：
  ```typescript
  export interface QuestionQualityCheck {
    id?: string;
    question_id?: string;
    batch_id?: string;
    check_type: string;
    is_passed: boolean;
    reason?: string | null;
    similarity_score?: number | null;
    check_metadata?: Record<string, unknown>;
    created_at?: string;
    // 兼容废弃字段别名
    rule_code?: string;
    passed?: boolean;
    message?: string;
  }
  ```

---

## 3. 影响文件清单

### 后端 (Backend)
1. `backend/app/schemas/question.py`
   - 为 `QuestionGenerateRequest.question_types` 添加非空及枚举值校验。
2. `backend/app/services/question.py`
   - 为 `GenerateQuestionsOptions.__post_init__` 添加 `question_types` 非空与枚举值校验。
3. `backend/app/core/algorithms/question_quality.py`
   - 在 `check_answer_conflict` 中加入题型答案域兼容性校验（判断题与选择题不跨类型比对答案冲突）。
4. `backend/app/api/v1/questions.py`
   - 在 `delete_question` 路由中补充对 request body 的兜底读取兼容。
5. 测试文件：
   - `backend/tests/unit/core/algorithms/test_question_quality.py`：新增跨题型（判断 vs 选择）相似题干不误判冲突的测试用例。
   - `backend/tests/unit/schemas/test_question_schemas.py`：新增 `question_types=[]` 校验失败的用例。
   - `backend/tests/unit/services/test_question_service.py`：新增 `GenerateQuestionsOptions(question_types=[])` 校验失败用例。
   - `backend/tests/unit/api/test_question_router.py`：补充 body 兜底传递 reason 的删除用例。

### 前端 (Miniprogram)
1. `miniprogram/src/subpackages/material/components/QuestionConfigDrawer.vue`
   - 修改文案为 1 到 20 道题目；
   - `clampCount` 上限改为 20；
   - 步进器按钮在 `>= 20` 时禁用。
2. `miniprogram/src/subpackages/material/utils/tree.ts`
   - `validateQuestionConfig` 上限校验由 50 改为 20。
3. `miniprogram/src/api/question.ts`
   - `deleteQuestion` 将 `reason` 组装为 query 参数。
4. `miniprogram/src/types/question.ts`
   - 更新 `QuestionQualityCheck` 接口定义，对齐后端模型字段。
5. `miniprogram/src/subpackages/material/pages/questions/index.vue`
   - 删除成功后，重置分页并刷新当前列表数据，防止后续翻页 offset 错位。
6. 测试文件：
   - `miniprogram/tests/unit/materialTreeUtils.spec.ts`：更新 20 上限校验测试用例。
   - `miniprogram/tests/unit/components/QuestionConfigDrawer.spec.ts`：更新 20 上限组件交互测试。
   - `miniprogram/tests/unit/api/question.spec.ts`：更新 `deleteQuestion` query 参数断言。
   - `miniprogram/tests/unit/pages/questionList.spec.ts`：更新删除后重新加载与数据一致性测试。

---

## 4. 兼容性与回滚方案

- **向后兼容性**：
  - QGEN-002：原本选择 >20 题在后端会被 422 拒绝，前端收紧至 20 消除隐形报错，完全向前向后兼容。
  - QGEN-003：后端同时接受 Query 和 Request Body，前端发出 Query，兼容所有旧客户端。
  - QGEN-004：前端字段保留可选别名，不会影响任何既有代码。
  - QGEN-005：删除后列表刷新确保客户端与数据库完全一致。
  - QGEN-006：质检算法放宽了误拦截，不会对正常出题产生破坏性影响。
  - QGEN-008：仅对异常空参数增加拦截，合法调用均自带默认或指定题型。
- **回滚方式**：
  - 各修改均内聚在各自的方法与组件内，可通过还原对应提交直接干净回滚。
