# Type Safety

> **事实源**：`miniprogram/src/types/index.ts`、`miniprogram/src/api/adapters/*`、`miniprogram/tsconfig.json`、`miniprogram/vite.config.ts`、`miniprogram/.eslintrc.cjs`
> **最后核对**：2026-09-29
> **核对方式**：`rg "interface|Wire|adapt" miniprogram/src/types miniprogram/src/api` + `pnpm run type-check`

> Type safety patterns in this project. 前端为严格 TypeScript，**全部数据契约集中在单一文件 `src/types/index.ts`**；后端原始载荷以 `Wire*` 命名、只允许出现在 `src/api/adapters/` 内。

---

## Overview

- 语言：TypeScript 5，`tsconfig.json` 开启 `strict: true`（`noImplicitAny` / `strictNullChecks` 由 `strict` 隐式开启，未单独覆写）；类型检查命令 `pnpm run type-check`（`vue-tsc --noEmit`）。
- **`tsconfig.json` 的 `include` 只覆盖 `src/**`，不含 `tests/**`**：`vue-tsc` 不对测试文件做类型检查（例如 `tests/practice.spec.ts` 里存在 `status: 'IN_PROGRESS'`、`submitted_count` 等不符合领域类型的字面量，门禁依然全绿）。测试的正确性靠 Vitest 运行时断言把守。
- Lint 层：`@typescript-eslint/no-explicit-any` 配置为 **`off`**（`.eslintrc.cjs`），`@typescript-eslint/no-unused-vars` 与 `ban-types` 同样为 `off`。因此显式 `any` 在本仓库是**允许的**，当前有 28 处，绝大多数是 `catch (error: any)` 与 `uni.*` 回调参数。
- 类型分两类：
  1. **前端领域契约（view 类型）**：定义在 `src/types/index.ts`，页面/组件/store 消费的规范模型（`QuestionItem`、`PracticeSession`、`AttemptResult`、`DiagnosisReport`、`WrongRecordItem` …）。
  2. **后端原始载荷（`Wire*` 前缀）**：定义在各 adapter 文件内（不在 `types/index.ts`），只在 `src/api/adapters/` 内被适配为领域契约。
- **不引入运行时校验库**（无 zod/yup/io-ts/valibot）；跨层形状差异全部在适配函数里显式归一化。
- `@/*` 路径别名同时由 `tsconfig.json`（`"@/*": ["./src/*"]`）与 `vite.config.ts`（`'@': '/src'`）声明，跨层引用统一用 `@/`。

**代码锚点**
- `miniprogram/tsconfig.json::compilerOptions.strict`
- `miniprogram/tsconfig.json::include`（仅 `src/**`）
- `miniprogram/.eslintrc.cjs::rules`（`@typescript-eslint/no-explicit-any: 'off'`）
- `miniprogram/src/types/index.ts`（唯一类型文件）

---

## Type Organization

- **单一类型文件**：所有领域类型集中在 `src/types/index.ts`（441 行），**没有** `types/<domain>.ts` 分文件，也没有 `types/index.ts` 之外的 barrel。
- 领域分组靠注释分段，不靠文件：`// 课程文件夹`、`// 资料状态机`、`// 七大题型`、`// 练习生命周期`、`// 单题判题状态`。
- **`Wire*` 与 view 类型的区分**：`Wire*` 只描述「后端 JSON 的实际字段名与可空性」，view 类型描述「页面消费的规范模型」。二者字段名有意不同，例如：

  | Wire（后端） | view（前端） | 归一化位置 |
  | --- | --- | --- |
  | `WireQuestion.question_type` | `QuestionItem.type` | `adaptQuestion` |
  | `WireQuestion.grading_rubric` | `QuestionItem.grading_points` / `scoring_criteria` | `adaptQuestion` |
  | `WireQuestion.source_snippet.snippet_content` | `QuestionItem.source_quote` | `adaptQuestion` |
  | `WirePracticeDetail.items[].question_snapshot` | `PracticeSession.questions` | `adaptPractice` |
  | `WireWeakKnowledgeItem.knowledge_name` | `WeakKnowledgeItem.knowledge_name`（双写 `knowledge_id`/`knowledge_point_id`） | `adaptDiagnosisReport` |
  | `WireWrongRecordItem.question_snapshot` | `WrongRecordItem.question_snapshot` | `adaptQuestion`（经 `wrongSnapshotOptions`） |

- **`Wire*` 类型清单**（全部定义在 adapter 文件内，不从 `types/index.ts` 导出）：
  - `src/api/adapters/question.ts::WireQuestion`
  - `src/api/adapters/practice.ts::WirePracticeItem` / `WirePracticeDetail`
  - `src/api/adapters/diagnosis.ts::WireWeakKnowledgeItem` / `WireDiagnosisReport`
  - `src/api/adapters/wrong.ts::WireWrongRecordItem`
- **`src/api/adapters/index.ts` 只是 `export *` 聚合**（5 行），`src/api/index.ts` 再 re-export 适配函数与 `Wire*` 类型供测试使用。
- **联合字面量类型替代枚举**：`MaterialStatus`、`QuestionType`、`PracticeStatus`、`GradingStatus` 均为字符串联合，注释里钉死后端事实源（如 `// 七大题型：与 backend/app/models/question.py::QuestionType 保持一致`）。
- **常量与类型同文件**：`SUBJECTIVE_QUESTION_TYPES: QuestionType[]` 与 `QuestionType` 同处 `types/index.ts`，供 `isSubjectiveType` 判定主观题。
- **`ApiResponse<T = any>` 是历史遗留死类型**：`request<T>()` 会解包 `body.data` 直接返回 `T`，全仓库无任何消费点（`rg "ApiResponse" src tests` 只命中定义本身）。新增代码请勿依赖它。
- **`RequestOptions` 定义在网络层而非类型层**：`src/utils/request.ts::RequestOptions`（`url` / `method?` / `data?` / `header?`），没有 `_retryCount` 之类的内部字段。

**代码锚点**
- `miniprogram/src/types/index.ts::QuestionType`（七大题型联合）
- `miniprogram/src/types/index.ts::SUBJECTIVE_QUESTION_TYPES`
- `miniprogram/src/types/index.ts::AttemptResult`（「结果页/报告页统一卷面投影」注释）
- `miniprogram/src/utils/request.ts::RequestOptions`
- `miniprogram/src/api/adapters/practice.ts::WirePracticeDetail`
- `miniprogram/src/api/adapters/diagnosis.ts::WireDiagnosisReport`

---

## 归一化边界（唯一收敛点）

**页面/组件/store 只消费归一化后的 view 类型**，禁止自行断言后端字段。

- `adaptMaterial(item)`：把后端可能返回的大写状态（如 `'READY'`）降为小写状态机取值，未知值回退 `'pending'`；**其余字段原样透传**（`parse_status` / `progress_percentage` 不被丢弃）。
- `adaptQuestion(WireQuestion): QuestionItem`：`question_type → type`、`options[{key,content}]` 保持 keyed 结构、`grading_rubric.points|key_points → grading_points: string[]`、`analysis` 兜底 `explanation`、`source_snippet.snippet_content → source_quote`、`max_score` 由 `grading_rubric.total_score` 兜底。
- `adaptPractice(WirePracticeDetail): PracticeSession`：以 `items[].question_snapshot` 为唯一题面来源，投影出 `questions`（统一卷面）与 `items`；`user_answers` 只由 `is_answered` 的条目派生；缺练习标识时抛 `Error('练习详情缺少练习标识')`。
- `buildAttemptResults(session): AttemptResult[]`：逐题判题状态投影，`resolveGradingStatus` 的优先级为 `未作答 → pending_regrade → graded → grading`。
- `adaptDiagnosisReport(WireDiagnosisReport)`：只消费后端真实字段；缺失的可选聚合字段补安全默认值（`[]` / `0` / `null` / `false`），注释明确禁止再假定 `score` / `accuracy` / `details` / `weaknesses` 等不存在的字段。
- `adaptStatus` **不存在**：练习状态不做前后端映射，`PracticeSession.status` 直接透传后端字符串（`wire.status as PracticeSession['status']`）。

**代码锚点**
- `miniprogram/src/api/adapters/material.ts::adaptMaterial`
- `miniprogram/src/api/adapters/question.ts::adaptQuestion`
- `miniprogram/src/api/adapters/practice.ts::adaptPractice`
- `miniprogram/src/api/adapters/practice.ts::buildAttemptResults`
- `miniprogram/src/api/adapters/diagnosis.ts::adaptDiagnosisReport`

---

## Runtime Guards（纯函数，非校验库）

跨层边界不做 schema 校验，只在**进入 UI 前**用无副作用纯函数兜底：

- **题型/主观题**：`isSubjectiveType(type)` 据 `SUBJECTIVE_QUESTION_TYPES` 判定；未知题型 `questionTypeLabel` 回退为通用文案 `'试题'`，不伪造具体题型。
- **选项展示**：`optionDisplayText(option, index)` 在 `option.key` 缺失时用 `String.fromCharCode(65 + index)` 补位，供核对页与练习页共用。
- **覆盖率**：`computeKnowledgeCoverage(questions, selectedIds)` 按题目快照实际携带的 `knowledge_point_id` 核算，返回 `{ covered, missing, ratio }`，**不把「生成目标」当成「覆盖成功」**。
- **去重**：`dedupeQuestions(list)` 按 `id` 去重并丢弃无 id 项。
- **错题题干**：`wrongSnapshotStem(item)` 只读后端 `question_snapshot.stem`，缺失时返回 `'题干快照缺失'`，禁止读不存在的 `question.stem`。
- **资料状态**：`materialState.ts` 的 `canStartMaterialParse` / `isMaterialParsing` / `materialStatusText` 把 `status` + `parse_status` 合成门禁与文案；`activeStages` 集合覆盖 `queued` / `parsing_doc` / `ocr_processing` / `extracting_knowledge` / `auditing_knowledge` / `embedding_generation`。
- **作答有效性**：`isAnswered` 只以 `undefined` / `null` / `''` / 空数组为「未作答」，是 `practiceStore.answeredCount` 与会话页 `isQuestionAnswered` 的共用口径（两处各有一份实现，未抽公共函数）。
- **Storage 无强类型白名单**：storage 只通过裸字符串 key 访问（`'access_token'`、`practice_draft_<userId>_<practiceId>`、`practice_submit_key_<practiceId>`），**没有** `StorageDataMap` 之类 key→value 映射，也没有字节数校验函数。

**代码锚点**
- `miniprogram/src/api/adapters/question.ts::computeKnowledgeCoverage`
- `miniprogram/src/api/adapters/question.ts::dedupeQuestions`
- `miniprogram/src/api/adapters/wrong.ts::wrongSnapshotStem`
- `miniprogram/src/utils/materialState.ts::isMaterialParsing`
- `miniprogram/src/stores/practice.ts::isAnswered`

---

## Common Patterns

- **泛型请求**：`request<T = any>(options: RequestOptions): Promise<T>`；调用点显式给出 `T`（如 `request<MaterialListResult | MaterialItem[]>({ url, method: 'GET' })`）。注意返回的是**解包后的 `data`**，不是 `ApiResponse<T>`。
- **双形态兼容再归一**：后端列表端点可能返回 `{ items: [] }` 或裸数组，调用侧统一 `'items' in res ? res.items.map(adapt…) : (res as T[]).map(adapt…)`。
- **adapter 组合**：`adaptPractice` 内部调用 `adaptQuestion`；`wrong.ts` 的 `wrongSnapshotOptions` 也复用 `adaptQuestion` 以复用 keyed options 归一。
- **类型收窄用 `Pick` / `Omit`**：`WirePracticeItem = Omit<PracticeItem, 'question_snapshot'> & { question_snapshot: WireQuestion }`；`MaterialState = Pick<MaterialItem, 'status' | 'parse_status'> | null | undefined`。
- **`as` 断言集中在网络边界**：`request.ts` 内 `(import.meta as any).env`、`res.data as any`、`options.method as any` 属于框架边界收窄；**仓库内没有任何 `as unknown as` 双重断言**。
- **`any` 的合法用法**：`catch (error: any)` 后读 `error?.message` 生成 toast 文案是本仓库的既定写法（`no-explicit-any` 已关闭，不构成门禁问题）。

**代码锚点**
- `miniprogram/src/utils/request.ts::request`
- `miniprogram/src/api/index.ts::apiGetMaterialList`（双形态兼容）
- `miniprogram/src/api/adapters/practice.ts::WirePracticeItem`
- `miniprogram/src/utils/materialState.ts::MaterialState`

---

## Forbidden Patterns

- **绕过适配层直接消费 `Wire*`**：`Wire*` 类型只允许出现在 `src/api/adapters/**` 与 `src/api/index.ts` 的 re-export 中；页面/组件/store 必须消费 view 类型。例外：测试为了构造后端样本会显式导入 `type WireWrongRecordItem`（`tests/backendContracts.spec.ts`），这是刻意的契约测试写法。
- **在页面里自行断言后端字段名**：如自行读 `repData.items`、`question.question_type`、`question.stem` 之类未经 adapter 的字段，会在后端改名时静默渲染 `undefined`。
- **自造漂移字段名**：前端消费侧必须与后端逐字一致（`is_archived` / `material_count` / `check_type` / `knowledge_point_id` 等），禁止用 `archived` / `materials_count` 之类别名做主字段。
- **把「生成目标」当成「覆盖成功」**：考点覆盖必须由题目快照实际携带的 `knowledge_point_id` 核算，禁止用「我请求了 N 个考点」推断覆盖率。
- **把未判题计为零分或答错**：判题中 / 待重判项的 `score` 与 `isCorrect` 必须保持 `null`。
- **未类型化的公开函数**：前端公开 API 函数、store action、组件 props/emits 必须显式类型化（`no-explicit-any` 虽为 `off`，但新增公开边界仍要求显式类型）。
- **在 `types/index.ts` 里新增 `Wire*` 类型**：wire 形状属于适配层，应与其 adapter 同文件。

**代码锚点**
- `miniprogram/src/types/index.ts::ApiResponse`（死类型，勿新增消费点）
- `miniprogram/src/api/adapters/practice.ts::resolveGradingStatus`（未判项不落零分）
- `miniprogram/src/api/adapters/wrong.ts::wrongSnapshotStem`
- `miniprogram/tests/backendContracts.spec.ts`（`WireWrongRecordItem` 的测试侧导入）
