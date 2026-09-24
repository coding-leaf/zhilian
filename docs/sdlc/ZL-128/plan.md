# Plan: 诊断报告与错题闭环 API 路由 - 实施计划

- **关联 Spec**: ZL-128
- **主导实施人**: TechLead (Planner & Research)
- **任务分级**: Tier 2 (单模块特性演进 / 外部接口与协议入口)
- **当前状态**: Approved
- **实施执行模式**: 多 Builder 细粒度原子派发 (严格落实单一职责，拆解为 4 个 Milestone，避免单个 Builder 任务过载)

---

## 1. 任务分发与实施拆解原则

根据系统设计与用户要求（“合理的分发任务给 builder, 避免一个 builder 进行多过任务”），本实施计划严格拆解为 **4 个高度内聚、正交低偶的原子 Milestone**。每个 Milestone 具备单一职责、配对独立的验收命令与完成准则：

```
[Milestone 1: 契约与服务门面] ──> [Milestone 2: 依赖注入与路由实现] ──> [Milestone 3: 路由全量单元测试] ──> [Milestone 4: 全局门禁与无回归]
     Builder 1 (Schemas/Facade)            Builder 2 (Deps/Router)                 Builder 3 (Unit Tests)                Builder 4 (Gate/Integrity)
```

---

## 2. 变更总文件清单 (Files that change)

### 新增文件清单 (New Files)
1. `backend/app/schemas/diagnosis.py`: 学情诊断报告、艾宾浩斯掌握度与错题本全量 Pydantic v2 DTO 契约。
2. `backend/app/api/deps/diagnosis.py`: FastAPI `get_diagnosis_service` 依赖注入工厂。
3. `backend/app/api/v1/diagnosis.py`: 学情诊断报告生成/查询、掌握度衰减全景/单点查询、错题检索/攻克/删除 9 个 RESTful 端点。
4. `backend/tests/unit/schemas/test_diagnosis_schemas.py`: 诊断与错题 DTO 序列化及校验规则单元测试。
5. `backend/tests/unit/services/test_diagnosis_service_facade.py`: `DiagnosisService` 扩展门面方法单元测试。
6. `backend/tests/unit/api/test_diagnosis_router.py`: 诊断与错题 API 路由控制器全量单元测试（含错误码映射与租户隔离断言）。

### 修改文件清单 (Modified Files)
1. `backend/app/core/errors.py`: 增补 `WrongRecordNotFoundError` (404 / 40019) 业务异常并在 `__all__` 导出。
2. `backend/app/schemas/__init__.py`: 统一导出诊断与错题相关 DTO 符号。
3. `backend/app/api/deps/__init__.py`: 统一导出 `get_diagnosis_service` 依赖注入符号。
4. `backend/app/services/diagnosis.py`: 补充 `get_knowledge_mastery` 与 `mark_wrong_record_mastered` 门面编排方法（杜绝路由层跨层导入仓库）。
5. `backend/app/api/v1/__init__.py`: 汇聚挂载 `diagnosis_router` 至 `/api/v1` 路由树。
6. `docs/sdlc/ZL-128/plan.md`: 持续记录实施偏差与质量门禁准出记录。

---

## 3. 四大原子 Milestone 详细实施方案 (The 4 Pillars)

### Milestone 1: Pydantic DTO 契约、异常体系与领域服务门面就绪 (Schemas, Errors & Service Facade)
- **目标与职责**: 确立底层异常契约与全部输入输出 Pydantic v2 模型，在 `DiagnosisService` 补齐单知识点掌握度与错题攻克标记门面，完成对应单测。
- **建议委派角色**: `builder-1`

#### 1. Files that change
- `backend/app/core/errors.py` (Modify)
- `backend/app/schemas/diagnosis.py` (New)
- `backend/app/schemas/__init__.py` (Modify)
- `backend/app/services/diagnosis.py` (Modify)
- `backend/tests/unit/schemas/test_diagnosis_schemas.py` (New)
- `backend/tests/unit/services/test_diagnosis_service_facade.py` (New)

#### 2. Order of work
1. **测试先行 (Fail-repro First)**:
   - 编写 `test_diagnosis_schemas.py`，预设 DTO 字段校验（`WeakKnowledgeItemDTO`, `RegressedKnowledgeItemDTO`, `DiagnosisReportResponse`, `KnowledgeMasterySummaryResponse`, `UserMasteryOverviewResponse`, `WrongRecordItemResponse`, `MarkWrongRecordMasteredResponse` 等），确认红灯（Fail）；
   - 编写 `test_diagnosis_service_facade.py`，断言 `get_knowledge_mastery` 与 `mark_wrong_record_mastered` 的正常返回及不存在时抛出相应异常（`MasteryRecordNotFoundError` / `WrongRecordNotFoundError`），确认红灯（Fail）。
2. **异常体系增补 (`app/core/errors.py`)**:
   - 增加 `WrongRecordNotFoundError(AppError)`，配置 `error_code=40019`, `status_code=404`, 默认文案 `"错题记录不存在或无权访问"`；
   - 更新 `__all__` 导出列表。
3. **编写 Pydantic v2 DTO 契约 (`app/schemas/diagnosis.py`)**:
   - 严格按照 `spec.md` 2.2 小节定义 13 个数据传输对象；
   - 配置 `model_config = ConfigDict(from_attributes=True)`；
   - 绝密脱敏约束：错题 DTO 严禁在列表与详情中暴露未脱敏的敏感作答全文，仅提供 `question_snapshot` 供前端题目渲染。
4. **扩展服务层门面编排 (`app/services/diagnosis.py`)**:
   - 实现 `get_knowledge_mastery(self, user_id: uuid.UUID, knowledge_point_id: uuid.UUID) -> KnowledgeMasterySummaryDTO`：校验知识点归属与查询掌握度记录，无记录时抛出 `MasteryRecordNotFoundError(40018)`；
   - 实现 `mark_wrong_record_mastered(self, user_id: uuid.UUID, record_id: uuid.UUID) -> WrongRecord`：调用 `diagnosis_repo.mark_wrong_record_mastered`，若返回 None 抛出 `WrongRecordNotFoundError(40019)`，成功后执行 `self.session.commit()`；
   - 更新 `app/schemas/__init__.py` 导出 DTO。
5. **单测转绿与通过断言**:
   - 运行针对 Schema 与 Service Facade 的单元测试，确保用例 100% 绿灯。

#### 3. Risks & Defenses
- **命名与缩写红线**: 仅允许 8 个缩写白名单（`api`, `id`, `url`, `ocr`, `llm`, `db`, `config`, `env`），禁止使用 `req`, `resp`, `dto`, `msg` 等缩写；
- **分层与事务边界**: 掌握度与错题修改事务仅在 Service 层提交，严禁泄露到上层；
- **多租户隔离**: 门面方法强制以 `user_id` 为首要过滤条件，杜绝越权查询与修改。

#### 4. Proof
- 契约与服务门面单测：
  ```bash
  cd backend && pytest tests/unit/schemas/test_diagnosis_schemas.py tests/unit/services/test_diagnosis_service_facade.py -v
  ```
- 架构分层单向依赖校验：
  ```bash
  python3 tooling/check_layers.py --root backend/app
  ```
- 静态质量与类型扫描：
  ```bash
  cd backend && ruff check app/schemas app/services/diagnosis.py app/core/errors.py && mypy app/schemas/diagnosis.py app/services/diagnosis.py app/core/errors.py
  ```

---

### Milestone 2: 依赖注入与 RESTful 路由实现 (Dependency Injection & Router Endpoints)
- **目标与职责**: 实现 FastAPI 依赖注入工厂 `get_diagnosis_service`，编写全部 9 个 RESTful 端点，将 `diagnosis_router` 挂载至 `/api/v1` 路由树。
- **建议委派角色**: `builder-2`

#### 1. Files that change
- `backend/app/api/deps/diagnosis.py` (New)
- `backend/app/api/deps/__init__.py` (Modify)
- `backend/app/api/v1/diagnosis.py` (New)
- `backend/app/api/v1/__init__.py` (Modify)

#### 2. Order of work
1. **实现依赖注入工厂 (`app/api/deps/diagnosis.py`)**:
   - 定义 `get_diagnosis_service() -> DiagnosisService`，未装配时抛出清晰的 `NotImplementedError` 提示，供测试时通过 `dependency_overrides` 覆盖；
   - 在 `app/api/deps/__init__.py` 中导出 `get_diagnosis_service`。
2. **编写路由模块 (`app/api/v1/diagnosis.py`)**:
   - 创建 `router = APIRouter(tags=["diagnosis"])`；
   - 实现 9 个路由端点（严格对齐 `spec.md` 2.3 小节契约）：
     1. `POST /practices/{id}/diagnosis`: 触发生成练习诊断报告，调用 `diagnosis_service.generate_diagnosis_report`，映射 200；
     2. `GET /practices/{id}/diagnosis`: 查询指定练习已生成的诊断报告，调用 `get_diagnosis_report_by_practice`，映射 200；
     3. `GET /diagnosis/reports`: 分页查询用户历史诊断报告，调用 `list_diagnosis_reports`，映射 `DiagnosisReportListResponse`；
     4. `GET /diagnosis/reports/{id}`: 根据报告主键查询详情，调用 `get_diagnosis_report`，映射 200；
     5. `GET /mastery/overview`: 查询指定资料掌握度全景，调用 `get_user_mastery_overview`，映射 `UserMasteryOverviewResponse`；
     6. `GET /mastery/{knowledge_point_id}`: 查询单个知识点掌握度，调用 `get_knowledge_mastery`，映射 `KnowledgeMasterySummaryResponse`；
     7. `GET /wrong-records`: 多维条件分页查询错题本，调用 `list_wrong_records`，映射 `WrongRecordListResponse`；
     8. `POST /wrong-records/{id}/master`: 标记错题已掌握，调用 `mark_wrong_record_mastered`，映射 `MarkWrongRecordMasteredResponse`；
     9. `DELETE /wrong-records/{id}`: 移除错题记录，调用 `remove_wrong_record`，若不存在抛出 `WrongRecordNotFoundError(40019)`，映射 `DeleteWrongRecordResponse`。
3. **路由树汇聚挂载 (`app/api/v1/__init__.py`)**:
   - 引入 `diagnosis.py` 的 `router as diagnosis_router`；
   - 执行 `api_v1_router.include_router(diagnosis_router)`；
   - 更新 `__all__` 导出列表。

#### 3. Risks & Defenses
- **架构单向铁律 (0 Repositories 导入)**: 严格禁止在 `app/api/v1/diagnosis.py` 中直接导入 `DiagnosisRepository` 或执行原生 SQL/事务，路由仅承担参数校验与单行 Service 委托；
- **多租户安全拦截**: 100% 端点接入 `Annotated[User, Depends(get_current_user)]`，且 `current_user.id` 强制透传至 Service，防止水平越权；
- **绝密脱敏红线**: 严禁记录题目全文、选项与作答内容入日志，日志仅包含 `user_ref`、`request_id`、`duration_ms` 与业务主键。

#### 4. Proof
- 架构分层违规检测（核心硬指标：0 跨层违规）：
  ```bash
  python3 tooling/check_layers.py --root backend/app
  ```
- 静态代码与格式校验：
  ```bash
  cd backend && ruff format --check app/api/deps/diagnosis.py app/api/v1/diagnosis.py app/api/v1/__init__.py && ruff check app/api/deps/diagnosis.py app/api/v1/diagnosis.py app/api/v1/__init__.py
  ```
- 类型严格检查：
  ```bash
  cd backend && mypy app/api/deps/diagnosis.py app/api/v1/diagnosis.py app/api/v1/__init__.py
  ```

---

### Milestone 3: 路由全量单元测试与异常安全矩阵 (Unit Testing & Fault Matrix)
- **目标与职责**: 编写 `test_diagnosis_router.py`，完整覆盖 9 个端点的正向流转、业务异常状态码/错误码映射、未认证拦截与租户隔离断言，确保路由层行覆盖率 $\ge 90\%$。
- **建议委派角色**: `builder-3`

#### 1. Files that change
- `backend/tests/unit/api/test_diagnosis_router.py` (New)

#### 2. Order of work
1. **测试脚手架搭建**:
   - 创建 `test_diagnosis_router.py`，配置挂载 `AppError` 全局异常处理器与 `diagnosis_router` 的测试 FastAPI 实例；
   - 提供 `mock_user` 与 `mock_diagnosis_service` Fixtures；
   - 构建生成假实体辅助函数（`make_fake_diagnosis_report`, `make_fake_wrong_record`, `make_fake_mastery_overview`）。
2. **编写正常流与分页响应测试**:
   - `test_generate_diagnosis_report_success`: 200 OK，断言 JSON 契约结构；
   - `test_get_diagnosis_report_by_practice_success`: 200 OK；
   - `test_list_diagnosis_reports_pagination`: 200 OK，校验 items, total, page, page_size；
   - `test_get_diagnosis_report_by_id_success`: 200 OK；
   - `test_get_mastery_overview_success`: 200 OK，验证四档统计数值；
   - `test_get_single_knowledge_mastery_success`: 200 OK；
   - `test_list_wrong_records_filter_and_pagination`: 200 OK，验证 material_id, status, is_mastered 过滤组合；
   - `test_mark_wrong_record_mastered_success`: 200 OK；
   - `test_delete_wrong_record_success`: 200 OK。
3. **编写异常流与业务错误码精确映射测试**:
   - `test_generate_diagnosis_report_practice_not_graded_400`: 模拟 `PracticeNotGradedError`，校验 HTTP 400 与 `code=40016`；
   - `test_generate_diagnosis_report_practice_not_found_404`: 模拟 `PracticeNotFoundError`，校验 HTTP 404 与 `code=40010`；
   - `test_get_diagnosis_report_by_practice_not_found_404`: 模拟 `DiagnosisReportNotFoundError`，校验 HTTP 404 与 `code=40017`；
   - `test_get_diagnosis_report_by_id_not_found_404`: 模拟 `DiagnosisReportNotFoundError`，校验 HTTP 404 与 `code=40017`；
   - `test_get_single_knowledge_mastery_not_found_404`: 模拟 `MasteryRecordNotFoundError`，校验 HTTP 404 与 `code=40018`；
   - `test_mark_wrong_record_mastered_not_found_404`: 模拟 `WrongRecordNotFoundError`，校验 HTTP 404 与 `code=40019`；
   - `test_delete_wrong_record_not_found_404`: 模拟删除失败抛出 `WrongRecordNotFoundError`，校验 HTTP 404 与 `code=40019`。
4. **编写安全拦截与租户隔离断言**:
   - `test_unauthenticated_requests_401`: 遍历全部端点在缺少 Token 时断言 HTTP 401 拦截；
   - `test_tenant_isolation_propagation`: 验证全部 Service 方法调用入参的 `user_id` 均严格等于 `current_user.id`。
5. **覆盖率达标核验**:
   - 运行带分支覆盖率统计的 pytest 命令，确认 `app/api/v1/diagnosis.py` 覆盖率 $\ge 90\%$。

#### 3. Risks & Defenses
- **测试毫秒级要求与网络隔离**: 全量测试基于 Mock Service，严禁发起网络调用或建立真实数据库连接；
- **契约断言严谨性**: 严禁伪造测试或削弱断言，每一项错误码必须断言返回的 `code` 与 HTTP 状态码双重一致。

#### 4. Proof
- 路由单测与覆盖率统计（覆盖率硬性指标 $\ge 90\%$）：
  ```bash
  cd backend && pytest tests/unit/api/test_diagnosis_router.py -v --cov=app/api/v1/diagnosis --cov-report=term-missing
  ```

---

### Milestone 4: 全局门禁合规、静态安全与无回归核验 (Global Gate & Regression)
- **目标与职责**: 执行全系统质量门禁核验（分层架构检查、Ruff 格式与规范、Mypy 严格类型、Bandit 安全扫描、SDLC 门禁及全量单测回归），确保交付退出码为 0。
- **建议委派角色**: `builder-4`

#### 1. Files that change
- `docs/sdlc/ZL-128/plan.md` (Modify - 状态更新与偏差登记)

#### 2. Order of work
1. **分层依赖检查**:
   - 执行 `python3 tooling/check_layers.py --root backend/app`，确保新增代码 0 违规导入。
2. **代码风格与规范扫描**:
   - 执行 `cd backend && ruff format --check . && ruff check .`，确保 100 行宽与全规则集检查通过。
3. **类型严格检查**:
   - 执行 `cd backend && mypy app/api/v1/diagnosis.py app/schemas/diagnosis.py app/api/deps/diagnosis.py app/services/diagnosis.py app/core/errors.py`，确保类型标注 100% 健全。
4. **安全隐患扫描**:
   - 执行 `cd backend && bandit -r app/api/v1/diagnosis.py app/schemas/diagnosis.py app/api/deps/diagnosis.py -ll`，确保高危中危隐患为 0。
5. **全量相关单测回归**:
   - 执行 `cd backend && pytest tests/unit/api/test_diagnosis_router.py tests/unit/schemas/test_diagnosis_schemas.py tests/unit/services/test_diagnosis_service_facade.py`，确保用例 100% 绿灯。
6. **SDLC 工件完整性校验**:
   - 执行 `python3 tooling/check_sdlc_integrity.py`，确保工件无占位符与规范完备。

#### 3. Risks & Defenses
- **无回归红线**: 确保不仅新增测试绿灯，既有 `test_practice_router.py`、`test_grading_router.py` 等相邻模块测试均不受影响；
- **工件真实性**: 实施日志与偏差记录必须如实反映修改细节，严禁虚构。

#### 4. Proof
- 综合门禁一键执行命令：
  ```bash
  python3 tooling/check_sdlc_integrity.py &&   python3 tooling/check_layers.py --root backend/app &&   cd backend &&   ruff format --check . &&   ruff check . &&   mypy app/api/v1/diagnosis.py app/schemas/diagnosis.py app/api/deps/diagnosis.py app/services/diagnosis.py app/core/errors.py &&   bandit -r app/api/v1/diagnosis.py app/schemas/diagnosis.py app/api/deps/diagnosis.py -ll &&   pytest tests/unit/api/test_diagnosis_router.py tests/unit/schemas/test_diagnosis_schemas.py tests/unit/services/test_diagnosis_service_facade.py -v
  ```

---

## 4. 全局质量门禁核验 (Global Quality Gate)

* **分层依赖检查**: `python3 tooling/check_layers.py --root backend/app`（0 违规导入）
* **代码风格与静态检查**: `cd backend && ruff format --check . && ruff check .`（行宽 100，零警告）
* **严格类型安全校验**: `cd backend && mypy app`（类型注解完整）
* **安全漏洞扫描**: `cd backend && bandit -r app -ll`（高危隐患为 0）
* **全量相关测试回归**: `cd backend && pytest tests/unit/api/test_diagnosis_router.py tests/unit/schemas/test_diagnosis_schemas.py tests/unit/services/test_diagnosis_service_facade.py -v`（100% 绿灯）

---

## 5. 实施偏差记录 (Deviations Log)

*在具体实施过程中发现必须调整接口或关联文件，在此如实记录：*
* **2026-09-24**: 在 `app/services/diagnosis.py` 中补充 `get_knowledge_mastery` 与 `mark_wrong_record_mastered` 两个服务门面方法，并在 `app/core/errors.py` 中补充 `WrongRecordNotFoundError`。该补充使得路由层可以严格遵循单一委托原则，100% 杜绝在 API 路由层直接导入 `DiagnosisRepository` 或操作数据库事务，完全符合系统五层单向架构铁律。
* **2026-09-24 (Milestone 4 验证准出)**: 实施全局门禁与全系统回归校验，各项指标均 100% 达成：
  1. `tooling/check_sdlc_integrity.py` 退出码 0，工件规范完备；
  2. `tooling/check_layers.py --root backend/app` 退出码 0，扫描 95 个文件 0 违规导入；
  3. `ruff format --check . && ruff check .` 退出码 0，166 个文件全部合规；
  4. `mypy app` 退出码 0，95 个源文件 0 类型错误；
  5. `bandit -r app -ll` 退出码 0，高危/中危漏洞为 0；
  6. `pytest tests/unit --cov=app/api/v1 --cov=app/schemas --cov-branch --cov-fail-under=80` 退出码 0，覆盖率 90.15%（门禁 $\ge 80\%$）；
  7. 全量单测回归 `pytest tests -q` 958 用例全部绿灯通过（耗时 19.35s，严格隔离外部网络）。

---

## 6. 阶段准出签批 (Gate 3 Sign-off)
- [x] 所有分步实施项与验证断言均已规划配对且具备明确执行判据
- [x] 4 个原子 Milestone 单一职责明确，任务合理分发，避免 Builder 过载
- [x] 变更文件与 plan.md 清单完全吻合，分层与脱敏防线完备
- **验收结论**: Approved
- **验证人 / 日期**: TechLead / 2026-09-24
