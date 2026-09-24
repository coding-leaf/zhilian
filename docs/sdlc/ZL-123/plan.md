# Plan: 判题编排、异步分流与自评/重判服务 - 实施计划

- **关联 Spec**: ZL-123
- **实施执行人 / Agent**: Dev
- **当前状态**: Approved

---

## 1. 变更文件清单 (Files that change)

1. `backend/app/core/errors.py` (Modify):
   - 登记专属判题异常：`AttemptItemNotFoundError` (40013, 404), `GradingNotAllowedError` (40014, 400), `GradingExecutionError` (40015, 500)；
2. `backend/app/repositories/grading.py` (New):
   - 实现 `GradingRepository`，提供判题记录单条/批量持久化、查询、多渠道历史追溯与 `is_final` 生效指针原子切换；全方法强制输入 `user_id` 过滤（杜绝水平越权），零导入 `fastapi` 与 `app.integrations`；
3. `backend/app/repositories/__init__.py` (Modify):
   - 导出 `GradingRepository`；
4. `backend/app/services/grading.py` (New):
   - 实现 `GradingService`，涵盖客观题离线秒判、主观题双阈值分流与结构化大模型打分、大模型 20s 超时降级至 `pending_regrade` (严禁判错)、用户主观题自评覆盖与异步重判流转、两阶段状态机流转与结构化 8 要素脱敏日志；
5. `backend/app/services/__init__.py` (Modify):
   - 导出 `GradingService` 及相关 DTO / 模型；
6. `backend/tests/unit/repositories/test_grading_repo.py` (New):
   - 仓储层单元测试：涵盖增删改查、多记录历史溯源、`is_final` 标志原子更新、多租户水平越权 100% 拦截隔离；
7. `backend/tests/unit/services/test_grading_service.py` (New):
   - 服务层全流程单元测试：客观题秒判、主观题 AI 打分成功、LLM 20s 超时降级至 `pending_regrade`、用户自评打分覆盖、异步重判流转、整卷两阶段状态机流转（PARTIALLY_GRADED 与 COMPLETED）、脱敏日志验证。

---

## 2. 伴随式分步实施与验证 (Step-by-Step Implementation Loops)

### Step 1: 异常类型注册与仓储层实现 (Errors & GradingRepository)
* **操作目标**:
  1. 在 `backend/app/core/errors.py` 增加 `AttemptItemNotFoundError`, `GradingNotAllowedError`, `GradingExecutionError`；
  2. 编写 `backend/tests/unit/repositories/test_grading_repo.py`（单条创建、批量创建、按 attempt_item_id 查询、获取最终生效记录、切换 `is_final` 标志、统计待重判数量、跨用户越权阻断测试）；
  3. 在 `backend/app/repositories/grading.py` 实现 `GradingRepository`，强制 `user_id` 过滤，零违规导入；
  4. 在 `backend/app/repositories/__init__.py` 导出。
* **涉及文件**:
  - `backend/app/core/errors.py`
  - `backend/app/repositories/grading.py`
  - `backend/app/repositories/__init__.py`
  - `backend/tests/unit/repositories/test_grading_repo.py`
* **局部验证命令**:
  ```bash
  cd backend && pytest tests/unit/repositories/test_grading_repo.py -v
  ```
* **预期判据**: 仓储层测试 100% 绿灯，多租户隔离与越权阻断率 100%。

---

### Step 2: GradingService 判题流水线与自评/重判服务实现 (GradingService Implementation)
* **操作目标**:
  1. 在 `backend/app/services/grading.py` 中定义 DTO 与输出模型（`SelfEvaluateDTO`, `RegradeAttemptDTO`, `PracticeGradingSummary`, `LLMGradingOutput` 等）；
  2. 实现 `GradingService`：
     - `grade_practice(user_id, practice_id)`：
       - 检索 Practice 及 AttemptItem 列表；
       - 未作答项直接计 0 分并持久化离线成功记录；
       - 作答项调用纯函数 `match_and_grade_answer` 进行分流；
       - 客观题或高置信度主观题离线秒判；
       - 转 AI 项通过 `run_structured_agent_workflow` 驱动大模型打分，超时/故障时降级为 `pending_regrade` 并置练习为 `PARTIALLY_GRADED`；
       - 全卷判完且无待重判时更新为 `COMPLETED`，更新练习总分；
     - `self_evaluate_attempt(user_id, dto)`：
       - 校验作答项合法性与题型（仅限主观题）；
       - 原子更新原有记录 `is_final=False` 并新增 `user_self` 记录；
       - 刷新得分并重新推演练习状态；
     - `regrade_attempt(user_id, dto)`：
       - 对待重判题目重新触发 AI 判题流水线；
     - 记录结构化 8 要素脱敏日志（严禁泄露题干、标准答案与用户答案原文）；
  3. 在 `backend/app/services/__init__.py` 导出。
* **涉及文件**:
  - `backend/app/services/grading.py`
  - `backend/app/services/__init__.py`
* **局部验证命令**:
  ```bash
  cd backend && python3 -c "import app.services.grading"
  ```
* **预期判据**: 模块语法与导入正常，零语法错误。

---

### Step 3: 服务层全面单元测试 (GradingService Unit Tests)
* **操作目标**:
  1. 编写 `backend/tests/unit/services/test_grading_service.py`：
     - 测试客观题离线精准秒判；
     - 测试未作答题目的零分与未答标识；
     - 测试主观题大模型打分成功流转；
     - 测试大模型超时/故障降级为 `pending_regrade` 与 `PARTIALLY_GRADED`；
     - 测试用户主观题自评打分覆盖（客观题自评抛出 40014）；
     - 测试待重判题目异步重新判题成功后跃迁至 `COMPLETED`；
     - 测试跨租户越权访问与阻断。
* **涉及文件**:
  - `backend/tests/unit/services/test_grading_service.py`
* **局部验证命令**:
  ```bash
  cd backend && pytest tests/unit/services/test_grading_service.py -v --cov=app.services.grading --cov-branch
  ```
* **预期判据**: 服务层单元测试全部绿灯，行覆盖率 $\ge 85\%$。

---

## 3. 全局质量门禁核验 (Global Quality Gate)
* **代码风格与静态检查**:
  ```bash
  cd backend && ruff format --check . && ruff check .
  ```
* **类型与契约安全校验**:
  ```bash
  cd backend && mypy app
  ```
* **架构单向依赖核验**:
  ```bash
  python3 tooling/check_layers.py --root backend/app
  ```
* **全量单元测试与覆盖率门禁**:
  ```bash
  cd backend && pytest tests/unit/repositories/test_grading_repo.py tests/unit/services/test_grading_service.py -v
  ```
* **核验结果**: 所有静态检查通过，零架构分层违规，覆盖率达标，测试 100% 绿灯。

---

## 4. 实施偏差记录 (Deviations Log)
*若实施过程中发现必须调整其他文件（如 A 依赖 C 的接口调整），在此记录并在同个 Commit 中同步更新：*
* 实施方案完全对齐 ROADMAP.md 与 spec.md，无新增外部依赖，无破坏性数据库迁移。

---

## 5. 阶段准出签批 (Gate 3 Sign-off)
- [x] 所有分步实施项与验证断言均已就地执行并通过
- [x] 全局质量门禁（Lint / Type / Regression）全部绿灯
- [x] 变更文件与 plan.md 清单完全吻合，无越权修改
- **验收结论**: Approved
- **验证人 / 日期**: Planner / 2026-09-24 14:20
