# Hook Guidelines

> **事实源**：`miniprogram/src/subpackages/material/composables/useQuestionCompose.ts`、`miniprogram/tests/diagnosisAndCompose.spec.ts`
> **最后核对**：2026-09-29
> **核对方式**：`rg "export function use|composables/" miniprogram/src`

> How hooks（组合式函数）are used in this project. 前端使用 Vue 3 Composition API 的 `composables` 承载有状态复用逻辑。

---

## Overview

- 组合式函数位于分包的 `composables/` 目录，命名统一 `useXxx`，采用**具名导出**（无默认导出）。
- **当前全仓库只有 1 个组合式函数**：`src/subpackages/material/composables/useQuestionCompose.ts`（组卷配置与出题/覆盖率门禁）。`stores/practice`、`stores/material` 等承担编排职责的代码都在 store 里，没有对应的 `use*` 包装。
- 该函数**不接收入参**（不是选项对象形式）：作用域通过返回的 `setScope({ folderId, materialId })` 在 `onLoad` 后注入。
- 返回值为**单一普通对象**，内含 `ref` / `computed` / 方法；调用方（页面）解构后使用。
- **没有定时器、没有 `onUnmounted`、没有 `getCurrentInstance()` 守卫**：该组合式函数是纯状态 + 异步动作，不需要生命周期收尾。全仓库 `rg "getCurrentInstance|onUnmounted" src` 无命中；唯一的卸载清理是 `subpackages/report/pages/detail/index.vue` 里 uni 的 `onUnload`（清判题轮询 `setTimeout`）。
- 组合式函数是**网络调用**的合法发起方：`useQuestionCompose` 内部直接调 `@/api` 的 `apiGenerateQuestions`。

**代码锚点**
- `miniprogram/src/subpackages/material/composables/useQuestionCompose.ts::useQuestionCompose`
- `miniprogram/src/subpackages/report/pages/detail/index.vue::onUnload`

---

## Custom Hook Patterns

`useQuestionCompose` 的完整契约：

| 项 | 内容 |
|---|---|
| 入参 | 无 |
| 导出的类型 | `ComposeScope { folderId?: string; materialId?: string }`、`KnowledgePointOption { id: string; name: string }` |
| state（`ref`） | `scope`、`availableKpList`、`selectedKpIds`、`selectedTypes`（默认 `DEFAULT_TYPES` = 单选/多选/判断/简答）、`questionCount`（默认 5）、`difficulty`（默认 3）、`questions`、`removedIds`、`hasGenerated`、`isGenerating`、`isStarting` |
| getters（`computed`） | `remainingQuestions`（排除 `removedIds`）、`coverage`（`computeKnowledgeCoverage` 投影）、`canStart`（有剩余题**且** `coverage.missing.length === 0`）、`plannedCount`（`max(已选考点数, 指定题量)`）、`generationNotice`（生成前后据实披露题量调整与覆盖缺口）、`isAllKpSelected` |
| 作用域 | `setScope(next)` |
| 考点操作 | `setKnowledgePoints(list)`（同时全选）、`flattenKnowledgePoints(FolderKnowledgePointItem[])`、`isKpSelected(id)`、`toggleKp(id)`、`toggleSelectAllKp()` |
| 题型操作 | `isTypeSelected(type)`、`toggleType(type)`（**至少保留一种题型**，否则 toast 并拒绝） |
| 出题 | `generate()`、`regenerateQuestion(question)`、`fillCoverageGap()`；内部共用 `generateForKnowledgePoints(ids, desiredCount)` → `planGenerationBatches` 分批 → `apiGenerateQuestions` |
| 题目裁剪 | `removeQuestion(target)`（接受 `QuestionItem` 或 id）、`restoreQuestion(id)` |

约定要点：

- **副作用与门禁内聚**：`canStart` / `coverage` / `generationNotice` 会随剔除题目自动重算，页面不需要自己判覆盖缺口。
- **失败一律 toast + 保持原状态**：`generate` / `regenerateQuestion` / `fillCoverageGap` 都在 `catch (error: any)` 里 `uni.showToast({ title: error?.message || '...' })`，并用 `finally` 复位 `isGenerating`。
- **返回的 `ref` 需在模板里显式 `.value`**：因为返回的是普通对象而非 `reactive`，页面写成 `compose.selectedKpIds.value.length`、`compose.isGenerating.value`（见 `subpackages/material/pages/questions/index.vue` 模板）。这是本仓库既有的写法，新增 `ref` 型组合式函数要么沿用、要么整体 `reactive` 化并统一改造调用点。
- **状态变更都通过返回的方法**：页面不直接改 `compose.selectedKpIds`，只调 `toggleKp` / `setKnowledgePoints` 等。

**代码锚点**
- `miniprogram/src/subpackages/material/composables/useQuestionCompose.ts::ComposeScope`
- `miniprogram/src/subpackages/material/composables/useQuestionCompose.ts::canStart`
- `miniprogram/src/subpackages/material/composables/useQuestionCompose.ts::generationNotice`
- `miniprogram/src/subpackages/material/composables/useQuestionCompose.ts::toggleType`（至少一种题型）
- `miniprogram/src/subpackages/material/pages/questions/index.vue`（消费点）

---

## Data Fetching

- 网络调用统一经 `src/api/*`（`apiGenerateQuestions`、`apiGetKnowledgeTree`、`apiListWrongRecords` 等）。组合式函数**不直接**使用 `uni.request`。
- `useQuestionCompose.generateForKnowledgePoints` 的调用形状：
  ```typescript
  const result = await apiGenerateQuestions({
    folder_id: scope.value.folderId,
    material_id: scope.value.folderId ? undefined : scope.value.materialId,
    knowledge_point_ids: batch.knowledgePointIds,
    question_types: selectedTypes.value,
    count: batch.count,
    difficulty: difficulty.value,
  });
  ```
  要点：**`folder_id` 与 `material_id` 互斥**（有课程就不传资料）；只累加 `result.qualified_questions`，`pending_count` 单独统计但当前调用方未展示。
- **失败处理约定**：主流程失败必须 toast；可降级的次要数据（如 `materialStore.loadKnowledgeTree` 失败）用 `console.error` + `return null` 静默降级。组合式函数内不做静默吞错。
- **轮询的现状**：全仓库**没有**组合式轮询，轮询实现在两处 store / 页面内联逻辑里，且都是固定间隔（**无自适应退避、无超时熔断**）：
  - `materialStore.pollMaterialStatus(id, maxAttempts = 20, interval = 1500)`：固定 1500ms，命中 `ready` / `failed` / `retake_required` 即返回，超时抛 `'资料解析超时，请稍后刷新'`。
  - `subpackages/report/pages/detail/index.vue::pollGrading`：最多 20 轮、每轮 2500ms，命中 `fullyGraded` 或 `needsRetry` 即 break；`onUnload` 清 `setTimeout`。
  
  新增轮询逻辑请沿用「有明确终止条件 + 有上限 + 卸载时清定时器」的现有形态，**不要**在文档里承诺不存在的退避算法。

**代码锚点**
- `miniprogram/src/subpackages/material/composables/useQuestionCompose.ts::generateForKnowledgePoints`
- `miniprogram/src/stores/material.ts::pollMaterialStatus`
- `miniprogram/src/subpackages/report/pages/detail/index.vue::pollGrading`

---

## Naming Conventions

- 文件名与函数名同为 `useXxx`（`useQuestionCompose.ts` → `useQuestionCompose`）。
- 导出的辅助类型用**领域名**而非 `UseXxxOptions`：本仓库只有 `ComposeScope` / `KnowledgePointOption`；没有 `UseXxxOptions` / `UseXxxReturn` 的命名先例。
- 返回的方法名以**动作开头**：`generate` / `regenerateQuestion` / `removeQuestion` / `restoreQuestion` / `fillCoverageGap` / `toggleKp` / `toggleSelectAllKp` / `setScope` / `setKnowledgePoints` / `flattenKnowledgePoints`；布尔判定用 `isXxx`（`isKpSelected` / `isTypeSelected` / `isAllKpSelected`）。**没有 `handle*` 前缀的方法**（`handle*` 出现在页面内联回调里，如 `questions/index.vue::handleStartPractice`）。
- store 实例变量小写驼峰（`materialStore`、`folderStore`、`practiceStore`、`authStore`）。

**代码锚点**
- `miniprogram/src/subpackages/material/composables/useQuestionCompose.ts::ComposeScope`
- `miniprogram/src/subpackages/material/pages/questions/index.vue::handleStartPractice`

---

## Common Mistakes

- **不要为「包装 store」而新建组合式函数**：现有 store 已经是编排层，直接 `useXxxStore()` 即可；新增 `use*` 应承载真正的**有状态 UI 逻辑复用**（如 `useQuestionCompose` 的组卷配置）。
- **不要在组合式函数里直接改全局状态而不经 store action**：跨页共享状态走 store；组合式函数内的 `ref` 只承载组件/页面级状态。
- **不要忘记 `ref` 的解包规则**：返回普通对象时调用方必须 `.value`；若改成 `reactive` 需同步改造全部消费点。
- **不要引入不存在的生命周期守卫**：当前没有组件内组合式函数注册 `onUnmounted` 的先例；若新增需要清理的定时器，按 `report/detail/index.vue` 的做法在页面 `onUnload` 里清。
- **不要在组合式函数里直接 `uni.request`**：网络统一经 `@/api`，保留适配层归一化。

**代码锚点**
- `miniprogram/src/subpackages/material/composables/useQuestionCompose.ts::setScope`
- `miniprogram/src/subpackages/report/pages/detail/index.vue::onUnload`
- `miniprogram/src/api/index.ts::apiGenerateQuestions`
