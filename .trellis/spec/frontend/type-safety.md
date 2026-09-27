# Type Safety

> **事实源**：`miniprogram/src/types/*`、`miniprogram/tsconfig.json`、`miniprogram/.eslintrc.cjs`、`miniprogram/src/api/adapters/*`
> **最后核对**：2026-09-28 @ ca062a1
> **核对方式**：`rg "interface|type |as unknown as" miniprogram/src/types miniprogram/src/api/adapters`

> Type safety patterns in this project. 前端为严格 TypeScript，数据契约集中在 `src/types/`，运行时校验以手写纯函数完成。

---

## Overview

- 语言：TypeScript 5，配置 `strict: true` / `noImplicitAny: true` / `strictNullChecks: true`（`tsconfig.json`）；类型检查命令 `pnpm run type-check`（`vue-tsc --noEmit`）。
- Lint 层：`@typescript-eslint/no-explicit-any` 配置为 `error`（`.eslintrc.cjs`），显式 `any` 被禁止。
- 类型分两类：
  1. **前端领域契约**（`src/types/*.ts`）：页面/组件/store 消费的规范模型。
  2. **后端原始载荷**（`Raw*` 前缀，定义在 `src/types/*.ts`）：仅在 `src/api/adapters/` 内被适配为领域契约。
- **不引入运行时校验库**（无 zod/yup/io-ts/valibot）；校验用手写纯函数（文件、出题配置、作答填充等）。
- `@/*` 路径别名同时由 `tsconfig.json` 与 `vite.config.ts` 声明，跨层引用统一用 `@/`。

**代码锚点**
- `miniprogram/tsconfig.json::compilerOptions.strict`
- `miniprogram/.eslintrc.cjs::rules`（`@typescript-eslint/no-explicit-any: 'error'`）
- `miniprogram/src/types/index.ts`（全量类型 barrel 导出）

---

## Type Organization

- 一个业务域一个文件：`auth` / `common` / `material` / `question` / `practice` / `report` / `folder` / `storage`；`src/types/index.ts` 做 `export *` 聚合。
- **通用响应与分页**在 `common.ts`：`ApiResponse<T>`、`PageResult<T>`（`items/total/limit/offset`）、`RequestOptions`（含 `_retryCount?` 内部字段）。
- **原始 vs 适配**显式区分：如 `RawQuestionItem`/`RawQuestionGenerateResponse`、`RawPracticeSession`/`RawPracticeItem`/`RawPracticeQuestionSnapshot`；适配函数集中在 `src/api/adapters/{question,practice,diagnosis}.ts`。
- **Storage 白名单强类型**：`StorageDataMap` 把 key 映射到具体值类型（`auth_tokens: TokenPairResponse`、`practice_drafts: Record<string, PracticeDraftRecord>`、`user_settings: UserSettings`）。
- **快照类型的权威来源在注释中钉死**：`RawPracticeQuestionSnapshot` 等注释指向 `backend/app/schemas/practice.py` 的对应模型。
- **可空字段显式标 `?`**：课程范围实践放开 `material_id`/`folder_id`/`knowledge_point_id` 为可选，消费处 `?? ''` / `?? null` 兜底。

**代码锚点**
- `miniprogram/src/types/common.ts::ApiResponse`
- `miniprogram/src/types/common.ts::RequestOptions`
- `miniprogram/src/types/storage.ts::StorageDataMap`
- `miniprogram/src/types/question.ts::RawQuestionGenerateResponse`
- `miniprogram/src/types/practice.ts::RawPracticeQuestionSnapshot`

---

## Validation

无运行时校验库，采用**类型 + 手写纯函数**的分工：

- **编译期**：所有边界数据在 API 适配层用 `Raw*` 类型标注，转换后返回领域契约，消费者只见强类型。
- **运行期**（进入 UI 前的必要校验）：
  - 文件：`validateMaterialFile(name, size)` 校验扩展名白名单与逐格式体积上限，返回 `{ valid, error? }`。
  - 出题配置：`validateQuestionConfig({ count, question_types })` 约束题数 `1~20` 且题型非空。
  - 作答填充：`isAnswerFilled(answer)` 统一判定字符串/数组/嵌套 `user_answer` 是否有效填写。
  - Storage：`validateStoragePayload(key, value)` 校验白名单 key、UTF-8 字节上限（20KB）与敏感内容键，失败抛 `AppError(10001)`。
- **适配边界单点**：后端 `options: { key, content }` → 前端 `{ key, text }` 由 `adapters/question.ts` / `adapters/practice.ts` 归一；`question_snapshot` 扁平化到 `PracticeSession.questions` 由 `adaptPracticeItem` 完成。

**代码锚点**
- `miniprogram/src/utils/file.ts::validateMaterialFile`
- `miniprogram/src/subpackages/material/utils/tree.ts::validateQuestionConfig`
- `miniprogram/src/subpackages/practice/utils/draft.ts::isAnswerFilled`
- `miniprogram/src/utils/storage.ts::validateStoragePayload`
- `miniprogram/src/api/adapters/practice.ts::adaptPracticeItem`

---

## Common Patterns

- **泛型请求**：`request<T>(options): Promise<ApiResponse<T>>`；调用点显式给出 `T`（如 `request<PageResult<MaterialItem>>({...})`）。
- **泛型 Storage 访问**：`getItem<K extends StorageKey>(key: K): StorageDataMap[K] | null`，key - 值类型联动。
- **联合字面量类型**：`MaterialStatus`、`QuestionType`、`PracticeStatus`、`WrongErrorType`、`MasteryTier` 等用字符串联合，替代枚举。
- **类型别名兼容层**：领域 model 与 `Raw*`、`KnowledgeTreeNodeItem`、`QuestionEditLogItem` 等通过 `type X = Y` 提供兼容别名，避免破坏历史引入。
- **纯函数优先**：格式化/计算（`formatPurgeRemaining`、`getMasteryTierInfo`、`buildCheckStatusMap`）为无副作用纯函数，便于类型收窄与单测。
- **边界断言**：在无法被类型系统精确描述的框架边界（`uni.request` 的返回形态、`import.meta.env`）用 `as unknown as` 局部收窄，并紧邻注释说明原因。

**代码锚点**
- `miniprogram/src/utils/request.ts::request`
- `miniprogram/src/utils/storage.ts::getItem`
- `miniprogram/src/types/question.ts::QuestionType`
- `miniprogram/src/types/report.ts::WrongErrorType`
- `miniprogram/src/utils/request.ts`（`res as unknown as Promise<...>` 边界断言）

---

## Forbidden Patterns

- **显式 `any`**：`no-explicit-any: error` 禁止。唯一例外是声明文件 `src/env.d.ts` 的 `declare const wx: any`，属三方全局声明，不在业务代码内。业务代码用 `unknown` + 收窄、泛型或明确的领域接口。
- **推导「死类型」强转**：禁止 `as unknown as Record<string, never>` 之类把契约强转成空对象类型的写法；`practice_drafts` 的唯一契约是 `Record<string, PracticeDraftRecord>`。
- **用 `String.length` 代替 UTF-8 字节数**：字节校验必须走 `TextEncoder`（缺失时手写回退），见 `miniprogram/src/utils/storage.ts::calculateUtf8Bytes`。
- **自造漂移字段名**：前端类型字段名必须与后端逐字一致（如 `is_archived` / `material_count` / `check_type` / `is_passed`），禁止自造 `archived`/`materials_count`/`passed` 等别名作为主字段（废弃别名仅可保留为可选）。
- **未类型化的公开函数**：`app/` 之外的前端公开 API 函数、store action、组件 props/emits 必须显式类型化。
- **绕过适配层直接消费 `Raw*`**：`Raw*` 类型只允许出现在 `src/api/adapters/` 与 API 模块内部。

**代码锚点**
- `miniprogram/src/env.d.ts`（`declare const wx: any`，唯一声明层例外）
- `miniprogram/src/types/storage.ts::StorageDataMap`
- `miniprogram/src/utils/storage.ts::calculateUtf8Bytes`
- `miniprogram/src/types/folder.ts::FolderItem`（与后端逐字一致的字段名）
- `miniprogram/src/types/question.ts::QuestionQualityCheck`
