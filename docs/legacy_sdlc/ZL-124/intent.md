# Intent: 掌握度衰减聚合与诊断报告生成服务 (DiagnosisService)

- **任务编号**: ZL-124
- **提出人**: Dev
- **创建时间**: 2026-09-24 18:19
- **初始 Change Tier**: Tier 2
- **当前状态**: Accepted

---

## 1. 问题与现状背景 (Problem)
智练系统在完成练习创建与答题保存 (ZL-122)、混合判题流水线与自评/重判 (ZL-123) 以及掌握度时间衰减算法纯函数核 (ZL-112) 和诊断规则合成纯函数核 (ZL-113) 之后，各领域模块均已就绪，但在业务服务编排层与数据仓储层之间仍存在关键断链：
1. **掌握度聚合与持久化断链 (FR-47)**：练习判题完成或作答历史沉淀后，缺乏统一的服务来提取该用户在各知识点的有效作答项与最终判题记录（至多 200 条快照），无法将作答记录转换为纯函数输入并调用 `aggregate_mastery_scores`，亦未将计算得到的掌握度数值 (`mastery_score`)、四档评级 (`level`) 与时间戳原子落库至 `mastery_records`。
2. **正式诊断报告生成与状态机阻断缺失 (FR-49, FR-53)**：交卷并全量判题完成后，缺少综合诊断报告生成引擎 (`DiagnosisService`)。根据《LEADER_ALIGNMENT.md》技术决策 1，当练习处于 `PARTIALLY_GRADED`（存在待重判题目）或非 `COMPLETED` 终态时，必须严格阻断生成诊断报告并返回明确业务错误 (40016)；缺乏服务负责协调知识点退步分析、薄弱识别、低可信度黄色标签传递与可执行复习建议生成。
3. **错题本联动更新未闭环 (FR-50, FR-54, FR-55)**：做错题目未能自动流转至错题本 (`wrong_records`)；缺少对连续答错题目的 `error_count` 累加逻辑，且在后续练习做对历史错题时，缺乏攻克掌握状态 (`is_mastered=True`) 的自动更新机制。
4. **数据仓储层缺少诊断与掌握度实体隔离封装**：当前仓储层缺少针对 `mastery_records`, `diagnosis_reports`, `wrong_records` 的 `DiagnosisRepository`，无法保障全查询强制携带 `user_id` 租户过滤条件，存在潜在水平越权风险。

## 2. 变更性质分类 (Change Archetype - 单选)
- [ ] 局部结构精简 (Local Cleanup - 仅限模块内部冗余消除，不改数据流向与全局装配)
- [x] 单模块特性演进 (Single-Module Feature - 单一模块业务增量或修复)
- [ ] 跨领域架构重构 (Cross-Domain Rewiring - 触及应用全局装配、生命周期或跨域流向，必须升 Tier 3)

## 3. 期望达成效果 (Proposed Outcome)
1. **实现 DiagnosisRepository 数据仓储 (`backend/app/repositories/diagnosis.py`)**：
   - 全方法强制输入 `user_id: uuid.UUID` 并作为底层 SQL 必选过滤条件，严格杜绝水平越权；
   - 提供 `MasteryRecord` 的获取、按知识点批量查询、upsert 原子更新（结合 200 条元数据快照）；
   - 提供 `DiagnosisReport` 的创建、按 ID 查询、按 practice_id 查询与用户报告列表分页查询；
   - 提供 `WrongRecord` 的检索、防重 upsert（若存在则累加 `error_count` 并重置 `is_mastered=False`）、做对攻克更新 (`mark_wrong_record_mastered`) 与分页列表查询。
2. **实现 DiagnosisService 领域服务 (`backend/app/services/diagnosis.py`)**：
   - **掌握度衰减聚合 (`calculate_and_update_mastery`)**：抽取关联知识点的有效作答历史，调用纯函数 `aggregate_mastery_scores`，映射四档掌握度等级，持久化 `MasteryRecord`；
   - **诊断报告生成 (`generate_diagnosis_report`)**：
     - 强校验练习归属与状态：若状态为 `PARTIALLY_GRADED` 或非 `COMPLETED`，立即阻断并抛出 `PracticeNotGradedError` (40016)；
     - 逐题统计耗时、得分、未作答数与错题；
     - 批量更新练习所涉知识点掌握度；
     - 调用纯函数 `synthesize_diagnosis_report` 识别薄弱知识点 (<0.40) 与退步知识点 (Delta >= 0.05)，提取认知成因归因与可执行建议；
     - 检查知识结构降级标记 (`is_structure_degraded`)：若关联知识点存在 `is_low_confidence=True`，设置报告黄色降级标签；
     - 联动同步更新错题本 (`WrongRecord`)；
     - 在数据库事务内原子创建 `DiagnosisReport` 实体并提交；
   - **诊断报告与掌握度查询**：提供 `get_diagnosis_report`, `get_diagnosis_report_by_practice`, `get_user_mastery_overview`, `list_wrong_records` 等多维度查询契约。
3. **安全与质量达标**：
   - 在 `backend/app/core/errors.py` 登记 3 个专属异常（40016, 40017, 40018）；
   - 输出结构化 8 要素脱敏日志，严禁记录题干、标准答案与用户作答原文；
   - 仓储层与服务层单元测试覆盖率达标（服务层行覆盖率 >= 85%，多租户隔离 100% 拦截）。

## 4. 波及工程分面 (Affected Architectural Layers)
- [x] 核心领域与计算逻辑 (Domain & Core Business Logic)
- [ ] 外部接口与协议入口 (Public Ingress & Controllers & Protocols)
- [x] 数据持久化与状态存储 (Database & Storage & Schemas)
- [x] 全局装配与应用入口 (Bootstrap & Lifecycle & Service Wiring)

## 5. 边界与硬性约束 (Constraints & Boundaries)
* **硬性技术制约**:
  - `DiagnosisRepository` 严格禁止导入 `fastapi` 与 `app.integrations`，所有 SQL 操作强制包含 `user_id` 条件；
  - `DiagnosisService` 是唯一事务边界与编排者，算法核严禁进行任何 I/O；
  - 缩写白名单仅限 8 个 (`api`, `id`, `url`, `ocr`, `llm`, `db`, `config`, `env`)；
  - 严格遵守两阶段状态机防错：若练习存在待重判题目 (`PARTIALLY_GRADED`)，严禁生成诊断报告，强制抛出 `PracticeNotGradedError` (40016)；
  - 绝密脱敏红线：日志中严禁出现题干全文、选项全文、参考答案与用户作答原文，仅记录量化统计指标（题目数、得分率、耗时、错误数、知识点数）。
* **明确非目标 (Non-Goals / Out-of-Scope)**:
  - 不包含对外 HTTP 路由控制器编写（由后续 `ZL-130` 承担）；
  - 不包含判题逻辑与 LLM 采分点评估（由前序 `ZL-123` 承担）；
  - 不包含前端报告看板与错题本界面渲染（由后续小程序任务承担）。
* **完成判定条件 (Definition of Done)**:
  - `backend/app/core/errors.py` 补充 3 个专属诊断与掌握度异常；
  - `backend/app/repositories/diagnosis.py` 实现并通过多租户隔离单元测试；
  - `backend/app/services/diagnosis.py` 实现掌握度计算、报告生成与错题同步并通过单元测试；
  - `python3 tooling/check_layers.py --root backend/app` 验证零架构分层违规；
  - 全量后端质量门禁（ruff check, ruff format, mypy, pytest）全绿。

## 6. 未决疑问与待探讨点 (Open Questions)
- 1. **历史作答记录快照上限策略**：每个知识点参与计算的最近有效作答记录上限设为 200 条，已在 `MasteryRecord.recent_records_snapshot` 中预留 JSONB 存储，当有效作答超过 200 条时按时间戳倒序截断保留最新 200 条。
- 2. **同一练习重复请求诊断报告的幂等性**：若同一练习已成功生成诊断报告，二次调用生成接口时，直接查询并返回已有报告实体，确保接口强幂等与报告唯一性。

---

## 7. 阶段准出签批 (Gate 1 Sign-off)
- [ ] 场景与问题已客观复现并达成共识
- [ ] 边界、非目标与约束清晰明确
- [ ] 初始 Change Tier 评定合理
- **准出结论**: Pending
- **签批人 / 日期**: 人类技术负责人 (待签批) / 2026-09-24 18:19
