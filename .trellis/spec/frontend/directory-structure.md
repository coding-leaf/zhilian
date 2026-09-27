# Directory Structure

> **事实源**：`miniprogram/src/**`、`miniprogram/src/pages.json`、`miniprogram/vite.config.ts`、`miniprogram/tsconfig.json`
> **最后核对**：2026-09-28 @ ca062a1
> **核对方式**：`rg "subPackages|alias|createSSRApp" miniprogram/src miniprogram/vite.config.ts`

> How frontend code is organized in this project. 本文档描述 `miniprogram/` 工程的**真实**布局，不描述理想态。

---

## Overview

本前端是 **uni-app + Vue 3 + Pinia + Wot Design Uni** 的微信小程序（`mp-weixin`），构建工具为 Vite，样式预处理器为 SCSS，单元测试为 Vitest，类型检查为 `vue-tsc`。所有命令在 `miniprogram/` 目录下用 `pnpm` 执行（`pnpm run lint` / `type-check` / `test:unit`）。

- 应用入口：`createApp()`（`createSSRApp` + 注册 Pinia）在 `main.ts` 装配；应用级生命周期（`onLaunch` / `onShow` / `onHide`）在 `App.vue` 内。
- 页面与分包注册、`easycom` 自动引入规则集中在 `pages.json`。
- 路径别名 `@` → `src` 由 `vite.config.ts` 与 `tsconfig.json` 双处声明，保持一致。
- 设计参数（色值、间距、字号、圆角、阴影）的唯一事实源是 `docs/DESIGN.md`，SCSS token 落在 `src/uni.scss`。

**代码锚点**
- `miniprogram/src/main.ts::createApp`
- `miniprogram/src/App.vue::onLaunch`
- `miniprogram/src/pages.json::easycom`
- `miniprogram/vite.config.ts::defineConfig`
- `miniprogram/src/uni.scss::$--wot-color-theme`

---

## Directory Layout

仓库根下的 `miniprogram/` 工程（`node_modules` / `dist` / `unpackage` 除外）：

```
miniprogram/
├── src/
│   ├── api/                     # 网络接口层（每资源一文件 + adapters/ 响应适配）
│   │   ├── adapters/            #   后端原始响应 → 前端领域模型的适配边界
│   │   ├── auth.ts              #   登录/刷新令牌
│   │   ├── diagnosis.ts         #   诊断报告/掌握度/错题本/自评/重判/继续练习
│   │   ├── folder.ts            #   课程文件夹
│   │   ├── index.ts             #   统一导出入口
│   │   ├── material.ts          #   资料列表/详情/状态/删除/重试/解析/移动/知识树
│   │   ├── materialUpload.ts    #   上传与单页重拍（multipart/JSON 双分支）
│   │   ├── practice.ts          #   练习创建/详情/草稿暂存/交卷/暂停/恢复
│   │   ├── question.ts          #   出题/题目检索/详情/更新/删除/审计
│   │   └── user.ts              #   用户画像
│   ├── components/              # 跨页面公共组件（按业务域分子目录）
│   │   ├── common/              #   通用（MaterialUpload）
│   │   ├── course/              #   课程域（CourseCard/PracticeStartBar/...）
│   │   └── home/                #   工作台首页域（CourseListSection/...）
│   ├── config/env.ts            # 运行时 API base 解析（storage/env/test 三优先级）
│   ├── pages/                   # 主包页面
│   │   ├── auth/login.vue       #   登录
│   │   ├── index/index.vue      #   控制台首页
│   │   ├── login/index.vue      #   登录
│   │   └── profile/index.vue    #   个人资料
│   ├── stores/                  # Pinia 全局状态（5 个域 store + 薄再导出 + 注册入口）
│   ├── subpackages/             # 分包（资料 / 练习 / 报告）
│   │   ├── material/            #   components/ composables/ pages/ utils/
│   │   ├── practice/            #   components/ composables/ pages/ types/ utils/
│   │   └── report/              #   components/ pages/ utils/
│   ├── types/                   # 全量 TS 数据契约（含 storage/raw/adapter 边界类型）
│   ├── utils/                   # 纯函数工具（request/storage/error/file/时间格式化等）
│   ├── App.vue                  # 应用生命周期
│   ├── main.ts                  # 根实例装配
│   ├── manifest.json            # uni-app 应用清单
│   ├── pages.json               # 页面/分包/easycom 注册
│   └── uni.scss                 # 设计 token 与 Wot 变量覆盖
├── tests/unit/                  # Vitest 单测（api/components/composables/pages/stores/utils）
├── .eslintrc.cjs                # ESLint（含 no-explicit-any: error）
├── package.json                 # 依赖与 lint/type-check/test:unit 脚本
├── tsconfig.json                # strict 类型配置 + @ 路径映射
└── vite.config.ts               # Vite + uni 插件 + @ 别名
```

**代码锚点**
- `miniprogram/src/api/index.ts`（聚合导出全部 API 模块）
- `miniprogram/src/stores/index.ts::pinia`
- `miniprogram/tests/unit/`（按层分子目录的测试）

---

## Module Organization

新增功能按**层级**归位，禁止跨层直连：

| 目录 | 职责 | 约束 |
|---|---|---|
| `src/pages/`、`src/subpackages/*/pages/` | 页面装配与生命周期 | 只做编排与展示，业务写入 store / api |
| `src/components/`、`src/subpackages/*/components/` | 可复用 UI 组件 | 纯展示优先，副作用经 emit 上交 |
| `src/subpackages/*/composables/` | 有状态复用逻辑（轮询、会话、动作） | `use*` 命名，返回 ref/函数对象 |
| `src/stores/` | 全局状态 | **禁止发网络请求**，仅内存增删改 |
| `src/api/` | 网络调用 | 唯一网络出口；响应经 `adapters/` 归一 |
| `src/types/` | 数据契约 | 后端字段名逐字对齐；raw 与 adapter 类型显式区分 |
| `src/utils/` | 无副作用纯函数 | 可被任意层引用，不反向依赖上层 |

- 每个分包自带 `components/`、`composables/`、`utils/` 三层，避免把分包私有逻辑提升到主包或全局。
- 目录级 `index.vue` 是该分组的页面入口（如 `subpackages/material/index.vue` 为资料管理首页，已注册于 `pages.json` 的 `subPackages.root=subpackages/material`）。
- 网络层入口统一经 `src/api/index.ts` 暴露；页面/组件从 `@/api/*` 或相对路径引入具体模块。

**代码锚点**
- `miniprogram/src/api/index.ts`（统一导出）
- `miniprogram/src/subpackages/material/index.vue`
- `miniprogram/src/subpackages/practice/composables/usePracticeSession.ts::usePracticeSession`

---

## Naming Conventions

- **文件/目录**：全英文标识符；页面统一 `index.vue`；组件 PascalCase（`MaterialCard.vue`）；工具/组合式函数 camelCase（`questionBatch.ts`、`useMaterialPolling.ts`）。
- **样式**：与组件/页面同名的 `.scss` 单独文件，SFC 内以 `@import './xxx.scss';` 引入（scoped）；少量组件使用内联 `<style lang="scss" scoped>`。
- **Store**：正式实现为 `xxxStore.ts`，同时提供 `xxx.ts` 薄再导出（`export * from './xxxStore'`）以兼容历史引入路径；`stores/index.ts` 是 `pinia` 与全部 store 的注册/导出唯一入口。
- **API**：每资源一文件，函数名以动作开头（`fetch*` 查询、`create*` 新建、`update*` 更新、`delete*` 删除）。
- **类型**：领域模型放 `src/types/<domain>.ts`；后端原始载荷用 `Raw*` 前缀，适配函数放 `src/api/adapters/`。
- **主键参数名**：跨页面跳转统一 `material_id` / `folder_id`（snake_case，与后端查询参数一致），接收页做 `materialId`/`id`/`folderId` 兜底解析。

**代码锚点**
- `miniprogram/src/stores/material.ts`（`export * from './materialStore'` 薄再导出）
- `miniprogram/src/stores/materialStore.ts::useMaterialStore`
- `miniprogram/src/api/materialUpload.ts::retakeMaterialPage`
- `miniprogram/src/subpackages/material/pages/questions/index.vue::initPage`（`material_id` / `materialId` / `id` 兜底）

---

## Configuration & Aliases

- `vite.config.ts`：注册 `@dcloudio/vite-plugin-uni`；`resolve.alias['@'] = resolve(__dirname, 'src')`；SCSS `api: 'modern-compiler'`。
- `tsconfig.json`：`strict` / `noImplicitAny` / `strictNullChecks` 全开；`paths['@/*'] = ['src/*']`；`include` 覆盖 `src/**` 与 `tests/**`。
- `.eslintrc.cjs`：`@typescript-eslint/no-explicit-any: 'error'`、`max-lines: ['warn', 500]`、`prettier/prettier: 'error'`；`uni`/`plus`/`wx` 声明为 readonly 全局。
- `package.json` 脚本：`lint`（eslint）、`type-check`（`vue-tsc --noEmit`）、`test:unit`（`vitest run`）、`build:mp-weixin`。

**代码锚点**
- `miniprogram/vite.config.ts::resolve.alias`
- `miniprogram/tsconfig.json::compilerOptions.paths`
- `miniprogram/.eslintrc.cjs::rules`
- `miniprogram/package.json::scripts`

---

## Examples

- **分包三层参考**：`subpackages/material/` —— `pages/list/index.vue` 装配页面，`composables/useMaterialListPolling.ts` 承担轮询，`utils/tree.ts` 提供纯函数，`api/material.ts` 发请求，`stores/materialStore.ts` 存状态。一条资料链路完整演示了「页面 → composable → api → store」的分层。
- **适配边界参考**：`api/adapters/practice.ts` 将后端 `items[].question_snapshot` 扁平化为前端 `PracticeSession.questions`，是跨层字段名契约的单一适配点。
- **设计 token 参考**：`src/uni.scss` 与 `docs/DESIGN.md` 一一对应，业务组件应引用 SCSS/CSS 变量而非裸 Hex。

**代码锚点**
- `miniprogram/src/subpackages/material/pages/list/index.vue::loadData`
- `miniprogram/src/api/adapters/practice.ts::adaptPracticeSession`
- `miniprogram/src/uni.scss::$spacing-lg`
