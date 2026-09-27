# Quality Guidelines

> Code quality standards and verification baseline for frontend development.

---

## Overview

Frontend quality standards for the UniApp / Vue 3 mini-program are enforced via ESLint, Prettier, vue-tsc, and Vitest.
All frontend commands must be run within the `miniprogram/` directory using `pnpm`.

### Quality Gate Commands

```bash
cd miniprogram
pnpm run lint          # ESLint + Prettier rules check
pnpm run type-check    # vue-tsc type checking across all Vue components and TS files
pnpm run test:unit     # Vitest unit test suite
```

---

## Forbidden Patterns

- **No `any` Usage**:
  - `@typescript-eslint/no-explicit-any` is configured to `error`. Explicit `any` is strictly forbidden. Use `unknown`, generics, or proper domain interfaces.
- **Direct Global Mutation**:
  - Do not mutate global state outside of Pinia stores.
- **Unscoped / Inline Secret Keys**:
  - API keys, secrets, or environment credentials must never be committed into frontend source code.

---

## Required Patterns

- **Strict Type Annotations**:
  - Component props, emits, and store actions must be strictly typed using TypeScript interfaces or types.
  - Pinia stores must declare typed state, getters, and actions.
- **Prettier Code Formatting**:
  - Code must adhere to Prettier rules integrated into ESLint (`prettier/prettier: error`).
- **Component File Size Control**:
  - Keep components modular and concise. `max-lines` is set to 500 lines (warning threshold) to encourage decomposition into reusable subcomponents or composables.

---

## Testing Requirements

- **Test Framework**: Vitest with `@vue/test-utils`.
- **Test Locations**: All tests live under `miniprogram/tests/unit/`.
- **Coverage & Pass Rate**: 100% test pass rate required. No regressions allowed.
- **Mocking**: UniApp APIs (`uni.*`) and network requests must be properly mocked in unit tests using Vitest vi mocks.

---

## Architectural Contracts & Composables Patterns

### Scenario: Long Polling with Adaptive Exponential Backoff

#### 1. Scope / Trigger
- 资料解析、报告生成等长耗时异步任务的前端轮询检测。

#### 2. Signatures
```typescript
interface UseMaterialPollingOptions {
  materialId?: MaybeRef<string>;
  initialInterval?: number; // 默认 1500ms
  maxInterval?: number;     // 默认 8000ms
  backoffFactor?: number;   // 默认 1.5
  maxTimeoutMs?: number;    // 默认 180,000ms (3分钟熔断保护)
  onTimeout?: () => void;
  onSuccess?: (material: MaterialItem) => void;
  onError?: (error: unknown) => void;
}
```

#### 3. Contracts
- 严禁使用固定无退避的 `setInterval` 长期轮询。
- 必须基于 `setTimeout` 调度并支持动态退避递增：$t_{next} = \min(t \times \text{factor}, t_{max})$。
- 必须包含超时熔断保护（默认 3 分钟），超时后必须主动释放定时器并提示用户，防止单页面无线挂起。
- 在页面卸载 (`onUnmounted`) 或命中终态（`READY`, `FAILED`, `COMPLETED`, `RETAKE_REQUIRED`）时必须即刻停帧清除定时器。

#### 4. Wrong vs Correct
##### Wrong
```typescript
// 错误做法：固定死循环轮询，无超时与退避，导致客户端卡顿与服务端压力激增
const timer = setInterval(async () => {
  await fetchDetail();
}, 2000);
```
##### Correct
```typescript
// 正确做法：自适应退避与超时熔断保护
const scheduleNext = (currentInterval: number) => {
  if (Date.now() - startTime > maxTimeoutMs) {
    stopPolling();
    onTimeout?.();
    return;
  }
  timer = setTimeout(async () => {
    await pollAction();
    scheduleNext(Math.min(currentInterval * backoffFactor, maxInterval));
  }, currentInterval);
};
```

---

### Scenario: User Auth State Hydration & Page Isolation

#### 1. Scope / Trigger
- 小程序启动 (`onLaunch`)、切前台 (`onShow`) 以及二级列表页与首页交互时的数据隔离与鉴权保护。

#### 2. Signatures
```typescript
interface UserStoreActions {
  initFromStorage: () => void;
  hydrateProfile: () => Promise<void>;
  logout: () => void;
}
```

#### 3. Contracts
- **鉴权静默水合**:
  - 本地存储白名单 (`auth_tokens`) 恢复令牌后，必须在 `onLaunch` 与 `onShow` 时异步触发 `hydrateProfile()` 校验令牌有效性并拉取真实用户画像。
  - 若服务端返回 401 或凭据过期，必须彻底清理本地令牌并重置用户画像，平滑回退至未登录态，严禁伪造虚假 Token。
- **列表页与全局 Store 隔离**:
  - 二级列表页应管理自身的分页展示数据集 (`listData`)，禁止用局部筛选/分页结果全量覆盖全局首页的概览切片。
  - 全局 Store 仅接收增量注入 (`addMaterial`)，防止因单页重置导致全局或返回首页时资料丢失。
  - 列表页与工作台首页均应在 `onShow` 阶段触发安全刷新，避免页面栈回退时呈现空白。

#### 4. Wrong vs Correct
##### Wrong
```typescript
// 错误做法：二级列表页在加载全部或分页时粗暴覆盖全局 Store，导致首页资料被污染或冲空
function loadData(items: MaterialItem[]) {
  materialStore.setMaterialsList(items); // 破坏了首页原本的 5 条精简视图
}
```
##### Correct
```typescript
// 正确做法：列表页维护独立展示状态，仅对全局缓存执行增量更新
const listData = ref<MaterialItem[]>([]);
function loadData(items: MaterialItem[]) {
  listData.value = items;
  items.forEach((item) => materialStore.addMaterial(item));
}
```

---

### Scenario: Material Status Filter & Parse Progress Contract

#### 1. Scope / Trigger
- 资料列表状态筛选（全部 / 解析中 / 待重拍 / 已完成）与解析进度展示。历史缺陷：`all` 标签误传 `status=undefined` 被后端当作有效过滤条件，导致「全部」返回空。

#### 2. Signatures
```typescript
// GET /api/v1/materials?status=<value>&page=&page_size=
// POST /api/v1/materials/{material_id}/parse   -> 手动触发/重新调度解析
interface MaterialItem {
  status: MaterialStatus;
  parse_status?: string | null;        // queued/parsing_doc/ocr_processing/extracting_knowledge/embedding_generation/ready/failed
  progress_percentage?: number | null; // 0-100
}
```

#### 3. Contracts
- **空参数必须清洗为“不过滤”**：前端 `request` 层与后端路由层双向清洗 `undefined`/`null`/空串/占位符（`all`/`undefined`/`null`）；后端未识别状态归一化为 `None`，禁止落成 `status == ''` 这类恒假条件。
- **状态语义映射（后端 Service 统一解析）**：
  - `parsing` → `[pending, parsing]`（多状态聚合）
  - `ready` / `completed` → `[ready]`
  - `retake_required` → `[]`（资料主表无该状态，诚实返回空列表，禁止回退为“全部”）
  - 其余合法状态 → 单值过滤
- **解析进度装配禁止 N+1**：列表装配 `parse_status`/`progress_percentage` 时，必须通过 `selectinload(Material.versions)` 等批量方式预加载版本，查询数须为常数级（与 page_size 无关），严禁在 item 循环内逐条查版本表。
- **版本选择语义**：优先 `current_version_id` 命中；否则取 `version_number` 最大者（`Material.versions` 已按 `version_number desc` 排序，`versions[0]` 即最新）。

#### 4. Wrong vs Correct
##### Wrong
```python
# 错误做法：列表逐条查询版本表，page_size=20 时最多 40 次额外查询（N+1）
for item in items:
    version = self.repo.get_latest_version(item.id, user_id)
    item.parse_status = version.parse_status
```
##### Correct
```python
# 正确做法：仓储批量预加载版本集合，Service 内存内挑选目标版本（固定 1 次额外查询）
stmt = stmt.options(selectinload(Material.versions))
# ...
version = self._pick_loaded_version(item)  # versions[0] 即最新，或命中 current_version_id
```

---

### Scenario: Material Subpackage Navigation Param Contract

#### 1. Scope / Trigger
- 资料分包内页面间跳转（`list` / `detail` / `knowledge-tree` / `questions` / `practice` / `report`）与生成成功后的跳转。

#### 2. Contracts
- **主键参数名统一为 `material_id`**（snake_case，与后端查询参数一致）；接收页必须兼容 `materialId` / `id` 兜底解析，禁止只认一种导致「跳过去却空白」。
- 所有 `uni.navigateTo` 必须带 `fail` 兜底提示，禁止静默无响应（用户会以为「原地不动」）。
- 生成成功后跳转目标统一：`/subpackages/material/pages/questions/index?material_id=<id>`。
- 页面数据源：二级列表页使用**页面本地 `listData`**，`onShow` 安全刷新；禁止用分页结果全量覆盖全局 Store。

#### 3. Wrong vs Correct
##### Wrong
```typescript
// 错误：同一资料主键在不同页面用不同参数名，接收页解析失败 → 空白/原地不动
uni.navigateTo({ url: `/subpackages/material/pages/detail/index?id=${id}` });        // 发送 id
// detail 页只读 query.material_id → undefined → 不加载
```
##### Correct
```typescript
// 正确：统一 material_id，接收页兼容兜底，且带 fail 提示
uni.navigateTo({
  url: `/subpackages/material/pages/questions/index?material_id=${id}`,
  fail: () => uni.showToast({ title: '页面打开失败', icon: 'none' }),
});
// 接收页：initPage(q?.material_id || q?.materialId || q?.id || props.id)
```

#### 4. Tests Required
- 页面单测覆盖参数解析：`material_id` / `materialId` / `id` 三种入参均能正确加载。

---

### Scenario: WeChat Mini-Program 禁止递归组件，深层树用扁平化渲染

#### 1. Scope / Trigger
- 微信小程序 (`mp-weixin`) 端渲染任意深度层级数据（知识点树、目录、组织树等）。
- 历史缺陷：`KnowledgeTreeNode.vue` 在模板中递归调用自身 + 自引用导入，页面整页崩溃 `TypeError: Cannot read properties of undefined (reading 'children')`，并伴随 `Setting data field "uP" to undefined is invalid`。

#### 2. Signatures
```typescript
// miniprogram/src/subpackages/material/utils/tree.ts
export interface KnowledgeTreeRow {
  node: KnowledgeTreeNode;
  depth: number; // 根为 1
}
export function flattenVisibleTree(
  nodes: KnowledgeTreeNode[],
  collapsedMap?: Record<string, boolean>,
): KnowledgeTreeRow[];
```

#### 3. Contracts
- **禁止组件模板递归自渲染**：不得在组件内 `import` 自身，也不得在模板中递归 `<Self v-for="child in node.children">`。
- uni-app mp-weixin 通过单一 `u-p`/`uP` 字符串 + 模块级 `propsCaches` 透传 props（`common/vendor.js` 的 `renderProps` / `findComponentPropsData`）；递归自引用组件会使该链路丢失 props，子组件 `props.node` 变为 `undefined`，计算属性首抛 `reading 'children'`。
- **深层树渲染路径**：数据仍是嵌套树 → 用纯函数 `flattenVisibleTree` 前序展开为「可见行（`node` + `depth`），折叠节点的子孙被裁剪」→ 页面**单层** `v-for` 渲染行组件，`level` 传渲染 `depth`。
- 折叠/级联语义：行组件持有完整 `node`（含 `children`），级联勾选继续用 `collectNodeAndDescendantIds` + `toggleKnowledgeSubtree`；「全选/覆盖率」基于全量 `flattenKnowledgeTree`，与折叠状态无关。

#### 4. Validation & Error Matrix
- `nodes` 非数组 / `null` -> `flattenVisibleTree` 返回 `[]`，不抛错。
- 节点项为 `null`/`undefined`/无 `id` -> 跳过该行，不抛错。
- 折叠节点 `collapsedMap[id] === true` -> 该节点自身保留、其子孙不进入结果。

#### 5. Wrong vs Correct
##### Wrong
```vue
<!-- 禁止：组件递归自引用，mp-weixin 下 props 透传丢失 → 整页崩溃 -->
<script setup lang="ts">
import KnowledgeTreeNode from './KnowledgeTreeNode.vue'; // 自引用导入
</script>
<template>
  <KnowledgeTreeNode v-for="child in node.children" :node="child" />
</template>
```
##### Correct
```vue
<!-- 页面：纯函数扁平化 + 单层 v-for -->
<script setup lang="ts">
import { computed } from 'vue';
import { flattenVisibleTree } from '../../utils/tree';
const visibleRows = computed(() =>
  flattenVisibleTree(materialStore.currentKnowledgeTree, materialStore.knowledgeTreeCollapsedMap),
);
</script>
<template>
  <KnowledgeTreeNode
    v-for="row in visibleRows"
    :key="row.node.id"
    :node="row.node"
    :level="row.depth"
  />
</template>
```

#### 6. Tests Required
- 纯函数单测：默认全展开的 `id`/`depth` 序列、折叠根节点仅保留自身、折叠中间节点仅裁剪其子树、空/`null`/畸形输入不抛错。
- 页面单测断言：折叠后子孙文本消失且节点自身保留；折叠态下「全选」仍覆盖整棵树。
- 编译产物断言：组件 `.json` 的 `usingComponents` 不含自引用键；组件 `.js` 不含自引用模块加载器。

---

### Scenario: Submit Idempotency Key Persistence & Degraded Storage Writes

#### 1. Scope / Trigger
- 任何「客户端生成幂等键、服务端据此去重」的提交/上传（练习交卷、资料上传等），以及任何向 `uni.setStorageSync` 写入可能超限的本地草稿。

#### 2. Signatures
```typescript
// miniprogram/src/subpackages/practice/utils/submitKey.ts
export function getOrCreateSubmitKey(practiceId: string): string;
export function clearSubmitKey(practiceId: string): void;

// miniprogram/src/utils/storage.ts
const MAX_STORAGE_BYTES = 20 * 1024; // setItem 超限抛 AppError(10001)
```

#### 3. Contracts
- **幂等键每次业务会话只生成一次并持久化**：`getOrCreateSubmitKey` 必须落盘（不得只在内存/仅在已有草稿时落盘）。零作答直接交卷（`confirm_unanswered`）同样要先持久化，否则 App 重启后生成新键，重试不再幂等。
- **清理时机**：仅在「确认成功」或「明确不可重试的业务终态」后 `clearSubmitKey`；网络超时/未知错误**必须保留**同一 key 供重试。
- **写入必须可降级**：所有可能超限的 Storage 写入（保存草稿、**清理草稿**、写幂等键）都必须 try/catch；`AppError(10001)` 不得向上传播打断主流程。
- **降级不得产生副作用**：写入失败后，store 内状态必须保留，且**远端同步调度（`setTimeout`/`saveAnswerDraft`）仍须注册**——写入失败只应影响本地备份，不应导致该次作答既未备份也未同步。
- **成功路径尤其危险**：交卷成功后的本地清理（`clearDraftFromStorage`）若因超限抛错，会被外层 catch 误判为交卷失败，形成「后端已成功 → 前端卡死」死结；必须包 try/catch。

#### 4. Validation & Error Matrix
- 已有幂等键 + 重试 → 复用同一 key。
- 成功/明确终态 → 清理 key。
- Storage 写超限（>20KB）→ 捕获并降级，不抛出；主流程继续。
- 清理草稿失败（成功路径）→ 捕获并降级，交卷仍视为成功并跳转。

#### 5. Wrong vs Correct
##### Wrong
```typescript
// 错误：每次交卷新建 key，且仅在有草稿时落盘 —— 零作答交卷 App 重启后非幂等
const key = generateIdempotencyKey();
await submitPractice(id, key);

// 错误：成功路径清理无保护，超限抛错被外层当作交卷失败
function onSuccess() { clearDraftFromStorage(id); redirectToReport(); }
```
##### Correct
```typescript
// 正确：每会话一次并持久化（含零作答），成功/终态后清理
const key = getOrCreateSubmitKey(id);
await submitPractice(id, key);
if (succeededOrTerminal) clearSubmitKey(id);

// 正确：清理同样降级，不阻断成功跳转
function onSuccess() {
  try { clearDraftFromStorage(id); } catch (err) { reportWarning(err); }
  redirectToReport();
}
```

#### 6. Tests Required
- 同一 practiceId 两次 `getOrCreateSubmitKey` 返回相同值，且**无草稿时也已落盘**。
- `clearSubmitKey` 后重新生成新 key。
- `storage.setItem` 抛 `AppError(10001)` 时：不抛出、store 作答保留、`saveAnswerDraft` 仍被调度（spy 断言）。
- 交卷成功路径的 `clearDraftFromStorage` 抛错时：不阻断跳转，仍判定成功。




### Scenario: Auth Token Refresh State Sync & Bounded 401 Retry

#### 1. Scope / Trigger
- 前端 `utils/request.ts` 的 401 静默刷新与重放，以及本地存储写入的大小门禁。

#### 2. Signatures
```typescript
// utils/request.ts
export function setTokenRefreshListener(listener: (tokens: AuthTokens) => void): void;
// types/common.ts
interface RequestOptions { _retryCount?: number }
// utils/storage.ts
const MAX_STORAGE_BYTES = 20 * 1024;
```

#### 3. Contracts
- 刷新成功后除写 `storage.auth_tokens` 外，必须经解耦订阅回调同步内存态（`userStore.tokens`）；`request.ts` 禁止直接 import store（避免循环依赖）。
- 401 重放必须携带 `_retryCount`，超过上限（1 次）直接抛 `AppError(20001)` 并清理会话+重定向，禁止无界刷新循环导致 Promise 挂起。
- storage 大小校验必须按 UTF-8 实际字节数（`TextEncoder`，缺失时手写回退），禁止用 `String.length`。

#### 4. Tests Required
- 刷新后 `userStore.tokens` 与 storage 严格同步；重放 1 次后仍 401 → 抛 20001 且不再刷新；8000 个中文字符（~24KB，`.length` 未超）必须触发 `AppError(10001)`。

### Scenario: Material File Validation, Tree Check-State & List Loading Contracts

#### 1. Scope / Trigger
- 资料上传前端校验、知识点树勾选/半选、资料列表分页与首屏加载。

#### 2. Contracts
- 文件大小上限必须与后端 `material.py:MAX_FILE_SIZES` 逐格式一致（pdf/docx 20MB、png/jpg/jpeg 10MB、txt/md 5MB），未知后缀回退 20MB；禁止单一 20MB 通吃导致前后端放行不一致。
- 前端可见格式白名单为后端 `MaterialDocType` 的有意子集（产品设计收窄），非缺陷；变更需双端同步评估。
- 单页重拍返回类型必须为后端 `MaterialReshootResponse`（`page_index/is_qualified/reshoot_count/parse_status/unqualified_reason`），禁止使用漂移类型（如 `page_no/status/message`）。
- 知识点树父节点勾选态必须由选中集合推导（`checked/indeterminate/unchecked`，纯函数），切换资料前必须重置选中与折叠态。
- 列表分页追加必须按 id 去重；首屏加载只由单一生命周期触发一次。

#### 3. Tests Required
- 15MB jpg 被拒 / 15MB pdf 通过；pptx/txt/md 被拒（收窄断言）；`getNodeCheckStatus` 叶子/混合/空输入；切换资料后选中与折叠归零；分页偏移重复数据去重；首屏仅发 1 次列表请求。

### Scenario: Question Config Bound, Deletion Reason Query & Quality-Check Type Alignment

#### 1. Scope / Trigger
- 出题数量配置、题目删除请求、质检记录消费。

#### 2. Contracts
- 出题数量上限与后端逐字一致（1–20）：`validateQuestionConfig` 上限、`clampCount` 截断、提示文案、`+` 按钮禁用条件全部对齐 20，禁止残留 50。
- `deleteQuestion(id, reason)` 必须把 `reason` 作为 **query** 拼接（`?reason=`），DELETE 不携带 body data。
- `QuestionQualityCheck` 字段名必须为后端 `QuestionQualityCheckResponse` 逐字（`check_type/is_passed/reason/similarity_score/check_metadata`）；旧别名仅可保留为**可选**废弃字段。
- 列表删除成功后必须重置到第 1 页重新拉取，避免 offset 前移跳题。

#### 3. Tests Required
- 21/50 被拒、1 与 20 通过；25/99 clamp 到 20；删除 URL 含 `?reason=` 且无 body；删除后重新请求 page=1。

### Scenario: Practice Draft Lifecycle & Status Mapping

#### 1. Scope / Trigger
- 交卷后本地草稿清理、`practice_drafts` 单一 schema、前后端练习状态映射。

#### 2. Contracts
- `StorageDataMap['practice_drafts']` 唯一契约为 `Record<string, PracticeDraftRecord>`；禁止 `as unknown as Record<string, never>` 之类强转。
- 交卷成功后必须同时清 Storage **与** store 内存 `drafts`，`extractLatestDraftPractice` 不得再提取已交卷练习；清理不得影响其他练习草稿。
- `adaptStatus` 必须覆盖后端全量状态（含 `timeout→submitted`、`paused`、`partially_graded`），未知值回退 `in_progress`。

#### 3. Tests Required
- `clearSession(id)` 删除目标 draft 且保留兄弟 draft；`adaptStatus('timeout')==='submitted'`；旧结构（仅 `answers`）读取不抛错。

### Scenario: Practice Session Teardown Flush, Subjective Fallback & Pause/Resume

#### 1. Scope / Trigger
- 练习会话卸载、题型渲染兜底、暂停/恢复。

#### 2. Contracts
- 会话卸载/清理前必须 flush 待同步草稿；flush 的完成回调必须以**身份令牌**判定是否仍为当前 pending 项，禁止用 questionId 判等（否则新作答会被旧同步的回调误标记已同步而丢失）。
- 题型渲染必须为 `term_explanation`/`case_analysis` 及未知主观题型提供文本输入兜底；客观题分支不得受影响；标签映射补全。
- 单题耗时必须取真实时间差（设上限），禁止常量；累计耗时读取后端 `time_elapsed_seconds` 起步。
- `pausePractice`/`resumePractice` 契约与后端逐字一致（`POST /practices/{id}/pause|resume`）。

#### 3. Tests Required
- 卸载 flush 触发且有 pending 不丢（竞态用例：旧同步回调不得清掉新作答）；`term_explanation`/`case_analysis` 渲染输入框与标签；真实耗时非常量；pause/resume 发对应 POST。

### Scenario: Report Detail Loading Guard, Subjective Regrade & Snippet/Keyword Reading

#### 1. Scope / Trigger
- 报告详情页首屏加载、主观题自评/重判入口、要点与原文渲染。

#### 2. Contracts
- 报告详情首屏只允许一次加载（并发锁 + 已加载 practiceId 守卫），返回刷新不得被永久阻断，切换 practiceId 必须重新加载。
- 逐题数据唯一来源为 `practiceRes.data.items`，禁止引用不存在的 `repData.items` 死分支；加载失败展示可重试错误态。
- `canSelfGrade` 的主观题集合须与后端 `SUBJECTIVE_QUESTION_TYPES` 一致（含 `term_explanation`/`case_analysis`）；客观题不受影响。
- 重判入口要求 `is_answered === true` 且 `user_answer` 非空，未作答不得展示（避免后端 403）。
- 要点读顶层或 `question_snapshot` 任一；原文按后端字段渲染，缺失显示空态。

#### 3. Tests Required
- 首屏单次加载与切换 pid 重载；主观题入口覆盖三类、客观题不显示；未作答题隐藏重判；要点双层来源；切片空态。

### Scenario: Wrong-Book Filter Enum Alignment & Reset Single-Trigger

#### 1. Scope / Trigger
- 错题筛选错误类型/题型枚举、重置筛选、删除错题响应字段消费。

#### 2. Contracts
- 错误类型筛选项必须发送后端权威枚举（`incomplete_expression`/`question_misreading`），并向下兼容旧简写（`incomplete`/`deviation`）。
- 题型取值必须与后端 `QuestionType` 逐字一致（如 `fill_in_blank`，禁止 `fill_in_the_blank`）；所有消费点（筛选栏、卡片标签）统一。
- 重置筛选只允许单通道触发（`filter-change`），禁止同时 `emit('reset')` 与 `emitChange()` 造成父组件双请求。
- `deleteWrongRecord` 读取 `removed` 字段（`removed: boolean; success?: boolean`）。

#### 3. Tests Required
- 标准+旧枚举均可识别；`fill_in_blank` 渲染「填空题」；点击重置父组件仅 1 次 `loadData`；删除响应解构 `removed === true`。

### Scenario: Report Reset, Draft Metadata & Continue-Practice Idempotency Header

#### 1. Scope / Trigger
- 报告状态重置、练习草稿元数据、继续练习幂等头、报告页空态。

#### 2. Contracts
- `setReport` 必须在新报告无 `weak_points`（缺失/null/空）时把 `weakPoints` 重置为 `[]`，禁止残留旧报告数据。
- `initSession` 生成的草稿必须写入 `total_count`（及可选 `title`/`material_id`），`extractLatestDraftPractice` 消费真实值。
- 继续练习请求头必须是 `Idempotency-Key`（与后端逐字一致）。
- 报告详情页在非 loading、非 error 且无 `currentReport` 时必须渲染空态（`.empty-state` + 操作按钮），不得白屏；空态不得遮蔽 loading/error 分支。

#### 3. Tests Required
- 空/无 `weak_points` 报告切换后无残留；草稿含 `total_count`/`title`/`material_id` 并被展示；`continuePractice` 头为 `Idempotency-Key`；无 pid/空报告渲染 `.empty-state` 且不发起请求。

### Scenario: Course IA Navigation, Unclassified & Archive Contracts

#### 1. Scope / Trigger
- 控制台课程列表入口、课程详情页、未分类资料列表、课程归档/恢复与资料移动课程。

#### 2. Signatures
```typescript
// src/types/folder.ts
export const UNCLASSIFIED_FOLDER_ID = '__none__';
export interface FolderItem {
  id: string; name: string; is_archived: boolean;
  archived_at?: string | null; purge_after?: string | null;
  material_count: number; ready_material_count: number;
  knowledge_point_count: number; question_count: number;
  last_practice_at?: string | null; created_at: string; updated_at?: string;
}
// src/api/folder.ts
fetchFolderList({ include_archived }); fetchFolderDetail(id);
createFolder({ name }); renameFolder(id, { name });
archiveFolder(id); restoreFolder(id);
// src/api/material.ts
moveMaterialFolder(materialId, folderId: string | null); // PATCH /materials/{id}/folder
uploadMaterial(file, title, idem, sourceType, onProgress, folderId?);
```

#### 3. Contracts
- **字段名与后端逐字一致**：消费 `FolderDetailResponse` 的 `is_archived` / `purge_after` / `material_count` / `ready_material_count` / `knowledge_point_count` / `question_count` / `last_practice_at`；禁止自造 `archived`/`materials_count` 等漂移名（渲染 `undefined` 静默失败）。
- **导航参数统一 `material_id`**：资料分包内跳转一律 `?material_id=<id>`；接收页必须兼容 `material_id` / `materialId` / `id` 兜底。课程相关跳转用 `folder_id`（未分类传 `__none__`）。所有 `uni.navigateTo` 必带 `fail` 兜底提示。
- **未分类入口门禁**：控制台「未分类」入口仅在 `folder_id IS NULL` 的资料存在时渲染；未选课程上传即落未分类（不阻断）。
- **Store 不发请求**：`folderStore` 仅承载 `folders`/`archivedFolders`/`unclassifiedCount`/`currentFolder` 状态与增删改 action；网络调用一律经 `src/api/folder.ts` 由组件触发。
- **归档反悔时间**：归档项展示 `purge_after - now` 剩余时间，使用纯函数 `formatPurgeRemaining(purgeAfter, now)`（缺省/非法/过期 → `已过期`）。
- **控制台去总分卡**：移除 `MasteryDashboardBar` 总分展示，但保留 `fetchMasteryOverview` API 能力（报告页仍可用），不得删除后端能力。
- **列表页隔离**：二级列表页维护本地 `listData`，仅对全局 `materialStore` 做增量 `addMaterial`；移动/删除后本地剔除并 `updateMaterialFolder`，禁止分页结果全量覆盖首页概览切片。

#### 4. Wrong vs Correct
##### Wrong
```typescript
// 错误：控制台首屏仍是总分卡；未分类入口恒显；导航只认一种参数名
uni.navigateTo({ url: `/subpackages/material/pages/detail/index?id=${id}` }); // 无 fail 兜底
```
##### Correct
```typescript
// 正确：课程列表入口 + 条件渲染未分类 + 统一 material_id 且带 fail
uni.navigateTo({
  url: `/subpackages/material/pages/detail/index?material_id=${id}`,
  fail: () => uni.showToast({ title: '页面打开失败', icon: 'none' }),
});
```

#### 5. Tests Required
- `formatPurgeRemaining` 边界（已过期/剩余天/剩余小时/剩余分钟/非法）。
- `folderStore` 增删改、归档拆分、`reset`；`materialStore.removeMaterial`/`updateMaterialFolder`/`unclassifiedMaterials`。
- 控制台断言**不再渲染** `MasteryDashboardBar`、课程列表入口与未分类门禁；课程详情页 `folder_id` 解析与移动；列表页 `folder_id=__none__` 过滤与移动剔除。
