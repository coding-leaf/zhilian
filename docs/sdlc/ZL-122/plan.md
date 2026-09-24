# Plan: 练习组卷、作答保存与交卷调度服务 - 实施计划

- **关联 Spec**: ZL-122
- **实施执行人 / Agent**: Dev
- **当前状态**: Draft / Approved / In-Execution / Completed

---

## 1. 变更文件清单 (Files that change)

1. `backend/app/core/errors.py` (Modify):
   - 登记异常 `PracticeNotFoundError` (40010, HTTP 404, 别名 `PracticeSessionNotFoundError`)、`PracticeStatusError` (40011, HTTP 400, 别名 `PracticeSessionStatusError`)、`PracticeEmptyQuestionsError` (40012, HTTP 400)；
2. `backend/app/core/algorithms/practice.py` (New):
   - 实现纯函数题目打散算法 `scatter_adjacent_knowledge_questions`（保证同知识点题目不相邻，贪心频次交替排列，环路复杂度 $V(G) \le 10$）；
3. `backend/app/core/algorithms/__init__.py` (Modify):
   - 导出 `scatter_adjacent_knowledge_questions`；
4. `backend/app/repositories/practice.py` (New):
   - 实现 `PracticeRepository`，提供 `Practice` 与 `AttemptItem` 的全量 CRUD，强制 `user_id` 过滤（杜绝水平越权），零导入 `fastapi` 与 `app.integrations`；
5. `backend/app/repositories/__init__.py` (Modify):
   - 导出 `PracticeRepository`；
6. `backend/app/services/practice.py` (New):
   - 实现 `PracticeService`，涵盖三种组卷模式（顺序、随机、薄弱知识点）、同知识点打散、未答统计、逐题作答 Upsert 保存、基于 `IdempotencyProtocol` 的交卷强幂等与 `QueueProtocol` 判题调度投递，8 要素脱敏日志；
7. `backend/app/services/__init__.py` (Modify):
   - 导出 `PracticeService` 及相关 DTO；
8. `backend/tests/unit/core/algorithms/test_practice_algorithm.py` (New):
   - 纯函数打散核单元测试：单知识点、多知识点、极端偏斜数据、空输入与打散边界值，100% 分支覆盖；
9. `backend/tests/unit/repositories/test_practice_repo.py` (New):
   - 仓储层单元测试：涵盖练习增删改查、断网逐题保存与恢复、未作答统计、跨租户水平越权 100% 拦截；
10. `backend/tests/unit/services/test_practice_service.py` (New):
    - 服务层全流程单元测试：三种组卷模式抽题、题库不足 40012 阻断、快照解耦验证、状态机流转合法性校验、交卷强幂等并发冲突与重放、队列任务投递与脱敏日志校验。

---

## 2. 伴随式分步实施与验证 (Step-by-Step Implementation Loops)

### Step 1: 异常类型注册与纯函数出题打散算法核 (Errors & Algorithm Core)
* **操作目标**:
  1. 在 `backend/app/core/errors.py` 增加 `PracticeNotFoundError`, `PracticeStatusError`, `PracticeEmptyQuestionsError`；
  2. 编写 `backend/tests/unit/core/algorithms/test_practice_algorithm.py` 覆盖打散算法全部边界；
  3. 在 `backend/app/core/algorithms/practice.py` 实现 `scatter_adjacent_knowledge_questions` 纯函数；
  4. 在 `backend/app/core/algorithms/__init__.py` 导出。
* **涉及文件**:
  - `backend/app/core/errors.py`
  - `backend/app/core/algorithms/practice.py`
  - `backend/app/core/algorithms/__init__.py`
  - `backend/tests/unit/core/algorithms/test_practice_algorithm.py`
* **局部验证命令**:
  ```bash
  cd backend && pytest tests/unit/core/algorithms/test_practice_algorithm.py -v --cov=app.core.algorithms.practice --cov-branch
  ```
* **预期判据**: 纯函数打散测试 100% 绿灯，行覆盖率 $\ge 95\%$，分支覆盖率 $\ge 90\%$。

---

### Step 2: 练习与答卷数据仓储层实现与多租户测试 (PracticeRepository & Tenant Isolation)
* **操作目标**:
  1. 编写 `backend/tests/unit/repositories/test_practice_repo.py` 测试用例（练习创建、按 ID 获取、列表分页查询、来源报告合并查询、状态更新、批量创建作答项、单题保存与原子 Upsert、未答题计数、跨租户越权隔离阻断）；
  2. 在 `backend/app/repositories/practice.py` 中实现 `PracticeRepository`，所有 SQL 操作强制绑定 `user_id` 条件；
  3. 在 `backend/app/repositories/__init__.py` 导出。
* **涉及文件**:
  - `backend/app/repositories/practice.py`
  - `backend/app/repositories/__init__.py`
  - `backend/tests/unit/repositories/test_practice_repo.py`
* **局部验证命令**:
  ```bash
  cd backend && pytest tests/unit/repositories/test_practice_repo.py -v
  ```
* **预期判据**: 仓储层用例全部通过，多租户水平越权拦截率 100%，耗时 < 1s。

---

### Step 3: PracticeService 服务编排、幂等交卷与异步调度集成 (PracticeService Orchestration)
* **操作目标**:
  1. 在 `backend/app/services/practice.py` 中定义 DTO（`CreatePracticeOptions`, `SaveAnswerDTO`, `SubmitPracticeDTO`, `PracticeSubmissionResult` 等）并实现 `PracticeService`：
     - 组卷逻辑：SEQUENTIAL、RANDOM、WEAK_POINTS 模式，题库不足抛出 `PracticeEmptyQuestionsError` (40012)；
     - 检查同来源未开始练习并复用（FR-58）；
     - 调用打散核完成同知识点不相邻排序（FR-31），校验快照完整性并原子持久化；
     - 逐题作答保存（`save_answer`）：状态流转与单题更新，支持耗时累加；
     - 交卷调度（`submit_practice`）：基于 `IdempotencyProtocol` 原子锁拦截并发，校验未作答确认（FR-36），持久化交卷凭据，向 `QueueProtocol` 投递 `grading_jobs` 任务，缓存响应快照；
     - 输出结构化脱敏 8 要素日志；
  2. 在 `backend/app/services/__init__.py` 导出；
  3. 编写 `backend/tests/unit/services/test_practice_service.py` 验证全流程业务逻辑。
* **涉及文件**:
  - `backend/app/services/practice.py`
  - `backend/app/services/__init__.py`
  - `backend/tests/unit/services/test_practice_service.py`
* **局部验证命令**:
  ```bash
  cd backend && pytest tests/unit/services/test_practice_service.py -v
  ```
* **预期判据**: 服务层用例全部通过，交卷幂等拦截与任务入队验证无误，日志严格脱敏。

---

## 3. 全局质量门禁核验 (Global Quality Gate)
* **代码风格与静态检查**:
  ```bash
  cd backend && ruff format --check . && ruff check .
  ```
* **类型与架构分层校验**:
  ```bash
  cd backend && mypy app && python3 ../tooling/check_layers.py --root app
  ```
* **全量单元测试与覆盖率门禁**:
  ```bash
  cd backend && pytest tests --cov=app --cov-branch --cov-fail-under=80
  ```
* **工件合规检查**:
  ```bash
  python3 tooling/check_sdlc_integrity.py
  ```
* **核验结果**: 所有命令退出码必须为 0，零新增 warning，分层依赖 0 违规。

---

## 4. 实施偏差记录 (Deviations Log)
* [无偏差 / 严格遵循 spec.md 与已有模型契约落地]

---

## 5. 阶段准出签批 (Gate 3 Sign-off)
- [ ] 所有分步实施项与验证断言均已就地执行并通过
- [ ] 全局质量门禁（Lint / Type / Regression）全部绿灯
- [ ] 变更文件与 plan.md 清单完全吻合，无越权修改
- **验收结论**: Pending
- **验证人 / 日期**: [待人类确认] / 2026-09-24 12:58
