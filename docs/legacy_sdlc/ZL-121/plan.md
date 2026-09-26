# Plan: 题目生成、质检过滤与来源溯源服务 - 实施计划

- **关联 Spec**: ZL-121
- **实施执行人 / Agent**: Dev
- **当前状态**: Completed

---

## 1. 变更文件清单 (Files that change)

1. `backend/app/core/errors.py` (Modify):
   - 补充 `MissingSourceSnippetError` (40003, HTTP 400), `QuestionQualityCheckError` (40008, HTTP 400), `QuestionNotFoundError` (40009, HTTP 404)；
2. `backend/app/repositories/question.py` (New):
   - 实现 `QuestionRepository`，对 `questions`, `question_quality_checks`, `question_audit_logs` 提供强制绑定 `user_id` 的 CRUD、批量插入与关联查询；
3. `backend/app/repositories/__init__.py` (Modify):
   - 导出 `QuestionRepository`；
4. `backend/app/services/question.py` (New):
   - 实现 `QuestionService`，编排切片检索前置门禁 (40003)、Top 4 切片聚合 (<=2400 字符)、LLM 结构化出题 (温度 0.3, 7 大题型与 6 要素)、题干 1024 维向量化、对接纯函数质检核 `filter_qualified_questions` (滑动窗口 500 题)、最多 2 次增量重抽熔断、原子事务持久化与 8 要素脱敏日志；
5. `backend/app/services/__init__.py` (Modify):
   - 导出 `QuestionService`；
6. `backend/tests/unit/repositories/test_question_repo.py` (New):
   - 仓储层单元测试：涵盖题目增删改查、多切片关联元数据、质检记录批量落库、修改痕迹审计日志及跨租户水平越权阻断；
7. `backend/tests/unit/services/test_question_service.py` (New):
   - 服务层全流程单元测试：检索先于生成门禁拦截 (40003)、LLM 结构化出题成功、题型与评分细则校验、纯函数质检通过、质检拦截与重抽自适应反馈 (最多 2 次)、待处理区状态归档、原子回滚防御及多租户隔离。

---

## 2. 伴随式分步实施与验证 (Step-by-Step Implementation Loops)

### Step 1: 异常类型注册与仓储层实现与多租户测试 (Repository & Tenant Isolation)
* **操作目标**:
  1. 在 `backend/app/core/errors.py` 增加 `MissingSourceSnippetError`, `QuestionQualityCheckError`, `QuestionNotFoundError`；
  2. 编写 `backend/tests/unit/repositories/test_question_repo.py` 测试用例（覆盖创建、根据版本/知识点获取列表、更新与软删除、质检记录批量创建、审计日志写入、跨用户访问拦截）；
  3. 实现 `backend/app/repositories/question.py`，所有查询和修改必须带 `user_id` 条件，严禁导入 `fastapi` 与 `app.integrations`；
  4. 在 `backend/app/repositories/__init__.py` 导出。
* **涉及文件**:
  - `backend/app/core/errors.py`
  - `backend/app/repositories/question.py`
  - `backend/app/repositories/__init__.py`
  - `backend/tests/unit/repositories/test_question_repo.py`
* **局部验证命令**:
  ```bash
  cd backend && pytest tests/unit/repositories/test_question_repo.py -v
  ```
* **预期判据**: 仓储层所有用例 100% 绿灯，多租户越权拦截断言生效，测试耗时 < 1s。

---

### Step 2: 题目服务纯辅助函数与 DTO Schema 构建 (DTOs & Helpers)
* **操作目标**:
  1. 在 `backend/app/services/question.py` 中定义出题入参 DTO、LLM 结构化输出 Pydantic 模型（`LLMQuestionBatchOutput` 等）及结果数据结构；
  2. 实现纯数据处理与上下文组装辅助函数：
     - `aggregate_snippet_context`: 选取 Top 4 优质切片，截断在 2400 字符以内；
     - `build_generation_prompt`: 构造包含题型、难度、来源片段及重抽 feedback 的系统与用户提示词；
     - `convert_llm_items_to_candidates`: 将 LLM 结构化结果转为纯函数质检核所需的 `CandidateQuestion`；
  3. 编写单测验证辅助函数与边界截断逻辑。
* **涉及文件**:
  - `backend/app/services/question.py`
  - `backend/tests/unit/services/test_question_service.py`
* **局部验证命令**:
  ```bash
  cd backend && pytest tests/unit/services/test_question_service.py -k "test_helpers or test_prompt" -v
  ```
* **预期判据**: 辅助函数测试全部绿灯，超长截断与提示词格式严格无误。

---

### Step 3: QuestionService 全流程编排与质检重抽熔断集成 (Service Orchestration & Quality Gate)
* **操作目标**:
  1. 实现 `QuestionService.generate_questions`:
     - 校验 `material_id`、`version_id`、`knowledge_point_id` 与租户归属；
     - 检索前置门禁：切片为空或最高相似度 < 0.35 抛出 `MissingSourceSnippetError` (40003)；
     - 上下文拼接与大模型生成（`temperature=0.3`）；
     - 题干+选项 1024 维定长向量化（`EmbeddingProtocol`）；
     - 获取同资料最近 500 道已有题目，对接纯函数 `filter_qualified_questions` 执行质检；
     - 质检未通过时，追加 Feedback 提示词并触发增量重抽（上限 2 次）；
     - 达到重抽上限后，合格题记为 `available`，残余未通过题目记为 `pending_review`；
     - 事务内持久化 `Question` 与 `QuestionQualityCheck`；
     - 记录 8 要素脱敏日志；
  2. 实现 `QuestionService.update_question` 与 `delete_question`，并记录 `QuestionAuditLog`；
  3. 在 `backend/app/services/__init__.py` 导出；
  4. 在 `backend/tests/unit/services/test_question_service.py` 补充完整的流程测试。
* **涉及文件**:
  - `backend/app/services/question.py`
  - `backend/app/services/__init__.py`
  - `backend/tests/unit/services/test_question_service.py`
* **局部验证命令**:
  ```bash
  cd backend && pytest tests/unit/services/test_question_service.py -v
  ```
* **预期判据**: 所有场景用例（正常生成、40003 拦截、重抽成功、2 次重抽熔断归入待处理区、事务回滚、越权拦截）100% 绿灯。

---

## 3. 全局质量门禁核验 (Global Quality Gate)

* **分层依赖检查**:
  ```bash
  python3 tooling/check_layers.py --root backend/app
  ```
* **SDLC 工件完整性校验**:
  ```bash
  python3 tooling/check_sdlc_integrity.py
  ```
* **代码格式与 Lint 检查**:
  ```bash
  cd backend && ruff format --check . && ruff check .
  ```
* **类型与覆盖率核验**:
  ```bash
  cd backend && mypy app && pytest tests/unit/repositories/test_question_repo.py tests/unit/services/test_question_service.py --cov=app/services/question --cov=app/repositories/question --cov-branch --cov-fail-under=85
  ```
* **核验结果**: 所有静态检查通过，零新增警告；全量相关测试用例 100% 绿灯，覆盖率达标。

---

## 4. 实施偏差记录 (Deviations Log)
* [当前无偏差]

---

## 5. 阶段准出签批 (Gate 3 Sign-off)
- [ ] 所有分步实施项与验证断言均已就地执行并通过
- [ ] 全局质量门禁（Lint / Type / Regression）全部绿灯
- [ ] 变更文件与 plan.md 清单完全吻合，无越权修改
- **验收结论**: Pending
- **验证人 / 日期**: [待人类确认] / 2026-09-24 11:22
