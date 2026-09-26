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

