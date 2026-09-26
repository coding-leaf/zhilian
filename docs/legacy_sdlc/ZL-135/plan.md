# Plan: 判题反馈、主观题自评/重判与诊断报告组件 - 实施计划

- **关联 Spec**: ZL-135
- **实施执行人 / Agent**: TechLead
- **当前状态**: Draft / Approved / In-Execution / Completed

---

## 1. 变更文件清单 (Files that change)

### 1.1 新增文件清单 (New Files)
1. `miniprogram/src/subpackages/report/utils/reportFormat.ts`：纯函数计算核（耗时格式化、四档色彩映射、判题状态映射、正则关键词安全切词高亮、退步标记计算）；
2. `miniprogram/src/subpackages/report/components/DiagnosisSummaryCard.vue`：诊断概览卡片组件（总分、总用时、正确率、四档等级徽章、待重判黄色告警栏与低可信度黄色标签）；
3. `miniprogram/src/subpackages/report/components/DiagnosisSummaryCard.scss`：概览卡片独立样式表；
4. `miniprogram/src/subpackages/report/components/WeakKnowledgeCard.vue`：薄弱知识点与退步归因卡片组件（掌握度进度条、退步徽章、认知成因与行动建议）；
5. `miniprogram/src/subpackages/report/components/WeakKnowledgeCard.scss`：薄弱知识点卡片独立样式表；
6. `miniprogram/src/subpackages/report/components/GradingResultList.vue`：逐题作答结果卡片列表组件（判对/判错/待重新判题三色状态、作答与答案比对、命中与遗漏关键词胶囊）；
7. `miniprogram/src/subpackages/report/components/GradingResultList.scss`：逐题列表独立样式表；
8. `miniprogram/src/subpackages/report/components/OriginalSnippetDrawer.vue`：原文切片溯源抽屉组件（章节页码定位与关键词安全高亮）；
9. `miniprogram/src/subpackages/report/components/OriginalSnippetDrawer.scss`：溯源抽屉独立样式表；
10. `miniprogram/src/subpackages/report/components/SelfGradeModal.vue`：主观题自评模态弹窗组件（评分细则比对、0~满分滑块选择、自评心得录入与覆盖提交）；
11. `miniprogram/src/subpackages/report/components/SelfGradeModal.scss`：自评弹窗独立样式表；
12. `miniprogram/src/subpackages/report/components/RegradeModal.vue`：主观题申请重判模态弹窗组件（申请重判理由录入与提交重试）；
13. `miniprogram/src/subpackages/report/components/RegradeModal.scss`：重判弹窗独立样式表；
14. `miniprogram/src/subpackages/report/pages/detail/index.vue`：诊断报告与判题反馈主装配页面；
15. `miniprogram/src/subpackages/report/pages/detail/detail.scss`：主页面独立样式表；
16. `miniprogram/tests/unit/report/reportFormat.spec.ts`：纯函数计算核单元测试（分支覆盖率 100%）；
17. `miniprogram/tests/unit/report/diagnosisCards.spec.ts`：概览摘要卡与薄弱知识点卡片单元测试；
18. `miniprogram/tests/unit/report/gradingResults.spec.ts`：逐题解析卡片与原文溯源高亮抽屉单元测试；
19. `miniprogram/tests/unit/report/gradingModals.spec.ts`：自评与重判模态弹窗交互单元测试；
20. `miniprogram/tests/unit/report/reportDetail.spec.ts`：诊断报告主页面装配、路由加载与降级告警端到端单元测试。

### 1.2 修改文件清单 (Modified Files)
1. `miniprogram/src/types/report.ts`：扩充对齐后端字段（如 `mastery_before`, `mastery_after`, `score_rate`, `pending_regrade_count`, `is_structure_degraded`, `associated_mistakes`, `cause_type` 等）；
2. `miniprogram/src/pages.json`：注册 `subpackages/report/pages/detail/index` 分包页面，替换原有临时的 `subpackages/report/index`。

---

## 2. 伴随式分步实施与验证 (Step-by-Step Implementation Loops)

### Milestone 1: 报告纯函数计算核与契约类型定义 (Utils & Types)
* **操作目标**: 扩展 `report.ts` 类型契约，编写 `reportFormat.ts` 纯函数计算核，涵盖秒数格式化、掌握度四级色彩/文案映射、判题状态判定（判对/判错/待重判）、正则关键词安全高亮切词及退步标记。
* **涉及文件**:
  - `miniprogram/src/types/report.ts`
  - `miniprogram/src/subpackages/report/utils/reportFormat.ts`
  - `miniprogram/tests/unit/report/reportFormat.spec.ts`
* **局部验证命令**:
  ```bash
  cd miniprogram && pnpm vitest run tests/unit/report/reportFormat.spec.ts
  ```
* **预期判据**: 纯函数测试全部通过，分支覆盖率达 100%（覆盖 0 秒、跨小时、负数、四档边界 0.40/0.70/0.85、关键词空列表/特殊正则字符转义、退步边界 -0.05）。

### Milestone 2: 概览摘要卡与薄弱知识点诊断组件 (Summary & Weakness Cards)
* **操作目标**: 依据 DESIGN.md 规范开发 `DiagnosisSummaryCard.vue` 与 `WeakKnowledgeCard.vue`。实现总分耗时展示、四档掌握度等级徽章、待重判黄色告警横幅、低可信度黄色标签、薄弱知识点按优先级列表展示、退步标签与归因阐释（含无错题时的特殊标记）。
* **涉及文件**:
  - `miniprogram/src/subpackages/report/components/DiagnosisSummaryCard.vue`
  - `miniprogram/src/subpackages/report/components/DiagnosisSummaryCard.scss`
  - `miniprogram/src/subpackages/report/components/WeakKnowledgeCard.vue`
  - `miniprogram/src/subpackages/report/components/WeakKnowledgeCard.scss`
  - `miniprogram/tests/unit/report/diagnosisCards.spec.ts`
* **局部验证命令**:
  ```bash
  cd miniprogram && pnpm vitest run tests/unit/report/diagnosisCards.spec.ts
  ```
* **预期判据**: 概览卡片在存在待重判题目时正确渲染黄色告警条；四档徽章背景色与文字色完全对齐规范；薄弱卡片正确展示退步标记与认知成因，各组件行数 $\le 300$ 行。

### Milestone 3: 逐题解析结果卡与原文溯源高亮抽屉 (Grading Results & Snippet Drawer)
* **操作目标**: 开发 `GradingResultList.vue` 与 `OriginalSnippetDrawer.vue`。支持按题号展示判对（绿色）、判错（红色）、待重新判题（黄色）状态；支持作答与参考答案对比；展示命中核心词与遗漏要点微胶囊；点击“查看原文依据”打开抽屉，对关联切片进行章节定位与纯文本分词安全高亮渲染。
* **涉及文件**:
  - `miniprogram/src/subpackages/report/components/GradingResultList.vue`
  - `miniprogram/src/subpackages/report/components/GradingResultList.scss`
  - `miniprogram/src/subpackages/report/components/OriginalSnippetDrawer.vue`
  - `miniprogram/src/subpackages/report/components/OriginalSnippetDrawer.scss`
  - `miniprogram/tests/unit/report/gradingResults.spec.ts`
* **局部验证命令**:
  ```bash
  cd miniprogram && pnpm vitest run tests/unit/report/gradingResults.spec.ts
  ```
* **预期判据**: 逐题卡片状态与分数映射正确，命中关键词正确高亮；点击切片抽屉能正确传递关键词并渲染高亮片段；组件单文件 $\le 300$ 行。

### Milestone 4: 主观题自评与重判模态弹窗交互 (Self-Grade & Regrade Modals)
* **操作目标**: 实现 `SelfGradeModal.vue`（标准答案对比、评分细则比对、0~满分滑块、自评心得输入）与 `RegradeModal.vue`（申请重判理由录入）。点击提交分别调用 `selfGradeQuestion` 与 `requestRegrade`，并向父层派发更新事件。
* **涉及文件**:
  - `miniprogram/src/subpackages/report/components/SelfGradeModal.vue`
  - `miniprogram/src/subpackages/report/components/SelfGradeModal.scss`
  - `miniprogram/src/subpackages/report/components/RegradeModal.vue`
  - `miniprogram/src/subpackages/report/components/RegradeModal.scss`
  - `miniprogram/tests/unit/report/gradingModals.spec.ts`
* **局部验证命令**:
  ```bash
  cd miniprogram && pnpm vitest run tests/unit/report/gradingModals.spec.ts
  ```
* **预期判据**: 自评弹窗滑块分数与输入双向绑定正确，提交携带合法参数；重判弹窗理由输入与提交状态反馈正常；两弹窗均具备空值防御与提交 loading 态。

### Milestone 5: 分包主页面装配、路由注册与全局质量门禁 (Page Assembly & Quality Gates)
* **操作目标**: 实现 `subpackages/report/pages/detail/index.vue`，串联所有 6 个子组件；在 `pages.json` 完成路由注册；接入 Pinia `reportStore` 管理状态；运行前端质量全量基线与工程门禁检查。
* **涉及文件**:
  - `miniprogram/src/subpackages/report/pages/detail/index.vue`
  - `miniprogram/src/subpackages/report/pages/detail/detail.scss`
  - `miniprogram/src/pages.json`
  - `miniprogram/tests/unit/report/reportDetail.spec.ts`
* **局部验证命令**:
  ```bash
  cd miniprogram && pnpm vitest run tests/unit/report/reportDetail.spec.ts
  ```
  全量质量基线与门禁检查：
  ```bash
  cd miniprogram && pnpm run lint && pnpm run type-check && pnpm run test:unit
  ```
  以及根目录 SDLC 完整性检查：
  ```bash
  python3 tooling/check_sdlc_integrity.py
  ```
* **预期判据**: 诊断报告页面端到端单测通过；`vue-tsc` 0 契约与类型错误；ESLint 0 告警；Vitest 全量单测全部绿灯；SDLC 门禁校验通过（Exit Code 0）。

---

## 3. 全局质量门禁核验 (Global Quality Gate)
* **代码风格与静态检查**: `cd miniprogram && pnpm run lint`（无未定义变量、单组件 $\le 300$ 行、单引号、尾随逗号、无隐式 any）；
* **类型与契约安全校验**: `cd miniprogram && pnpm run type-check`（`vue-tsc --noEmit` 0 error）；
* **全量单元测试覆盖**: `cd miniprogram && pnpm run test:unit`（报告与判题单测全量通过，毫秒级脱机运行）；
* **SDLC 门禁合规检查**: `python3 tooling/check_sdlc_integrity.py`（退出码 0，工件完整无偷跑）。

## 4. 实施偏差记录 (Deviations Log)
* [无偏差 / 严格遵循 spec.md 技术契约与 ROADMAP.md 规划]

---

## 5. 阶段准出签批 (Gate 3 Sign-off)
- [x] 所有分步实施项与验证断言均已就地执行并通过
- [x] 全局质量门禁（Lint / Type / Regression）全部绿灯
- [x] 变更文件与 plan.md 清单完全吻合，无越权修改
- **验收结论**: Approved
- **验证人 / 日期**: TechLead / 2026-09-25 11:05
