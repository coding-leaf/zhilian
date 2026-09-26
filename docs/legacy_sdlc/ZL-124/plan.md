# Plan: 掌握度衰减聚合与诊断报告生成服务 - 实施计划

- **关联 Spec**: ZL-124
- **实施执行人 / Agent**: Dev
- **当前状态**: In-Review

---

## 1. 变更文件清单 (Files that change)

1. `backend/app/core/errors.py` (Modify):
   - 登记专属异常：`PracticeNotGradedError` (40016, 400), `DiagnosisReportNotFoundError` (40017, 404), `MasteryRecordNotFoundError` (40018, 404)；并在 `__all__` 导出；
2. `backend/app/repositories/diagnosis.py` (New):
   - 实现 `DiagnosisRepository`，封装 `mastery_records`, `diagnosis_reports`, `wrong_records` 数据库操作，全方法强制 `user_id` 过滤，严禁导入 `fastapi` 与 `app.integrations`；
3. `backend/app/repositories/__init__.py` (Modify):
   - 导出 `DiagnosisRepository`；
4. `backend/app/services/diagnosis.py` (New):
   - 实现 `DiagnosisService` (及别名 `ReportService = DiagnosisService`)，覆盖掌握度批量衰减聚合 (`calculate_and_update_mastery`)、学情诊断报告生成 (`generate_diagnosis_report`)、错题本联动更新、多维度掌握度总览与查询，8 要素脱敏结构化日志输出；
5. `backend/app/services/__init__.py` (Modify):
   - 导出 `DiagnosisService`, `ReportService`, `KnowledgeMasterySummaryDTO`, `UserMasteryOverviewDTO`；
6. `backend/tests/unit/core/test_errors.py` (Modify):
   - 补充 40016, 40017, 40018 异常错误码与 HTTP 状态码断言测试；
7. `backend/tests/unit/repositories/test_diagnosis_repo.py` (New):
   - 仓储层单元测试：MasteryRecord upsert/查询/快照截断，DiagnosisReport 创建/按ID/按practice_id查询，WrongRecord 防重累加/攻克更新/过滤，100% 租户越权阻断；
8. `backend/tests/unit/services/test_diagnosis_service.py` (New):
   - 服务层单元测试：练习未判完/待重判阻断 (40016)、报告生成幂等性、掌握度 30 天半衰期衰减聚合、薄弱/退步识别、低可信度黄色标签传递 (`is_structure_degraded`)、错题本自动流转与做对攻克、多租户越权拦截、绝密日志脱敏。

---

## 2. 伴随式分步实施与验证 (Step-by-Step Implementation Loops)

### Milestone 1: 异常体系与数据仓储层构建 (Errors & DiagnosisRepository)

* **Step 1.1**: 扩展业务异常与错误码
  - 操作目标: 在 `backend/app/core/errors.py` 中注册 `PracticeNotGradedError` (40016, 400), `DiagnosisReportNotFoundError` (40017, 404), `MasteryRecordNotFoundError` (40018, 404)，并更新 `tests/unit/core/test_errors.py`。
  - 涉及文件:
    - `backend/app/core/errors.py`
    - `backend/tests/unit/core/test_errors.py`
  - 局部验证命令:
    ```bash
    cd backend && pytest tests/unit/core/test_errors.py -k "PracticeNotGraded or DiagnosisReportNotFound or MasteryRecordNotFound" -v
    ```
  - 预期判据: 3 个新增异常类的 error_code 与 status_code 测试 100% 绿灯通过。

* **Step 1.2**: 仓储层实现与多租户测试 (DiagnosisRepository)
  - 操作目标: 编写 `tests/unit/repositories/test_diagnosis_repo.py` 先行定义断言；实现 `DiagnosisRepository`；在 `repositories/__init__.py` 导出。
  - 涉及文件:
    - `backend/tests/unit/repositories/test_diagnosis_repo.py`
    - `backend/app/repositories/diagnosis.py`
    - `backend/app/repositories/__init__.py`
  - 局部验证命令:
    ```bash
    cd backend && pytest tests/unit/repositories/test_diagnosis_repo.py -v
    ```
  - 预期判据: 仓储层所有增删改查与越权拦截用例全部 Pass，无任何未捕获异常。

---

### Milestone 2: 掌握度聚合、报告生成与错题闭环服务 (DiagnosisService)

* **Step 2.1**: 服务层掌握度衰减聚合与落库 (`calculate_and_update_mastery`)
  - 操作目标: 
    - 实现作答历史查询，转换数据为 `AttemptRecord` 序列；
    - 调用纯函数 `aggregate_mastery_scores`，等级映射 (`UNLEARNED`, `WEAK`, `BASIC`, `PROFICIENT`)；
    - Upsert 持久化至 `MasteryRecord`，存储最近 200 条作答快照元数据。
  - 涉及文件:
    - `backend/app/services/diagnosis.py`
    - `backend/tests/unit/services/test_diagnosis_service.py`
  - 局部验证命令:
    ```bash
    cd backend && pytest tests/unit/services/test_diagnosis_service.py -k "test_calculate_and_update_mastery" -v
    ```
  - 预期判据: 掌握度得分计算准确，等级映射正确，快照正确截断且成功落库。

* **Step 2.2**: 诊断报告生成流水线与状态机阻断 (`generate_diagnosis_report`)
  - 操作目标:
    - 校验练习归属与状态：若状态处于 `PARTIALLY_GRADED` 或非 `COMPLETED`，严格抛出 `PracticeNotGradedError` (40016)；
    - 若已有报告则幂等返回；
    - 组装 `KnowledgeEvaluationInput` 与 `MistakeEvidence`，检查关联知识点 `is_low_confidence` 标记；
    - 调用纯函数 `synthesize_diagnosis_report` 合成薄弱点与建议；
    - 同步更新错题本：做错题目累加 `error_count`，做对历史错题置 `is_mastered=True`；
    - 在原子事务内持久化 `DiagnosisReport`；输出脱敏日志。
  - 涉及文件:
    - `backend/app/services/diagnosis.py`
    - `backend/tests/unit/services/test_diagnosis_service.py`
  - 局部验证命令:
    ```bash
    cd backend && pytest tests/unit/services/test_diagnosis_service.py -k "test_generate_diagnosis_report" -v
    ```
  - 预期判据: 阻断条件判定严格生效，诊断报告内容完整自洽，错题本正确更新。

* **Step 2.3**: 宏观总览与错题本查询接口
  - 操作目标:
    - 实现 `get_diagnosis_report`, `get_diagnosis_report_by_practice`, `get_user_mastery_overview`, `list_wrong_records`, `remove_wrong_record`；
    - 在 `backend/app/services/__init__.py` 导出。
  - 涉及文件:
    - `backend/app/services/diagnosis.py`
    - `backend/app/services/__init__.py`
    - `backend/tests/unit/services/test_diagnosis_service.py`
  - 局部验证命令:
    ```bash
    cd backend && pytest tests/unit/services/test_diagnosis_service.py -v
    ```
  - 预期判据: 服务层全部单测 100% 绿灯，覆盖率达标 (Line Coverage >= 85%)。

---

### Milestone 3: 端到端集成与全局质量门禁回归 (Integration & Quality Gate)

* **Step 3.1**: 架构分层单向依赖校验
  - 局部验证命令:
    ```bash
    python3 tooling/check_layers.py --root backend/app
    ```
  - 预期判据: 零跨层违规导入，退出码 0。

* **Step 3.2**: 代码规范与静态类型全量扫描
  - 局部验证命令:
    ```bash
    cd backend && ruff format --check . && ruff check . && mypy app && bandit -r app -ll
    ```
  - 预期判据: 格式检查通过，Ruff 静态检查 0 警告，Mypy 严格类型检查全过，Bandit 高危隐患为 0。

* **Step 3.3**: 全量测试与覆盖率门禁验证
  - 局部验证命令:
    ```bash
    cd backend && pytest tests --cov=app --cov-branch --cov-fail-under=80
    ```
  - 预期判据: 全量单元测试无任何 Failure，全局行覆盖率 >= 80%，服务层行覆盖率 >= 85%。

* **Step 3.4**: SDLC 工件合规审计
  - 局部验证命令:
    ```bash
    python3 tooling/check_sdlc_integrity.py
    ```
  - 预期判据: 工件完整规范，所有阶段检查绿灯。

---

## 3. 风险与破坏面分析 (Risks & Blast Radius)

| 风险类别 | 风险描述 | 规避与防御措施 |
| :--- | :--- | :--- |
| **状态机穿透** | 未完成判题的练习提前请求生成报告，产生空数据或脏数据报告 | 在服务入口第一步强校验状态，非 COMPLETED 直接抛出 40016，单测注入 PARTIALLY_GRADED 专测拦截 |
| **并发重复生成** | 客户端并发两次调用 `generate_diagnosis_report` 引发报告重复创建 | 依据 `practice_id` 唯一约束做前置查询与事务级原子锁，已存在报告则直接幂等返回 |
| **水平越权漏洞** | 恶意用户传入他人 `practice_id` 或 `report_id` 读取报告或掌握度 | 仓储层与服务层所有 SQL 条件与业务前置校验全部强制绑定上下文 `user_id` |
| **敏感文本泄露** | 日志中输出题干、标准答案或用户作答原文 | 结构化 8 要素日志脱敏，仅记录数量、耗时、得分等量化脱敏指标，专设正则断言用例验证 |

---

## 4. 实施偏差记录 (Deviations Log)
*本任务严格遵循 Spec 设计，无新增跨领域文件与破坏性变更。*
- 无偏差 / 遵循 Spec 契约设计

---

## 5. 阶段准出签批 (Gate 3 Sign-off)
- [ ] 所有分步实施项与验证断言均已就地执行并通过
- [ ] 全局质量门禁（Lint / Type / Regression）全部绿灯
- [ ] 变更文件与 plan.md 清单完全吻合，无越权修改
- **验收结论**: Pending
- **验证人 / 日期**: 人类技术负责人 (待确认) / 2026-09-24 18:29
