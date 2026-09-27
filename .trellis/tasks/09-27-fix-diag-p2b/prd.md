# 修复 DIAG 切片 P2-B（016-022）

## Goal

修复只读审计清单 DIAG 切片 P2-B 批次的 7 条缺陷（BUG-DIAG-016 … BUG-DIAG-022），覆盖报告状态重置、草稿关键字段缺失、继续练习幂等头未生效、报告生成唯一键并发冲突、掌握度全景薄弱点未排序、潜伏掌握度契约对齐以及报告页缺失空态分支等问题。

## 需求来源

上游审计 `09-27-read-only-bug-audit` 成果文档 `.trellis/tasks/archive/2026-09/09-27-read-only-bug-audit/research/slice-DIAG.md`：

| ID | 级别 | 层 | 一句话 |
|---|---|---|---|
| BUG-DIAG-016 | P2 | frontend | `setReport` 仅在 `report?.weak_points` 为真时更新 `weakPoints`，新报告无薄弱点时不重置，保留陈旧数据 |
| BUG-DIAG-017 | P2 | frontend | `extractLatestDraftPractice` 读取草稿 `title`/`total_count`/`material_id`，但 `practiceStore` 构造时恒缺，致最近学习信息失真 |
| BUG-DIAG-018 | P2 | cross-layer | 继续练习发送 `X-Idempotency-Key`，但后端通用幂等规范为 `Idempotency-Key` 且 `POST /practices` 路由与 DTO 未对齐/未接入校验 |
| BUG-DIAG-019 | P2 | backend | 报告生成幂等为先查后插，并发时 `practice_id` 唯一约束抛 `IntegrityError` 未捕获回查既有报告导致 500 |
| BUG-DIAG-020 | P2 | backend | 掌握度全景中 `weak_knowledge_points` 按知识点遍历顺序追加未排序，与算法层薄弱点最弱优先（掌握度升序）约定不一致 |
| BUG-DIAG-021 | P2 | cross-layer | 潜伏类型契约不一致：前端 `UserMasteryOverview` / `KnowledgeMasterySummary` 字段命名与后端掌握度响应 DTO 存在别名缺失 |
| BUG-DIAG-022 | P2 | frontend | 报告详情页模板仅覆盖 loading/error/currentReport，缺少“无 practiceId 或报告未找到”的空态分支，致异常白屏 |

## Requirements

### 功能要求
1. **DIAG-016（报告状态重置）**：
   - 前端 `reportStore.setReport` 在传入新报告但无 `weak_points`（或空数组/null）时，必须将 `weakPoints.value` 重置为空数组 `[]`，彻底消除旧报告薄弱点残留。
2. **DIAG-017（草稿关键元数据补齐）**：
   - 前端 `AnswerDraft` 类型扩展可选字段 `title?: string`、`total_count?: number`、`material_id?: string`。
   - `practiceStore.initSession` 初始化草稿时，同步记录题数 `total_count: questionList.length` 及由外部传入或 session 提供的 `title`、`material_id`。
   - `extractLatestDraftPractice` 优先消费草稿内保存的真实 `total_count`、`title`、`material_id`。
3. **DIAG-018（继续练习幂等键对齐）**：
   - 跨层协议对齐：前端 `api/diagnosis.ts::continuePractice` 请求头由 `X-Idempotency-Key` 统一修正为系统标准规范 `Idempotency-Key`（与 `practice.ts`、`material.ts` 保持一致）。
   - 后端路由 `POST /api/v1/practices` 增加可选 Header `idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None`。
   - `PracticeCreateRequest` 增加可选字段 `idempotency_key: str | None = None`，若携带则经由 `practice_service.create_practice` 或幂等适配器进行防重/或在服务层校验，防止快速重复连击创建重复练习。
4. **DIAG-019（报告生成并发冲突捕获）**：
   - 后端 `DiagnosisService.generate_diagnosis_report` 在 `self.diagnosis_repo.create_diagnosis_report` 和 `self.session.commit()` 处捕获 SQLAlchemy `IntegrityError`。
   - 发生唯一键冲突时执行 `self.session.rollback()`，重新查询 `get_diagnosis_report_by_practice_id`。若已生成则幂等返回既有报告，避免 500 崩溃。
5. **DIAG-020（全景薄弱点最弱优先排序）**：
   - 后端 `DiagnosisService.get_user_mastery_overview` 在组装 `weak_points_summary` 后，按掌握度得分升序（`mastery_score` 升序，最薄弱排在前）进行稳定排序，与算法层规则保持一致。
6. **DIAG-021（掌握度跨层契约与别名对齐）**：
   - 后端 `UserMasteryOverviewResponse` 增加或保障别名 `weak_points` 兼容 `weak_knowledge_points`。
   - 前端 `KnowledgeMasterySummary` 与后端 `KnowledgeMasterySummaryResponse` 补齐兼容字段别名映射（如 `mastery_score` vs `current_score`，`level` vs `tier`），使类型层和运行时解析双向兼容。
7. **DIAG-022（报告详情页空态分支）**：
   - 前端 `subpackages/report/pages/detail/index.vue` 模板增加 `v-else` 空态分支，当既非 loading、非 error 且无 `currentReport`（例如未传入有效 practiceId 或报告为空）时，展示友好空态提示“暂无诊断报告数据”及“返回首页/重试”按钮，杜绝白屏。

### 约束
- 契约权威：后端 `backend/app/schemas/diagnosis.py` 与 `backend/app/schemas/practice.py`。
- 新增字段一律**附加可选**，默认值保持旧行为，存量调用不破坏。
- 前端严禁出现 `any`，严格遵守 TypeScript 类型守卫与 `@/*` 导入规范。
- 后端严格遵守分层架构与 import-linter 规则，禁止跨层反向调用。
- 前端测试夹具字段名逐字对应后端 DTO 定义。
- 门禁全绿：后端 ruff + mypy + import-linter + pytest 全绿；前端 lint + type-check + test:unit 全绿。

### 不在范围内
- DIAG P1 批次（BUG-DIAG-001 … 008）及 P2-A 批次（BUG-DIAG-009 … 015）已独立归档或在其他切片处理，本任务严格限定 016-022。
- 练习作答核心判题算法与 LLM 提示词重构不在本任务范围。

## Acceptance Criteria

- [ ] **DIAG-016**：`reportStore.setReport(reportWithoutWeakPoints)` 执行后，`weakPoints.value` 为 `[]`；切换报告时无旧薄弱点残留。
- [ ] **DIAG-017**：`practiceStore.initSession` 生成的草稿包含 `total_count`（以及可选 `title`/`material_id`）；`extractLatestDraftPractice` 解析草稿能正确读出真实的题数与标题。
- [ ] **DIAG-018**：前端 `continuePractice` 请求头携带 `Idempotency-Key`；后端 `POST /practices` 接口支持接收 `Idempotency-Key` Header，幂等创建或拦截并发重复提交。
- [ ] **DIAG-019**：并发重复生成报告触发 `IntegrityError` 唯一约束时，后端捕获冲突并 rollback，安全返回已存在的报告实体，不抛 500。
- [ ] **DIAG-020**：掌握度全景中返回的 `weak_knowledge_points` 严格按 `mastery_score` 升序排列（得分最低的排在最前）。
- [ ] **DIAG-021**：掌握度 DTO 前后端字段完全对齐，`UserMasteryOverviewResponse` 包含 `weak_points` 兼容输出；前端 `KnowledgeMasterySummary` 包含对齐字段定义。
- [ ] **DIAG-022**：报告详情页在缺失 practiceId 或空报告时渲染空态结构 `.empty-state`，并展示操作按钮，无静默白屏。
- [ ] 后端门禁全绿：`uv run ruff format --check .`、`uv run ruff check .`、`uv run mypy app`、`uv run lint-imports`、`uv run pytest tests`。
- [ ] 前端门禁全绿：`pnpm run lint`、`pnpm run type-check`、`pnpm run test:unit`。

## Notes

- 父任务：`09-27-fullstack-bug-audit-and-fix`。
- 对应审计：`.trellis/tasks/archive/2026-09/09-27-read-only-bug-audit/research/slice-DIAG.md` 中的 BUG-DIAG-016 到 BUG-DIAG-022。
- 状态判定：经当前 HEAD 源码核验，7 条 Bug 均在代码库中客观存在，无误报或失效项。
