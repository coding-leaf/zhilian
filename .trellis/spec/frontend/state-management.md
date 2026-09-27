# State Management

> **事实源**：`miniprogram/src/stores/*`、`miniprogram/src/subpackages/**/pages/*`（页面本地状态）
> **最后核对**：2026-09-28 @ ca062a1
> **核对方式**：`rg "defineStore|createPinia|addMaterial|setMaterialsList" miniprogram/src`

> How state is managed in this project. 本项目用 **Pinia**（Composition API 风格）承载全局状态，页面本地状态用 `ref`。

---

## Overview

- 状态容器为 Pinia，注册入口与统一导出在 `src/stores/index.ts`：`export const pinia = createPinia()`，并 `export *` 全部 store。
- 全局状态**收敛为 5 个域 store**（`index.ts` 注释明确「exactly 5 stores」）：`user`、`material`、`folder`、`practice`、`report`。
- 每个 store 用 **setup 风格** `defineStore('<id>', () => { ... })`：`ref` 为 state、`computed` 为 getters、普通函数为 actions，末尾以对象统一 return。
- store 实现文件为 `xxxStore.ts`，另有 `xxx.ts` 薄再导出（`user/material/practice/report` 有；`folder` 无）。
- **铁律：Store 不发网络请求**（各 store 头部注释「pure state mutation without direct network API calls」）。网络由页面/组件/composable 经 `src/api/*` 发起，再把结果注入 store。
  - 已知例外：`userStore.hydrateProfile()` 会调用 `fetchUserProfile()` 做鉴权静默水合；这是刻意的鉴权例外，需与「store 不发请求」的其余部分区分理解。

**代码锚点**
- `miniprogram/src/stores/index.ts::pinia`
- `miniprogram/src/stores/userStore.ts::hydrateProfile`
- `miniprogram/src/stores/material.ts`（薄再导出）
- `miniprogram/src/stores/folderStore.ts::useFolderStore`

---

## State Categories

| 类别 | 载体 | 示例 |
|---|---|---|
| 全局域状态 | Pinia store | `materialStore.materials`、`folderStore.folders`、`reportStore.currentReport`、`practiceStore.drafts` |
| 派生状态 | Pinia getter（`computed`） | `materialStore.unclassifiedMaterials`、`reportStore.masteryTier`、`practiceStore.progressPercentage` |
| 页面本地状态 | 页面内 `ref` | 列表页 `listData`、`page`、`loading`；题目页 `listData`、`total`、`activeBatchId` |
| UI 瞬时状态 | 组件内 `ref` | 抽屉 `visible`、`submitting`、`moveVisible` |
| 会话缓存 | Storage（白名单 3 键） | `auth_tokens`、`practice_drafts`、`user_settings` |

- **Page-local 分页数据与全局概览切片隔离**：二级列表页维护自己的 `listData`，仅对全局 `materialStore` 做增量 `addMaterial`，**禁止**用分页结果全量覆盖首页概览。首页概览只由 `setMaterialsList`（5 条精简视图）填充。
- `materialStore` 同时提供 `setMaterials`/`setMaterialsList`（全量替换）、`addMaterial`（按 id upsert）、`appendMaterialsList`（追加）、`removeMaterial`/`updateMaterialFolder`（本地剔除/改归属，不发请求）。

**代码锚点**
- `miniprogram/src/subpackages/material/pages/list/index.vue::listData`
- `miniprogram/src/subpackages/material/pages/list/index.vue::loadData`
- `miniprogram/src/stores/materialStore.ts::addMaterial`
- `miniprogram/src/stores/materialStore.ts::unclassifiedMaterials`
- `miniprogram/src/pages/index/index.vue::recentMaterials`

---

## When to Use Global State

提升到全局 store 的判据：

- **跨页面共享**：首页、列表页、详情页都读的资料集合 / 课程列表。
- **需要跨页保留的会话**：`practiceStore.sessionId`/`questions`/`drafts` 在练习页与报告页、首页「继续练习」之间共享。
- **报告与错题本**：`reportStore.currentReport`/`wrongRecords` 在报告详情页与错题本页共享。

保持页面本地（不进全局）：

- 分页游标、`loading`、`activeTab`、抽屉开关、表单草稿等**仅本页生命周期有意义**的状态。
- 筛选条件若需跨页保留则进 store（`reportStore.wrongFilters`），否则留在页面。

写入约定：

- 状态变更优先走 store action（`setXxx`/`addXxx`/`toggleXxx`/`reset`），便于测试与追踪。
- 已存在的直接赋值先例：练习页对 `practiceStore.isSubmitting` 直接赋值（`session/index.vue`），属于可直接 `ref` 语义的简单标志位；新增复杂状态仍应走 action。

**代码锚点**
- `miniprogram/src/stores/practiceStore.ts::initSession`
- `miniprogram/src/stores/reportStore.ts::setReport`
- `miniprogram/src/stores/reportStore.ts::setWrongFilters`
- `miniprogram/src/subpackages/practice/pages/session/index.vue`（`practiceStore.isSubmitting = true`）

---

## Server State

store 中的服务端数据是**前端缓存**，由页面拉取后注入；不引入 react-query/SWR 类库，缓存一致性靠显式刷新与增量合并保证。

- **注入方式**：页面 `loadXxx()` 调 API → 成功后 `store.setXxx(...)` / `store.addXxx(...)`。
- **增量合并**：`materialStore.addMaterial` 按 id upsert（存在则替换、否则 `unshift`）；列表页追加分页时按 id 去重后再 `append`。
- **重置语义**：切换上下文必须重置，避免旧数据残留。
  - `reportStore.setReport(null/无 weak_points)` 会把 `weakPoints` 重置为 `[]`。
  - `materialStore.clearKnowledgeState()` 切换资料前清空知识树、选中集与折叠态。
  - `practiceStore.clearSession(id)` 删除指定草稿并清空会话，但保留其他练习草稿。
- **令牌同步**：`userStore` 通过 `setTokenRefreshListener` 订阅请求层的静默刷新结果，刷新成功后同步内存 `tokens`；`request.ts` 不 import store，避免循环依赖。
- **鉴权失效**：`hydrateProfile` 捕获 401/20001 时 `clearTokens()` + `clearProfile()`，回退未登录态。

**代码锚点**
- `miniprogram/src/stores/userStore.ts::setTokenRefreshListener`
- `miniprogram/src/stores/reportStore.ts::setReport`
- `miniprogram/src/stores/materialStore.ts::clearKnowledgeState`
- `miniprogram/src/stores/practiceStore.ts::clearSession`
- `miniprogram/src/utils/request.ts::setTokenRefreshListener`

---

## Common Mistakes

- **用二级列表的分页结果全量覆盖全局 Store**：会冲空首页的 5 条概览切片。列表页必须维护本地 `listData`，只对全局做 `addMaterial` 增量。
- **在 store 内发网络请求**：除 `userStore.hydrateProfile` 这一鉴权例外，其余 store 不得直连 API；网络经页面/composable → `src/api/*`。
- **切换资料不重置知识树状态**：进入新资料前必须 `clearKnowledgeState()`，否则旧的选中/折叠态跨资料泄漏。
- **`setReport` 不清理旧 `weak_points`**：新报告无 `weak_points` 时必须重置为 `[]`，否则残留上一份报告的薄弱点。
- **越过 store 直接改共享数组**：应从 store 返回的 action 变更，保持响应式与可测性。

**代码锚点**
- `miniprogram/src/stores/materialStore.ts::clearKnowledgeState`
- `miniprogram/src/stores/reportStore.ts::setReport`
- `miniprogram/src/subpackages/material/pages/list/index.vue::loadData`
- `miniprogram/src/stores/folderStore.ts`（头部「Store 内严禁发网络请求」注释）
