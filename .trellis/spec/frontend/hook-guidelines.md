# Hook Guidelines

> **事实源**：`miniprogram/src/subpackages/**/composables/*`、`miniprogram/src/subpackages/practice/composables/usePracticeSession.ts`
> **最后核对**：2026-09-28 @ ca062a1
> **核对方式**：`rg "export function use|getCurrentInstance\(\)|onUnmounted" miniprogram/src`

> How hooks（组合式函数）are used in this project. 前端使用 Vue 3 Composition API 的 `composables` 承载有状态复用逻辑。

---

## Overview

- 组合式函数位于各分包的 `composables/` 目录，命名统一 `useXxx`，采用**具名导出**（无默认导出）。
- 输入优先采用**选项对象**（`options: { ... }`）并解构默认值；输出为普通对象，内含 `ref` / `computed` / 方法，供页面或组件解构使用。
- 组合式函数是**网络调用**的合法发起方（与「Store 不发请求」铁律互补）：内部直接调用 `src/api/*`，再由页面消费。
- 定时器/副作用必须可释放：轮询与动画类组合式函数在 `getCurrentInstance()` 存在时注册 `onUnmounted` 清理；无组件实例（如被纯函数测试调用）时跳过注册。

**代码锚点**
- `miniprogram/src/subpackages/material/composables/useMaterialPolling.ts::useMaterialPolling`
- `miniprogram/src/subpackages/practice/composables/usePracticeSession.ts::usePracticeSession`

---

## Custom Hook Patterns

现有 6 个组合式函数与其契约：

| 组合式函数 | 选项/入参 | 返回值（节选） | 生命周期 |
|---|---|---|---|
| `useMaterialPolling` | `materialId: Ref<string>\|string`，`options: UseMaterialPollingOptions` | `status`、`materialData`、`isPolling`、`error`、`startPolling`、`stopPolling` | `onUnmounted` 自动 `stopPolling` |
| `useMaterialListPolling` | `{ items, isPageVisible, onItemUpdated }` | `stopPolling`、`checkAndStartPolling`、`isPending` | `onUnmounted` 自动 `stopPolling` |
| `useGenerationProgress` | `{ stages?, stageInterval?, tickInterval? }` | `stages`、`stageIndex`、`elapsedSeconds`、`isRunning`、`currentStage`、`start`、`stop` | `onUnmounted` 自动 `stop` |
| `useMaterialCardActions` | `{ refresh }` | `handleCardClick/Delete/Retry/TriggerParse` | 无定时器 |
| `useMaterialFolderMove` | `{ listData }` | `moveVisible`、`moveTarget`、`loadMoveTargets`、`handleOpenMove`、`handleMoveSelect` | 无定时器 |
| `usePracticeSession` | 无 | `practiceId`、`loading`、`loadPractice`、`handleAnswerChange`、`flushPendingDraft`、`pauseSession`、`resumeSession`、`cleanupSession` | 由页面显式调用 `cleanupSession` |

约定要点：

- **选项默认值在函数体解构**：`const { interval = 1500, backoffFactor = 1.5, maxInterval = 8000, maxTimeout = 180000, immediate = true } = options`。
- **返回值聚合成单对象**，不返回元组；调用方按需解构。
- **可测性**：涉及定时器的组合式函数通过 `getCurrentInstance()` 守卫注册 `onUnmounted`，使单元测试可在组件外直接调用（见 `tests/unit/composables/useMaterialPolling.spec.ts`）。
- **无组件的会话型组合式函数**（`usePracticeSession`）不自行注册卸载钩子，改由页面在 `onUnload`/`onBeforeUnmount` 调用 `cleanupSession()` 收尾。

**代码锚点**
- `miniprogram/src/subpackages/material/composables/useMaterialPolling.ts::UseMaterialPollingOptions`
- `miniprogram/src/subpackages/material/composables/useMaterialListPolling.ts::useMaterialListPolling`
- `miniprogram/src/subpackages/material/composables/useGenerationProgress.ts::GENERATION_STAGES`
- `miniprogram/src/subpackages/practice/pages/session/index.vue::onUnload`
- `miniprogram/tests/unit/composables/useMaterialPolling.spec.ts`

---

## Data Fetching

- 网络调用统一经 `src/api/*`（如 `fetchMaterialStatus`、`fetchPracticeSession`、`saveAnswerDraft`）。组合式函数**不直接**使用 `uni.request`。
- **轮询必须自适应退避 + 超时熔断**，禁止固定间隔死循环：
  - 单条目 `useMaterialPolling`：初始 `1500ms`，`t_{next} = min(t × 1.5, 8000)`，默认 `180000ms`（3 分钟）熔断，超时 `stopPolling()` 并 toast「解析等待超时，请稍后刷新查看」；命中终态（`COMPLETED`/`READY`/`FAILED`/`RETAKE_REQUIRED`）立即停止。
  - 列表 `useMaterialListPolling`：同样 `1.5x` 退避、上限 `8000ms`、`180000ms` 超时；页面 `isPageVisible=false` 或不再有 pending 项时停止；对 pending 项并发 `Promise.allSettled`，结果原地合并并回调 `onItemUpdated`。
- **草稿远端同步**（`usePracticeSession`）：`handleAnswerChange` 先写 store、再写本地 Storage、最后 `setTimeout(..., 600)` 防抖同步远端；`flushPendingDraft()` 在会话卸载前立即冲刷，靠 `pendingSync` 的**身份引用**判定回调有效性，避免慢请求覆盖新作答。
- **暂停/恢复**：`pauseSession` 先停本地计时再 `POST /practices/{id}/pause`，失败则重启计时；`resumeSession` 先 `POST /practices/{id}/resume` 再重启计时。
- 组合式函数内的失败处理：可降级的静默忽略（如列表轮询、移动目标加载），主流程失败必须 toast。

**代码锚点**
- `miniprogram/src/subpackages/material/composables/useMaterialPolling.ts::scheduleNext`
- `miniprogram/src/subpackages/material/composables/useMaterialPolling.ts::handleTimeout`
- `miniprogram/src/subpackages/material/composables/useMaterialListPolling.ts::pollPendingItems`
- `miniprogram/src/subpackages/practice/composables/usePracticeSession.ts::flushPendingDraft`
- `miniprogram/src/subpackages/practice/composables/usePracticeSession.ts::syncSingleDraft`
- `miniprogram/src/subpackages/practice/composables/usePracticeSession.ts::pauseSession`
- `miniprogram/src/api/practice.ts::pausePractice`

---

## Naming Conventions

- 文件名与函数名同为 `camelCase` 的 `useXxx`（`useMaterialPolling.ts` → `useMaterialPolling`）。
- 返回的方法以 `handle*` 前缀命名交互回调（`handleCardClick`、`handleMoveSelect`、`handleAnswerChange`）；轮询控制用 `startPolling`/`stopPolling`/`checkAndStartPolling`。
- store 实例变量小写驼峰（`materialStore`、`folderStore`、`practiceStore`）。
- 选项接口命名 `UseXxxOptions`；返回接口（若显式声明）命名 `UseXxxReturn`。

**代码锚点**
- `miniprogram/src/subpackages/material/composables/useMaterialCardActions.ts::UseMaterialCardActionsOptions`
- `miniprogram/src/subpackages/material/composables/useGenerationProgress.ts::UseGenerationProgressReturn`

---

## Common Mistakes

- **不要用固定 `setInterval` 长期轮询**：必须 `setTimeout` 调度 + 退避 + 超时熔断，否则客户端卡顿、服务端压力激增。
- **不要在非组件上下文中无脑调用 `onUnmounted`**：必须 `if (getCurrentInstance())` 守卫，否则测试环境报错。
- **不要在卸载时丢弃待同步草稿**：`cleanupSession` 必须触发 `flushPendingDraft()`，且同步完成回调用身份令牌判定，不能按 `questionId` 判等（新作答会被旧回调误标已同步而丢失）。
- **不要让轮询在终态/页面隐藏后继续**：命中终态或 `isPageVisible=false` 必须立即清定时器。
- **不要在组合式函数里直接改全局状态而不经 store action**：状态变更统一走对应 store 的 action。

**代码锚点**
- `miniprogram/src/subpackages/practice/composables/usePracticeSession.ts::pendingSync`
- `miniprogram/src/subpackages/practice/composables/usePracticeSession.ts::cleanupSession`
- `miniprogram/src/subpackages/material/composables/useMaterialListPolling.ts::stopPolling`
