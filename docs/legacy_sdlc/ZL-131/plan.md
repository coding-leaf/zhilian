# Plan: 小程序基础脚手架、Pinia 4-Store与Storage白名单封装 - 实施计划

- **关联 Spec**: ZL-131
- **主导设计人**: TechLead (Planner & Research)
- **任务分级**: Tier 2 (单模块特性演进 / 前端应用入口与状态底座)
- **当前状态**: Approved
- **实施执行模式**: 多 Builder 细粒度原子派发 (严格落实单一职责，拆解为 5 个独立 Milestone，避免单个 Builder 任务过载)

---

## 1. 任务分发与实施拆解原则

根据系统设计与用户要求（“合理的分发任务给 builder, 避免一个 builder 进行多过任务”），本实施计划将前端工程底座严格拆解为 **5 个高度解耦、正交递进的原子 Milestone**。每个 Milestone 具备明确边界、严格的契约输入输出与配对的验证命令：

```
[Milestone 1: 脚手架与工具链] ──> [Milestone 2: 契约/Storage/Request] ──> [Milestone 3: API 网络接口封装] ──> [Milestone 4: Pinia 4-Store] ──> [Milestone 5: 入口装配与全局门禁]
     Builder 1 (Scaffold/Deps)           Builder 2 (Core/Storage/Req)              Builder 3 (API Modules)               Builder 4 (Stores)                 Builder 5 (Assembly/Gates)
```

---

## 2. 变更总文件清单 (Files that change)

### 根目录与配置清单 (Scaffold & Tooling)
1. `miniprogram/package.json`: 依赖定义（Vue 3.4+, Pinia 2.1+, Wot Design Uni 1.3+, Vitest, TypeScript, ESLint, Prettier）。
2. `miniprogram/vite.config.ts`: Vite 5 与 @dcloudio/vite-plugin-uni 插件配置、路径别名（`@/*`）及 Vitest 环境配置。
3. `miniprogram/tsconfig.json`: TypeScript 严格模式配置、uni-app 类型拓展。
4. `miniprogram/.eslintrc.cjs` & `miniprogram/.prettierrc`: ESLint 规则集（Vue3+TS）与格式化规则（行宽 100、单引号、尾逗号）。
5. `miniprogram/index.html`: Web 预览与构建入口模版。

### 核心样式与 Tokens
6. `miniprogram/src/uni.scss`: 全局样式定义与 Wot Design Uni SCSS 变量覆盖（对齐 `docs/DESIGN.md` 色盘与参数）。

### 类型契约定义清单 (`miniprogram/src/types/`)
7. `miniprogram/src/types/api.d.ts`: 统一 `ApiResponse<T>`, `RequestOptions`, `PaginationParams`, `PaginationResult<T>` 接口。
8. `miniprogram/src/types/auth.d.ts`: `AuthTokens`, `UserProfile`, `WeChatLoginRequest` 接口。
9. `miniprogram/src/types/material.d.ts`: 资料列表、大纲与处理状态契约。
10. `miniprogram/src/types/practice.d.ts`: 练习大纲、题目选项、作答状态契约。
11. `miniprogram/src/types/report.d.ts`: 诊断报告摘要与艾宾浩斯掌握度契约。
12. `miniprogram/src/types/storage.d.ts`: `STORAGE_WHITELIST` 常量数组、`StorageKey` 联合类型与 `StorageDataMap` 字典。

### 核心基础工具清单 (`miniprogram/src/utils/`)
13. `miniprogram/src/utils/error.ts`: 5 位业务错误码映射函数 `mapErrorCodeToMessage` 与零度文案字典。
14. `miniprogram/src/utils/storage.ts`: 本地存储白名单保护器（白名单拦截 + 敏感全文防泄露特征扫描）。
15. `miniprogram/src/utils/request.ts`: 统一网络客户端（401 双令牌静默刷新锁、挂起排队重放队列、错误码拦截转换）。
16. `miniprogram/src/utils/logger.ts`: 绝密脱敏前端日志记录器。

### API 模块清单 (`miniprogram/src/api/`)
17. `miniprogram/src/api/auth.ts`: 微信登录、Token 刷新与登出吊销。
18. `miniprogram/src/api/user.ts`: 用户个人画像获取与注销账号。
19. `miniprogram/src/api/material.ts`: 资料上传、任务轮询、资料列表与大纲。
20. `miniprogram/src/api/practice.ts`: 练习创建、答题草稿提交与交卷。
21. `miniprogram/src/api/diagnosis.ts`: 学情诊断报告与掌握度全景查询。

### Pinia 4-Store 状态层清单 (`miniprogram/src/stores/`)
22. `miniprogram/src/stores/index.ts`: Pinia 实例导出与统一注册。
23. `miniprogram/src/stores/user.ts`: `useUserStore`（用户凭据、登录态、Profile）。
24. `miniprogram/src/stores/material.ts`: `useMaterialStore`（跨页面活跃资料、版本、分页列表）。
25. `miniprogram/src/stores/practice.ts`: `usePracticeStore`（练习题列、作答进度、草稿同步与清理）。
26. `miniprogram/src/stores/report.ts`: `useReportStore`（诊断报告概要、掌握度全景）。

### 应用入口与页面路由配置
27. `miniprogram/src/main.ts`: 应用启动入口（Vue 实例创建、Pinia 装配、Wot Design Uni 挂载）。
28. `miniprogram/src/App.vue`: 小程序根组件生命周期监听（App Launch/Show/Hide）。
29. `miniprogram/src/pages.json`: 路由表、TabBar、主包与分包规划（`subpackages/material`, `subpackages/report`）。
30. `miniprogram/src/pages/index/index.vue`: 首页工作台占位页（<= 300 行）。
31. `miniprogram/src/pages/login/index.vue`: 登录授权页（<= 300 行）。
32. `miniprogram/src/pages/profile/index.vue`: 个人中心设置页（<= 300 行）。

### 自动化测试套件 (`miniprogram/tests/`)
33. `miniprogram/tests/setup.ts`: 微信小程序环境 Mock 全局桩（`uni.request`, `uni.getStorageSync`, `uni.showToast` 等）。
34. `miniprogram/tests/unit/utils/error.spec.ts`: 错误码映射纯函数单测（100% 覆盖）。
35. `miniprogram/tests/unit/utils/storage.spec.ts`: 白名单读写隔离与全文注入拦截单测。
36. `miniprogram/tests/unit/utils/request.spec.ts`: 401 拦截、双令牌排队静默刷新与错误重试单测。
37. `miniprogram/tests/unit/api/api_modules.spec.ts`: API 模块参数映射与请求发起单测。
38. `miniprogram/tests/unit/stores/user.spec.ts`: `useUserStore` 凭据持久化与流转单测。
39. `miniprogram/tests/unit/stores/material.spec.ts`: `useMaterialStore` 状态隔离与分页单测。
40. `miniprogram/tests/unit/stores/practice.spec.ts`: `usePracticeStore` 答题线性队列与草稿同步单测。
41. `miniprogram/tests/unit/stores/report.spec.ts`: `useReportStore` 报告概要与掌握度看板单测。

---

## 3. 五大原子 Milestone 详细实施方案 (The 4 Pillars Breakdown)

### Milestone 1: 脚手架工程与基础依赖初始化 (Scaffold, Tooling & Design Tokens)
- **目标与职责**: 在 `miniprogram/` 目录完成 Vue3 + Vite5 + TypeScript + Wot Design Uni 脚手架配置，引入核心依赖，配置严格的 ESLint、Prettier、Vitest 工具链与全系统 Design Tokens（对齐 `docs/DESIGN.md` 色盘与零表情包规范）。
- **建议委派角色**: `builder-1`

#### 1. Files that change
- `miniprogram/package.json` (New)
- `miniprogram/vite.config.ts` (New)
- `miniprogram/tsconfig.json` (New)
- `miniprogram/.eslintrc.cjs` (New)
- `miniprogram/.prettierrc` (New)
- `miniprogram/index.html` (New)
- `miniprogram/src/uni.scss` (New)

#### 2. Order of work
1. **依赖清单确立与安装准备 (`package.json`)**:
   - 生产依赖引入：`vue@^3.4.21`, `@dcloudio/uni-app@^3.0.0-4020920240930001`, `pinia@^2.1.7`, `wot-design-uni@^1.3.10`；
   - 开发与测试依赖：`vite@^5.2.8`, `typescript@^5.4.5`, `vitest@^1.5.0`, `@vue/test-utils@^2.4.5`, `sass@^1.75.0`, `eslint`, `prettier`；
   - 脚本配置：`"dev:mp-weixin"`, `"build:mp-weixin"`, `"lint"`, `"type-check"`, `"test:unit"`。
2. **构建与编译配置 (`vite.config.ts`, `tsconfig.json`)**:
   - 配置 `@dcloudio/vite-plugin-uni` 插件；
   - 配置别名 `@` 映射至 `./src`；
   - 配置 Vitest 运行环境为 `happy-dom` 或 `node`，引入 `tests/setup.ts` 测试启动桩；
   - 启用 TypeScript 严格模式（`strict: true`, `noImplicitAny: true`）。
3. **代码风格门禁与格式化规范 (`.eslintrc.cjs`, `.prettierrc`)**:
   - 行宽上限设为 100；
   - 开启单引号、尾随逗号；严格禁止 `any`（除特定通用底层反序列化外）。
4. **设计令牌与样式变量覆盖 (`src/uni.scss`)**:
   - 严格覆盖 Wot Design Uni SCSS 变量：
     - 主交互色 `$--wot-color-theme: #2563EB;`
     - 主色悬浮/按压 `$--wot-color-theme-hover: #1D4ED8;`
     - 背景底色 `$--wot-color-gray-1: #F8FAFC;` (冷灰护眼)
     - 辅助与文字色 `$--wot-color-gray-7: #64748B;`、`$--wot-color-gray-9: #0F172A;`
     - 掌握度四级离散状态色（精通 `#7C3AED`、良好 `#059669`、需巩固 `#B45309`、未学 `#64748B`）；
   - 定义 4 档圆角（`--radius-sm: 8rpx`, `--radius-md: 16rpx`, `--radius-lg: 24rpx`, `--radius-pill: 9999rpx`）与间距变量。

#### 3. Risks & Defenses
- **架构契约防御**: 单文件严格控制在 300 行以内；全样式文件中零裸 Hex 色值，均使用标准 Token 变量；
- **环境隔离防御**: Vitest 隔离网络，配置统一桩入口，确保不产生外部网络连接。

#### 4. Proof
- 依赖校验与类型检查：
  ```bash
  cd miniprogram && pnpm install && pnpm run type-check
  ```
- 代码风格检查：
  ```bash
  cd miniprogram && pnpm run lint
  ```

---

### Milestone 2: 类型定义与基础工具层 (Types, Storage Whitelist & Request Core)
- **目标与职责**: 实现完整的 TypeScript 契约声明，完成 `src/utils/storage.ts`（仅限 3 类白名单并拦截全文注入）与 `src/utils/request.ts`（401 双令牌静默刷新锁、并发排队重放队列、业务错误码映射），并提供 100% 覆盖的单元测试。
- **建议委派角色**: `builder-2`

#### 1. Files that change
- `miniprogram/src/types/api.d.ts` (New)
- `miniprogram/src/types/auth.d.ts` (New)
- `miniprogram/src/types/storage.d.ts` (New)
- `miniprogram/src/types/material.d.ts` (New)
- `miniprogram/src/types/practice.d.ts` (New)
- `miniprogram/src/types/report.d.ts` (New)
- `miniprogram/src/utils/error.ts` (New)
- `miniprogram/src/utils/logger.ts` (New)
- `miniprogram/src/utils/storage.ts` (New)
- `miniprogram/src/utils/request.ts` (New)
- `miniprogram/tests/setup.ts` (New)
- `miniprogram/tests/unit/utils/error.spec.ts` (New)
- `miniprogram/tests/unit/utils/storage.spec.ts` (New)
- `miniprogram/tests/unit/utils/request.spec.ts` (New)

#### 2. Order of work
1. **测试先行 (Fail-repro First)**:
   - 编写 `tests/setup.ts`，为 Node 运行环境挂载 `uni.request`, `uni.getStorageSync`, `uni.setStorageSync`, `uni.removeStorageSync`, `uni.showToast` 等全局桩；
   - 编写 `error.spec.ts`，预设 10xxx, 20xxx, 30xxx, 40xxx, 50xxx 等错误码映射断言，确认红灯；
   - 编写 `storage.spec.ts`，断言白名单读写正常，非白名单键（如 `illegal_key`）写入抛出 `StorageViolationError`，包含资料全文或超长字符串时抛出 `StorageSecurityError`，确认红灯；
   - 编写 `request.spec.ts`，断言正常请求返回数据、401 时触发静默刷新重试、多个并发 401 请求被排队并在刷新后统一重放成功、刷新失败时清空 Token 并抛出登录过期错误，确认红灯。
2. **编写 TypeScript 契约 (`src/types/*`)**:
   - `api.d.ts`: `ApiResponse<T>`, `RequestOptions`；
   - `auth.d.ts`: `AuthTokens`, `UserProfile`；
   - `storage.d.ts`: `STORAGE_WHITELIST = ['auth_tokens', 'practice_drafts', 'user_settings']`；
   - `material.d.ts`, `practice.d.ts`, `report.d.ts`: 对齐后端各领域 DTO 结构。
3. **实现错误码映射与零度文案字典 (`src/utils/error.ts`)**:
   - 纯函数 `mapErrorCodeToMessage(code: number, fallback?: string): string`；
   - 字典严格对齐 `docs/DESIGN.md` 与 `spec.md` 2.1 节，无任何表情包。
4. **实现 Storage 白名单安全保护器 (`src/utils/storage.ts`)**:
   - 纯函数 `validateStoragePayload(key: string, value: any): void`：
     - 白名单校验：非 `auth_tokens`, `practice_drafts`, `user_settings` 抛出 `StorageViolationError`；
     - 全文特征拦截：扫描对象键是否包含 `material_content`, `raw_text`, `full_content`, `question_text`, `reference_answer`，或单字段长度超过 1000 字符（排除 token 字段），触发抛出 `StorageSecurityError`；
   - 封装 `storage.getItem`, `storage.setItem`, `storage.removeItem`, `storage.clearWhitelistStorage`。
5. **实现统一网络客户端 (`src/utils/request.ts`)**:
   - 基于原生 `uni.request` 返回 Promise；
   - 自动在 Headers 中携带 `Authorization: Bearer <access_token>`；
   - 维护 `isRefreshing` 标志与 `pendingQueue: Array<(token: string) => void>`；
   - 遇到 401 / 业务码 20001 时：
     - 若未处于刷新中：置 `isRefreshing = true`，读取 `auth_tokens.refresh_token`，调用刷新端点 `/api/v1/auth/refresh`；刷新成功更新 Storage 并唤醒重放队列；若失败清空凭据并驳回所有挂起请求；
     - 若已处于刷新中：将请求封入挂起队列等待刷新完成后携带新 Token 重放；
   - 对 10xxx~50xxx 业务错误码拦截并通过 `mapErrorCodeToMessage` 输出友好文案并以 `AppError` 抛出。
6. **实现脱敏日志器 (`src/utils/logger.ts`)**:
   - 严格遵循绝密脱敏红线（严禁记录题目全文、资料全文、作答原文与明文 Token），仅记录 `request_id`, `url`, `duration_ms`, `error_code`。
7. **单测转绿与覆盖率核验**:
   - 执行单元测试，确保 `error.spec.ts`, `storage.spec.ts`, `request.spec.ts` 100% 绿灯。

#### 3. Risks & Defenses
- **并发雪崩防御**: 401 刷新锁确保同一时间仅有 1 个刷新请求到达后端，挂起队列确保并发请求无缝等待；
- **存储泄漏红线**: 白名单与敏感特征双重硬拦截，从物理底层杜绝把题目/资料大文本写入 Storage。

#### 4. Proof
- 核心工具单元测试全绿断言：
  ```bash
  cd miniprogram && pnpm run test:unit tests/unit/utils
  ```
- 静态质量与类型校验：
  ```bash
  cd miniprogram && pnpm run type-check && pnpm run lint
  ```

---

### Milestone 3: API 网络接口封装层 (API Modules & Domain Protocols)
- **目标与职责**: 封装 5 大业务领域的 API 模块（`auth.ts`, `user.ts`, `material.ts`, `practice.ts`, `diagnosis.ts`），100% 对齐后端 API 契约，单文件 $\le 300$ 行，并配备参数映射单元测试。
- **建议委派角色**: `builder-3`

#### 1. Files that change
- `miniprogram/src/api/auth.ts` (New)
- `miniprogram/src/api/user.ts` (New)
- `miniprogram/src/api/material.ts` (New)
- `miniprogram/src/api/practice.ts` (New)
- `miniprogram/src/api/diagnosis.ts` (New)
- `miniprogram/tests/unit/api/api_modules.spec.ts` (New)

#### 2. Order of work
1. **测试先行 (Fail-repro First)**:
   - 编写 `tests/unit/api/api_modules.spec.ts`，对每个 API 函数在不同入参下的 URL 拼装、HTTP Method、Query/Body 序列化进行断言打桩，确认红灯。
2. **实现各领域 API 纯函数模块**:
   - `src/api/auth.ts`:
     - `wechatLogin(code: string): Promise<AuthTokens>`
     - `refreshToken(refreshToken: string): Promise<AuthTokens>`
     - `revokeToken(): Promise<void>`
   - `src/api/user.ts`:
     - `getUserProfile(): Promise<UserProfile>`
     - `deleteAccount(): Promise<void>`
   - `src/api/material.ts`:
     - `uploadMaterial(filePath: string, title?: string): Promise<MaterialSummary>`
     - `getMaterialTaskStatus(taskId: string): Promise<MaterialTaskStatus>`
     - `listMaterials(page: number, pageSize: number): Promise<PaginationResult<MaterialSummary>>`
     - `getMaterialOutline(materialId: string): Promise<MaterialOutline>`
   - `src/api/practice.ts`:
     - `createPractice(materialId: string, options: PracticeCreateOptions): Promise<PracticeSession>`
     - `submitPractice(practiceId: string, submission: PracticeSubmission): Promise<PracticeResult>`
     - `getPracticeDetail(practiceId: string): Promise<PracticeSession>`
   - `src/api/diagnosis.ts`:
     - `getDiagnosisReport(practiceId: string): Promise<DiagnosisReportSummary>`
     - `getUserMasteryOverview(materialId?: string): Promise<MasteryOverview>`
     - `getKnowledgeMastery(knowledgePointId: string): Promise<KnowledgeMasterySummary>`
3. **单测转绿与契约核验**:
   - 运行 API 模块单元测试，确认所有端点契约准确无误。

#### 3. Risks & Defenses
- **架构单向铁律**: API 模块仅负责网络请求与响应 DTO 转换，严禁在 API 模块中直接操作 Pinia Store 或写入 Storage；
- **命名规范红线**: 仅使用规范缩写白名单（`api`, `id`, `url`, `ocr`, `llm`, `db`, `config`, `env`），所有参数与方法名全英文。

#### 4. Proof
- API 模块单元测试：
  ```bash
  cd miniprogram && pnpm run test:unit tests/unit/api
  ```

---

### Milestone 4: Pinia 4-Store 状态层 (Pinia 4-Store State Matrix)
- **目标与职责**: 实现系统收敛的 4 个 Pinia Store（`userStore`, `materialStore`, `practiceStore`, `reportStore`），严格落实“Store 内严禁直接调用网络接口”与“仅跨页面共享状态进 Store”，并为 4 个 Store 编写状态变迁单元测试。
- **建议委派角色**: `builder-4`

#### 1. Files that change
- `miniprogram/src/stores/index.ts` (New)
- `miniprogram/src/stores/user.ts` (New)
- `miniprogram/src/stores/material.ts` (New)
- `miniprogram/src/stores/practice.ts` (New)
- `miniprogram/src/stores/report.ts` (New)
- `miniprogram/tests/unit/stores/user.spec.ts` (New)
- `miniprogram/tests/unit/stores/material.spec.ts` (New)
- `miniprogram/tests/unit/stores/practice.spec.ts` (New)
- `miniprogram/tests/unit/stores/report.spec.ts` (New)

#### 2. Order of work
1. **测试先行 (Fail-repro First)**:
   - 编写 `tests/unit/stores/user.spec.ts`：测试 `setTokens` 同步写入 Storage、`logout` 清空状态与凭据、`isLoggedIn` Getter 派生；
   - 编写 `tests/unit/stores/material.spec.ts`：测试 `setMaterialsList`、`appendMaterialsList` 分页追加与当前活跃资料切换；
   - 编写 `tests/unit/stores/practice.spec.ts`：测试题目线性队列跳转、`updateAnswer` 更新、`syncDraftToStorage` 草稿写入与 `loadDraftFromStorage` 恢复；断言严禁存储参考答案；
   - 编写 `tests/unit/stores/report.spec.ts`：测试报告概要派生与四级掌握度标签计算；
   - 确认测试全部红灯。
2. **实现 Pinia 统一注册与导出 (`src/stores/index.ts`)**:
   - 创建并导出 `pinia` 实例。
3. **实现 `useUserStore` (`src/stores/user.ts`)**:
   - 状态：`user: UserProfile | null`, `tokens: AuthTokens | null`；
   - 动作：`setTokens`, `setUserProfile`, `initFromStorage`, `logout`；
   - 单文件行数控制在 100 行内。
4. **实现 `useMaterialStore` (`src/stores/material.ts`)**:
   - 状态：`currentMaterialId`, `materialsList`, `pagination`, `activeVersion`；
   - 动作：`setCurrentMaterialId`, `setMaterialsList`, `appendMaterialsList`, `resetMaterialState`；
   - 单文件行数控制在 120 行内。
5. **实现 `usePracticeStore` (`src/stores/practice.ts`)**:
   - 状态：`practiceId`, `status`, `questions` (仅大纲，无参考答案), `currentIndex`, `answers`, `timeElapsedSeconds`；
   - 动作：`initSession`, `updateAnswer`, `nextQuestion`, `prevQuestion`, `jumpToQuestion`, `syncDraftToStorage`, `loadDraftFromStorage`, `clearSession`；
   - 绝密脱敏防线：草稿仅存储用户选择项，严禁附加题干与全文；
   - 单文件行数控制在 180 行内。
6. **实现 `useReportStore` (`src/stores/report.ts`)**:
   - 状态：`currentReportId`, `reportSummary`, `masteryOverview`；
   - 动作：`setReportSummary`, `setMasteryOverview`, `resetReportState`；
   - 单文件行数控制在 90 行内。
7. **单测转绿与合规校验**:
   - 执行全部 Store 单测，断言 100% 绿灯通过；
   - 校验 Store 文件源码，断言无任何直接的 `request` 或 `api` 导入。

#### 3. Risks & Defenses
- **架构违规防御**: 严厉审查 Store 内部代码，100% 杜绝直接发起 HTTP 请求；所有数据均由组件从 API 拉取后通过 Action 喂入 Store；
- **状态污染防御**: 每个 Store 必须具备确定性的 `reset` 或 `clear` 动作，防止跨用户或跨会话脏数据残留。

#### 4. Proof
- 4-Store 单元测试全绿断言：
  ```bash
  cd miniprogram && pnpm run test:unit tests/unit/stores
  ```
- Store 无网络请求与行数红线核验：
  ```bash
  cd miniprogram && pnpm run lint && pnpm run type-check
  ```

---

### Milestone 5: 应用入口装配、分包路由规划与全局门禁验收 (Assembly, Routing & Global Quality Gate)
- **目标与职责**: 完成 `App.vue`、`main.ts`、`pages.json`（主包与独立分包划分）装配，创建首页/登录/个人中心占位页面，确保前端全量测试、类型检查、代码规范、主包体积与 SDLC 门禁一键通过，退出码为 0。
- **建议委派角色**: `builder-5`

#### 1. Files that change
- `miniprogram/src/main.ts` (New)
- `miniprogram/src/App.vue` (New)
- `miniprogram/src/pages.json` (New)
- `miniprogram/src/pages/index/index.vue` (New)
- `miniprogram/src/pages/login/index.vue` (New)
- `miniprogram/src/pages/profile/index.vue` (New)
- `docs/sdlc/ZL-131/plan.md` (Modify - 状态更新与偏差核验)

#### 2. Order of work
1. **应用入口装配 (`src/main.ts`)**:
   - 装配 Pinia 状态管理插件；
   - 挂载 Wot Design Uni 组件体系；
   - 初始化挂载 Vue 应用。
2. **应用根生命周期 (`src/App.vue`)**:
   - `onLaunch`: 调用 `userStore.initFromStorage()` 自动恢复登录态凭证；
   - `onShow`, `onHide`: 记录应用运行状态日志。
3. **路由表与分包配置 (`src/pages.json`)**:
   - 全局窗口样式：冷灰背景 `#F8FAFC`、深蓝导航背景 `#2563EB`；
   - 主包页面规划（严格控制在 2.0MB 以内）：
     - `pages/index/index` (工作台首页，TabBar 页面)
     - `pages/login/index` (微信一键登录页)
     - `pages/profile/index` (个人中心设置，TabBar 页面)
   - 独立分包规划：
     - `subpackages/material`: 资料上传与大纲管理分包
     - `subpackages/report`: 学情诊断报告与掌握度看板分包
   - TabBar 配置：工作台与个人中心，使用矢量图标与零表情包文案。
4. **占位页面实现 (`src/pages/*`)**:
   - 实现极简标准骨架，引入 Wot Design Uni 基础组件；
   - 严格杜绝 Emoji，各页面文件代码行数控制在 80 行以内。
5. **全局质量门禁与全量测试核验**:
   - 运行前端 Lint 检查（行宽 100，零警告）；
   - 运行 TypeScript 类型扫描（0 错误）；
   - 运行全量单元测试（全部通过，毫秒级完成）；
   - 运行 SDLC 工件合规校验工具 `python3 tooling/check_sdlc_integrity.py`。

#### 3. Risks & Defenses
- **体积超标防御**: 严格将资料与报告归入分包，主包依赖收敛，确保主包代码体积远低于 2.0MB 阈值；
- **视觉风格防御**: 零 Emoji 表情包，统一采用冷灰底色与 Tokens 变量。

#### 4. Proof
- 前端全量质量门禁一键执行命令：
  ```bash
  cd miniprogram && pnpm run lint && pnpm run type-check && pnpm run test:unit
  ```
- SDLC 工件完整性与门禁合规检查：
  ```bash
  python3 tooling/check_sdlc_integrity.py
  ```

---

## 4. 全局质量门禁核验 (Global Quality Gate)

* **代码风格与静态检查**: `cd miniprogram && pnpm run lint`（ESLint 与 Prettier 行宽 100，零警告）
* **严格类型安全校验**: `cd miniprogram && pnpm run type-check`（vue-tsc 严格检查 0 类型错误）
* **全量单元测试与覆盖率**: `cd miniprogram && pnpm run test:unit`（涵盖 Storage 白名单、Request 静默刷新队列、4-Store 状态流转，全部通过）
* **工程架构与代码行数规范**: 单文件代码行数严格 $\le 300$ 行，Store 内部 0 网络请求，0 Unicode Emoji
* **SDLC 门禁合规**: `python3 tooling/check_sdlc_integrity.py` 退出码为 0，无任何未替换占位符

---

## 5. 实施偏差记录 (Deviations Log)

*在具体实施过程中若发现必须调整其他文件或契约，在此如实记录：*
* **2026-09-25 (Milestone 规划启动)**: 前端工程采用轻量原生 `uni.request` 封装替代笨重的 `axios`，避免因外部适配器引起的主包体积膨胀；确定采用双令牌 401 挂起队列模式，彻底阻断并发请求引起的令牌置换风暴。

---

## 6. 阶段准出签批 (Gate 3 Sign-off)
- [x] 所有分步实施项与验证断言均已规划配对且具备明确执行判据
- [x] 5 个原子 Milestone 单一职责明确，任务合理分发，避免 Builder 过载
- [x] 变更文件与 plan.md 清单完全吻合，分层与脱敏防线完备
- **验收结论**: Approved
- **验证人 / 日期**: TechLead (人类授权推进模式) / 2026-09-25
