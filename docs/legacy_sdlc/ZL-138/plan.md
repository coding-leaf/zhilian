# Plan: 首页工作台UI重构与状态栏/快捷上传/最近学习流组件 - 实施计划

- **关联 Spec**: ZL-138
- **实施执行人 / Agent**: TechLead
- **当前状态**: Approved

---

## 1. 变更文件清单 (Files that change)

### 1.1 新增文件清单 (New Files)
1. `miniprogram/src/components/home/MasteryDashboardBar.vue`：掌握度状态栏组件（左侧大号得分与四档徽章，右侧紧凑四档横条与数量标注）；
2. `miniprogram/src/components/home/MasteryDashboardBar.scss`：掌握度状态栏独立样式表；
3. `miniprogram/src/components/home/QuickUploadBar.vue`：快捷上传行动栏组件（一体化上传横幅，高触控区，底部选单呼出与 `MaterialUpload.vue` 业务闭环）；
4. `miniprogram/src/components/home/QuickUploadBar.scss`：快捷上传行动栏独立样式表；
5. `miniprogram/src/components/home/RecentLearningSection.vue`：最近学习内容流组件（智能双轨流：进行中练习置顶卡 + 最近 2 份资料快捷出题卡）；
6. `miniprogram/src/components/home/RecentLearningSection.scss`：最近学习内容流独立样式表；
7. `miniprogram/src/components/home/NewbieGuideCard.vue`：新手引导指南卡组件（零数据态温和引导、3 步学习流程与首次学习触发）；
8. `miniprogram/src/components/home/NewbieGuideCard.scss`：新手引导指南卡独立样式表；
9. `miniprogram/src/pages/index/index.scss`：首页页面容器样式表（抽离原行内样式，保持 `.vue` 文件精简）；
10. `miniprogram/tests/unit/components/MasteryDashboardBar.spec.ts`：掌握度状态栏单元测试；
11. `miniprogram/tests/unit/components/QuickUploadBar.spec.ts`：快捷上传行动栏单元测试；
12. `miniprogram/tests/unit/components/RecentLearningSection.spec.ts`：最近学习内容流单元测试；
13. `miniprogram/tests/unit/components/NewbieGuideCard.spec.ts`：新手引导指南卡单元测试。

### 1.2 修改文件清单 (Modified Files)
1. `miniprogram/src/pages/index/index.vue`：重构为轻量容器组件，集成 `wd-skeleton` 骨架屏、`Promise.allSettled` 并发请求与下拉刷新；
2. `miniprogram/tests/unit/pages/index.spec.ts`：同步更新首页工作台集成单元测试，校验全新组件装配、并发拉取与容灾表现。

---

## 2. 伴随式分步实施与验证 (Step-by-Step Implementation Loops)

### Milestone 1: 掌握度状态栏组件与四档考点分布横条 (MasteryDashboardBar)
* **操作目标**: 实现 `MasteryDashboardBar.vue` 及其独立样式表 `MasteryDashboardBar.scss`。构建左侧大号得分（字号 44rpx，字重 800）与四档状态徽章（精通/良好/需巩固/未学）；构建右侧紧凑四档考点分布横条（高度 16rpx，纯 CSS 比例填充，色值严格对齐精通 `#8B5CF6`、良好 `#10B981`、需巩固 `#F59E0B`、未学 `#94A3B8`）；支持点击整卡路由跳转至学情诊断报告页；编写配套单元测试。
* **涉及文件**:
  - `miniprogram/src/components/home/MasteryDashboardBar.vue`
  - `miniprogram/src/components/home/MasteryDashboardBar.scss`
  - `miniprogram/tests/unit/components/MasteryDashboardBar.spec.ts`
* **局部验证命令**:
  ```bash
  cd miniprogram && pnpm vitest run tests/unit/components/MasteryDashboardBar.spec.ts
  ```
* **预期判据**: 单元测试 100% 通过；覆盖零分未诊断、满分全精通、常规比例划分各边界；点击事件成功触发跳转；组件单文件严格 $\le 300$ 行；零 Emoji。

### Milestone 2: 快捷上传行动栏组件与选单集成 (QuickUploadBar)
* **操作目标**: 实现 `QuickUploadBar.vue` 与 `QuickUploadBar.scss`。呈现一体化浅蓝主题横幅（背景 `$--wot-color-theme-light`，边框 `$--wot-color-theme-border`）；确保最小触控热区 $\ge 88\text{rpx}$ 与按压缩放动效 `transform: scale(0.985)`；点击调起底部操作选单并集成复用 `subpackages/material/components/MaterialUpload.vue`；上传成功后向父级派发 `upload-success` 事件；编写配套单元测试。
* **涉及文件**:
  - `miniprogram/src/components/home/QuickUploadBar.vue`
  - `miniprogram/src/components/home/QuickUploadBar.scss`
  - `miniprogram/tests/unit/components/QuickUploadBar.spec.ts`
* **局部验证命令**:
  ```bash
  cd miniprogram && pnpm vitest run tests/unit/components/QuickUploadBar.spec.ts
  ```
* **预期判据**: 单元测试 100% 通过；点击横幅成功打开上传弹窗；模拟上传成功正确派发事件；组件单文件 $\le 300$ 行；无任何裸 Hex 色值。

### Milestone 3: 最近学习内容流组件与智能双轨动态卡片 (RecentLearningSection)
* **操作目标**: 实现 `RecentLearningSection.vue` 与 `RecentLearningSection.scss`。搭建智能双轨流：检测到活跃练习或本地草稿时置顶展示【继续练习】卡片（展示已答进度与更新时间，提供继续作答入口）；下方展示最多 2 份最近学习资料卡片（展示标题、格式标签、解析状态如已就绪/解析中、考点数与【快捷出题】入口）；右上角提供“全部资料”跳转；编写配套单元测试。
* **涉及文件**:
  - `miniprogram/src/components/home/RecentLearningSection.vue`
  - `miniprogram/src/components/home/RecentLearningSection.scss`
  - `miniprogram/tests/unit/components/RecentLearningSection.spec.ts`
* **局部验证命令**:
  ```bash
  cd miniprogram && pnpm vitest run tests/unit/components/RecentLearningSection.spec.ts
  ```
* **预期判据**: 单元测试 100% 通过；草稿存在时轨 1 置顶且进度正确显示，无草稿时轨 1 自动折叠隐藏；快捷出题与查看详情跳转入参正确；单文件行数 $\le 300$ 行。

### Milestone 4: 新手引导指南卡与首页容器骨架重构 (NewbieGuideCard & Index Page)
* **操作目标**: 实现 `NewbieGuideCard.vue` 与 `NewbieGuideCard.scss`，展示 3 步新手学习流程；全面重塑 `miniprogram/src/pages/index/index.vue` 并拆分 `index.scss`；生命周期集成 `Promise.allSettled` 并发拉取掌握度与资料列表，实现优雅降级容灾；集成 `wd-skeleton` 骨架屏；接入 `onPullDownRefresh` 并调用 `uni.stopPullDownRefresh`；更新首页综合单测。
* **涉及文件**:
  - `miniprogram/src/components/home/NewbieGuideCard.vue`
  - `miniprogram/src/components/home/NewbieGuideCard.scss`
  - `miniprogram/src/pages/index/index.vue`
  - `miniprogram/src/pages/index/index.scss`
  - `miniprogram/tests/unit/components/NewbieGuideCard.spec.ts`
  - `miniprogram/tests/unit/pages/index.spec.ts`
* **局部验证命令**:
  ```bash
  cd miniprogram && pnpm vitest run tests/unit/components/NewbieGuideCard.spec.ts tests/unit/pages/index.spec.ts
  ```
* **预期判据**: 首页集成测试全部绿灯；零数据时渲染新手引导卡；存在数据时展示仪表盘；骨架屏在加载完成后平滑隐藏；未登录态与已登录态切换流畅；`index.vue` 代码行数控制在 160 行以内。

### Milestone 5: 前端全量质量基线与 SDLC 门禁全通 (Full Quality Gate)
* **操作目标**: 执行前端全量静态检查、类型检查、全部单元测试回归与 SDLC 架构合规门禁。
* **涉及文件**: 全量前端重构涉及文件及 SDLC 工件。
* **局部验证命令**:
  ```bash
  cd miniprogram && pnpm run lint && pnpm run type-check && pnpm run test:unit
  python3 tooling/check_sdlc_integrity.py
  ```
* **预期判据**: ESLint 0 错误（单组件强制严格 $\le 300$ 行）；vue-tsc 0 错误；Vitest 前端单元测试 100% 绿灯；SDLC 门禁校验通过。

---

## 3. 全局质量门禁核验 (Global Quality Gate)
* **代码风格与静态检查**: `cd miniprogram && pnpm run lint`（强制单组件行数 $\le 300$ 行、单引号、尾随逗号、严禁隐式 any、零 Emoji）；
* **类型与契约安全校验**: `cd miniprogram && pnpm run type-check`（执行 `vue-tsc --noEmit`，确保组件模板属性与 Props 类型 100% 吻合）；
* **全量相关测试回归**: `cd miniprogram && pnpm run test:unit`（全量脱机单元测试毫秒级全绿）；
* **工件与门禁合规检查**: `python3 tooling/check_sdlc_integrity.py`（检查工件完整性与防跳步约束）。

---

## 4. 实施偏差记录 (Deviations Log)
*若实施过程中发现必须调整其他文件，在此记录理由与涉及文件：*
- 记录 1: 为保证 `pages/index/index.vue` 严格遵守 $\le 300$ 行架构红线，将原有页面样式与新增样式抽取至 `pages/index/index.scss` 单独管理，保持组件逻辑极其清爽。
- 记录 2: 快捷上传组件直接引用现有的 `subpackages/material/components/MaterialUpload.vue`，实现跨包复用，避免产生两套上传实现。

---

## 5. 阶段准出签批 (Gate 3 Sign-off)
- [x] 所有分步实施项与验证断言均已就地执行并通过
- [x] 全局质量门禁（Lint / Type / Regression）全部绿灯
- [x] 变更文件与 plan.md 清单完全吻合，无越权修改
- **验收结论**: Approved
- **验证人 / 日期**: TechLead / 2026-09-25 13:15
