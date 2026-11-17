# Frontend (`miniprogram`) Architecture & Redundancy Audit

> **Audit Scope**: `miniprogram/src/**`, `miniprogram/tests/**`, `miniprogram/package.json`, build/lint/test configs vs `.trellis/spec/frontend/*.md` & `docs/DESIGN.md`
> **Audit Date**: 2026-11-17 (read-only static inspection + `pnpm run lint` / `type-check` / `test:unit` / `test:cov`)

## Executive Summary

- **Codebase Scale**: `miniprogram/src/` contains **54 files / 10,692 physical lines** (`21 .vue`, `27 .ts`, `4 .scss`, `2 .json`); `miniprogram/tests/` contains **17 files / 3,101 physical lines** (`15 *.spec.ts`, `setup.ts`, `fixtures/backendResponses.ts`); total **71 files / 13,793 lines**.
- **Quality Gates**: `pnpm run lint` (exit 0), `pnpm run type-check` (exit 0, excludes `tests/**`), and `pnpm run test:unit` (**15 files / 140 tests passed**) all pass; `vitest run --coverage` reports **45.69%** line/statement coverage (**0%** on 8 of 9 page files and `reportView.ts`).
- **Dead Packages, Pages & Exports**: **7 unused npm packages** (`wot-design-uni` + `easycom` rule, `unocss` / `@unocss/vite` / `@unocss/preset-uno`, `prettier` / `eslint-plugin-prettier` / `eslint-config-prettier`), **1 dead placeholder page** (`subpackages/material/pages/upload/index.vue`), **11 unused store state/action members** (e.g., `practiceStore.latestDiagnosis`, `practiceStore.askCoach`, `materialStore.questions`/`generateQuestions`), and **10+ dead runtime/type exports** (`apiGetDiagnosisReport`, `useQuestionCompose.restoreQuestion`, `ApiResponse`, `AnswerPayload`, `optionDisplayText`, `wrongSnapshotOptions`, `groupCounts`, `resolveGradingStatusText`, `isSelectableForRegrade`).
- **Monolithic Hotspots**: **6 `.vue` files > 300 lines** (violating `docs/DESIGN.md` §6, led by `pages/index/index.vue` at 906L and `course/index.vue` at 796L), **5 `.ts` files > 250 lines** (`api/index.ts` 553L, `types/index.ts` 509L, `useQuestionBank.ts` 349L, `useQuestionCompose.ts` 325L, `stores/practice.ts` 302L), and **4 `.scss` files > 250 lines**.
- **Critical Contract & Style Debt**: `profile/index.vue:89` bypasses `@/api` to call `uploadFile` directly; `stores/practice.ts:233` & `questions/index.vue:286` omit `question_count` / 50-item cap (mitigated at runtime for `<=50` by `backend/app/schemas/practice.py:133-140`, making `api-payload-contracts.md` stale); `CreatePracticeParams.title` is optional vs backend required; **384 hardcoded Hex literals** vs **9 `var(--color-*)` usages**; 4 duplicated modal style blocks; **0 `safe-area-inset-bottom`** paddings; 23 lines violating zero-emoji policy; and `.trellis/spec/frontend/*.md` has drifted from 2026-09-29 reality.
- **Recommended Refactoring Plan**: (1) Purge 7 dead packages, `upload/index.vue`, dead store members, and unused exports; (2) Route `profile` avatar upload through `@/api`, tighten `CreatePracticeParams` (`title` required + explicit `question_count` / 50-item cap), and unify `isAnswered`/tree-walk/option-display helpers; (3) Decompose `index.vue`, `course/index.vue`, `profile/index.vue`, `AiCoachDrawer.vue`, `detail/index.vue`, `questions/index.vue`, and split `api/index.ts` & `types/index.ts` by domain; (4) Extract shared `AppModal`/`BottomActionBar` + SCSS tokens; (5) Add `reportView.ts` & store tests and sync `.trellis/spec/frontend/*.md`.

---

## 1. Oversized Files & Responsibility Entanglement

Thresholds: `.vue > 300` lines (`docs/DESIGN.md:149-150` hard limit), `.ts > 250` lines, `.scss > 250` lines.

| File | LOC | Limit | Entangled Concerns | Target Decomposition |
| --- | --- | --- | --- | --- |
| `src/pages/index/index.vue` | 906 | 300 `.vue` | Hero header + auth status + folder tabs + folder create/rename/archive modal + file upload (`wx.chooseMessageFile`/`uni.chooseImage`) + material list + parse trigger/polling + AI coach drawer + 486L inline CSS (`420-905`) | Extract `FolderFilterBar.vue`, `FolderFormModal.vue`, `MaterialCard.vue`, `useFolderModal.ts`, and `useMaterialUpload.ts`; move shared modal/page CSS to `src/styles/` |
| `src/subpackages/material/pages/course/index.vue` | 796 | 300 `.vue` | Material status header + parse trigger/polling + generated question count + tree flattening (`flattenTree`) + knowledge point detail modal + snippet fetching + AI coach mounting + 438L inline CSS (`358-795`) | Extract `MaterialStatusCard.vue`, `KnowledgeTreeList.vue`, `KnowledgePointSheet.vue`; move `flattenTree` to shared `utils/knowledgeTree.ts` |
| `src/api/index.ts` | 553 | 250 `.ts` | All 8 domain HTTP APIs + 6 param/result interfaces (`GenerateQuestionsParams`, `QuestionGenerateResult`, `QuestionBatchQuery`, `QuestionBankQuery`, `ScopedCoachParams`, `CreatePracticeParams`) + 17 re-exports from `./adapters` | Split into `src/api/{auth,folders,materials,knowledge,questions,practices,grading,diagnosis,wrong}.ts` with thin `src/api/index.ts` barrel; move request/response interfaces to `src/types/` |
| `src/types/index.ts` | 509 | 250 `.ts` | All domain view types across auth, folder, material, knowledge, question, practice, diagnosis, wrong-record in one flat file | Split into `src/types/{auth,folder,material,knowledge,question,practice,diagnosis,wrong}.ts` + `src/types/index.ts` barrel |
| `src/pages/review/review.scss` | 503 | 250 `.scss` | Summary header + wrong-record cards + practice cards + entire question-bank section styles; compiled/duplicated into 6 SFC scoped bundles | Extract shared primitives (`card`, `status-tag`, `section-header`) to `src/styles/common.scss`; split `questionBank.scss` |
| `src/subpackages/report/report.scss` | 416 | 250 `.scss` | Summary card + adaptive card + attempt detail + modal overlay/header/footer (duplicated with `index.vue`/`profile/index.vue`); compiled into 4 SFCs | Extract shared modal/bottom-bar/badge styles to `src/styles/`; keep only report-specific rules |
| `src/pages/profile/index.vue` | 411 | 300 `.vue` | Profile card + direct `uploadFile` avatar upload + edit-profile modal + logout + `LearningStatisticsCard` + 218L inline CSS (`193-410`) | Extract `ProfileEditModal.vue`; move `/users/me/avatar` upload into `api/auth.ts::apiUploadAvatar` + `authStore.updateAvatar`; reuse shared modal CSS |
| `src/components/AiCoachDrawer.vue` | 410 | 300 `.vue` | Bottom-sheet modal + message list rendering + context/sources/suggestions UI + direct API orchestration (`apiAskQuestionCoach`/`apiAskScopedCoach`) + 231L inline CSS (`179-409`) | Extract `CoachMessageList.vue` + `useCoachChat.ts` (or route question-level ask through a shared service) + reuse shared drawer/backdrop CSS |
| `src/pages/review/composables/useQuestionBank.ts` | 349 | 250 `.ts` | Batch pagination + per-batch question expansion/caching + 3-state selection delegation + server availability resolution + mismatch modal + `apiCreatePractice` navigation | Extract `useBatchQuestionsCache` (pagination + per-batch fetching) and `confirmPracticeCountMismatch` helper; keep `useQuestionBank` as thin coordinator |
| `src/subpackages/report/pages/detail/index.vue` | 343 | 300 `.vue` | Practice/diagnosis loading + 20-round `pollGrading` loop (`onUnload` cleanup) + retry grading + regrade/self-eval modal orchestration + adaptive practice regeneration + coach drawer | Extract `useGradingPolling.ts` composable and `AdaptivePracticeCard.vue` |
| `src/subpackages/material/composables/useQuestionCompose.ts` | 325 | 250 `.ts` | Scope/KP/type/count/difficulty config + multi-batch `apiGenerateQuestions` + `loadGeneratedBatches` summary lookup + existing question loading + coverage/notice computation + single-question regeneration/gap-fill | Split into `useComposeConfig.ts` (KP/type/count selection) and `useComposeGeneration.ts` (API orchestration + batch notice + gap-fill) |
| `src/subpackages/material/pages/questions/index.vue` | 314 | 300 `.vue` | Config view (KP chips + type chips + sliders) + preview view (notices + coverage gap + cards) + tree-walk KP loader + `practiceStore.initPractice` & navigation | Extract `QuestionConfigPanel.vue` and `QuestionPreviewList.vue`; reuse shared `flattenKnowledgeTree` |
| `src/stores/practice.ts` | 302 | 250 `.ts` | Session CRUD + answer map + local storage draft/submit-key persistence + `draftQueue` + submit idempotency + regrade/self-eval/retryGrading + wrong-point regeneration + practice listing + unused `askCoach` | Extract `practiceStorage.ts` (keyed storage helpers) and move `regenerateFromWrongPoints` orchestration to a composable/service or dedicated action helper |
| `src/subpackages/practice/session.scss` | 299 | 250 `.scss` | Progress bar + question card + option cards + card drawer + bottom bar | Deduplicate `.bottom-bar`, `.card-drawer-overlay` with shared `src/styles/` |
| `src/subpackages/material/questions.scss` | 296 | 250 `.scss` | Config form cards + chip groups + preview cards + bottom action bar | Deduplicate `.bottom-action-bar`, `.notice-box` with shared `src/styles/` |

*(Borderline `.vue` file: `src/subpackages/practice/pages/session/index.vue` is 289 lines — extract `AnswerCardDrawer.vue` and `QuestionRenderer.vue` before adding features.)*

---

## 2. Dead Dependencies, Pages, Components & Exports

### P1 — Dead Packages, Dead Page & Unused Store/API Members

1. **Unused UI library `wot-design-uni` + `easycom` rule**
   - **Evidence**: `miniprogram/package.json:19` (`"wot-design-uni": "^1.3.10"`), `miniprogram/src/pages.json:4-6` (`"^wd-(.*)": "wot-design-uni/components/wd-$1/wd-$1.vue"`).
   - **Zero-reference proof**: Grep for `wot-design-uni` and `wd-` across `src/**` and `tests/**` returns **0 matches**. All UI uses custom `.vue` components + `App.vue` `.paper-card`/`.paper-btn-primary`.
2. **Unused UnoCSS packages (`unocss`, `@unocss/vite`, `@unocss/preset-uno`)**
   - **Evidence**: `miniprogram/package.json:30-31,43`.
   - **Zero-reference proof**: Grep for `unocss` and `@unocss` across `vite.config.ts`, `main.ts`, `src/**`, and `tests/**` returns **0 matches**; no `uno.config.*` exists.
3. **Unused Prettier ESLint integration (`prettier`, `eslint-plugin-prettier`, `eslint-config-prettier`)**
   - **Evidence**: `miniprogram/package.json:36-37,40`.
   - **Zero-reference proof**: `.eslintrc.cjs:1-33` does not include `prettier` in `extends` or `plugins`; `package.json:6-13` has no `format` script; no `.prettierrc*` exists.
   - *(Note: `@vue/test-utils` at `package.json:34` and `@vitest/coverage-v8` at `package.json:33` ARE actively used by `tests/learningStatistics.spec.ts:2`, `tests/questionBankSection.spec.ts:11`, and `vitest.config.ts:20`.)*
4. **Dead placeholder page `src/subpackages/material/pages/upload/index.vue`**
   - **Evidence**: `miniprogram/src/subpackages/material/pages/upload/index.vue:1-32` (static card, empty `<script setup lang="ts">`), registered at `miniprogram/src/pages.json:61-66`.
   - **Zero-reference proof**: Grep for `upload/index` and `subpackages/material/pages/upload` across `src/**` and `tests/**` returns **0 matches**. Real uploads use `src/pages/index/index.vue:336-383`.
5. **Dead state/actions in Pinia stores**
   - `practiceStore.latestDiagnosis` (`src/stores/practice.ts:61,279`): **0 external reads/writes** in `src/**` and `tests/**`.
   - `practiceStore.askCoach` (`src/stores/practice.ts:256-258,297`): **0 callers** anywhere (`AiCoachDrawer.vue:136` calls `apiAskQuestionCoach` directly).
   - `practiceStore.flushDrafts` (`src/stores/practice.ts:140,288`) & `practiceStore.retryDraft` (`src/stores/practice.ts:142-144,289`): **0 external callers** (`submit()` calls `draftQueue.flush()` directly; `session/index.vue:7` only calls `retryAllDrafts`).
   - `materialStore.isUploading` (`src/stores/material.ts:28,36,43,160`), `materialStore.questions` (`src/stores/material.ts:27,139,142,144,152-153,159`), `materialStore.generateQuestions` (`src/stores/material.ts:130-148,173`): **0 external readers/callers** in `src/**` or `tests/**` (`questions/index.vue` uses `useQuestionCompose`; `index.vue` uses `uni.showLoading`).
   - `materialStore.currentKnowledgeTree` (`src/stores/material.ts:30,105,162`), `materialStore.activeSnippets` (`src/stores/material.ts:32,121,164`), `folderStore.currentFolderKnowledgePoints` (`src/stores/folder.ts:15,65,79`), `folderStore.isLoading` (`src/stores/folder.ts:16,20,29,62,68,80`): **0 external readers** (pages consume the returned Promise values directly).
   - `diagnosisStore.currentReport` / `isLoading` / `isPending` / `reset` (`src/stores/diagnosis.ts:9-12,45-55`): **0 consumers in `src/**`** (`subpackages/report/pages/detail/index.vue:162` stores the return value of `loadReport()` into a local `report` ref; only `tests/diagnosisAndCompose.spec.ts` asserts on `isPending`/`currentReport`).
6. **Dead composable method & dead API endpoint wrapper**
   - `useQuestionCompose.restoreQuestion` (`src/subpackages/material/composables/useQuestionCompose.ts:241-243,321`): **0 callers** in `src/**` or `tests/**`.
   - `apiGetDiagnosisReport` (`src/api/index.ts:489-494`): **0 callers** in `src/**` or `tests/**` (`diagnosisStore.loadReport` calls `apiTriggerDiagnosis`).
   - Legacy `string` overload branches in `apiCreatePractice(params | string)` (`src/api/index.ts:366-369`), `practiceStore.initPractice(practiceId?, params | string)` (`src/stores/practice.ts:102`), and `materialStore.generateQuestions(params | string)` (`src/stores/material.ts:130-135`): **0 callers** pass a `string` for `params`.

### P2 — Unused Types, Helpers & Over-Exported Symbols

All verified with **0 external references** across `src/**` and `tests/**` (excluding self-file declaration/usage):

| Symbol | Location | Category | Action |
| --- | --- | --- | --- |
| `ApiResponse<T>` | `src/types/index.ts:1-5` | Legacy envelope type (`request<T>()` already unwraps `data`) | Delete |
| `AnswerPayload` | `src/types/index.ts:355-359` | Dead payload type (`apiSavePracticeDraft` sends inline fields) | Delete |
| `optionDisplayText` | `src/api/adapters/question.ts:178-181` | Unused helper (3 SFCs inline `option.key \|\| String.fromCharCode(65 + idx)`) | Adopt in SFCs or delete |
| `wrongSnapshotOptions` | `src/api/adapters/wrong.ts:42-52` | Unused adapter helper | Delete (or use in `WrongRecordCard`) |
| `groupCounts` | `src/pages/review/reviewView.ts:46-49` | Unused view helper | Delete |
| `resolveGradingStatusText` | `src/subpackages/report/utils/reportView.ts:43-50` | Unused view helper | Delete |
| `isSelectableForRegrade` | `src/subpackages/report/utils/reportView.ts:100-102` | Unused view helper | Delete |
| `WireWeakKnowledgeItem`, `WirePracticeItem` | `src/api/adapters/diagnosis.ts:4`, `adapters/practice.ts:10` | Internal wire types exported unnecessarily | Un-export (`interface` without `export`) |
| `API_BASE_URL`, `RequestOptions` | `src/utils/request.ts:7,22` | Module-internal constant/type exported unnecessarily | Un-export (keep `RequestOptions` internal unless tested) |
| `QuestionGenerateResult`, `QuestionBatchQuery`, `QuestionBankQuery`, `ScopedCoachParams`, `MaterialDeleteApi`, `MaterialDeleteController`, `WrongMarking`, `LoginFailureReason`, `LoginOutcome`, `RegenerateResult`, `ComposeScope`, `KnowledgePointOption`, `PracticeProgress`, `WrongRegenerateScope`, `ResultBadge`, `DraftSaver`, `DraftFailure`, `DraftQueueState`, `RequestErrorKind`, `RequestErrorDetails` | `src/api/index.ts`, `composables/*`, `stores/*`, `adapters/*`, `utils/*`, `reportView.ts` | Return/param interfaces exported for internal TS satisfaction (0 direct external imports) | Keep only public contract types; un-export internal helper types or move API param types to `src/types/` |

*(Component check: all 11 custom `.vue` components in `src/components/`, `src/pages/**/components/`, and `src/subpackages/**/components/` are actively imported and rendered — **0 orphan components**.)*

---

## 3. Logic Duplication, Store/API/Type Coupling & Style Debt

### P1 — Contract Clarity, Layer Violations, Duplicated Orchestration & Type Scattering

1. **Inconsistent `question_ids` / `question_count` & 50-item cap handling across callers**
   - `src/stores/practice.ts:233-240` (`regenerateFromWrongPoints`) and `src/subpackages/material/pages/questions/index.vue:286-293` (`handleStartPractice`) pass `question_ids` to `apiCreatePractice` / `practiceStore.initPractice` without `question_count` and without clamping to 50 items (unlike `src/pages/review/composables/useQuestionBank.ts:287,297-302`).
   - **Verified runtime behavior**: `backend/app/schemas/practice.py:133-140` (`PracticeCreateRequest._sync_question_count_with_ids`) automatically overrides `self.question_count = len(self.question_ids)` when `self.question_count == 10` (default) or `> len(self.question_ids)`, so omitting `question_count` does **not** silently truncate to 10 at HTTP runtime for `<=50` items. However, explicit `question_count` + 50-item upper-bound handling remain inconsistent across the 3 frontend call sites, and `.trellis/spec/frontend/api-payload-contracts.md:57-77` is stale relative to `backend/app/schemas/practice.py:133-140`.
   - **Fix**: Standardize `question_count: questionIds.length` and `MAX_PRACTICE_QUESTIONS = 50` validation/clamping across all `question_ids` callers, and make `CreatePracticeParams.title` required (matching `backend/app/schemas/practice.py:52-57`).
2. **Page directly calling transport layer (`uploadFile`) & mutating store `ref`**
   - `src/pages/profile/index.vue:89,136-137` imports `uploadFile` from `@/utils/request` directly (the **only** page/component in `src/` importing `utils/request`) and mutates `authStore.user = { ...authStore.user!, avatar_url: profile.avatar_url }` inline.
   - **Fix**: Wrap `/users/me/avatar` in `src/api/` (`apiUploadAvatar`) and add `authStore.updateAvatar(filePath)`.
3. **Component directly calling API vs unused Store proxy**
   - `src/components/AiCoachDrawer.vue:88,136,148` calls `apiAskQuestionCoach` / `apiAskScopedCoach` directly while `src/stores/practice.ts:256-258` defines an unused `askCoach` proxy.
   - **Fix**: Remove `practiceStore.askCoach`, and encapsulate coach chat state + API calls in `useCoachChat.ts`.
4. **Duplicated polling loops without shared abort/cleanup**
   - Three separate fixed-interval polling loops exist: `materialStore.pollMaterialStatus` (`src/stores/material.ts:64-73`, 20×1500ms, **no `onUnload` cancellation**), `diagnosisStore.loadReport` (`src/stores/diagnosis.ts:18-43`, 15×2000ms, **no cancellation**), and `detail/index.vue::pollGrading` (`src/subpackages/report/pages/detail/index.vue:179-193`, 20×2500ms; `onUnload` calls `clearTimeout(pollTimer.value)` at line 230, leaving the pending `Promise` dangling).
   - **Fix**: Extract a shared cancellable `createPoller` / `usePolling` utility with an `AbortSignal`/cancel flag and explicit `onUnload` cleanup.
5. **Duplicated pure logic across pages/stores/components**
   - `isAnswered` (`src/stores/practice.ts:70-74`) vs `isQuestionAnswered` (`src/subpackages/practice/pages/session/index.vue:203-208`): identical non-empty check implemented twice.
   - Tree flattening: `flattenTree` (`src/subpackages/material/pages/course/index.vue:227-239`) vs `walk` (`src/subpackages/material/pages/questions/index.vue:213-220`).
   - Option key formatting: `option.key || String.fromCharCode(65 + idx)` duplicated in `session/index.vue:179-180`, `QuestionPreviewCard.vue:19`, and `AttemptResultCard.vue:12`, while `optionDisplayText` (`src/api/adapters/question.ts:178-181`) goes unused.
   - Multi-batch `apiGenerateQuestions` loop duplicated between `useQuestionCompose.ts:114-133` and `practice.ts:214-225` (plus unused single-call wrapper in `material.ts:130-148`).
6. **Type boundary inconsistencies**
   - Request/query interfaces (`GenerateQuestionsParams`, `QuestionGenerateResult`, `QuestionBatchQuery`, `QuestionBankQuery`, `ScopedCoachParams`, `CreatePracticeParams`) live in `src/api/index.ts:224-364` instead of `src/types/`.
   - `apiListQuestionBankItems` (`src/api/index.ts:309`) uses an inline wire shape instead of a named `WireQuestionBankList` in `src/api/adapters/question.ts`.
   - `CreatePracticeParams.title` (`src/api/index.ts:353`) is typed optional (`title?: string`), whereas backend `PracticeCreateRequest.title` (`backend/app/schemas/practice.py:52-57`) is required (`min_length=1`).

### P1/P2 — Style, Design-Token & Hygiene Debt

1. **P1: Design System Palette Divergence (`docs/DESIGN.md` vs `App.vue` + `pages.json`)**
   - `docs/DESIGN.md:29-65` mandates Wot/Tailwind Cool Blue (`#2563EB`, `#F8FAFC`, `#0F172A`, `#10B981`, `#F59E0B`, `#EF4444`), whereas `src/App.vue:19-31` and `src/pages.json:38-41,110-111` implement Warm Academic Paper (`#1E3A8A`, `#F7F5F0`, `#1C1917`, `#0D9488`, `#D97706`, `#B91C1C`). Either `docs/DESIGN.md` or `App.vue` must be declared the single truth source.
2. **P1: Hardcoded Hex Proliferation & Unused CSS Variables**
   - **384** hardcoded Hex literals across `src/**/*.{vue,scss}` (top offenders: `review.scss` 65, `course/index.vue` 59, `report.scss` 58, `index/index.vue` 54, `session.scss` 41, `questions.scss` 40, `AiCoachDrawer.vue` 26, `profile/index.vue` 19) plus 5 in `pages.json`.
   - Only **9** `var(--color-*)` references exist across all `src/**` (`App.vue`: 5, `LearningStatisticsCard.vue`: 4).
3. **P1: Duplicated Modal & Layout CSS + Scoped `@import` Bloat**
   - Identical `.modal-overlay` / `.modal-backdrop` / `.modal-content` / `.modal-header` / `.modal-footer` / `.modal-cancel-btn` / `.modal-confirm-btn` rules are copy-pasted across 4 files (`index/index.vue:810-904`, `profile/index.vue:294-410`, `course/index.vue:639-651,782-794`, `report.scss:328-416` + `GradingActionModal.vue:117-129`).
   - `.section-title-row`, `.section-title`, `.bottom-bar`, `.bottom-action-bar`, `.empty-state`, `.stat-divider` are duplicated across 2–4 files.
   - Each of the 10 SFCs using `<style lang="scss" scoped>@import '../<area>.scss'` duplicates the entire area stylesheet into its own scoped CSS bundle.
4. **P1: Missing `safe-area-inset-bottom` & Missing `retake_required` Badge Class**
   - **0 occurrences** of `safe-area-inset-bottom` across all `src/**`, leaving fixed bottom bars (`course/index.vue:605`, `questions.scss:263`, `session.scss:268`, `report.scss:313`, `AiCoachDrawer.vue:371`) unpadded on iPhone home-indicator devices (violates `docs/DESIGN.md:15,123`).
   - `pages/index/index.vue:104` renders `status-${item.status}` and `course/index.vue:7` renders `badge-${material.status}`, but neither defines `.status-retake_required` (`index.vue:681-706`) nor `.badge-retake_required` (`course/index.vue:386-411`).
5. **P2: Zero-Emoji Policy Violations**
   - **23 lines across 8 `.vue` files** contain Unicode Emoji or symbol glyphs (`AiCoachDrawer.vue:9,16,24,33`, `index/index.vue:61,81,125,149,168`, `profile/index.vue:12,13,53`, `course/index.vue:25,39,89,106,112,121`, `questions/index.vue:29,49`, `session/index.vue:62`, `QuestionBatchRow.vue:5`, `QuestionBankQuestionRow.vue:5`).
6. **P2: Explicit `any` Assertions & Scattered Storage Keys**
   - **40 explicit `any` occurrences** in `src/**` (17 `catch (err/error: any)`, 12 in `utils/request.ts`, 4 in `pages/index/index.vue`, 2 in `questions/index.vue`, 2 in `env.d.ts`, 1 in `types/index.ts:1`).
   - Bare storage keys scattered across 3 files: `'access_token'` (`stores/auth.ts:44,51,57`, `utils/request.ts:10,38,109`), `'practice_draft_<userId>_<practiceId>'` & `'practice_submit_key_<practiceId>'` (`stores/practice.ts:85-86,114,135,160-166`) — centralize in `src/utils/storageKeys.ts` and reconcile with `docs/DESIGN.md:155-158`.

---

## 4. Test Coverage Gaps & Spec/Design Drift

### Test Coverage Gaps (`vitest run --coverage`: 45.69% stmts/lines, 75.74% branch, 61.62% funcs)

- **Untested Pure Logic (Easy Wins)**: `src/subpackages/report/utils/reportView.ts` (104 lines) has **0% coverage** (`resolveResultBadge`, `collectWrongKnowledgePointIds`, `buildWeakPointViews`, `resolveSessionScope`, `formatAnswer`). `src/pages/review/reviewView.ts` is at **69.69%** (missing `practiceStatusText`, `practiceActionText`, `practiceQuestionLabel`, `groupKnowledgePointIds`, `recordRegenerateScope`).
- **Low-Coverage Stores**: `src/stores/material.ts` (**51.13%** — `upload`, `triggerParse`, `pollMaterialStatus`, `loadMaterialList`, `loadKnowledgeTree`, `loadKnowledgePointWithSnippets`, `loadQuestions` untested) and `src/stores/folder.ts` (**55.68%** — `createFolder`, `renameFolder`, `archiveFolder`, `loadFolderKnowledgePoints` untested).
- **0%-Covered UI Modules**: **8 of 9 page SFCs** (`pages/index`, `pages/review`, `pages/auth/login`, `course`, `questions`, `upload`, `session`, `report/detail`; only `pages/profile/index.vue` has 83.21% via `learningStatistics.spec.ts`), `App.vue`, and **7 of 11 components** (`AiCoachDrawer`, `QuestionPreviewCard`, `WrongRecordCard`, `PracticeEntryCard`, `ReportSummaryCard`, `AttemptResultCard`, `GradingActionModal`) have **0% coverage**.
- **Test Type-Safety Blind Spot**: `miniprogram/tsconfig.json:22-27` includes only `src/**`, so `vue-tsc --noEmit` never type-checks `miniprogram/tests/**`.

### `.trellis/spec/frontend/*.md` Drift (Last Verified `2026-09-29`, Stale vs `2026-11-17`)

Discovered spec files under `.trellis/spec/frontend/`:
- `D:/code/Workspace/zhilian/.trellis/spec/frontend/index.md`
- `D:/code/Workspace/zhilian/.trellis/spec/frontend/directory-structure.md`
- `D:/code/Workspace/zhilian/.trellis/spec/frontend/component-guidelines.md`
- `D:/code/Workspace/zhilian/.trellis/spec/frontend/hook-guidelines.md`
- `D:/code/Workspace/zhilian/.trellis/spec/frontend/state-management.md`
- `D:/code/Workspace/zhilian/.trellis/spec/frontend/type-safety.md`
- `D:/code/Workspace/zhilian/.trellis/spec/frontend/quality-guidelines.md`
- `D:/code/Workspace/zhilian/.trellis/spec/frontend/api-payload-contracts.md`
- `D:/code/Workspace/zhilian/.trellis/spec/frontend/network-contract.md`

Key drifts against 2026-11-17 code:
1. **Composables & Components count**: `index.md:19`, `directory-structure.md:66`, `hook-guidelines.md:14`, `component-guidelines.md:17-27` claim "only 1 composable (`useQuestionCompose.ts`)" and "7 components", omitting 4 newer composables (`useMaterialDelete`, `useLearningStatistics`, `useQuestionBank`, `useWrongMarking`, located under `pages/*/composables/` not just `subpackages/*/composables/`) and 4 newer components (`LearningStatisticsCard`, `QuestionBankSection`, `QuestionBatchRow`, `QuestionBankQuestionRow`, total 11 custom components) plus `src/utils/questionBatch.ts`.
2. **Test runner & `@vue/test-utils` status**: `index.md:20`, `quality-guidelines.md:28,86,90,91,608` claim "9 spec files / 62 (or 69) tests", "no `mount()` tests", and "no `coverage` config in `vitest.config.ts`". Actual: **15 spec files / 140 tests**, `@vue/test-utils` `mount()` IS used (`tests/learningStatistics.spec.ts`, `tests/questionBankSection.spec.ts`), and `vitest.config.ts:19-31` configures v8 coverage.
3. **Oversized file & token metrics**: `index.md:54`, `quality-guidelines.md:548-566`, `component-guidelines.md:129`, `type-safety.md:15,32` cite 5 `.vue` > 300L (now **6**), 3 `.ts` > 300L (now **5** > 250L), 28 `any` (now **40**), 361 Hex literals (now **384**), and 5 `var(--color-*)` all in `App.vue` (now **9**, including `LearningStatisticsCard.vue`).
4. **Hook lifecycle & store inventory**: `hook-guidelines.md:17` claims 0 `onUnmounted`/`getCurrentInstance` and no lifecycle cleanup in composables, missing `onScopeDispose` in `useLearningStatistics.ts:53`; `state-management.md:33` omits `materialStore.deleteMaterial`.
5. **Payload contract drift (`api-payload-contracts.md`)**: `api-payload-contracts.md:57-77,124-126` claims omitting `question_count` when sending `question_ids` silently truncates to 10 at runtime, which is now stale relative to `backend/app/schemas/practice.py:133-140` (`_sync_question_count_with_ids`).
