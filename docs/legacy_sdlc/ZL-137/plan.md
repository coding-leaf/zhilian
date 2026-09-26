# Plan: P0 端到端全链路闭环集成与质量门禁审计 - 实施计划

- **关联 Spec**: ZL-137
- **实施执行人 / Agent**: Dev
- **当前状态**: Draft / Approved / In-Execution / Completed

---

## 1. 变更文件清单 (Files that change)

### 1.1 新增文件清单 (New Files)
1. `backend/tests/integration/__init__.py`：集成测试套件包声明模块；
2. `backend/tests/integration/test_p0_full_chain_e2e.py`：P0 端到端全链路闭环集成与 16 维多租户越权阻断测试套件（含纯内存数据库、ASGI 客户端、真实纯函数计算核装配、8 步正向生命周期与 AT-01 ~ AT-16 攻击拦截）。

### 1.2 修改文件清单 (Modified Files)
1. `docs/sdlc/ZL-137/plan.md`：根据技术契约与架构基线起草并细化的 4 支柱实施计划工件；
2. **严禁修改项**：严禁修改任何生产业务逻辑代码（`backend/app/`）、已冻结 API 契约、数据库 Schema 或前端生产代码。

---

## 2. 伴随式分步实施与验证 (Step-by-Step Implementation Loops)

### Step 1: 端到端集成测试骨架与安全隔离装配 (Scaffold & Isolation Fixtures)
* **操作目标**: 
  - 创建 `backend/tests/integration/__init__.py` 与 `backend/tests/integration/test_p0_full_chain_e2e.py`；
  - 装配纯内存 SQLite 数据库（`sqlite:///:memory:`）并生成全量实体表（`Base.metadata.create_all`）；
  - 实例化纯内存适配器（`MemoryStorageAdapter`, `FakeOCRAdapter`, `FakeLLMAdapter`, `FakeEmbeddingAdapter`, `MemoryQueueAdapter`, `MemoryIdempotencyAdapter`）；
  - 构造包含所有真实领域服务（`AuthService`, `MaterialService`, `KnowledgeService`, `QuestionService`, `PracticeService`, `GradingService`, `DiagnosisService`）并直连 5 块真实纯函数计算核的依赖注入体系；
  - 构建挂载 `api_v1_router` 与全局 `AppError` 处理器的测试 FastAPI 应用，并通过 `httpx.AsyncClient(transport=ASGITransport)` 建立 User A 与 User B 独立双会话。
* **涉及文件**:
  - `backend/tests/integration/__init__.py`
  - `backend/tests/integration/test_p0_full_chain_e2e.py`
* **局部验证命令**:
  ```bash
  cd backend && pytest tests/integration/test_p0_full_chain_e2e.py -k "test_e2e_infrastructure_setup" -v
  ```
* **预期判据**: 基础设施与环境装配测试毫秒级通过（Pass），ASGI 传输层通信正常，User A 与 User B 独立租户会话初始化成功，数据库会话与内存适配器完全就绪。

### Step 2: 完整编写 8 步正向端到端全业务链路流转测试 (8-Step Full Business Flow)
* **操作目标**: 
  - 按照 `spec.md` 第 1 节时序拓扑，编写真实业务闭环端到端流转测试：
    1. **步骤 1 (鉴权)**: 调用 `POST /api/v1/auth/login` 签发 User A 访问与刷新双令牌（`token_version=1`）；
    2. **步骤 2 (资料与切片)**: 调用 `POST /api/v1/materials/upload` 上传教材 PDF，触发 `POST /api/v1/materials/{id}/parse` 执行 `split_material_into_snippets` 真实物理切分，调用 `POST /api/v1/materials/{id}/reshoot` 验证就地重拍；
    3. **步骤 3 (知识点与建树)**: 调用 `POST /api/v1/materials/{id}/knowledge/extract` 触发 `verify_knowledge_points` 4 条件决策表质检并生成知识树，调用 `GET /api/v1/materials/{id}/knowledge-tree` 验证树形拓扑与切片双向溯源；
    4. **步骤 4 (题目与编辑)**: 调用 `POST /api/v1/questions/generate` 触发 `filter_qualified_questions` 题目质检门禁（排重、无冲突），调用 `PUT /api/v1/questions/{id}` 微调题干并断言生成 `QuestionAuditLog`；
    5. **步骤 5 (练习与草稿)**: 调用 `POST /api/v1/practices` 智能打散组卷并冻结 6 要素题目快照，调用 `PUT /api/v1/practices/{id}/answers` 暂存作答草稿，调用 `pause` 与 `resume` 验证状态切换；
    6. **步骤 6 (幂等交卷与判题)**: 携带 `Idempotency-Key` 调用 `POST /api/v1/practices/{id}/submit`，验证重复交卷强幂等回放，调用 `match_and_grade_answer` 秒判客观题、转 AI 判分主观题；
    7. **步骤 7 (诊断与自评重判)**: 调用 `POST /api/v1/practices/{id}/diagnosis` 触发 `aggregate_mastery_scores` 计算艾宾浩斯掌握度衰减与四级离散状态，调用 `POST /api/v1/grading/self-evaluate` 用户自评覆盖得分，调用 `POST /api/v1/grading/regrade` 发起复核；
    8. **步骤 8 (错题与继续练习)**: 调用 `GET /api/v1/wrong-records` 检索错题，调用 `POST /api/v1/wrong-records/{id}/master` 攻克错题，调用 `POST /api/v1/practices`（`source_type="weakness"`）实现一键继续练习闭环。
* **涉及文件**:
  - `backend/tests/integration/test_p0_full_chain_e2e.py`
* **局部验证命令**:
  ```bash
  cd backend && pytest tests/integration/test_p0_full_chain_e2e.py -k "test_p0_positive_full_chain" -v
  ```
* **预期判据**: 8 步正向端到端链路顺畅流转，HTTP 状态码符合预期（200/201），5 块纯函数算法核真实执行且无异常，全流程在 10 秒内毫秒级完成。

### Step 3: 编写 16 维多租户越权阻断测试矩阵 (16-Dimensional Tenant Isolation Matrix)
* **操作目标**: 
  - 按照 `spec.md` 第 2 节表格规范，编写 AT-01 至 AT-16 全量越权攻击测试用例；
  - 构造攻击者 User B（携带合法 Token B），在 8 步生命周期的各个阶段对 User A 的私有资源发起未授权探测；
  - 断言 AT-01 ~ AT-13 及 AT-16 针对专属资源的操作 100% 被系统拦截并返回 `HTTP 404 Not Found`（错误码 `400xx`）或 `HTTP 403 Forbidden`；
  - 断言 AT-14（掌握度看板）与 AT-15（错题本检索）在 User B 查询时返回 `HTTP 200 OK`，但返回结果完全按 User B 自身租户聚合（数据项为空 `items=[]`，`total=0`），零 User A 数据泄漏；
  - 验证绝密脱敏红线：响应体与异常详情绝对不泄露 User A 的资料内容、题干答案、用户作答及个人隐私。
* **涉及文件**:
  - `backend/tests/integration/test_p0_full_chain_e2e.py`
* **局部验证命令**:
  ```bash
  cd backend && pytest tests/integration/test_p0_full_chain_e2e.py -k "test_tenant_isolation_attack_matrix" -v
  ```
* **预期判据**: 16 维越权攻击用例 100% 拦截并断言成功，跨租户隔离坚不可摧，零越权成功穿透。

### Step 4: 全系统质量基线门禁审计流程执行与对齐 (Full System Quality Gate Audit)
* **操作目标**: 
  - 对齐 `AGENTS.md` 规范，在真实物理终端执行全栈端到端质量门禁检查：
    1. 后端代码格式与规范扫描（`ruff format --check .` 与 `ruff check .`）；
    2. 后端严格静态类型检查（`mypy app`）；
    3. 后端高危安全漏洞扫描（`bandit -r app -ll`）与依赖安全审计（`pip-audit --strict`）；
    4. 架构五层单向导入校验（`python3 ../tooling/check_layers.py --root app`）；
    5. 后端单测与集成测试全量回归及覆盖率统计（`pytest tests --cov=app --cov-branch --cov-fail-under=80`）；
    6. 前端代码规范、单组件行数与格式检查（`pnpm run lint`）；
    7. 前端类型安全检查（`pnpm run type-check`）；
    8. 前端脱机单元测试（`pnpm run test:unit`）；
    9. 微信小程序生产编译打包验证（`pnpm run build:mp-weixin`）；
    10. SDLC 工具链合规检查（`python3 tooling/check_sdlc_integrity.py`）。
* **涉及文件**:
  - `backend/` 目录下全部源码与测试文件；
  - `miniprogram/` 目录下全部源码与测试文件；
  - `tooling/` 工具链脚本。
* **局部验证命令**:
  ```bash
  # 后端全量质量基线
  cd backend && \
  ruff format --check . && \
  ruff check . && \
  mypy app && \
  bandit -r app -ll && \
  pip-audit --strict && \
  python3 ../tooling/check_layers.py --root app && \
  pytest tests/integration/test_p0_full_chain_e2e.py -v && \
  pytest tests --cov=app --cov-branch --cov-fail-under=80

  # 前端全量质量基线
  cd ../miniprogram && \
  pnpm run lint && \
  pnpm run type-check && \
  pnpm run test:unit && \
  pnpm run build:mp-weixin

  # SDLC 流程与工具链合规
  cd .. && \
  python3 -m unittest discover tests && \
  python3 tooling/check_sdlc_integrity.py
  ```
* **预期判据**: 终端全量检查命令退出码均为 0，无任何 warning/error，后端全局覆盖率 $\ge 80\%$、分支覆盖率 $\ge 70\%$，纯函数核覆盖率 $\ge 90\%$，前端编译通过且主包体积 $\le 2\text{MB}$。

---

## 3. 7 维动态风险核验与回滚预案 (Risks & Rollback Plan)

### 3.1 7 维动态风险核验
1. **Files (文件)**: 仅新增集成测试模块 `backend/tests/integration/`，不触动任何已有业务逻辑或既有单测，爆炸半径严格隔离在测试目录内；
2. **API (接口契约)**: 纯只读使用已冻结的 v1 API 契约，测试完全遵从既有请求/响应 Schema，零接口破坏；
3. **Schema (数据模型)**: 测试运行于独立的 SQLite 纯内存库，不产生任何物理表结构变更或持久化脏数据；
4. **Auth (鉴权机制)**: 严格通过系统内置的 JWT 签名与解析逻辑，测试 User A 与 User B 双租户隔离，无安全削弱；
5. **Deps (外部依赖)**: 采用纯内存 Fake/Stub 适配器，零引入外部依赖库，零公网联网；
6. **Migration/Rollback (迁移与回滚)**: 无需数据库数据回滚，若测试套件存在任何缺陷，直接回滚或删除测试文件即可；
7. **Blast Radius (爆炸半径)**: 影响范围仅限于测试运行环境，不影响已部署的微服务或小程序端。

### 3.2 回滚操作指南
若测试实施过程中出现严重阻塞或非预期依赖异常：
1. 删除新增的集成测试文件：`rm -rf backend/tests/integration`；
2. 还原工作树：`git checkout -- docs/sdlc/ZL-137/plan.md`；
3. 执行 `git status` 确认工作区完全干净，系统立即可回退至稳定基线。

---

## 4. 全局质量门禁核验 (Proof & Global Quality Gate)
* **代码风格与静态检查**: `ruff format --check .` 强制行宽 100；`ruff check .` 零警告；
* **类型与契约安全校验**: `mypy app` 开启严格模式，所有函数类型标注 100% 覆盖；`bandit -r app -ll` 高危中危 0 发现；`pip-audit --strict` 零 CVE；
* **架构分层约束**: `python3 tooling/check_layers.py --root backend/app` 零跨层违规导入；
* **测试真实性与覆盖率**: `pytest tests --cov=app --cov-branch --cov-fail-under=80`，全局后端行覆盖率 $\ge 80\%$、分支覆盖率 $\ge 70\%$，算法核覆盖率 $\ge 95\%$，外部网络阻断拦截器有效生效；
* **前端编译与类型**: `vue-tsc --noEmit` 0 错误，ESLint 规范通过，组件行数 $\le 300$ 行，`pnpm run build:mp-weixin` 产物正常且主包体积 $\le 2\text{MB}$；
* **SDLC 工具链完整性**: `python3 tooling/check_sdlc_integrity.py` 退出码 0，工件一致性全绿。

---

## 5. 实施偏差记录 (Deviations Log)
* [无实施偏差 / 严格遵循 spec.md 技术契约实施]

---

## 6. 阶段准出签批 (Gate 3 Sign-off)
- [x] 所有分步实施项与验证断言均已就地执行并通过
- [x] 全局质量门禁（Lint / Type / Regression）全部绿灯
- [x] 变更文件与 plan.md 清单完全吻合，无越权修改
- **验收结论**: Accepted
- **验证人 / 日期**: yezisama / 2026-09-25 17:15
