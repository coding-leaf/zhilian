# Plan: 知识点抽取建树与质检重抽服务 - 实施计划

- **关联 Spec**: ZL-120
- **实施执行人 / Agent**: Dev
- **当前状态**: Draft / Approved / In-Execution / Completed

---

## 1. 变更文件清单 (Files that change)

1. `backend/app/core/errors.py` (Modify):
   - 登记 40005 (`KnowledgePointQualityError`), 40006 (`KnowledgeExtractionRetryExceededError`), 40007 (`KnowledgeNotFoundError`)；
2. `backend/app/repositories/knowledge.py` (New):
   - 实现 `KnowledgeRepository`，提供严格携带 `user_id` 过滤的知识点树与切片双向溯源关联 CRUD；
3. `backend/app/services/knowledge.py` (New):
   - 实现 `KnowledgeService`，编排切片批次分发、LLM 结构化抽取、向量余弦去重 (> 0.92)、纯函数质检核集成、最多 2 次重抽熔断与降级低可信度标记、知识树拓扑组装与落库；
4. `backend/app/repositories/__init__.py` (Modify):
   - 导出 `KnowledgeRepository`；
5. `backend/app/services/__init__.py` (Modify):
   - 导出 `KnowledgeService`；
6. `backend/tests/unit/repositories/test_knowledge_repo.py` (New):
   - 仓储层多租户隔离、CRUD 及双向溯源单测；
7. `backend/tests/unit/services/test_knowledge_service.py` (New):
   - 编排全流程单测：正常抽取建树、语义去重合并、质检未通过重抽成功、2 次重抽超限熔断降级标记 `is_low_confidence=True`、多租户越权拦截、空切片防御。

---

## 2. 伴随式分步实施与验证 (Step-by-Step Implementation Loops)

### Step 1: 异常类型定义与仓储层实现与测试 (Repository & Multi-Tenant Isolation)
* **操作目标**:
  1. 在 `backend/app/core/errors.py` 增加知识点相关异常；
  2. 编写 `backend/tests/unit/repositories/test_knowledge_repo.py` 测试桩（覆盖创建、根据版本读取、根据 ID 读取、双向关联查询、跨租户越权防御）；
  3. 实现 `backend/app/repositories/knowledge.py` 及其在 `__init__.py` 的导出。
* **涉及文件**:
  - `backend/app/core/errors.py`
  - `backend/app/repositories/knowledge.py`
  - `backend/app/repositories/__init__.py`
  - `backend/tests/unit/repositories/test_knowledge_repo.py`
* **局部验证命令**:
  ```bash
  cd backend && pytest tests/unit/repositories/test_knowledge_repo.py -v
  ```
* **预期判据**: 仓储层所有用例 100% 绿灯，多租户越权拦截断言生效，测试耗时 < 1s。

---

### Step 2: 纯函数计算核与辅助函数解耦与测试 (Deduplication & Tree Assembly)
* **操作目标**:
  1. 在 `backend/app/services/knowledge.py` 中拆解并实现纯函数模块：
     - `deduplicate_knowledge_items`: 针对候选知识点，依据向量余弦相似度（> 0.92）执行语义去重合并与切片溯源汇总；
     - `build_knowledge_hierarchy`: 将抽取的临时标识节点组装为带有 `parent_id`、`level` 的持久化实体，处理孤儿节点自愈与层级溢出防御；
  2. 针对纯函数编写单元测试，验证 $V(G) \le 8$ 与高覆盖率。
* **涉及文件**:
  - `backend/app/services/knowledge.py`
  - `backend/tests/unit/services/test_knowledge_service.py`
* **局部验证命令**:
  ```bash
  cd backend && pytest tests/unit/services/test_knowledge_service.py -k "test_deduplicate or test_hierarchy" -v
  ```
* **预期判据**: 边界用例（单节点、完全重复、环形引用、深度超限）全部绿灯。

---

### Step 3: KnowledgeService 业务编排全流程与质检重抽熔断 (Service Orchestration & Quality Gate)
* **操作目标**:
  1. 实现 `KnowledgeService.extract_and_build_knowledge_tree`：
     - 校验 `MaterialRepository` 切片数据；
     - 切片分批（默认 40，重抽 20）；
     - AgentGraph / LLMProtocol 结构化抽取调用；
     - 纯函数 `verify_knowledge_points` 门禁质检；
     - 自适应 Feedback 与最多 2 次重抽控制；
     - 熔断降级标记 `is_low_confidence=True`；
     - 事务内清理与持久化；
     - 8 要素结构化日志记录；
  2. 在 `backend/tests/unit/services/test_knowledge_service.py` 中补充完整端到端编排场景用例。
* **涉及文件**:
  - `backend/app/services/knowledge.py`
  - `backend/app/services/__init__.py`
  - `backend/tests/unit/services/test_knowledge_service.py`
* **局部验证命令**:
  ```bash
  cd backend && pytest tests/unit/services/test_knowledge_service.py -v --cov=app/services/knowledge --cov-report=term-missing
  ```
* **预期判据**: 全部测试通过，`app/services/knowledge.py` 行覆盖率 $\ge 85\%$。

---

## 3. 全局质量门禁核验 (Global Quality Gate)

* **代码风格与静态检查**:
  ```bash
  cd backend && ruff format --check . && ruff check .
  ```
* **类型与契约安全校验**:
  ```bash
  cd backend && mypy app/repositories/knowledge.py app/services/knowledge.py
  ```
* **分层依赖架构校验**:
  ```bash
  python3 tooling/check_layers.py --root backend/app
  ```
* **全量单测回归与覆盖率门禁**:
  ```bash
  cd backend && pytest tests/unit/repositories/test_knowledge_repo.py tests/unit/services/test_knowledge_service.py --cov=app/services/knowledge --cov=app/repositories/knowledge --cov-fail-under=85
  ```
* **SDLC 工件完整性与门禁合规检查**:
  ```bash
  python3 tooling/check_sdlc_integrity.py
  ```
* **核验结果预期**:
  - Ruff 零格式错误、零静态警告；
  - Mypy 类型检查严格通过；
  - 架构分层校验零违规导入；
  - 知识点仓储与服务覆盖率均 $\ge 85\%$；
  - SDLC 工件检查无占位符遗留。

---

## 4. 实施偏差记录 (Deviations Log)
* [暂无偏差 / 严格遵循方案架构规划] (Gate 3 Sign-off)
- [ ] 所有分步实施项与验证断言均已就地执行并通过
- [ ] 全局质量门禁（Lint / Type / Regression）全部绿灯
- [ ] 变更文件与 plan.md 清单完全吻合，无越权修改
- **验收结论**: Pending
- **验证人 / 日期**: [待人类确认] / 2026-09-24 10:41
