# State Management

> **事实源**：`miniprogram/src/stores/{auth,material,folder,practice,diagnosis}.ts`、`miniprogram/src/pages/**`（页面本地状态）
> **最后核对**：2026-09-29
> **核对方式**：`rg "defineStore|createPinia|const .* = ref\(|computed\(" miniprogram/src`

> How state is managed in this project. 本项目用 **Pinia**（Composition API 风格）承载全局状态，页面本地状态用 `ref`。

---

## Overview

- 状态容器为 Pinia。**没有 `src/stores/index.ts`**：`pinia` 实例在 `main.ts` 内 `Pinia.createPinia()` 创建并 `app.use(pinia)`，各 store 直接从 `@/stores/<domain>` 具名导入。
- 全局状态收敛为 **5 个域 store**：`auth` / `material` / `folder` / `practice` / `diagnosis`。
- 每个 store 都是 **setup 风格** `defineStore('<id>', () => { ... })`：`ref` 即 state、`computed` 即 getters、普通/异步函数即 actions，末尾以对象统一 return。
- 文件命名就是 `<domain>.ts`（`auth.ts` / `material.ts` / `folder.ts` / `practice.ts` / `diagnosis.ts`），导出 `useXxxStore`。**没有 `xxxStore.ts` + `xxx.ts` 薄再导出的双层结构**。
- **store 直接调用 `@/api`**：这不是例外而是既定做法——`authStore.fetchProfile` → `apiGetUserProfile`、`materialStore.upload` → `apiUploadMaterial`、`folderStore.loadFolders` → `apiListFolders`、`practiceStore.submit` → `apiSubmitPractice`、`diagnosisStore.loadReport` → `apiGetPracticeSession` + `apiTriggerDiagnosis`。store 承担编排职责（含 loading 标志、错误兜底、状态重置）。
- 网络层与 store **不互相 import**：`request.ts` 需要清会话时用动态 `import('@/stores/auth')` 延迟加载（`handleUnauthorized`），避免循环依赖。

**代码锚点**
- `miniprogram/src/main.ts::createApp`（`Pinia.createPinia()`）
- `miniprogram/src/utils/request.ts::handleUnauthorized`（动态 import store）
- `miniprogram/src/stores/auth.ts::useAuthStore`
- `miniprogram/src/stores/practice.ts::usePracticeStore`

---

## Store Inventory

| Store | State（`ref`） | Getters（`computed`） | Actions |
|---|---|---|---|
| `auth` | `token`（初值取 `uni.getStorageSync('access_token')`）、`user` | 无（`isLoggedIn()` 是**函数**不是 getter） | `setToken` / `clearAuth` / `loginWithWechat` / `fetchProfile` / `updateProfile` |
| `material` | `currentMaterial`、`materialList`、`questions`、`isUploading`、`isGenerating`、`currentKnowledgeTree`、`activeKnowledgePoint`、`activeSnippets` | 无 | `upload` / `triggerParse` / `fetchMaterialDetail` / `pollMaterialStatus` / `loadMaterialList` / `loadKnowledgeTree` / `loadKnowledgePointWithSnippets` / `generateQuestions` / `loadQuestions` |
| `folder` | `folders`、`currentFolderId`（`'all'` \| `'__none__'` \| 真实 id）、`currentFolderKnowledgePoints`、`isLoading` | 无 | `loadFolders` / `createFolder` / `renameFolder` / `archiveFolder` / `loadFolderKnowledgePoints` / `setCurrentFolderId` |
| `practice` | `currentSession`、`currentIndex`、`userAnswers`、`isSubmitting`、`isSavingDrafts`、`draftFailures`、`latestDiagnosis` | `questions`、`attemptResults`、`currentQuestion`、`answeredCount`、`unansweredCount` | `initPractice` / `refreshSession` / `recordAnswer` / `flushDrafts` / `retryDraft` / `retryAllDrafts` / `submit` / `requestRegrade` / `retryGrading` / `selfEvaluate` / `regenerateFromWrongPoints` / `loadPractices` / `askCoach` / `nextQuestion` / `prevQuestion` / `jumpTo` |
| `diagnosis` | `currentReport`、`isLoading`、`isPending` | 无 | `loadReport` / `reset` |

- **`practiceStore.latestDiagnosis` 是死状态**：声明并 return 了，但全仓库无任何写入或读取点（`rg "latestDiagnosis" src tests` 只命中声明与 return）。新增诊断相关状态前请先确认是否该复用它。
- `materialStore` / `folderStore` / `diagnosisStore` 目前**没有 getter**；筛选/派生逻辑要么写成页面 `computed`，要么抽成 `src/**/utils/*.ts` 纯函数（后者是本仓库的主流做法）。

**代码锚点**
- `miniprogram/src/stores/practice.ts::latestDiagnosis`（死状态）
- `miniprogram/src/stores/auth.ts::isLoggedIn`（函数而非 getter）
- `miniprogram/src/pages/index/index.vue::activeFolderDetail`（页面派生 `computed`）

---

## State Categories

| 类别 | 载体 | 示例 |
|---|---|---|
| 全局域状态 | Pinia store | `materialStore.materialList`、`folderStore.folders`、`practiceStore.currentSession` |
| 派生状态 | Pinia getter（`computed`） | `practiceStore.questions` / `attemptResults` / `answeredCount` / `unansweredCount` |
| 页面本地状态 | 页面内 `ref` | `pages/index/index.vue` 的 `showFolderModal` / `folderToRename`；`questions/index.vue` 的 `isConfigMode` / `isLoadingKp` |
| UI 瞬时状态 | 组件内 `ref` | `AiCoachDrawer` 的 `inputQuery` / `isThinking` / `messageList`；`GradingActionModal` 的 `reason` / `scoreInput` |
| 跨页保留的筛选 | `folderStore.currentFolderId` | 工作台课程筛选（`'all'` / `'__none__'` / 课程 id） |
| 会话缓存 | Storage（裸 key，无白名单类型） | `'access_token'`、`practice_draft_<userId>_<practiceId>`、`practice_submit_key_<practiceId>` |

- **`folderStore.archiveFolder` 顺带重置筛选**：归档当前选中课程后，`currentFolderId` 回落 `'all'`。
- **`materialStore.loadMaterialList(folderId)` 做别名清洗**：`folderId === 'all'` 时改传 `undefined`（即不带 `folder_id` 参数）。

**代码锚点**
- `miniprogram/src/stores/folder.ts::archiveFolder`
- `miniprogram/src/stores/material.ts::loadMaterialList`
- `miniprogram/src/stores/practice.ts::getStorageKey`

---

## When to Use Global State

提升到全局 store 的判据：

- **跨页面/跨步骤共享**：课程列表（工作台 ↔ 课程页）、资料列表（工作台 ↔ 课程页）、当前练习会话（出题页 → 作答页 → 结果页 ↔ 学情页）。
- **需要跨页保活的进行中会话**：`practiceStore.currentSession` / `userAnswers` / `draftFailures`，供作答页、结果页、学情页「继续作答」共用。
- **需要跨页保留的筛选**：`folderStore.currentFolderId`。

保持页面本地（不进全局）：

- 分页游标、`loading`、`activeTab`、弹窗开关、表单草稿等仅本页生命周期有意义的状态。

写入约定：

- 状态变更优先走 store action（`setToken` / `clearAuth` / `archiveFolder` / `setCurrentFolderId` / `recordAnswer`…），便于测试与追踪。
- **页面直接给 store 的 `ref` 赋值在既有代码中存在**，属可接受的写法：`pages/profile/index.vue::chooseAvatar` 里 `authStore.user = { ...authStore.user!, avatar_url: profile.avatar_url }`（上传头像后只补一个字段，不必为此加 action）。
- **测试里直接赋 `store.currentSession`** 是 `tests/practice.spec.ts` 的既定模式（`setActivePinia(createPinia())` 后手工构造会话）。

**代码锚点**
- `miniprogram/src/stores/practice.ts::initPractice`
- `miniprogram/src/stores/folder.ts::setCurrentFolderId`
- `miniprogram/src/pages/profile/index.vue::chooseAvatar`
- `miniprogram/tests/practice.spec.ts`（`store.currentSession = {...}`）

---

## Server State

store 中的服务端数据是**前端缓存**，由页面或 store 自身拉取后注入；不引入 react-query/SWR 类库，一致性靠显式刷新与重置保证。

- **注入方式**：`loadXxx()` 调 API → 成功后写 store。全量替换与增量 upsert 并存：`materialStore.materialList` 在 `upload` 里 `unshift`、在 `fetchMaterialDetail` 里按 id 就地替换、在 `loadMaterialList` 里整体替换。
- **重置语义**：切换上下文必须重置，避免旧数据残留。
  - `diagnosisStore.reset()` 清空 `currentReport` 与 `isPending`。
  - `practiceStore.initPractice()` 开头 `draftQueue.reset()`，并按「本地草稿优先、服务端 `user_answers` 其次」重建 `userAnswers`。
  - `practiceStore.regenerateFromWrongPoints()` 成功后重置 `currentIndex` / `userAnswers` 并 `draftQueue.reset()`。
  - `folderStore.archiveFolder()` 从 `folders` 中剔除并重置 `currentFolderId`。
- **幂等**：`practiceStore.submit()` 的提交键在请求前落盘、成功后清理；`diagnosisStore.loadReport` 用 `POST /practices/{id}/diagnosis` 触发/取回（后端按幂等语义处理重复触发）。
- **鉴权失效**：`request.ts::handleUnauthorized` 清 `access_token` 并调用 `authStore.clearAuth()`（`token = ''`、`user = null`、`uni.removeStorageSync('access_token')`），回退未登录态；`authStore.fetchProfile` 自身失败时静默 catch，等待统一拦截处理。

**代码锚点**
- `miniprogram/src/stores/diagnosis.ts::reset`
- `miniprogram/src/stores/practice.ts::initPractice`
- `miniprogram/src/stores/auth.ts::clearAuth`
- `miniprogram/src/utils/request.ts::handleUnauthorized`

---

## Common Mistakes

- **不要以为 store 不能发请求**：本仓库的 store 就是编排层，5 个 store 都直连 `@/api`。真正要避免的是「在 `<script setup>` 里散落请求逻辑却不管 loading / 错误 / 状态重置」。
- **不要在 store 里 import `request.ts` 去绕开 `@/api`**：网络出口经 `src/api/index.ts`，那里才有 adapter 归一化。
- **不要忘记 `draftQueue.reset()`**：切换练习（`initPractice`）或再生题（`regenerateFromWrongPoints`）时必须重置队列，否则上一练习的待写草稿会串到新练习。
- **不要在未全卷判完时写 `currentReport`**：`diagnosisStore` 的 `isPending` 语义就是「报告还不存在」，伪造零分报告会在结果页渲染出全错的假象。
- **不要用 `practiceStore.latestDiagnosis`**：它是死状态，诊断报告的数据源是 `diagnosisStore.currentReport`。
- **不要假设存在 `stores/index.ts`**：没有聚合入口，从 `@/stores/<domain>` 直接导入。

**代码锚点**
- `miniprogram/src/stores/practice.ts::initPractice`
- `miniprogram/src/stores/diagnosis.ts::isPending`
- `miniprogram/src/stores/material.ts`（store 直连 `@/api` 的先例）
