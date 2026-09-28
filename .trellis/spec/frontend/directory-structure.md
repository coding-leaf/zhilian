# Directory Structure

> **事实源**：`miniprogram/src/**`、`miniprogram/src/pages.json`、`miniprogram/vite.config.ts`、`miniprogram/tsconfig.json`、`miniprogram/vitest.config.ts`
> **最后核对**：2026-09-29
> **核对方式**：`find miniprogram/src -type f` 全量枚举 + 逐项对照 `pages.json` 注册表

> How frontend code is organized in this project. 本文档描述 `miniprogram/` 工程的**真实**布局，不描述理想态。

---

## Overview

本前端是 **uni-app + Vue 3 + Pinia** 的微信小程序（`mp-weixin`），构建工具为 Vite，样式预处理器为 SCSS，单元测试为 Vitest，类型检查为 `vue-tsc`。所有命令在 `miniprogram/` 目录下用 `pnpm` 执行（`pnpm run lint` / `type-check` / `test:unit`）。

- 应用入口：`main.ts` 的 `createApp()` 使用 `createSSRApp(App)` + `Pinia.createPinia()`；应用级生命周期（`onLaunch` / `onShow` / `onHide`）在 `App.vue` 内（当前只打日志）。
- 页面与分包注册、`easycom` 规则集中在 `pages.json`。`easycom` 声明的 `^wd-(.*)` 规则当前**没有使用点**。
- 路径别名 `@` 由 `vite.config.ts`（`'@': '/src'`）与 `tsconfig.json`（`"@/*": ["./src/*"]`）双处声明。
- 设计参数的事实源是 `docs/DESIGN.md`；代码侧只有 `App.vue` 在 `page` 上定义的一组 `--color-*` CSS 变量（无 `src/uni.scss`、无 `src/styles/`）。

**代码锚点**
- `miniprogram/src/main.ts::createApp`
- `miniprogram/src/App.vue::page`（`--color-*` 变量）
- `miniprogram/src/pages.json::easycom`
- `miniprogram/vite.config.ts::resolve.alias`

---

## Directory Layout

仓库根下的 `miniprogram/` 工程（`node_modules` / `dist` 除外）：

```
miniprogram/
├── src/
│   ├── api/
│   │   ├── adapters/            # 后端 wire → 前端 view 的归一化边界
│   │   │   ├── diagnosis.ts     #   adaptDiagnosisReport / WireDiagnosisReport
│   │   │   ├── index.ts         #   export * 聚合（5 行）
│   │   │   ├── material.ts      #   adaptMaterial（状态大小写归一）
│   │   │   ├── practice.ts      #   adaptPractice / buildAttemptResults / summarizeProgress
│   │   │   ├── question.ts      #   adaptQuestion / 出题规划 / 覆盖率 / 题型标签
│   │   │   └── wrong.ts         #   错题分组 / 再生范围 / 快照读取
│   │   └── index.ts             # 唯一 API 文件：全部 apiXxx 函数 + 适配函数 re-export
│   ├── components/
│   │   └── AiCoachDrawer.vue    # 唯一跨页面共享组件（AI 助教抽屉）
│   ├── pages/                   # 主包页面（3 Tab + 登录）
│   │   ├── auth/login.vue       #   登录
│   │   ├── index/index.vue      #   Tab 1: 学习工作台
│   │   ├── profile/index.vue    #   Tab 3: 个人中心
│   │   └── review/
│   │       ├── components/
│   │       │   ├── PracticeEntryCard.vue
│   │       │   └── WrongRecordCard.vue
│   │       ├── index.vue        #   Tab 2: 学情与错题攻克
│   │       ├── review.scss      #   该功能区共享样式表
│   │       └── reviewView.ts    #   展示纯函数（状态文案 / 可续练 / 再生范围）
│   ├── stores/                  # Pinia 域 store（5 个，无 index.ts 聚合）
│   │   ├── auth.ts              #   token / user / loginWithWechat / fetchProfile
│   │   ├── diagnosis.ts         #   currentReport / isPending / loadReport
│   │   ├── folder.ts            #   folders / currentFolderId / 课程 CRUD
│   │   ├── material.ts          #   materialList / 知识树 / 上传解析出题
│   │   └── practice.ts          #   会话 / 作答 / 草稿队列 / 交卷 / 再生题
│   ├── subpackages/
│   │   ├── material/
│   │   │   ├── components/QuestionPreviewCard.vue
│   │   │   ├── composables/useQuestionCompose.ts   # 全仓库唯一的组合式函数
│   │   │   ├── pages/course/index.vue              # 资料详情 + 知识树 + 考点切片
│   │   │   ├── pages/questions/index.vue           # 组卷配置 + 题目核对 + 开始作答
│   │   │   ├── pages/upload/index.vue              # 占位页（32 行，无逻辑）
│   │   │   └── questions.scss
│   │   ├── practice/
│   │   │   ├── pages/session/index.vue             # 作答页
│   │   │   └── session.scss
│   │   └── report/
│   │       ├── components/
│   │       │   ├── AttemptResultCard.vue
│   │       │   ├── GradingActionModal.vue
│   │       │   └── ReportSummaryCard.vue
│   │       ├── pages/detail/index.vue              # 结果页 + 诊断报告
│   │       ├── report.scss
│   │       └── utils/reportView.ts
│   ├── types/
│   │   └── index.ts             # 唯一类型文件（441 行，无分域文件）
│   ├── utils/
│   │   ├── draftQueue.ts        # 逐题草稿串行写入队列
│   │   ├── materialState.ts     # 资料解析状态门禁与文案
│   │   └── request.ts           # uni.request / uni.uploadFile 封装 + API_BASE_URL
│   ├── App.vue                  # 应用生命周期 + 全局 CSS 变量与 .paper-card
│   ├── env.d.ts                 # *.vue 模块声明 + declare const wx: any
│   ├── main.ts                  # 根实例装配
│   ├── manifest.json            # uni-app 应用清单
│   └── pages.json               # 页面/分包/easycom 注册
├── tests/                       # Vitest 单测（平铺，无 unit/ 子目录）
│   ├── fixtures/backendResponses.ts   # 后端响应样本（钉死跨层字段名）
│   ├── setup.ts                       # 内存版 uni mock（storage/toast/navigate）
│   ├── apiContracts.spec.ts
│   ├── backendContracts.spec.ts
│   ├── diagnosisAndCompose.spec.ts
│   ├── draftQueue.spec.ts
│   ├── materialState.spec.ts
│   ├── practice.spec.ts
│   └── practiceStore.spec.ts
├── .eslintignore                # dist / node_modules / *.local
├── .eslintrc.cjs                # ESLint（no-explicit-any 为 off）
├── package.json                 # lint / type-check / test:unit / dev|build:mp-weixin
├── pnpm-lock.yaml
├── pnpm-workspace.yaml
├── tsconfig.json                # strict + @ 映射（include 仅 src/**）
├── vite.config.ts               # Vite + uni 插件 + @ 别名
└── vitest.config.ts             # happy-dom + globals + tests/setup.ts
```

**代码锚点**
- `miniprogram/src/api/index.ts`（唯一 API 文件，424 行）
- `miniprogram/src/api/adapters/index.ts`（adapter 聚合导出）
- `miniprogram/tests/setup.ts`（`uni` 全局 mock）

---

## Module Organization

新增功能按**层级**归位：

| 目录 | 职责 | 约束 |
|---|---|---|
| `src/pages/`、`src/subpackages/*/pages/` | 页面装配与生命周期 | 编排 + 展示；取数经 store 或直接调 `@/api`，但必须处理失败 |
| `src/components/`、`src/pages/**/components/`、`src/subpackages/*/components/` | 可复用 UI 组件 | 数据经 props 下传、交互经 emit 上交 |
| `src/subpackages/*/composables/` | 有状态复用逻辑 | `use*` 命名；当前仅 `useQuestionCompose` |
| `src/stores/` | 全局状态 | **每个 store 直接调用 `@/api`**（见下方说明） |
| `src/api/` | 网络调用 | 唯一网络出口；响应经 `adapters/` 归一 |
| `src/types/` | 数据契约 | 单文件集中；wire 类型反而不在这里（在 adapters 内） |
| `src/utils/` | 无副作用纯函数 | 可被任意层引用，不反向依赖上层 |

- **分包的目录不是固定三层**：`subpackages/material/` 有 `components/` + `composables/` + 共享 scss；`subpackages/practice/` 只有 `pages/` + 共享 scss；`subpackages/report/` 有 `components/` + `utils/` + 共享 scss。新增代码按实际需要建目录，不要为了凑结构造空目录。
- **store 是编排层而非纯状态容器**：5 个 store 都直接 import `@/api` 并发起请求（`materialStore.upload` → `apiUploadMaterial`、`practiceStore.submit` → `apiSubmitPractice`、`folderStore.loadFolders` → `apiListFolders`、`authStore.fetchProfile` → `apiGetUserProfile`、`diagnosisStore.loadReport` → `apiGetPracticeSession` + `apiTriggerDiagnosis`）。页面既可经 store 取数，也可直接调 `@/api`（如 `pages/review/index.vue` 调 `apiListWrongRecords`）。
- **没有 `src/api/<resource>.ts` 分文件**：所有 API 函数集中在 `src/api/index.ts`；分包内也没有 `api/` 目录。
- 主包与分包的页面入口统一命名 `index.vue`。

**代码锚点**
- `miniprogram/src/stores/material.ts::upload`
- `miniprogram/src/stores/diagnosis.ts::loadReport`
- `miniprogram/src/pages/review/index.vue::loadWrongs`（页面直连 API 的先例）
- `miniprogram/src/subpackages/material/composables/useQuestionCompose.ts::useQuestionCompose`

---

## Naming Conventions

- **文件/目录**：全英文标识符；页面统一 `index.vue`；组件 PascalCase（`AiCoachDrawer.vue`、`QuestionPreviewCard.vue`）；工具/纯函数模块 camelCase（`draftQueue.ts`、`materialState.ts`、`reportView.ts`、`reviewView.ts`）；组合式函数 `useXxx.ts`。
- **样式**：两种写法并存——`<style lang="scss" scoped>` + `@import '<区域>.scss'`（10 个文件，样式表按功能区共享），或 `<style scoped>` 内联普通 CSS（6 个文件）。名字里不带 `theme` / `tokens` 的全局样式文件不存在。
- **Store**：文件名即域名的 `camelCase`（`auth.ts` / `material.ts` / `folder.ts` / `practice.ts` / `diagnosis.ts`），导出 `useXxxStore`（`useAuthStore` / `useMaterialStore` / `useFolderStore` / `usePracticeStore` / `useDiagnosisStore`）。**没有 `xxxStore.ts` + `xxx.ts` 薄再导出的双层结构，也没有 `stores/index.ts`**。
- **API**：函数名前缀统一为 `api` + 动词 + 资源（`apiGetMaterialList`、`apiListFolders`、`apiCreatePractice`、`apiTriggerMaterialParse`、`apiSavePracticeDraft`），**不用** `fetch*` / `create*` 裸前缀。adapter 函数则是裸动词（`adaptQuestion`、`buildAttemptResults`、`summarizeProgress`、`computeKnowledgeCoverage`）。
- **类型**：领域模型与 wire 模型不在同一处——view 类型集中在 `src/types/index.ts`；`Wire*` 类型与其 adapter 同文件（`WireQuestion` 在 `adapters/question.ts`，`WirePracticeDetail` 在 `adapters/practice.ts`，`WireDiagnosisReport` 在 `adapters/diagnosis.ts`，`WireWrongRecordItem` 在 `adapters/wrong.ts`）。
- **跨页参数名按页面各自约定**：资料详情页用 `id`，出题页用 `material_id` / `folder_id`，练习与报告页用 `practice_id`。发送方与接收方必须逐字对齐（完整契约见 `quality-guidelines.md` 的「跨页导航参数契约」）。

**代码锚点**
- `miniprogram/src/stores/practice.ts::usePracticeStore`
- `miniprogram/src/api/index.ts::apiGetMaterialList` / `::apiTriggerMaterialParse`
- `miniprogram/src/api/adapters/question.ts::WireQuestion`
- `miniprogram/src/subpackages/material/pages/questions/index.vue::onLoad`（`folder_id` / `material_id`）

---

## Configuration & Aliases

- `vite.config.ts`：注册 `@dcloudio/vite-plugin-uni`（对 ESM/CJS 互操作做了 `(uniPlugin as any).default || uniPlugin` 兼容）；`resolve.alias['@'] = '/src'`；`server.port = 5173`、`host = '0.0.0.0'`。**没有** SCSS `api: 'modern-compiler'` 配置。
- `tsconfig.json`：`strict: true`（`noImplicitAny` / `strictNullChecks` 由 strict 隐式开启，未单独列出）；`paths['@/*'] = ['./src/*']`；`include` 仅 `src/**/*.{ts,d.ts,tsx,vue}` —— **不含 `tests/**`**。
- `.eslintrc.cjs`：`extends` 为 `eslint:recommended` + `plugin:vue/vue3-recommended` + `plugin:@typescript-eslint/recommended`；`@typescript-eslint/no-explicit-any` / `no-unused-vars` / `ban-types` 均为 **`off`**；`uni` / `wx` 声明为 `readonly` 全局；**未配置 `max-lines`，也未启用 `prettier/prettier`**。
- `vitest.config.ts`：`plugins: [vue()]`、`resolve.alias['@']`、`environment: 'happy-dom'`、`globals: true`、`setupFiles: ['./tests/setup.ts']`；未配 `coverage`，未配 `include`（用默认 glob 命中 `tests/*.spec.ts`）。
- `package.json` 脚本：`lint`（`eslint . --ext .vue,.js,.ts`）、`type-check`（`vue-tsc --noEmit`）、`test:unit`（`vitest run`）、`dev:mp-weixin`、`build:mp-weixin`。

**代码锚点**
- `miniprogram/vite.config.ts::resolve.alias`
- `miniprogram/tsconfig.json::include`
- `miniprogram/.eslintrc.cjs::rules`
- `miniprogram/vitest.config.ts::test`
- `miniprogram/package.json::scripts`

---

## Examples

- **字段归一化参考**：`api/adapters/practice.ts` 将后端 `items[].question_snapshot` 扁平化为前端 `PracticeSession.questions`，并同时产出结果页用的 `AttemptResult[]`；这是跨层字段名契约的单一适配点。
- **纯函数下移参考**：`pages/review/reviewView.ts` 把「练习状态文案 / 是否可续练 / 单条错题的再生范围」抽成纯函数，页面与卡片组件共用且可单测。
- **共享样式参考**：`subpackages/report/report.scss` 被报告页与 3 个报告组件共同 `@import`（各自 `scoped` 复制），是「按功能区共享样式表」的既有做法。
- **跨层测试参考**：`tests/fixtures/backendResponses.ts` 手写后端响应样本并注明事实源，配合 `tests/backendContracts.spec.ts` 把前后端字段漂移挡在适配层。

**代码锚点**
- `miniprogram/src/api/adapters/practice.ts::adaptPractice`
- `miniprogram/src/pages/review/reviewView.ts::practiceStatusText`
- `miniprogram/src/subpackages/report/report.scss`
- `miniprogram/tests/fixtures/backendResponses.ts`
