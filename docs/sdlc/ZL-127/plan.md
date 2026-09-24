# Plan: 练习会话与判题自评 API 路由 - 实施计划

- **关联 Spec**: ZL-127
- **主导实施人**: TechLead (Planner & Research)
- **任务分级**: Tier 2 (单模块特性演进 / 外部接口与协议入口)
- **当前状态**: Draft
- **实施执行模式**: 多 Builder 细粒度原子派发 (遵循单一职责，避免单个 Builder 任务过载)

---

## 1. 任务分发与实施拆解原则

根据系统设计与用户要求，为避免单个 Builder 上下文过载或跨领域混杂修改，本实施计划拆解为 **4 个高度内聚、正交隔离的原子 Milestone**。每个 Milestone 配置独立的委派目标、变更范围、防护底线与验收判据。

```
[Milestone 1: 契约与依赖] -> [Milestone 2: 判题路由] -> [Milestone 3: 练习路由] -> [Milestone 4: 装配与门禁]
  Builder 1 (Schemas)       Builder 2 (Grading API)    Builder 3 (Practice API)   Builder 4 (Integrate & Gate)
```

---

## 2. 变更总文件清单 (Files that change)

### 新增文件清单 (New Files)
1. `backend/app/schemas/practice.py`：练习组卷、作答暂存、交卷强幂等请求与响应 DTO。
2. `backend/app/schemas/grading.py`：主观题自评、申请重判、判题明细与历史记录 DTO。
3. `backend/app/api/deps/practice.py`：FastAPI `get_practice_service` 依赖注入工厂。
4. `backend/app/api/deps/grading.py`：FastAPI `get_grading_service` 依赖注入工厂。
5. `backend/app/api/v1/practices.py`：练习会话全生命周期与交卷强幂等路由端点。
6. `backend/app/api/v1/grading.py`：主观题自评、重判与作答项判题历史路由端点。
7. `backend/tests/unit/schemas/test_practice_schemas.py`：练习 DTO 校验单元测试。
8. `backend/tests/unit/schemas/test_grading_schemas.py`：判题 DTO 校验单元测试。
9. `backend/tests/unit/api/test_practice_router.py`：练习路由控制器单元测试。
10. `backend/tests/unit/api/test_grading_router.py`：判题路由控制器单元测试。
11. `backend/tests/unit/api/test_practice_grading_flow.py`：全链路端到端与多租户越权集成测试。

### 修改文件清单 (Modified Files)
1. `backend/app/schemas/__init__.py`：导出练习与判题相关 DTO 符号。
2. `backend/app/api/deps/__init__.py`：导出服务依赖注入符号。
3. `backend/app/services/grading.py`：扩展只读方法 `get_attempt_grading_detail`（防跨层违规）。
4. `backend/app/api/v1/__init__.py`：汇聚挂载 `practices.router` 与 `grading.router`。

---

## 3. 四大原子 Milestone 详细实施方案 (The 4 Pillars)

### Milestone 1: Pydantic DTO 契约与依赖注入装配 (Schemas & Service Deps)
- **目标与职责**: 确立全部输入输出数据模型与类型安全约束，提供 FastAPI 服务依赖注入桩，完成独立单元测试。
- **建议委派角色**: `builder-1`

#### 1. Files that change
- `backend/app/schemas/practice.py` (New)
- `backend/app/schemas/grading.py` (New)
- `backend/app/schemas/__init__.py` (Modify)
- `backend/app/api/deps/practice.py` (New)
- `backend/app/api/deps/grading.py` (New)
- `backend/app/api/deps/__init__.py` (Modify)
- `backend/tests/unit/schemas/test_practice_schemas.py` (New)
- `backend/tests/unit/schemas/test_grading_schemas.py` (New)

#### 2. Order of work
1. **测试先行 (Fail-repro First)**:
   - 编写 `test_practice_schemas.py` 与 `test_grading_schemas.py`，断言字段约束（题量 1~50、难度 1~5、枚举值验证、分值上限非负等）与序列化；
   - 运行测试确认因未实现而红灯（Fail）。
2. **编写练习契约 (`app/schemas/practice.py`)**:
   - 实现 `PracticeCreateRequest`（包含 `material_id`, `knowledge_point_ids`, `question_count`, `mode` 等）；
   - 实现 `PracticeCreateResponse`、`PracticeListItemResponse`、`PracticeListResponse`；
   - 实现 `QuestionSnapshotDTO`、`AttemptItemDetailResponse`、`PracticeDetailResponse`；
   - 实现 `PracticeSaveAnswerRequest`、`PracticeSaveAnswerResponse`；
   - 实现 `PracticeStatusActionResponse`、`PracticeSubmitRequest`、`PracticeSubmitResponse`；
   - 启用 Pydantic v2 `ConfigDict(from_attributes=True)`。
3. **编写判题契约 (`app/schemas/grading.py`)**:
   - 实现 `SelfEvaluateRequest`（包含 `attempt_item_id`, `score`, `is_correct`, `feedback`）；
   - 实现 `RegradeAttemptRequest`（包含 `attempt_item_id`）；
   - 实现 `GradingRecordResponse` 与 `AttemptGradingDetailResponse`。
4. **编写依赖注入项 (`app/api/deps/practice.py` & `grading.py`)**:
   - 定义 `get_practice_service()` 与 `get_grading_service()` 依赖函数，遵循统一的未装配抛错提示模式；
   - 更新 `app/schemas/__init__.py` 与 `app/api/deps/__init__.py` 的 `__all__` 导出。
5. **单测转绿与通过断言**:
   - 运行测试确保用例全部通过。

#### 3. Risks & Defenses
- **命名红线**: 严格遵守 8 个白名单缩写（`api`, `id`, `url`, `ocr`, `llm`, `db`, `config`, `env`），严禁使用 `req`, `resp`, `dto`, `usr`；
- **分层安全**: 依赖模块严禁导入 `app.repositories`，保持纯 Service 依赖桩；
- **脱敏合规**: DTO 中 `QuestionSnapshotDTO` 必须严格对齐 6 要素，不额外泄露底层不必要字段。

#### 4. Proof
- 单元测试验证：
  ```bash
  cd backend && pytest tests/unit/schemas/test_practice_schemas.py tests/unit/schemas/test_grading_schemas.py -v
  ```
- 架构分层校验：
  ```bash
  python3 tooling/check_layers.py --root backend/app
  ```
- 静态与类型检查：
  ```bash
  cd backend && ruff check app/schemas app/api/deps && mypy app/schemas app/api/deps
  ```

---

### Milestone 2: 判题自评、重判与作答判题记录查询 API 路由 (Grading Domain API)
- **目标与职责**: 在 `GradingService` 补充只读查询透传支持（杜绝跨层导入仓库），实现判题领域 RESTful 端点与错误码映射，完成控制器单测。
- **建议委派角色**: `builder-2`

#### 1. Files that change
- `backend/app/services/grading.py` (Modify)
- `backend/app/api/v1/grading.py` (New)
- `backend/tests/unit/api/test_grading_router.py` (New)

#### 2. Order of work
1. **测试先行 (Fail-repro First)**:
   - 编写 `test_grading_router.py`，定义模拟客户端与 Mock Service；
   - 预设测试场景：自评成功、客观题禁止自评(40014)、题目不存在(40013)、重判成功、未作答禁止重判(40014)、LLM服务异常(40015)、查询历史记录(200)；
   - 运行测试确认红灯（Fail）。
2. **Service 补充只读透传方法 (`app/services/grading.py`)**:
   - 添加 `get_attempt_grading_detail(user_id: uuid.UUID, attempt_item_id: uuid.UUID)` 方法；
   - 校验作答项归属，若不存在抛出 `AttemptItemNotFoundError`(40013)；
   - 调用 `grading_repo.get_final_record_for_attempt` 与 `grading_repo.list_records_by_attempt_item`，返回作答项、最新生效记录与历史记录；
   - 保持只读事务，严禁路由跨层操作。
3. **实现判题 API 路由 (`app/api/v1/grading.py`)**:
   - 创建 `router = APIRouter(tags=["grading"])`；
   - `POST /grading/self-evaluate`：校验用户、调用 `grading_service.self_evaluate_attempt`、返回 `GradingRecordResponse`；
   - `POST /grading/regrade`：校验用户、调用 `grading_service.regrade_attempt`、返回 `GradingRecordResponse`；
   - `GET /attempts/{attempt_item_id}/grading`：校验用户、调用 `grading_service.get_attempt_grading_detail`、返回 `AttemptGradingDetailResponse`；
   - 路由函数仅做 1 行委托，不编写额外业务分支。
4. **单测转绿与通过断言**:
   - 运行 `test_grading_router.py`，断言 HTTP 状态码、JSON 结构和错误码转换。

#### 3. Risks & Defenses
- **架构单向铁律**: 严禁在 `grading.py` 中直接导入 `GradingRepository` 或执行 SQL 查询；
- **租户安全与水平越权**: 100% 端点接入 `Depends(get_current_user)`，且 `user.id` 强制传给 Service；
- **脱敏日志**: 禁止将评语原文或作答记录打印在日志明文中，日志仅包含 `attempt_item_id`, `score`, `duration_ms`。

#### 4. Proof
- 单元测试验证：
  ```bash
  cd backend && pytest tests/unit/api/test_grading_router.py -v
  ```
- 架构分层校验：
  ```bash
  python3 tooling/check_layers.py --root backend/app
  ```
- 静态与代码规范检查：
  ```bash
  cd backend && ruff check app/api/v1/grading.py app/services/grading.py && mypy app/api/v1/grading.py
  ```

---

### Milestone 3: 练习会话全生命周期与交卷强幂等调度 API 路由 (Practice Domain API)
- **目标与职责**: 实现练习会话的创建、分页列表、详情与题目快照、作答实时暂存、暂停/恢复、强幂等交卷端点与异常阻断，完成控制器单测。
- **建议委派角色**: `builder-3`

#### 1. Files that change
- `backend/app/api/v1/practices.py` (New)
- `backend/tests/unit/api/test_practice_router.py` (New)

#### 2. Order of work
1. **测试先行 (Fail-repro First)**:
   - 编写 `test_practice_router.py`，覆盖全部 7 个练习端点；
   - 覆盖正常流：组卷成功(201)、列表分页(200)、详情快照(200)、暂存作答(200)、暂停(200)、恢复(200)、交卷成功(200)；
   - 覆盖异常流：题库不足(40012)、练习未找到(40010)、已完成禁止修改(40011)、非法状态流转(40011)、缺少幂等Header(400/30018)、并发交卷冲突(409/30017)；
   - 运行测试确认红灯（Fail）。
2. **实现练习 API 路由 (`app/api/v1/practices.py`)**:
   - 创建 `router = APIRouter(prefix="/practices", tags=["practices"])`；
   - `POST /practices`：组装 `CreatePracticeOptions`，调用 `practice_service.create_practice`，映射 201；
   - `GET /practices`：调用 `practice_service.list_practices`，返回分页列表；
   - `GET /practices/{id}`：调用 `practice_service.get_practice`，映射包含题目快照的 `PracticeDetailResponse`；
   - `PUT /practices/{id}/answers`：组装 `SaveAnswerDTO`，调用 `practice_service.save_answer`，映射 200；
   - `POST /practices/{id}/pause` 与 `POST /practices/{id}/resume`：分别调用 `pause_practice` 与 `resume_practice`；
   - `POST /practices/{id}/submit`：
     - 从 Header 提取 `Idempotency-Key`（缺失或为空抛出 `IdempotencyKeyInvalidError` / 30018）；
     - 组装 `SubmitPracticeDTO`，调用 `practice_service.submit_practice`；
     - 映射 `PracticeSubmitResponse` 返回。
3. **单测转绿与通过断言**:
   - 运行 `test_practice_router.py`，全绿通过。

#### 3. Risks & Defenses
- **强幂等并发防御**: 必须显式通过 `Header(..., alias="Idempotency-Key")` 获取幂等键，捕获并正确响应 409 状态码；
- **极速响应与低延迟**: 作答暂存端点仅做单题透传，路由层不得进行额外重度计算；
- **绝密脱敏红线**: 严禁在日志中记录题干、选项与 `user_answer` 作答原文，仅记录作答长度。

#### 4. Proof
- 单元测试验证：
  ```bash
  cd backend && pytest tests/unit/api/test_practice_router.py -v
  ```
- 架构分层校验：
  ```bash
  python3 tooling/check_layers.py --root backend/app
  ```
- 静态与代码规范检查：
  ```bash
  cd backend && ruff check app/api/v1/practices.py && mypy app/api/v1/practices.py
  ```

---

### Milestone 4: 全局路由装配、多租户全链路集成测试与门禁全绿验收 (Wiring & Quality Gates)
- **目标与职责**: 在 `app/api/v1/__init__.py` 汇聚挂载路由，编写跨模块全链路端到端流转测试与多租户越权攻击验证，通过全套工程质量门禁。
- **建议委派角色**: `builder-4`

#### 1. Files that change
- `backend/app/api/v1/__init__.py` (Modify)
- `backend/tests/unit/api/test_practice_grading_flow.py` (New)

#### 2. Order of work
1. **全局路由汇聚挂载 (`app/api/v1/__init__.py`)**:
   - 引入 `practices_router` (`app/api/v1/practices.py`) 与 `grading_router` (`app/api/v1/grading.py`)；
   - 通过 `api_v1_router.include_router(...)` 挂载；
   - 更新 `__all__` 导出列表。
2. **编写跨模块全链路集成测试 (`test_practice_grading_flow.py`)**:
   - 端到端流转：创建练习 -> 逐题保存作答 -> 暂停与恢复 -> 提交交卷 -> 题目判题历史查询 -> 主观题自评 -> 申请异步重判；
   - 租户越权攻击防御：用户 B 携带合法 Token，试图访问/修改用户 A 的练习、作答项或判题记录，断言 100% 阻断 (404/403)；
   - 快照回放验证：携带相同 `Idempotency-Key` 再次提交，断言直接回放首次交卷响应，无副作用。
3. **全量工程质量门禁检查**:
   - 执行分层导入防违规自动化校验；
   - 执行 Ruff 格式与静态扫描、Mypy 严格类型检查、Bandit 安全隐患排查；
   - 执行全量单元测试与覆盖率门禁（要求覆盖率 >= 80%）。

#### 3. Risks & Defenses
- **URL 路径与命名空间冲突**: 严格核对路径前缀：`/api/v1/practices`、`/api/v1/grading`、`/api/v1/attempts`，不得与既有路由冲突；
- **网络隔离红线**: 确保所有测试均在本地虚拟环境中运行，无真实外网流量或云端配额消耗。

#### 4. Proof
- 门禁合规检查：
  ```bash
  python3 tooling/check_sdlc_integrity.py
  ```
- 分层依赖检查：
  ```bash
  python3 tooling/check_layers.py --root backend/app
  ```
- 后端代码质量全量基线（必须全绿）：
  ```bash
  cd backend &&   ruff format --check . &&   ruff check . &&   mypy app &&   bandit -r app -ll &&   pytest tests/unit --cov=app/api/v1 --cov=app/schemas --cov-branch --cov-fail-under=80
  ```

---

## 4. 实施偏差记录 (Deviations Log)

*若在具体实施过程中发现必须调整接口或关联文件，在此记录并在当前 Commit 中同步更新：*
* [2026-09-24]: 在 `app/services/grading.py` 中补充只读方法 `get_attempt_grading_detail`，以彻底规避路由层跨层直接导入 `GradingRepository` 违反架构铁律的风险。

---

## 5. 阶段准出签批 (Gate 3 Sign-off)
- [x] 4 个 Milestone 的职责与文件拆解清晰正交
- [x] 每个 Milestone 均配对具体的 Fail-repro 先行测试与独立验收命令
- [x] 分层依赖隔离、租户鉴权透传与绝密脱敏红线具备明确防御
- **验收结论**: Approved
- **验证人 / 日期**: TechLead / 2026-09-24
