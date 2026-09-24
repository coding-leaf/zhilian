# Plan: 知识点树与题目管理 API 路由 - 实施计划

- **关联 Spec**: ZL-126
- **实施执行人 / Agent**: Dev
- **当前状态**: Draft / Approved / In-Execution / Completed

---

## 1. 变更文件清单 (Files that change)

### 新增文件 (New)
1. `backend/app/schemas/knowledge.py`: 知识点树形拓扑、详情、切片溯源及抽取请求响应 DTO
2. `backend/app/schemas/question.py`: 题目生成请求响应、题目详情、多条件筛选列表、编辑更新、软删除、质检记录及审计日志 DTO
3. `backend/app/api/deps/knowledge.py`: FastAPI 依赖注入 `get_knowledge_service`
4. `backend/app/api/deps/question.py`: FastAPI 依赖注入 `get_question_service`
5. `backend/app/api/v1/knowledge.py`: 知识点与溯源相关路由
6. `backend/app/api/v1/questions.py`: 题目生成、检索、审核与质检拦截记录路由
7. `backend/tests/unit/api/test_knowledge_router.py`: 知识点路由全量单测
8. `backend/tests/unit/api/test_question_router.py`: 题目路由全量单测

### 修改文件 (Modify)
1. `backend/app/services/knowledge.py`: 暴露单个知识点详情、双向溯源切片列表查询代理方法，规避路由层跨层导入
2. `backend/app/services/question.py`: 暴露题目列表多条件筛选、修改审计日志查询、质检拦截记录查询代理方法
3. `backend/app/api/v1/__init__.py`: 挂载 `knowledge_router` 与 `questions_router`
4. `backend/app/schemas/__init__.py`: 导出新增知识点与题目相关 DTO 模型

---

## 2. 伴随式分步实施与验证 (Step-by-Step Implementation Loops)

### Milestone 1: 知识点与溯源 API 落地 (Knowledge Schemas, Deps, Service Methods & Router)
* **Step 1.1 (Service 补充)**:
  - 操作目标: 在 `KnowledgeService` 中补充 `get_knowledge_point(knowledge_point_id, user_id)`、`get_snippets_by_point(knowledge_point_id, user_id)`、`get_points_by_snippet(snippet_id, user_id)`。
  - 涉及文件: `backend/app/services/knowledge.py`
  - 局部验证命令: `cd backend && pytest tests/unit/services/test_knowledge_service.py -k "knowledge"`
  - 预期判据: 现有测试与新方法单元测试全部通过。
* **Step 1.2 (DTO 与依赖注入)**:
  - 操作目标: 创建 `app/schemas/knowledge.py`，定义 `KnowledgeTreeNode`、`KnowledgeTreeResponse`、`KnowledgePointDetailResponse`、`KnowledgeSnippetsResponse`、`SnippetKnowledgePointsResponse`、`KnowledgeExtractRequest`、`KnowledgeExtractResponse`；创建 `app/api/deps/knowledge.py`。
  - 涉及文件: `backend/app/schemas/knowledge.py`, `backend/app/api/deps/knowledge.py`, `backend/app/schemas/__init__.py`
  - 局部验证命令: `cd backend && python3 -c "import app.schemas.knowledge; import app.api.deps.knowledge"`
  - 预期判据: 模块成功导入无语法及导入错误。
* **Step 1.3 (路由与单元测试)**:
  - 操作目标: 实现 `app/api/v1/knowledge.py`，挂载知识树获取、知识点详情、双向切片溯源、抽取触发路由；编写 `tests/unit/api/test_knowledge_router.py`，覆盖正常响应、404、401、越权阻断。
  - 涉及文件: `backend/app/api/v1/knowledge.py`, `backend/app/api/v1/__init__.py`, `backend/tests/unit/api/test_knowledge_router.py`
  - 局部验证命令: `cd backend && pytest tests/unit/api/test_knowledge_router.py -v`
  - 预期判据: 知识点相关 API 测试 100% 绿灯。

### Milestone 2: 题目管理与质检记录 API 落地 (Question Schemas, Deps, Service Methods & Router)
* **Step 2.1 (Service 补充)**:
  - 操作目标: 在 `QuestionService` 中补充 `list_questions(...)`（支持多条件筛选分页）、`list_audit_logs(question_id, user_id)`、`list_quality_checks_by_material(material_id, user_id)`。
  - 涉及文件: `backend/app/services/question.py`
  - 局部验证命令: `cd backend && pytest tests/unit/services/test_question_service.py -k "question"`
  - 预期判据: 题目服务单测全部通过。
* **Step 2.2 (DTO 与依赖注入)**:
  - 操作目标: 创建 `app/schemas/question.py`，定义生成请求出参、题目详情、多条件列表筛选、题目更新修改、软删除、质检拦截记录及审计日志 DTO；创建 `app/api/deps/question.py`。
  - 涉及文件: `backend/app/schemas/question.py`, `backend/app/api/deps/question.py`, `backend/app/schemas/__init__.py`
  - 局部验证命令: `cd backend && python3 -c "import app.schemas.question; import app.api.deps.question"`
  - 预期判据: 模块成功导入无语法及导入错误。
* **Step 2.3 (路由与单元测试)**:
  - 操作目标: 实现 `app/api/v1/questions.py`，挂载生成、详情、筛选、修改、删除、审计日志、质检拦截记录路由；编写 `tests/unit/api/test_question_router.py`，重点覆盖 40003 切片门禁阻断、修改痕迹审计留痕、越权访问 404/20002、参数校验 422。
  - 涉及文件: `backend/app/api/v1/questions.py`, `backend/app/api/v1/__init__.py`, `backend/tests/unit/api/test_question_router.py`
  - 局部验证命令: `cd backend && pytest tests/unit/api/test_question_router.py -v`
  - 预期判据: 题目相关 API 测试 100% 绿灯。

### Milestone 3: 端到端分层校验与全局门禁验证 (Quality Gates Verification)
* **Step 3.1 (架构分层单向依赖验证)**:
  - 操作目标: 执行 `tooling/check_layers.py`，确保 `app/api/v1/` 绝无 `app.repositories` 导入。
  - 涉及文件: 全局 backend/app
  - 局部验证命令: `python3 tooling/check_layers.py --root backend/app`
  - 预期判据: 0 违规导入。
* **Step 3.2 (API 单元测试套件全量回归)**:
  - 操作目标: 运行所有 API 单元测试。
  - 涉及文件: `backend/tests/unit/api/`
  - 局部验证命令: `cd backend && pytest tests/unit/api -v`
  - 预期判据: 全部测试通过，退出码 0。
* **Step 3.3 (代码风格与类型安全扫描)**:
  - 操作目标: 运行 ruff 格式化与 lint 校验。
  - 涉及文件: 全量修改与新增代码
  - 局部验证命令: `cd backend && ruff check app tests && ruff format --check app tests`
  - 预期判据: 0 错误，0 格式违规。

---

## 3. 全局质量门禁核验 (Global Quality Gate)
* **代码风格与静态检查**: `cd backend && ruff check app tests && ruff format --check app tests` 0 报错；
* **分层依赖规范校验**: `python3 tooling/check_layers.py --root backend/app` 0 违规；
* **测试套件回归**: `cd backend && pytest tests/unit/api tests/unit/services -v` 100% 通过；
* **核验结果**: 所有静态检查通过，零新增警告；全量相关测试用例 100% 绿灯。

---

## 4. 实施偏差记录 (Deviations Log)
* [无偏差 / 严格遵循 spec.md 技术契约实施]

---

## 5. 阶段准出签批 (Gate 3 Sign-off)
- [ ] 所有分步实施项与验证断言均已就地执行并通过
- [ ] 全局质量门禁（Lint / Type / Regression）全部绿灯
- [ ] 变更文件与 plan.md 清单完全吻合，无越权修改
- **验收结论**: Pending
- **验证人 / 日期**: [待人类确认] / 2026-09-24 20:11
