# Plan: 错题本与一键继续练习交互模块 - 实施计划

- **关联 Spec**: ZL-136
- **实施执行人 / Agent**: TechLead
- **当前状态**: Draft / Approved / In-Execution / Completed

---

## 1. 变更文件清单 (Files that change)

### 1.1 新增文件清单 (New Files)
1. `miniprogram/src/subpackages/report/utils/wrongBookFormat.ts`：纯函数计算核（错误类型映射、攻克状态色彩映射、答错次数格式化、离线过滤器、UUID 幂等键生成、纯函数防抖器）；
2. `miniprogram/src/subpackages/report/components/WrongRecordFilterBar.vue`：多维筛选栏组件（攻克状态 Tab、知识点筛选、题型筛选胶囊、错误类型胶囊）；
3. `miniprogram/src/subpackages/report/components/WrongRecordFilterBar.scss`：多维筛选栏独立样式表；
4. `miniprogram/src/subpackages/report/components/WrongRecordCard.vue`：错题简报卡片组件（四类错误色盘、连续答错次数徽章、原题快照、作答答案比对折叠、一键攻克标记切换、多选勾选）；
5. `miniprogram/src/subpackages/report/components/WrongRecordCard.scss`：错题卡片独立样式表；
6. `miniprogram/src/subpackages/report/components/ContinuePracticeBar.vue`：通用吸底防抖防重继续练习栏组件（500ms 防抖、UUID 幂等键防重、按钮 loading 态与防重锁、多选统计文案、会话承接并跳转）；
7. `miniprogram/src/subpackages/report/components/ContinuePracticeBar.scss`：吸底操作栏独立样式表；
8. `miniprogram/src/subpackages/report/pages/wrong-book/index.vue`：错题本分包主装配页面（生命周期、下拉刷新、触底分页加载、空状态与骨架屏）；
9. `miniprogram/src/subpackages/report/pages/wrong-book/wrongBook.scss`：错题本主页面独立样式表；
10. `miniprogram/tests/unit/report/wrongBookFormat.spec.ts`：纯函数计算核单元测试（分支覆盖率 100%）；
11. `miniprogram/tests/unit/report/wrongRecordComponents.spec.ts`：错题筛选栏与错题卡片组件单元测试；
12. `miniprogram/tests/unit/report/continuePracticeBar.spec.ts`：吸底防抖防重继续练习栏单元测试；
13. `miniprogram/tests/unit/report/wrongBookPage.spec.ts`：错题本主页面装配、路由加载与流转交互单元测试。

### 1.2 修改文件清单 (Modified Files)
1. `miniprogram/src/types/report.ts`：扩充对齐 `ErrorType`, `ErrorTypeInfo`, `ResolvedStatusInfo`, `WrongRecordItem` 完整字段（`question_snapshot`, `error_count`, `wrong_count`, `first_wrong_at`, `mastered_at`）及 `WrongRecordQueryParams`；
2. `miniprogram/src/api/diagnosis.ts`：新增 `markWrongRecordMastered` 与 `deleteWrongRecord` API 函数，完善 `continuePractice` 幂等参数；
3. `miniprogram/src/stores/reportStore.ts`：增加错题列表缓存 `wrongRecords`、总数 `wrongRecordTotal`、多选勾选集 `selectedRecordIds` 与纯状态修改 actions；
4. `miniprogram/src/subpackages/report/pages/detail/index.vue`：重构引入 `ContinuePracticeBar` 替换原行内原生按钮，将页面行数由 297 行精简至 245 行左右；
5. `miniprogram/src/pages.json`：在 `subpackages/report` 分包中注册 `pages/wrong-book/index` 页面；
6. `miniprogram/tests/unit/api/diagnosis.spec.ts`：追加新增错题 API 的单元测试；
7. `miniprogram/tests/unit/stores/report.spec.ts`：追加错题缓存与状态变更的单元测试；
8. `miniprogram/tests/unit/report/reportDetailPage.spec.ts`：更新对 `ContinuePracticeBar` 接驳后的测试断言。

---

## 2. 伴随式分步实施与验证 (Step-by-Step Implementation Loops)

### Milestone 1: 契约类型、API 扩展与纯函数计算核 (Contracts, API & Pure Functions)
* **操作目标**: 扩展 `report.ts` 类型契约，补齐 `api/diagnosis.ts` 中的错题攻克与删除端点，实现 `wrongBookFormat.ts` 纯函数计算核（错误类型映射、攻克状态色盘映射、答错次数格式化、纯函数离线过滤、UUID v4 幂等键生成与通用防抖器）。
* **涉及文件**:
  - `miniprogram/src/types/report.ts`
  - `miniprogram/src/api/diagnosis.ts`
  - `miniprogram/src/subpackages/report/utils/wrongBookFormat.ts`
  - `miniprogram/tests/unit/report/wrongBookFormat.spec.ts`
  - `miniprogram/tests/unit/api/diagnosis.spec.ts`
* **局部验证命令**:
  ```bash
  cd miniprogram && pnpm vitest run tests/unit/report/wrongBookFormat.spec.ts tests/unit/api/diagnosis.spec.ts
  ```
* **预期判据**: 纯函数测试与 API 单元测试全部通过，纯函数分支覆盖率达 100%（覆盖四类错误、未定义降级、已攻克/未攻克色彩映射、次数格式化边界、离线多条件与组合过滤、UUID v4 正则格式匹配、防抖延时与取消机制）。

### Milestone 2: 错题多维筛选栏与错题卡片组件 (FilterBar & WrongRecordCard)
* **操作目标**: 依据 DESIGN.md 规范开发 `WrongRecordFilterBar.vue` 与 `WrongRecordCard.vue`。实现攻克状态 Tab（全部/待攻克/已攻克）、知识点联动选择、题型筛选胶囊与四类错误类型胶囊；实现错题卡片四类错误低饱和色盘展示、累计答错次数徽章、原题快照、作答与标准答案比对折叠、一键攻克标记切换按键与多选复选框。
* **涉及文件**:
  - `miniprogram/src/subpackages/report/components/WrongRecordFilterBar.vue`
  - `miniprogram/src/subpackages/report/components/WrongRecordFilterBar.scss`
  - `miniprogram/src/subpackages/report/components/WrongRecordCard.vue`
  - `miniprogram/src/subpackages/report/components/WrongRecordCard.scss`
  - `miniprogram/tests/unit/report/wrongRecordComponents.spec.ts`
* **局部验证命令**:
  ```bash
  cd miniprogram && pnpm vitest run tests/unit/report/wrongRecordComponents.spec.ts
  ```
* **预期判据**: 组件测试全部通过，覆盖筛选条件切换触发 `filter-change` 事件、错题卡片折叠展开作答对比、点击攻克切换触发乐观事件与按压缩放 `scale(0.985)` 样式。

### Milestone 3: 吸底防抖防重继续练习操作栏与多端复用 (ContinuePracticeBar & Detail Refactor)
* **操作目标**: 开发通用的 `ContinuePracticeBar.vue` 吸底组件，内置 500ms 纯函数防抖、UUID v4 幂等键防重、按钮 loading 与防重锁，成功后由 `practiceStore` 承接会话并跳转答题页面；重构 `subpackages/report/pages/detail/index.vue` 引入该组件替换原有原生按钮，消减页面行数规避 300 行超限红线。
* **涉及文件**:
  - `miniprogram/src/subpackages/report/components/ContinuePracticeBar.vue`
  - `miniprogram/src/subpackages/report/components/ContinuePracticeBar.scss`
  - `miniprogram/src/subpackages/report/pages/detail/index.vue`
  - `miniprogram/tests/unit/report/continuePracticeBar.spec.ts`
  - `miniprogram/tests/unit/report/reportDetailPage.spec.ts`
* **局部验证命令**:
  ```bash
  cd miniprogram && pnpm vitest run tests/unit/report/continuePracticeBar.spec.ts tests/unit/report/reportDetailPage.spec.ts
  ```
* **预期判据**: 测试全部通过，验证 500ms 内连续双击仅触发一次 API 调用、UUID 幂等键正常生成、成功响应后正确调用 `practiceStore.initSession` 并触发页面跳转；`detail/index.vue` 行数降低至 250 行以内。

### Milestone 4: 错题本主页面装配、分包路由注册与 Pinia 状态流转 (WrongBookPage & Pinia Flow)
* **操作目标**: 扩展 `reportStore.ts` 增加错题列表缓存与筛选勾选状态；在 `pages.json` 中将 `subpackages/report/pages/wrong-book/index` 注册至 `subpackages/report` 分包；开发 `wrong-book/index.vue` 组装筛选栏、卡片列表、空状态占位、骨架屏与吸底继续练习栏，支持下拉刷新与触底分页追加（每页 20 条）。
* **涉及文件**:
  - `miniprogram/src/stores/reportStore.ts`
  - `miniprogram/src/pages.json`
  - `miniprogram/src/subpackages/report/pages/wrong-book/index.vue`
  - `miniprogram/src/subpackages/report/pages/wrong-book/wrongBook.scss`
  - `miniprogram/tests/unit/stores/report.spec.ts`
  - `miniprogram/tests/unit/report/wrongBookPage.spec.ts`
* **局部验证命令**:
  ```bash
  cd miniprogram && pnpm vitest run tests/unit/stores/report.spec.ts tests/unit/report/wrongBookPage.spec.ts
  ```
* **预期判据**: 错题本页面与 Store 测试全部通过，分页加载、下拉刷新、攻克标记乐观更新、勾选多题并点击底部继续练习流转顺畅。

### Milestone 5: 全链路端到端集成、Lint/Type 门禁与工程闭环 (E2E Integration & Verification Gates)
* **操作目标**: 运行全量单元测试套件、`vue-tsc` 类型严格检查、ESLint 代码规范扫描以及小程序全量生产打包构建，验证主包体积维持在 2MB 以内，单组件代码行数严格 <= 300 行，零 Unicode Emoji，Storage 零错题持久化。
* **涉及文件**: 全量新增与修改文件。
* **局部验证命令**:
  ```bash
  cd miniprogram && pnpm run test:unit && pnpm run type-check && pnpm run lint && pnpm run build:mp-weixin
  ```
* **预期判据**: 全量单元测试 100% 通过（测试数达 330+）；`vue-tsc --noEmit` 0 error；`eslint` 0 error；生产打包成功且无体积违规；`python3 tooling/check_sdlc_integrity.py` 退出码 0。

---

## 3. 风险分析与规避预案 (Risks & Mitigations)

| 风险场景 | 影响程度 | 规避与处置方案 |
| :--- | :--- | :--- |
| **弱网快速重复连击继续练习** | 中 | 前端 500ms 纯函数防抖 + `isSubmitting` 禁用锁 + UUID v4 幂等键 + 后端 `source_report_id` 未开始同来源练习防重合并 (FR-58)。 |
| **错题卡片内容展开导致长列表卡顿** | 低 | 采用分页加载机制（单页 20 条），避免一次性加载过多 DOM 节点；答案对比默认折叠，按需展开。 |
| **组件代码行数超标 (>300行)** | 高 (违背红线) | 严格抽离独立 SCSS 样式文件；`detail/index.vue` 剥离 `ContinuePracticeBar`；`wrong-book/index.vue` 剥离 `FilterBar` 与 `Card`，确保单文件均在 250 行以内。 |
| **错题文本意外持久化至本地 Storage** | 高 (违背安全红线) | 错题本数据全量托管于 Pinia `reportStore` 内存中，严禁调用 `storage.set` 写入错题相关数据，Storage 守护白名单强阻断。 |

---

## 4. 完成判据与验收证据 (Proof & Verification Criteria)

* **客观证据 1 (单元测试全绿)**:
  `cd miniprogram && pnpm run test:unit` 全部通过，纯函数计算核分支覆盖率 100%。
* **客观证据 2 (类型与规范 0 Error)**:
  `cd miniprogram && pnpm run type-check` 与 `pnpm run lint` 退出码 0，无任何 TypeScript 类型错误与 ESLint 错误。
* **客观证据 3 (生产打包合规)**:
  `cd miniprogram && pnpm run build:mp-weixin` 编译成功，分包 `subpackages/report` 正常打包，主包体积保持在 2MB 以内。
* **客观证据 4 (门禁合规检查通过)**:
  `python3 tooling/check_sdlc_integrity.py` 输出 `✅ 门禁检查通过，工件完整规范`，退出码 0。

---

## 5. 阶段准出签批 (Gate 3 Sign-off)
- [x] 变更文件清单完整清晰
- [x] 里程碑分步实施与局部验证命令配对完备
- [x] 风险预案与完成判据客观可量化
- **准出结论**: Approved
- **签批人 / 日期**: TechLead / 2026-09-25 11:42
