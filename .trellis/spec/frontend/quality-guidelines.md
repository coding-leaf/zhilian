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

## Code Review Checklist

1. Does `pnpm run lint` pass without errors?
2. Does `pnpm run type-check` (vue-tsc) report zero type errors?
3. Does `pnpm run test:unit` pass all tests?
4. Are all component props and composable return values properly typed without `any`?
5. Is responsive styling and uni-app lifecycle handling clean and leak-free?
