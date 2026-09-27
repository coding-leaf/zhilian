# 需求规格说明书 (PRD)：GRADE 切片 P2-A 缺陷修复

## Goal

针对只读审计切片 GRADE 中确认存在的 6 条 P2 缺陷（BUG-GRADE-003 至 BUG-GRADE-008），在保证系统分层架构规范、类型安全与零阻断兼容性的前提下，彻底修复要点关键词不显示、原文溯源抽屉恒空、报告页 items 死分支与异常处理、生命周期重复双请求、主观题题型判定缺口以及未作答题目误暴露重判入口的问题。

---

## 需求来源

根据 `.trellis/tasks/archive/2026-09/09-27-read-only-bug-audit/research/slice-GRADE.md` 审计底账与当前代码 HEAD 核验：

| Bug ID | 级别 | 影响层 | 核心现象与根因 | HEAD 核验结论 |
|---|---|---|---|---|
| **BUG-GRADE-003** | P2 | cross-layer | 要点命中/遗漏关键词永远不显示。后端存储于 `GradingRecord.hit_keywords/missing_keywords`，但练习详情 DTO 未透传该数据，导致前端从 `item.question_snapshot` 读取恒为空 | 有效，需修复 |
| **BUG-GRADE-004** | P2 | cross-layer | 原文溯源抽屉内容恒为空。前端根据 `source_snippet_id` 显示入口，但抽屉读取 `question_snapshot.source_snippet` 对象（后端仅存 id 未组装对象） | 有效，需修复 |
| **BUG-GRADE-005** | P2 | cross-layer | 报告页 items 分支为死代码。`DiagnosisReportResponse` 无 `items` 字段，且 `fetchPracticeSession` 失败时列表静默置空无容错提示 | 有效，需修复 |
| **BUG-GRADE-006** | P2 | frontend | 报告详情页初始化生命周期双触发。`onMounted` 与 `onLoad` 同时调用 `loadReportData` 发起重复网络请求 | 有效，需修复 |
| **BUG-GRADE-007** | P2 | cross-layer | 名词解释（`term_explanation`）与案例分析（`case_analysis`）无自评与重判入口且题型标签回退“试题” | 有效，需修复 |
| **BUG-GRADE-008** | P2 | cross-layer | 未作答主观题错误展示“申请重判”按钮，点击后被后端 403 阻断拒绝（`not item.is_answered or not item.user_answer`） | 有效，需修复 |

---

## Requirements

### 1. BUG-GRADE-003: 判题命中与遗漏要点关键词透传与呈现
- **后端**：
  - 在 `PracticeItemDetailResponse`（及 `QuestionSnapshotDTO`）中增加附加可选字段 `hit_keywords: list[str] = Field(default_factory=list)` 与 `missing_keywords: list[str] = Field(default_factory=list)`。
  - 在练习详情序列化/构建流程中，若作答项关联有生效终态 `GradingRecord`（或在 `synchronize_item_fields` 阶段若由 ORM 模型带入），将生效记录中的 `hit_keywords` 与 `missing_keywords` 映射到 DTO 中。
- **前端**：
  - `AttemptGradingItem` 及其 `question_snapshot` 契约明确支持可选 `hit_keywords?: string[]` 与 `missing_keywords?: string[]`。
  - `GradingResultList.vue` 的 `hasKeywords` 与模板渲染逻辑兼容读取 `item.hit_keywords || item.question_snapshot?.hit_keywords`，避免因字段放置层级导致胶囊不显示。

### 2. BUG-GRADE-004: 原文溯源切片对象关联与展示
- **后端**：
  - 定义来源切片概要 DTO `SourceSnippetDTO`（或复用现有 `SnippetSourceResponse` 契约字段：`id`, `chapter_title`, `page_index`, `snippet_content`）。
  - 在 `PracticeItemDetailResponse`（及 `QuestionSnapshotDTO`）中附加可选字段 `source_snippet: SourceSnippetDTO | dict[str, Any] | None = None`。
  - 练习服务/DTO 转换层在提供练习详情时，依据 `source_snippet_id` 安全关联查询或填充切片简要信息。
- **前端**：
  - `detail/index.vue` 的 `handleViewSnippet` 兼容直接读取 `item.source_snippet || item.question_snapshot?.source_snippet`。
  - `OriginalSnippetDrawer.vue` 正常渲染 `chapter_title`、`page_index` 与 `snippet_content`。

### 3. BUG-GRADE-005: 报告页数据源收敛与异常状态处理
- **前端**：
  - 移除 `repData.items` 死代码分支，明确作答项数据的主数据源来自 `practiceRes.data.items`。
  - 当 `practiceRes` 获取失败或为空且无作答项时，若 `reportRes` 成功，界面应能合理降级或展示“作答明细加载失败，请重试”，而非静默展示空白或假死。

### 4. BUG-GRADE-006: 报告详情页初始化请求去重（同款模式复用）
- **前端**：
  - 引入 `initialLoaded` 守卫标志与并发锁。
  - `onLoad` 获取到 `pid` 时标记并触发一次加载；`onMounted` 在检测到该 `pid` 已经由 `onLoad` 发起加载时不重复调用。
  - 确保仅向后端发起 1 次 `fetchDiagnosisReport` + `fetchPracticeSession` 并发请求。

### 5. BUG-GRADE-007: 补全主观题集合支持自评/重判与题型映射
- **前端**：
  - 扩展题型字典 `questionTypeMap`，补充：
    - `term_explanation`: '名词解释'
    - `case_analysis`: '案例分析'
  - 将 `canSelfGrade` 中的主观题判断与后端 `SUBJECTIVE_QUESTION_TYPES` 对齐，支持 `['short_answer', 'term_explanation', 'case_analysis']`。

### 6. BUG-GRADE-008: 未作答题目重判入口隐藏防 403
- **前端**：
  - 明确“申请重判”的前置条件：题目必须已作答（`item.is_answered === true` 且 `item.user_answer` 非空）。
  - 对未作答的主观题（`is_answered === false` 或 `user_answer == null`），隐藏“申请重判”按钮。

---

## 约束

1. **零阻断兼容性**：所有新增契约字段（`hit_keywords`, `missing_keywords`, `source_snippet`）必须为**附加可选（Optional/None）**，保证默认值与现有逻辑一致，不破坏历史调用方与测试。
2. **零 `any`**：前端 TypeScript 严禁使用 `any`，后端严格执行 Pydantic DTO 校验及 Python 类型标注。
3. **架构与分层守则**：遵守 Clean Architecture 与 import-linter 规则，严禁逆向依赖。
4. **与 P1 改动协同**：严格与此前 P1 引入的 `grading_status` 保持逻辑一致与协同，不得产生冲突或倒退。
5. **门禁全绿**：修复完成后，前端（lint/type-check/vitest）与后端（ruff/mypy/pytest）门禁必须全绿。

---

## 不在范围内

- P1 已修复的 `BUG-GRADE-001`（重批同步语义）与 `BUG-GRADE-002`（待重判状态机）。
- GRADE P2-B 批次（`BUG-GRADE-009` ~ `BUG-GRADE-016`：算法银行家舍入、自评细则解析渲染、字数上限等）。
- 离线外部 worker 消费链路探查（`WIRING-GRADE-01`）。

---

## Acceptance Criteria

- [ ] **AC-GRADE-003**: 逐题列表项能正确呈现生效判题记录中的命中关键词胶囊（“已命中：xxx”）与遗漏关键词胶囊（“遗漏：xxx”）。
- [ ] **AC-GRADE-004**: 点击“查看原文依据”打开抽屉，能完整展示章节标题、页码及切片原文正文，不再出现“暂无原文切片内容”空态。
- [ ] **AC-GRADE-005**: 报告详情页清除 `repData.items` 死代码；当练习接口调用失败时有明确的错误提示与重试机制。
- [ ] **AC-GRADE-006**: 报告页进入时首屏仅发起 1 次接口请求组合，`onLoad` 与 `onMounted` 不发生重复请求覆盖。
- [ ] **AC-GRADE-007**: 名词解释（`term_explanation`）和案例分析（`case_analysis`）卡片正确展示题型标签，且作答后展示“手动自评”与“申请重判”按钮。
- [ ] **AC-GRADE-008**: 未作答的主观题目不显示“申请重判”入口，彻底阻断后端 403 异常。
- [ ] **AC-QUALITY**: 前后端静态门禁与单元测试全部绿灯通过。

---

## Notes

- 误报/已失效复核：本切片 6 条经与 HEAD 核对均为有效缺陷，无误报。
- 完整缺陷审计依据请参考 `.trellis/tasks/archive/2026-09/09-27-read-only-bug-audit/research/slice-GRADE.md`。
