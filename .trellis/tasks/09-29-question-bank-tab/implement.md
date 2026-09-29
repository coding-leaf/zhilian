# 题库 Tab 重构：执行计划

## 前置检查（开工前必做）

- [ ] `python ./.trellis/scripts/task.py current` 确认活动任务是本任务。
- [ ] 读 `docs/DESIGN.md` §6（单 `.vue` ≤300 行硬约定）与 `spec/frontend/index.md` 的「已知偏离」。
- [ ] 记录 `wc -l src/pages/review/index.vue`（**基线 252 行**）——
      每一步之后要能证明没有越界。
- [ ] 确认 `pages/review/index.vue` 里 `buildWrongGroupOptions` 的**全部**引用点
      （决策 7：它服务错题 chips 与举一反三，**不能**跟着「归属范围」一起删）。

## 实施顺序

**顺序是刻意的：先做纯搬家与纯修复，最后才动骨架。**
每一步单独提交，出问题时能立刻定位是哪一步引入的。

### 1. 纯搬家：抽出 `WrongSection.vue`（行为必须不变）

- [ ] 把「错题巩固 + 错题列表」整段（含范围 chips、举一反三入口、`WrongRecordCard` 列表）
      搬到 `src/pages/review/components/WrongSection.vue`。
- [ ] 只搬不改：文案、条件分支、事件、样式类名逐一对齐。
- [ ] 跑既有用例确认零回归（`tests/diagnosisAndCompose.spec.ts` 覆盖到 review 页）。
- [ ] 记录搬家后 `wc -l` 两个文件的数值。

### 2. 修 F2：两处吞错误（决策 4）

- [ ] `loadWrongs` / `loadPractices` 两处 catch：保留 `console.error`，**新增**区块级 `loadError`。
- [ ] 失败态渲染成失败卡片（说明 + 重试），**不得渲染成空态**。
- [ ] 错误分类走 `src/utils/requestError.ts` 的 `RequestError` / `RequestErrorKind`，
      **不按 `error.message` 字符串判断**。
- [ ] 补用例：失败态与空态可区分；重试动作可再次触发加载。**两处都要有**。

### 3. F1 防回归测试（决策 6，**只加测试，不改实现**）

- [ ] 后端新增测试：`items` 每条的 `material_id`/`folder_id` 与 `groups` 的归属一致。
- [ ] **变异验证**：临时移除 `app/api/v1/diagnosis.py:338-350` 的回填，确认该测试**失败**
      → 恢复回填，确认通过。**没有这一步就不算完成**（否则无法排除「写了测试但永远不会失败」）。
- [ ] 清理临时改动，`git diff` 确认只剩测试文件。

### 4. 骨架改动：删 summary 卡 + 定区块顺序（决策 1）

- [ ] 删除 summary 卡模板与样式（`summary-card` / `stats-row` / `stat-col` / `stat-divider`）。
- [ ] 「待攻克 N · 已消灭 M」搬到错题区块标题。
- [ ] 区块顺序改为：**我的题目 → 错题与举一反三 → 我的练习**。
- [ ] 清理 `groupOptions.length` 的引用，但**保留** `buildWrongGroupOptions`（决策 7）。
- [ ] `task verify-frontend` 全绿（eslint / vue-tsc 能抓出删引用留下的死代码与未用 import）。

### 5. 空态三档（决策 5）

- [ ] 引入 `hasActivity = practices.length > 0 || wrongRecords.length > 0 || batchTotal > 0`。
- [ ] 三档互斥：`!hasActivity && !loadError` → 全新用户引导；
      `hasActivity && 无错题` → 说明依据的正向语；`loadError` → 失败态。
- [ ] **失败优先级高于空态**（决策 5 明确点出的易错点）：
      三个请求全失败时 `length` 也都是 0，若不先判 `loadError` 就会把故障伪装成「全新用户」。
- [ ] 删掉「太棒了！当前范围内没有待巩固的错题。」这类**伪正向**文案（未做过练习时不得出现）。
- [ ] 补用例：三档各自的判据与互斥性；**「三个请求全失败」不得落入全新用户档**。

### 6. tabBar 与标题改名（决策 3）

- [ ] `src/pages.json`：tabBar `text` 与 `navigationBarTitleText` 同改。
- [ ] 页面内部标题文案同步。
- [ ] **三处必须一致**，否则出现「标签写题库、标题写学情」的混称。

### 7. 挂载题库区块（**依赖 `09-29-question-bank-page`**）

- [ ] 在页面上部挂 `<QuestionBankSection />`，由该子任务提供组件与数据加载。
- [ ] 容器样式与既有 `.paper-card` 一致，不与该子任务自带的样式重复定义。
- [ ] 确认它的加载失败**只影响该区块**（区块级失败隔离，决策 7）。
- [ ] 它的批次总数透出给本任务用于 `hasActivity` 判定（`batchTotal`）。

### 8. 门禁与端到端

```bash
task verify   # 后端 + 前端
```

- [ ] `task verify` 退出码 0。
- [ ] `wc -l src/pages/review/index.vue` **≤300**（硬约定）；新增/改动组件同样 ≤300。
- [ ] 既有用例零回归（尤其 `tests/diagnosisAndCompose.spec.ts`）。

## 风险点与回滚

| 风险 | 症状 | 处理 |
| --- | --- | --- |
| 三个请求全失败被当成「全新用户」 | 故障伪装成空态，用户被引去「导入资料」而实际是接口挂了 | 决策 5：失败优先级高于空态，专门用例覆盖 |
| 一个区块失败渲染成整页失败 | 「我的练习拉取失败」变成「整页打不开」 | 区块级失败隔离（决策 7） |
| 删「归属范围」时误删 `buildWrongGroupOptions` | 错题 chips 与举一反三范围解析一起坏掉 | 第 0 步先列全部引用点；它服务的不止 summary 卡 |
| `index.vue` 越 300 行 | 违反硬约定，且既有 5 个文件已超标 | 第 1 步先搬家；每步后记录 `wc -l` |
| 改名只改一处 | 标签与标题混称 | 第 6 步三处同改，一次提交 |
| F1 测试不会失败 | 变异验证不通过，等于没测 | 第 3 步强制做变异验证 |

**回滚**：前端纯改动，回滚 = 恢复 `pages/review/index.vue` 与组件目录。
`get_wrong_record_scopes` 全程不动，**回滚不影响已修复的 F1**。
后端唯一改动是一个新增测试文件，回滚无副作用。

## 收口时必须重核（对应 PRD XAC-5）

- [ ] 在「零数据 / 有数据 / 请求失败」三种状态下**各走一遍**，逐段记录
      「用户此刻能不能看懂这一屏在说什么、下一步该做什么」。
- [ ] 特别重核**用户说重构好了**是否真的成立——父批次已被同类问题坑过一次
      （「足迹存在」但实际少算一半，「数字不是 0」不等于修好了）。
- [ ] `09-29-review-page-ia` 归档后，确认它的两条结论（F1 已修 / F2 待修）
      在本任务里各自有了归宿，没有悬空。
