# Quality Guidelines

> **事实源**：`miniprogram/src/**`、`miniprogram/tests/**`、`miniprogram/.eslintrc.cjs`、`miniprogram/package.json`、`miniprogram/vitest.config.ts`、`miniprogram/tsconfig.json`
> **最后核对**：2026-09-29
> **核对方式**：逐条对照代码锚点 + 实跑 `pnpm run lint` / `pnpm run type-check` / `pnpm run test:unit`
> 本文档所述约定均已对照上述代码核实；与现状不符的历史承诺已在文末「已知偏离」中如实列出。

> Code quality standards and verification baseline for frontend development.

---

## Overview

Frontend quality standards for the UniApp / Vue 3 mini-program are enforced via ESLint, vue-tsc, and Vitest.
All frontend commands must be run within the `miniprogram/` directory using `pnpm`.

### Quality Gate Commands

```bash
cd miniprogram
pnpm run lint          # eslint . --ext .vue,.js,.ts
pnpm run type-check    # vue-tsc --noEmit（仅 src/**，见 tsconfig.include）
pnpm run test:unit     # vitest run
```

等价入口：仓库根 `Taskfile.yml` 的 `task verify-frontend`（依次跑上述三条）/ `task test-frontend` / `task format`（`pnpm run lint --fix`）。

**2026-09-29 实测**：三条门禁全绿；Vitest 输出 `Test Files 7 passed (7)` / `Tests 39 passed (39)`。

---

## Forbidden Patterns

按 `.eslintrc.cjs` 的**真实配置**描述（不是理想态）：

- **显式 `any` 是允许的**：`@typescript-eslint/no-explicit-any` 配置为 **`off`**。当前 `src/**` 有 28 处 `any`，主要是 `catch (error: any)` 与 uni 回调参数（`success: async (res: any)`）。**不要**在规范或 review 里把 `any` 说成被禁止——它不会被门禁拦下。
- **未使用变量是允许的**：`@typescript-eslint/no-unused-vars` 为 **`off`**；`@typescript-eslint/ban-types` 同为 `off`。
- **直接改全局状态而不经 store**：页面/组件对全局状态一律经 `useXxxStore()` 的 action 或 `ref` 赋值（store 内 `ref` 是响应式的，如 `authStore.user = {...}`），不在模块级维护可变的跨页单例。
- **内联密钥**：API key / secret 不得进前端源码。`API_BASE_URL` 经 `(import.meta as any).env?.VITE_API_BASE_URL` 读取，默认 `http://localhost:8000/api/v1`。
- **静默吞错**：主流程失败必须 toast；`catch { console.error(...) }` 只允许出现在非关键路径（如 `materialStore.loadKnowledgeTree`、`pages/review/index.vue::loadWrongs`），且不得让用户以为操作成功。

---

## Required Patterns

- **显式类型化的公开边界**：组件 props/emits、store action、`src/api/*` 的导出函数必须显式类型化（`any` 虽为 `off`，但门禁依赖 `vue-tsc --strict` 通过）。
- **网络出口唯一**：所有 HTTP 调用经 `src/utils/request.ts` 的 `request` / `uploadFile`，或经 `src/api/*` 封装。页面可以直接调 `@/api`，但没有页面自行 `uni.request`。
- **跳转必须带 `fail` 兜底**：全仓库 12 处 `uni.navigateTo` / `uni.redirectTo` **全部**带 `fail` 提示；`request.ts` 的 `uni.reLaunch` 与报告页的 `uni.switchTab` 同样带 `fail`。已知例外：`pages/auth/login.vue::handleLogin` 登录成功后的 `uni.switchTab` 未带 `fail`。
- **可选 query 参数由 API 函数条件拼装**：API 函数内用 `queryParts.push(...)` + `encodeURIComponent` 组装，**真值才拼接**（如 `if (params?.folder_id) queryParts.push(...)`；分页用 `!== undefined` 判断以放行 `0`）。`request.ts` 本身**不做** GET data 清洗，它把 `options.data` 原样交给 `uni.request`。
- **未判题不得计零分或答错**：`score` / `isCorrect` 保持 `null`，UI 渲染「判题中 / 待重判 / 未作答」。
- **正式诊断必须有门禁**：未全卷判完不得请求/展示诊断报告。

---

## Testing Requirements

- **框架**：Vitest + `happy-dom` 环境 + `globals: true`，setup 文件 `tests/setup.ts`（`vitest.config.ts`）。
- **位置**：`miniprogram/tests/` 平铺（**没有** `tests/unit/` 子目录层级）；后端契约样本在 `tests/fixtures/backendResponses.ts`，注释钉死事实源为 `backend/app/schemas/{practice,diagnosis,question}.py`。
- **当前规模**：7 个 spec 文件 / 39 个用例 —— `apiContracts`(3)、`backendContracts`(15)、`diagnosisAndCompose`(5)、`draftQueue`(4)、`materialState`(2)、`practice`(2)、`practiceStore`(8)。
- **`uni` 全局 mock**：`tests/setup.ts` 注入内存版 `uniMock`（`Map` 支撑的 `getStorageSync`/`setStorageSync`/`removeStorageSync`/`clearStorageSync`，以及 `showToast`/`showLoading`/`hideLoading`/`navigateTo`/`redirectTo`/`switchTab`/`showModal`）。
- **网络 mock**：用 `vi.hoisted` + `vi.mock('@/utils/request', ...)` 替换 `request` / `uploadFile`，测试内按 `options.url` 匹配响应（`tests/practiceStore.spec.ts`、`tests/diagnosisAndCompose.spec.ts`）。
- **Store 测试用 `setActivePinia(createPinia())`**（`beforeEach`）。
- **只测纯函数、适配器与 store**：当前**没有任何组件挂载测试**；`@vue/test-utils` 虽在 `devDependencies` 中，但 `rg "test-utils|mount(" tests/` 无命中。需要验证组件行为时，优先把逻辑下移到纯函数（`reportView.ts` / `reviewView.ts` / `adapters/*`）再测。
- **通过率**：门禁要求 100% 通过，不允许回归；**没有覆盖率阈值**（`vitest` 未配 coverage，与后端 `--cov-fail-under=80` 不同）。
- **测试文件不受类型门禁约束**：`tsconfig.include` 只覆盖 `src/**`，`vue-tsc` 不检查 `tests/**`。新增测试请自行保持类型正确，不要指望门禁兜住。

---

## 契约 Scenario

### Scenario: 草稿串行写入队列（同题串行 + 失败可见 + 交卷前 flush）

#### 1. Scope / Trigger
- 练习作答的每一次改动（单选/多选/填空/简答/判断题）。

#### 2. Signatures
```typescript
// miniprogram/src/utils/draftQueue.ts
export interface DraftQueue {
  enqueue(questionId: string, answer: unknown): void;
  flush(): Promise<boolean>;          // false = 仍有失败未恢复
  retry(questionId: string): Promise<void>;
  retryAll(): Promise<void>;
  reset(): void;
  hasFailures(): boolean;
  state(): DraftQueueState;           // { isPending, failures: { questionId, error }[] }
}
export function createDraftQueue(
  save: (questionId: string, answer: unknown) => Promise<void>,
  onChange?: (state: DraftQueueState) => void,
): DraftQueue;
```

#### 3. Contracts
- **同题串行**：同一 `questionId` 同时在飞的写入最多 1 个（`workers: Map<string, Promise<void>>`）；写入期间的新输入只覆盖 `latest` 的**最后值**，不排队堆积。
- **跨题并行**：不同题目各自起 worker，互不阻塞、互不串数据。
- **退出瞬间窗口必须封死**：worker 的 `finally` 里若发现 `latest` 又有新值，要立刻重新 `startWorker`，否则那次输入会被漏派发。
- **`flush()` 反复收敛**：在「等待在途 worker」与「把等待期间新入队的题目继续派发」之间循环，直到两者都为空（上限 1000 轮防死循环），返回 `failures.size === 0`。
- **失败可见**：写入失败进 `failures`，经 `onChange` 冒泡到 `practiceStore.draftFailures`，由会话页顶部横幅展示并给出「重试」按钮（`retryAllDrafts`）。不静默吞错。
- **交卷前必须 flush 成功**：`practiceStore.submit()` 先 `await draftQueue.flush()`，返回 `false` 时抛 `Error('仍有作答未保存成功，请检查网络后重试')` 并**不提交**。

#### 4. Validation & Error Matrix
- 同题快速连续输入 `A → AB → ABC` → 实际落库为 `A`、`ABC`（首值与最后值；中间值被合并掉）。
- 不同题目并发 → 都落库，无交叉污染。
- 写入失败 → `hasFailures()` 为真，`flush()` 返回 `false`；`retry(questionId)` 用**最后一次作答**重发。
- 交卷时仍有失败 → 提交被阻断，错误信息上抛给 `uni.showToast`。

#### 5. Wrong vs Correct
##### Wrong
```typescript
// 错误：每次输入直接发请求 —— 快速输入乱序到达，后到的旧值覆盖新值
const handleInput = (qid: string, value: string) => {
  void apiSavePracticeDraft(practiceId, qid, value);
};
// 错误：交卷不等草稿 —— 用户刚输入的答案还没落库就交卷
await apiSubmitPractice(practiceId, true, key);
```
##### Correct
```typescript
// 正确：内存 + 本地 storage 先落，再入队串行写后台
practiceStore.recordAnswer(qid, value);
// 正确：交卷前 flush，失败即阻断
const saved = await draftQueue.flush();
if (!saved) throw new Error('仍有作答未保存成功，请检查网络后重试');
```

#### 6. Tests Required
- `tests/draftQueue.spec.ts`：同题快速输入合并、跨题并行不串、失败可见且可重试、flush 期间新入队不被漏掉。
- `tests/practiceStore.spec.ts`：交卷前 flush 且刷新会话；草稿保存失败时阻断提交并上抛失败；同一提交重试复用稳定 `Idempotency-Key`。

#### 代码锚点
- `miniprogram/src/utils/draftQueue.ts::createDraftQueue`
- `miniprogram/src/utils/draftQueue.ts::flush`
- `miniprogram/src/utils/draftQueue.ts::startWorker`
- `miniprogram/src/stores/practice.ts::recordAnswer`
- `miniprogram/src/stores/practice.ts::submit`
- `miniprogram/src/subpackages/practice/pages/session/index.vue::.draft-banner`
- `miniprogram/tests/draftQueue.spec.ts`
- `miniprogram/tests/practiceStore.spec.ts`

---

### Scenario: 草稿本地持久化按「用户 + 练习」隔离

#### 1. Scope / Trigger
- 换账号或切换练习后，上一账号/上一练习的本地草稿不得被复用到新会话。

#### 2. Contracts
- 本地草稿 key 为 `practice_draft_${resolveUserId()}_${practiceId}`，`resolveUserId()` 取 `useAuthStore().user?.id`，取不到时回退 `'anonymous'`（`try/catch` 包裹，store 未初始化也不抛）。
- 幂等键 key 为 `practice_submit_key_${practiceId}`，与用户无关。
- 初始化练习时**优先恢复本地草稿**，其次才用服务端 `session.user_answers`；两者都为空则空作答。
- 交卷成功后同时清 `practice_draft_*` 与 `practice_submit_key_*`。

#### 3. Tests Required
- `tests/practiceStore.spec.ts`：本地草稿按用户隔离，只恢复当前用户的草稿。

#### 代码锚点
- `miniprogram/src/stores/practice.ts::getStorageKey`
- `miniprogram/src/stores/practice.ts::resolveUserId`
- `miniprogram/src/stores/practice.ts::initPractice`

---

### Scenario: 交卷幂等键稳定性

#### 1. Scope / Trigger
- 交卷请求 `POST /practices/{id}/submit` 的网络重试、用户重复点击、App 重启后重试。

#### 2. Signatures
```typescript
// miniprogram/src/api/index.ts
export function apiSubmitPractice(
  practiceId: string,
  confirmUnanswered = true,
  idempotencyKey = practiceId,
): Promise<{ practice_id: string; status: string; task_id?: string }>;
```
请求头携带 `Idempotency-Key`。

#### 3. Contracts
- 同一练习的同一轮提交必须复用**同一个** key：`submit()` 先读 `practice_submit_key_<id>`，读不到才用 `randomKey()`（`Date.now().toString(36)` + `Math.random().toString(36).slice(2, 10)`）生成并**立即落盘**，然后才发请求。
- 只有在「提交 + 拉取会话」都成功后，才 `removeStorageSync` 掉草稿 key 与 submit key。
- key 落盘必须发生在请求之前，否则 App 重启后生成新 key，重试不再幂等。

#### 4. Tests Required
- `tests/practiceStore.spec.ts`：同一提交重试时 `Idempotency-Key` 保持不变。

#### 代码锚点
- `miniprogram/src/stores/practice.ts::submit`
- `miniprogram/src/stores/practice.ts::getSubmitKeyStorage`
- `miniprogram/src/api/index.ts::apiSubmitPractice`

---

### Scenario: 正式诊断必须等全卷判完（不得伪造零分报告）

#### 1. Scope / Trigger
- 结果页 / 报告页首屏加载、判题轮询、「判题中」态展示。

#### 2. Signatures
```typescript
// miniprogram/src/stores/diagnosis.ts
const loadReport = async (
  practiceId: string,
  maxAttempts = 15,
  intervalMs = 2000,
): Promise<DiagnosisReport | null>;   // null = 尚未判完

// miniprogram/src/api/adapters/practice.ts
export function summarizeProgress(session: PracticeSession | null): PracticeProgress;
// PracticeProgress: { total, graded, grading, pendingRegrade, unanswered, fullyGraded }
```

#### 3. Contracts
- **触发时序**：交卷 → `uni.redirectTo` 结果页 → 结果页逐题渲染判题进度 → 全卷判完才请求诊断。**不存在**「交卷后直达诊断报告」的路径。
- **两个全判口径并存，各自使用**：
  - `diagnosisStore.loadReport` 的判定是 `Boolean(session.completed_at) && session.status === 'completed'`；命中才调 `POST /practices/{id}/diagnosis` 取回/生成正式报告，否则置 `isPending = true`、`currentReport` 保持 `null`。
  - `summarizeProgress().fullyGraded` 更严格：`completed_at` 非空 **且** `grading === 0` **且** `pendingRegrade === 0` **且** 有题目；结果页的 UI 门禁用它。
- **未判完必须可视化**：`ReportSummaryCard` 在 `!isFullyGraded` 时渲染「全卷仍在判题中，正式学情诊断将在全部题目判完后自动生成。待判题目不计入错题与得分统计。」，得分率显示 `—`。
- **轮询终止条件**：结果页 `pollGrading` 最多 20 轮、每轮 2.5s，命中 `fullyGraded` **或** `needsRetry` 即 break（避免无效等待后仍无提示）；`onUnload` 必须 `clearTimeout`。
- **失败/缺失**：`loadReport` 用尽 `maxAttempts` 仍返回 `null`，不抛错、不伪造报告。

#### 4. Wrong vs Correct
##### Wrong
```typescript
// 错误：交卷后直接 POST /diagnosis 并渲染报告 —— 判题未完成时会渲染出零分/全错
await submitPractice(id);
const report = await triggerDiagnosis(id);
render(report);
```
##### Correct
```typescript
// 正确：先确认全卷判完，再触发/取回正式报告
const fullyGraded = Boolean(session.completed_at) && session.status === 'completed';
if (!fullyGraded) {
  isPending.value = true;
  await sleep(intervalMs);
  continue;
}
currentReport.value = await apiTriggerDiagnosis(practiceId);
```

#### 5. Tests Required
- `tests/diagnosisAndCompose.spec.ts`：未判完时 `loadReport` 返回 `null`、`isPending` 为真、`currentReport` 仍为 `null`，且**不发出**任何 `/practices/*/diagnosis` 请求；`completed_at` 落库后才拉取正式报告。
- `tests/backendContracts.spec.ts`：`fullyGraded` 只在 `completed_at` 落库后为真。

#### 代码锚点
- `miniprogram/src/stores/diagnosis.ts::loadReport`
- `miniprogram/src/api/adapters/practice.ts::summarizeProgress`
- `miniprogram/src/subpackages/report/pages/detail/index.vue::pollGrading`
- `miniprogram/src/subpackages/report/components/ReportSummaryCard.vue`（`.pending-notice`）
- `miniprogram/tests/diagnosisAndCompose.spec.ts`

---

### Scenario: 未判定题目不得显示为零分或答错

#### 1. Scope / Trigger
- 逐题结果卡片的判题状态与分数展示。

#### 2. Contracts
- `resolveGradingStatus(item)` 的优先级：`!is_answered → 'unanswered'`；`grading_status === 'pending_regrade' → 'pending_regrade'`；`grading_status === 'graded' → 'graded'`；有 `score` 数字 → `'graded'`；否则 → `'grading'`。
- `isCorrect` 只在 `gradingStatus === 'graded' && typeof score === 'number'` 时计算（`score >= maxScore`），其余情况一律 `null`。
- `score` 只在 `typeof item.score === 'number'` 时取值，否则 `null`（不得回退成 `0`）。
- `isPending = gradingStatus === 'grading' || gradingStatus === 'pending_regrade'`。
- UI 文案由 `resolveResultBadge` 统一映射：`未作答` / `判题中` / `待重判` / `正确 x/y` / `错误 x/y`；`isCorrect === null` 一律落「判题中」。
- 得分/错题统计不得把 pending 项算进去：报告页 `wrongCount` 在未全判时用 `results.filter(r => r.isCorrect === false).length`，全判后才用后端 `report.wrong_count`。

#### 3. Tests Required
- `tests/backendContracts.spec.ts`：pending 项 `score === null`、`isCorrect === null`、`isPending === true`；未作答项 `gradingStatus === 'unanswered'`；`summarizeProgress` 统计为 `{ total: 3, graded: 1, pendingRegrade: 1, unanswered: 1, fullyGraded: false }`。

#### 代码锚点
- `miniprogram/src/api/adapters/practice.ts::resolveGradingStatus`
- `miniprogram/src/api/adapters/practice.ts::buildAttemptResults`
- `miniprogram/src/subpackages/report/utils/reportView.ts::resolveResultBadge`
- `miniprogram/src/subpackages/report/components/AttemptResultCard.vue`（待重判/判题中分支）

---

### Scenario: 判题重试入口只在 `partially_graded` 出现

#### 1. Scope / Trigger
- 主观题 LLM 超时降级为待重判，或判题任务终态失败被后端回写为待重判。

#### 2. Contracts
- `needsGradingRetry(session)` 等价于 `session?.status === 'partially_graded'`。
- **`submitted`（判题进行中）不提供重试入口**，避免重复派发判题任务。
- 结果页的 `needsRetry = needsGradingRetry(session) && !fullyGraded`：已全判完则不显示。
- `retryGrading(practiceId)` 调 `POST /practices/{id}/regrade` 后必须 `refreshSession` 读回真实状态；无进行中练习时抛 `Error('当前没有可重试判题的练习')`。

#### 3. Tests Required
- `tests/backendContracts.spec.ts`：`partially_graded` 为真、`submitted` / `completed` 为假。
- `tests/practiceStore.spec.ts`：重试会重新派发判题并刷新会话；无活跃练习时拒绝重试。

#### 代码锚点
- `miniprogram/src/api/adapters/practice.ts::needsGradingRetry`
- `miniprogram/src/api/index.ts::apiRetryPracticeGrading`
- `miniprogram/src/stores/practice.ts::retryGrading`
- `miniprogram/src/subpackages/report/pages/detail/index.vue::handleRetryGrading`

---

### Scenario: 后端 wire 契约归一化单点

#### 1. Scope / Trigger
- 任何消费后端 JSON 的页面 / 组件 / store。

#### 2. Contracts
- `items[].question_snapshot` 是练习卷面的**唯一**题面来源；禁止引用不存在的 `data.items` / `question.stem` 之类的漂移字段。
- 诊断报告只消费后端真实字段；禁止假定 `details` / `score` / `accuracy` / `weaknesses`。
- 错题题干只来自后端下发的 `question_snapshot`（`wrongSnapshotStem` 缺失时返回 `'题干快照缺失'`）。
- `source_quote` 的正文由两侧的下发路径提供：练习详情响应（`PracticeService._attach_source_snippets`）与题目响应（`QuestionService.attach_source_snippets`），二者都装配 `source_snippet{chapter_title, page_index, snippet_content}`。无来源或切片已删除时后端返回 `null`，断言 `source_quote` 为 `undefined`（空态）；**不得**靠手工补字段让断言通过。
- 资料状态大小写归一：后端可能返回 `'READY'`，`adaptMaterial` 统一降为小写状态机取值，未知值回退 `'pending'`。

#### 3. Tests Required
- `tests/apiContracts.spec.ts` + `tests/backendContracts.spec.ts` 覆盖三条主链路 + 错题分组 + 出题规划 + 题目/练习两侧的来源正文映射（含无来源空态）。用例数用 `pnpm run test:unit` 的实时结果，不在文档里手抄。

#### 代码锚点
- `miniprogram/src/api/adapters/practice.ts::adaptPractice`
- `miniprogram/src/api/adapters/question.ts::adaptQuestion`
- `miniprogram/src/api/adapters/diagnosis.ts::adaptDiagnosisReport`
- `miniprogram/src/api/adapters/wrong.ts::wrongSnapshotStem`
- `miniprogram/tests/fixtures/backendResponses.ts`

---

### Scenario: 多考点出题必须真覆盖，且遵守单批上限

#### 1. Scope / Trigger
- 勾选多个考点出题、剔除/重生成题目后的「开始作答」门禁。

#### 2. Signatures
```typescript
export const MAX_QUESTION_BATCH = 20;
export function planGenerationBatches(
  knowledgePointIds: string[],
  desiredCount: number,
): GenerationBatch[];                       // { knowledgePointIds, count }[]
export function computeKnowledgeCoverage(
  questions: Array<Pick<QuestionItem, 'knowledge_point_id'>>,
  selectedKnowledgePointIds: string[],
): CoverageResult;                          // { covered, missing, ratio }
```

#### 3. Contracts
- **目标题量取上界**：`target = max(uniqueKpCount, desiredCount)`，即「覆盖全部已选考点」优先于用户指定题量；UI 必须把题量调整**预先披露**（`generationNotice` / 计划题量提示），不静默加量。
- **分批**：按 `MAX_QUESTION_BATCH = 20` 切块；每批 `count` 取 `min(20, max(chunk.length, share))`，保证每批考点数不超过题数。
- **覆盖以题目快照为准**：`computeKnowledgeCoverage` 只认题目实际携带的 `knowledge_point_id`；`missing.length > 0` 时 `canStart` 为假，必须先 `fillCoverageGap()` 补齐或调整考点。
- **剔题后重算**：`remainingQuestions` 变化会驱动 `coverage` / `canStart` / `generationNotice` 重算；剔除到覆盖缺口时开始按钮自动禁用。
- **失败/空结果不推进状态**：生成 0 道合格题时 toast 并保持原状态，不清空既有题目。

#### 4. Tests Required
- `tests/backendContracts.spec.ts`：每个已选考点都被覆盖且单批不超 20；目标题量被抬到考点数；覆盖不足时报缺口而非假定成功。
- `tests/diagnosisAndCompose.spec.ts`：计划题量抬升；剔除造成缺口时阻断开始；补齐只对缺失考点生成。

#### 代码锚点
- `miniprogram/src/api/adapters/question.ts::planGenerationBatches`
- `miniprogram/src/api/adapters/question.ts::computeKnowledgeCoverage`
- `miniprogram/src/subpackages/material/composables/useQuestionCompose.ts::canStart`
- `miniprogram/src/subpackages/material/pages/questions/index.vue::handleStartPractice`

---

### Scenario: 错题再生题范围必须单一归属

#### 1. Scope / Trigger
- 学情页按课程/资料分组巩固错题、报告页「错题针对性生题」。

#### 2. Contracts
- 分组枚举来自后端 `groups`（覆盖完整错题本而非当前分页第一页）：一个完整课程（`folder_id`）或一份未分类资料（`material_id`），两者互斥。
- `resolveRegenerateScope(option)` 必须且只能解析出 `{ folderId }` 或 `{ materialId }`；两者皆无时返回 `null`。
- `practiceStore.regenerateFromWrongPoints` 的三道守卫：知识点为空 → `'未提供错题知识点'`；scope 为空 → `'缺少课程或资料范围，无法再生题'`；两者同时给出 → `'再生题范围只能指定一个课程或一份资料'`。
- 生成结果为空 → `'未生成可用题目，请稍后重试'`，不落空练习。
- 客户端的 `recordsInGroup` 按 `folder_id` / `material_id` 精确匹配，不得把跨课程错题混进同一分组。
- 报告页的 scope 来自练习详情自身（`resolveSessionScope`：`folder_id` 优先，其次 `material_id`），不让页面猜归属。

#### 3. Wrong vs Correct
##### Wrong
```typescript
// 错误：把多个课程的错题汇总成一次再生题 —— 归属错误的学习记录
await regenerate(allKpIdsFromAllCourses, { folderId: firstCourseId });
```
##### Correct
```typescript
// 正确：先选分组，再按该分组的单一归属再生
const scope = resolveRegenerateScope(activeGroup);       // 唯一归属或 null
if (!scope || !activeKpIds.length) return;
await practiceStore.regenerateFromWrongPoints(activeKpIds, scope);
```

#### 4. Tests Required
- `tests/backendContracts.spec.ts`：分组为一个课程 + 一个未分类资料；再生范围恰好落一个课程或一个未分类资料；按分组过滤不混课程。
- `tests/practiceStore.spec.ts`：再生前必须恰有一个课程或资料范围；在单一范围内再生并回报覆盖率。

#### 代码锚点
- `miniprogram/src/api/adapters/wrong.ts::buildWrongGroupOptions`
- `miniprogram/src/api/adapters/wrong.ts::resolveRegenerateScope`
- `miniprogram/src/api/adapters/wrong.ts::recordsInGroup`
- `miniprogram/src/stores/practice.ts::regenerateFromWrongPoints`
- `miniprogram/src/subpackages/report/utils/reportView.ts::resolveSessionScope`
- `miniprogram/src/pages/review/index.vue::handleBatchRegenerate`

---

### Scenario: 资料解析状态机与手动解析门禁

#### 1. Scope / Trigger
- 资料上传后手动触发解析、解析中展示、终态判定。

#### 2. Signatures
```typescript
// miniprogram/src/utils/materialState.ts
export function canStartMaterialParse(material: MaterialState): boolean;
export function isMaterialParsing(material: MaterialState): boolean;
export function materialStatusText(material: MaterialState): string;
// MaterialState = Pick<MaterialItem, 'status' | 'parse_status'> | null | undefined
```

#### 3. Contracts
- **主状态机**：`pending | parsing | ready | failed | retake_required`（`MaterialStatus`，与 `backend/app/models/material.py` 对齐）。
- **门禁**：`canStartMaterialParse` 要求 `status === 'pending'` **且** `parse_status` 为空或 `'not_started'`——已排队（`queued`）的资料不得重复触发。
- **进行中判定**：`isMaterialParsing` 先短路终态（`ready` / `failed` / `retake_required` 一律为假），否则 `status === 'parsing'` 或 `parse_status ∈ {queued, parsing_doc, ocr_processing, extracting_knowledge, auditing_knowledge, embedding_generation}`。
- **文案**：`queued → '排队中'`，其余进行中 → `'解析中'`；终态映射为 `'已解析' / '解析失败' / '需要重拍'`，默认 `'待解析'`。
- **轮询**：`materialStore.pollMaterialStatus(id, maxAttempts = 20, interval = 1500)`，命中 `ready` / `failed` / `retake_required` 即返回，超时抛 `'资料解析超时，请稍后刷新'`。**没有自适应退避，也没有 3 分钟熔断**——间隔固定 1500ms、最多 20 次。
- **触发点**：工作台卡片与课程详情页均可在 `canStartMaterialParse` 或 `status === 'failed'` 时按钮触发 `POST /materials/{id}/parse`。

#### 4. Tests Required
- `tests/materialState.spec.ts`：新上传可触发、已排队不可重复触发且判定为进行中；OCR / 知识抽取等阶段判定为进行中；`failed` 短路为终态；`retake_required` 文案正确。

#### 代码锚点
- `miniprogram/src/utils/materialState.ts::canStartMaterialParse`
- `miniprogram/src/utils/materialState.ts::isMaterialParsing`
- `miniprogram/src/utils/materialState.ts::materialStatusText`
- `miniprogram/src/stores/material.ts::pollMaterialStatus`
- `miniprogram/src/subpackages/material/pages/course/index.vue::syncParseProgress`

---

### Scenario: 跨页导航参数契约

#### 1. Scope / Trigger
- 所有 `uni.navigateTo` / `uni.redirectTo` 的目标页参数。

#### 2. 真实契约（逐条核对代码得出）

| 目标页 | 参数名 | 发送方 | 接收方解析 |
| --- | --- | --- | --- |
| `subpackages/material/pages/course/index` | `id`（= materialId） | `pages/index/index::goToDetail`、`AiCoachDrawer::openSource` | `options.id`（无兜底，缺则整页不加载） |
| `subpackages/material/pages/questions/index` | `material_id` **或** `folder_id` | `pages/index/index::goToQuestions` / `::goToCourseGenerate`、`course/index::goToQuestionConfig` | 先 `options.folder_id`，否则 `options.material_id` |
| `subpackages/practice/pages/session/index` | `practice_id` | `pages/review/index::navigateToSession`、`questions/index::handleStartPractice`、`report/detail::handleAdaptivePractice` | `options.practice_id`（缺失 toast「缺少练习标识」） |
| `subpackages/report/pages/detail/index` | `practice_id` | `pages/review/index::openPractice`、`session/index::confirmSubmit`（`redirectTo`） | `options.practice_id`（缺失置 `loadError`） |
| `pages/auth/login` | 无 | `pages/index/index::goToLogin`、`pages/profile/index::goToLogin`、`request.ts::handleUnauthorized`（`reLaunch`） | — |

- **参数名不统一是现状，不是错误**：课程/资料详情页用裸 `id`，出题页用 `material_id` / `folder_id`，练习与报告页统一 `practice_id`。规范只要求「发送方与接收方逐字对齐」+「接收页对缺失参数给出显式提示」，**不要求**统一成 `material_id`。
- 出题页的 `folder_id` 与 `material_id` 互斥：`onLoad` 用 `if (options?.folder_id) … else if (options?.material_id) …`；`handleStartPractice` 提交时同样保证 `folder_id` 存在则不传 `material_id`。
- 所有跳转必须带 `fail` 提示。

#### 3. Wrong vs Correct
##### Wrong
```typescript
// 错误：给 course 页发 material_id —— 接收页只读 options.id，页面整片空白
uni.navigateTo({ url: `/subpackages/material/pages/course/index?material_id=${id}` });
// 错误：改参数名却不改接收页，且无 fail 兜底 —— 用户看到「原地不动」
uni.navigateTo({ url: `/subpackages/material/pages/questions/index?id=${id}` });
```
##### Correct
```typescript
// 正确：发送方与接收方逐字对齐，且带 fail 兜底
uni.navigateTo({
  url: `/subpackages/material/pages/course/index?id=${item.id}`,
  fail: () => uni.showToast({ title: '打开讲义失败，请重试', icon: 'none' }),
});
uni.navigateTo({
  url: `/subpackages/material/pages/questions/index?material_id=${item.id}`,
  fail: () => uni.showToast({ title: '打开出题页失败，请重试', icon: 'none' }),
});
```

#### 4. Tests Required
- 当前**没有**页面参数解析的单测（`tests/` 下无页面级 spec）。改动导航契约时请人工核对上表的两端，或补纯函数化的参数解析后再测。

#### 代码锚点
- `miniprogram/src/subpackages/material/pages/course/index.vue::onLoad`
- `miniprogram/src/subpackages/material/pages/questions/index.vue::onLoad`
- `miniprogram/src/subpackages/practice/pages/session/index.vue::onLoad`
- `miniprogram/src/subpackages/report/pages/detail/index.vue::onLoad`

---

### Scenario: 网络层错误处理与 401 收敛

#### 1. Scope / Trigger
- 所有 HTTP 调用。

#### 2. Contracts
- `request<T>` **解包** `{ code, message, data }` 信封后返回 `data`；若响应体不是信封形状则原样返回。
- 2xx → resolve；`401` → `handleUnauthorized()`（清 `access_token`、动态 import `useAuthStore().clearAuth()`、toast「登录已过期，请重新登录」、`reLaunch` 登录页并带 `fail`）后 reject `Error('Unauthorized')`。
- 其他非 2xx → toast `errData.detail || errData.message || '请求失败 (statusCode)'` 并 reject。
- 网络失败（`fail`）→ toast「网络连接异常，请重试」并 reject。
- `uploadFile` 走同构分支：202 → `JSON.parse(res.data)` 解包 `data`；解析失败则 resolve 原始字符串；401 同上；其他非 2xx → toast「上传失败，请重试」。
- **没有 token 刷新、没有重试计数、没有请求超时设置**：`RequestOptions` 只有 `url` / `method?` / `data?` / `header?`（无 `_retryCount`）；`request.ts` 内不存在 `setTokenRefreshListener` / `executeRefreshToken` / `MAX_AUTH_RETRY_COUNT`。
- 存令牌只用一个裸 key：`uni.getStorageSync('access_token')`。

#### 3. Tests Required
- 当前无 `request.ts` 的单测；`tests/practiceStore.spec.ts` / `tests/diagnosisAndCompose.spec.ts` 通过 mock 掉整个 `@/utils/request` 模块来隔离网络层。

#### 代码锚点
- `miniprogram/src/utils/request.ts::request`
- `miniprogram/src/utils/request.ts::handleUnauthorized`
- `miniprogram/src/utils/request.ts::uploadFile`
- `miniprogram/src/utils/request.ts::RequestOptions`

---

## 已知偏离（如实记录，勿美化）

### 1. 单文件 ≤ 300 行约定与当前超标文件

`docs/DESIGN.md` 第 6 节硬性约定：任何单 `.vue` 文件不得超过 **300 行**。现状（2026-09-29 实测 `wc -l`）：

**违反该条约定的 `.vue` 文件（5 个）**

| 文件 | 行数 | 超出 | 备注 |
| --- | --- | --- | --- |
| `src/pages/index/index.vue` | 865 | +565 | 模板 + 脚本 + 内联样式全在一个文件 |
| `src/subpackages/material/pages/course/index.vue` | 728 | +428 | 含知识树、考点弹窗、助教挂载 |
| `src/pages/profile/index.vue` | 440 | +140 | |
| `src/components/AiCoachDrawer.vue` | 392 | +92 | |
| `src/subpackages/report/pages/detail/index.vue` | 343 | +43 | |

**不受该条约定约束、但同属「单文件过大」的 `.ts` 文件（3 个）**

| 文件 | 行数 | 备注 |
| --- | --- | --- |
| `src/types/index.ts` | 441 | 类型单文件集中是刻意约定（见 `type-safety.md`），但已到需要按域拆分的体量 |
| `src/api/index.ts` | 424 | API 函数 + `GenerateQuestionsParams` / `CreatePracticeParams` 等接口全在一个文件 |
| `src/stores/practice.ts` | 302 | 会话 / 作答 / 草稿队列 / 交卷 / 再生题 / 判题重试全在一个 store |

其中 `pages/index/index.vue`、`subpackages/material/pages/course/index.vue`、`components/AiCoachDrawer.vue`、`api/index.ts` 在 `5d7a2f3` 之前就已超标，不是本次引入。**新代码应遵守 300 行约定**；拆分这些文件属待办项，不要在规范里写成「已拆分」。

### 2. ESLint 实际配置（与历史文档描述不同）

`.eslintrc.cjs` 的真实内容：

```javascript
module.exports = {
  root: true,
  env: { browser: true, es2021: true, node: true },
  extends: ['eslint:recommended', 'plugin:vue/vue3-recommended', 'plugin:@typescript-eslint/recommended'],
  parser: 'vue-eslint-parser',
  parserOptions: { parser: '@typescript-eslint/parser', ecmaVersion: 'latest', sourceType: 'module' },
  plugins: ['vue', '@typescript-eslint'],
  rules: {
    'vue/multi-word-component-names': 'off',
    'vue/singleline-html-element-content-newline': 'off',
    'vue/max-attributes-per-line': 'off',
    'vue/html-self-closing': 'off',
    '@typescript-eslint/no-explicit-any': 'off',
    '@typescript-eslint/no-unused-vars': 'off',
    '@typescript-eslint/ban-types': 'off',
  },
  globals: { uni: 'readonly', wx: 'readonly' },
};
```

- **`max-lines` 未配置**：不存在 500 行兜底阈值，行数只由 `docs/DESIGN.md` 的 300 行约定（人工）约束。
- **`prettier/prettier` 未配置**：`eslint-plugin-prettier` 与 `eslint-config-prettier` 装在 `devDependencies` 里，但既未进 `plugins` 也未进 `extends`，**格式规则不在门禁内**。
- `.eslintignore` 只忽略 `dist` / `node_modules` / `*.local`。
- `uni` / `wx` 声明为 `readonly` 全局；`wx` 另有 `src/env.d.ts::declare const wx: any` 的三方声明（`pages/index/index.vue` 里实际用 `(globalThis as any).wx` 取用，以规避 `#ifdef MP-WEIXIN` 之外的引用）。

### 3. 零表情包原则与现状不符

见 `component-guidelines.md` 的 Accessibility 一节；6 个文件共 19 行含 Unicode Emoji / 符号字符（合计 20 个字符）。`docs/DESIGN.md` 第 1 节要求「全系统严禁 Unicode Emoji」，当前**未落地**。

### 4. 设计 token 与裸 Hex

`docs/DESIGN.md` 第 2 节「禁止在业务组件中使用未经本规范收敛的裸 Hex 色值」。现状：`src/**` 内联 Hex 约 361 处，`var(--color-*)` 仅 5 处（全在 `App.vue`）；`src/uni.scss`、`src/styles/theme.scss` 均**不存在**。

### 5. 组件挂载测试缺失

`@vue/test-utils` 是 `devDependencies` 之一，但 `tests/` 下没有任何 `mount()` 调用；7 个 spec 全部是纯函数 / 适配器 / store 级测试。改动页面与组件行为时，请优先把逻辑抽到可测的纯函数（现有先例：`reportView.ts`、`reviewView.ts`、`api/adapters/*`、`utils/materialState.ts`、`utils/draftQueue.ts`）。

### 6. 占位页

`src/subpackages/material/pages/upload/index.vue` 是 32 行的静态占位页（`<script setup lang="ts">` 为空），已在 `pages.json` 注册但无实际功能；真实上传入口在工作台 `pages/index/index.vue::handleChooseFile`。
