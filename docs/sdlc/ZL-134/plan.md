# Plan: 练习作答、本地草稿队列与交卷确认组件 - 实施计划

- **关联 Spec**: ZL-134
- **实施执行人 / Agent**: TechLead
- **当前状态**: Draft / Approved / In-Execution / Completed

---

## 1. 变更文件清单 (Files that change)

### 1.1 新增文件清单 (New Files)
1. `miniprogram/src/subpackages/practice/types/draft.ts`：本地草稿条目与同步状态机类型契约；
2. `miniprogram/src/subpackages/practice/utils/draft.ts`：草稿落盘、离线队列暂存、未答题盘点与耗时格式化纯函数计算核；
3. `miniprogram/src/subpackages/practice/components/OptionCard.vue`：单选/多选/判断通用选项卡片组件（遵循 96rpx 最小高度与微交互）；
4. `miniprogram/src/subpackages/practice/components/QuestionRenderer.vue`：5 大题型（单选/多选/判断/填空/简答）分发渲染组件；
5. `miniprogram/src/subpackages/practice/components/PracticeHeader.vue`：练习顶部导航、进度胶囊、倒计时与答题卡展开入口；
6. `miniprogram/src/subpackages/practice/components/AnswerSheetDrawer.vue`：答题卡底部抽屉（已答/当前/未答状态矩阵与跳转）；
7. `miniprogram/src/subpackages/practice/components/SubmitConfirmModal.vue`：未答题二次确认阻断与交卷弹窗；
8. `miniprogram/src/subpackages/practice/components/BottomActionBar.vue`：吸底常驻操作栏（上一题/下一题/交卷与安全区适配）；
9. `miniprogram/src/subpackages/practice/pages/session/index.vue`：练习作答主会话页面；
10. `miniprogram/src/subpackages/practice/pages/session/session.scss`：主页面样式文件（遵循低饱和色盘与设计规范）；
11. `miniprogram/tests/unit/practice/draftUtils.spec.ts`：草稿纯函数计算核单元测试；
12. `miniprogram/tests/unit/practice/questionRenderer.spec.ts`：题型渲染组件单元测试；
13. `miniprogram/tests/unit/practice/practiceDrawers.spec.ts`：答题卡与未答确认弹窗交互单元测试；
14. `miniprogram/tests/unit/practice/practiceSession.spec.ts`：答题会话页面装配与断网重连同步流程单元测试。

### 1.2 修改文件清单 (Modified Files)
1. `miniprogram/src/pages.json`：注册 `subpackages/practice` 分包及 `pages/session/index` 页面；
2. `miniprogram/src/stores/practiceStore.ts`：扩展草稿队列状态管理与单题耗时更新辅助方法。

---

## 2. 伴随式分步实施与验证 (Step-by-Step Implementation Loops)

### Milestone 1: 纯函数草稿队列与答题辅助计算核 (Core & Utils)
* **操作目标**: 实现无副作用纯函数库 `draft.ts`，涵盖秒数格式化、答案非空判断、未答题目统计、草稿不可变合并与待同步队列抽取。
* **涉及文件**:
  - `miniprogram/src/subpackages/practice/types/draft.ts`
  - `miniprogram/src/subpackages/practice/utils/draft.ts`
  - `miniprogram/tests/unit/practice/draftUtils.spec.ts`
* **局部验证命令**:
  ```bash
  cd miniprogram && pnpm vitest run tests/unit/practice/draftUtils.spec.ts
  ```
* **预期判据**: 纯函数测试用例全绿，边界值覆盖（0秒、超1小时、空字符串、空数组、多选反选全部），分支覆盖率达 100%。

### Milestone 2: 题型渲染体系与卡片交互组件群 (UI Components)
* **操作目标**: 依据 DESIGN.md 开发 `OptionCard.vue` 与 `QuestionRenderer.vue`。单选采用圆圈、多选采用微圆角方框，支持单选/多选/判断/填空/简答 5 大题型。
* **涉及文件**:
  - `miniprogram/src/subpackages/practice/components/OptionCard.vue`
  - `miniprogram/src/subpackages/practice/components/QuestionRenderer.vue`
  - `miniprogram/tests/unit/practice/questionRenderer.spec.ts`
* **局部验证命令**:
  ```bash
  cd miniprogram && pnpm vitest run tests/unit/practice/questionRenderer.spec.ts
  ```
* **预期判据**: 单选题单选互斥、多选题多选勾选、判断题双卡片切换、填空/简答文本双向绑定测试全部通过；单个组件代码行数严格 $\le 300$ 行。

### Milestone 3: 答题卡抽屉与未答题二次确认阻断弹窗 (Drawers & Modals)
* **操作目标**: 实现 `AnswerSheetDrawer.vue`（已答/当前/未答三色态高亮与点击跳题）及 `SubmitConfirmModal.vue`（未答题清单二次确认阻断）。
* **涉及文件**:
  - `miniprogram/src/subpackages/practice/components/AnswerSheetDrawer.vue`
  - `miniprogram/src/subpackages/practice/components/SubmitConfirmModal.vue`
  - `miniprogram/tests/unit/practice/practiceDrawers.spec.ts`
* **局部验证命令**:
  ```bash
  cd miniprogram && pnpm vitest run tests/unit/practice/practiceDrawers.spec.ts
  ```
* **预期判据**: 答题卡网格正确映射题目状态并触发 `select` 事件；未答题弹窗在未答数 $>0$ 时正确列出未答题号，点击“去检查”跳转首个未答题，“确认交卷”携带 `confirm_unanswered=true`。

### Milestone 4: 顶部导航、吸底操作栏与主答题页面装配 (Page Integration & Flow)
* **操作目标**: 完成 `PracticeHeader.vue`、`BottomActionBar.vue`、`session/index.vue` 装配，并在 `pages.json` 注册分包；集成 `practiceStore`、断网事件监听与强幂等交卷。
* **涉及文件**:
  - `miniprogram/src/subpackages/practice/components/PracticeHeader.vue`
  - `miniprogram/src/subpackages/practice/components/BottomActionBar.vue`
  - `miniprogram/src/subpackages/practice/pages/session/index.vue`
  - `miniprogram/src/subpackages/practice/pages/session/session.scss`
  - `miniprogram/src/pages.json`
  - `miniprogram/src/stores/practiceStore.ts`
  - `miniprogram/tests/unit/practice/practiceSession.spec.ts`
* **局部验证命令**:
  ```bash
  cd miniprogram && pnpm vitest run tests/unit/practice/practiceSession.spec.ts
  ```
* **预期判据**: 模拟路由参数加载练习成功；上一题/下一题平滑切题；断网时暂存至 `practice_drafts`，重连触发补发；交卷携带客户端 UUIDv4 `Idempotency-Key`。

### Milestone 5: 全局质量门禁与工程合规闭环 (Quality & Gate Verification)
* **操作目标**: 运行前端代码静态扫描、类型检查与全量单元测试，核验主包体积与单组件行数。
* **涉及文件**: 全部相关文件
* **局部验证命令**:
  ```bash
  cd miniprogram && pnpm run lint && pnpm run type-check && pnpm run test:unit
  ```
  以及根目录下运行门禁检查：
  ```bash
  python3 tooling/check_sdlc_integrity.py
  ```
* **预期判据**: `eslint` 0 error，`vue-tsc` 严格类型检查通过无报错，Vitest 全量单测 100% 绿灯通过，SDLC 门禁校验通过。

---

## 3. 全局质量门禁核验 (Global Quality Gate)
* **代码风格与静态检查**: `cd miniprogram && pnpm run lint`（强制行宽 100、单引号、尾随逗号、严禁隐式 any、单组件 $\le 300$ 行）。
* **类型与契约安全校验**: `cd miniprogram && pnpm run type-check`（执行 `vue-tsc --noEmit`，杜绝任何未定义属性与类型不兼容）。
* **全量相关测试回归**: `cd miniprogram && pnpm run test:unit`（所有纯函数与组件测试全部脱机运行且 100% 通过）。
* **门禁完整性校验**: `python3 tooling/check_sdlc_integrity.py`（退出码 0 为交付标准）。

---

## 4. 实施偏差记录 (Deviations Log)
*若实施过程中发现必须调整其他文件，在此记录并在同个 Commit 中同步更新：*
* 实施方案完全对齐 ROADMAP.md 与 DESIGN.md，无跨模块越权修改与偏差。

---

## 5. 阶段准出签批 (Gate 3 Sign-off)
- [ ] 所有分步实施项与验证断言均已就地执行并通过
- [ ] 全局质量门禁（Lint / Type / Regression）全部绿灯
- [ ] 变更文件与 plan.md 清单完全吻合，无越权修改
- **验收结论**: Pending
- **验证人 / 日期**: 待人类确认 / 2026-09-25 03:47
