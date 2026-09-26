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


