# Intent: 小程序基础脚手架、Pinia 4-Store与Storage白名单封装

- **任务编号**: ZL-131
- **提出人**: TechLead
- **创建时间**: 2026-09-25 01:09
- **初始 Change Tier**: Tier 2
- **当前状态**: Accepted

---

## 1. 问题与现状背景 (Problem)
后端 5 大核心业务领域的 API 路由（认证授权、学习资料、知识点/题目、练习/判题、诊断报告）已全量构建并完成测试闭关（共 1013 个后端用例）。
然而前端工程目前尚为空白（`miniprogram/` 目录尚未初始化）。前端缺少基于 uni-app (Vue 3 + Vite + TypeScript) 的标准化工程脚手架，缺少 Wot Design Uni 视觉与组件库基座配置，缺少统一的网络请求拦截器（含 401 双令牌静默刷新排队重放机制与统一业务错误码映射），缺少按照架构规范严格收敛的 Pinia 4-Store，以及防止敏感数据本地泄漏的 Storage 白名单封装。

## 2. 变更性质分类 (Change Archetype - 单选)
- [ ] 局部结构精简 (Local Cleanup - 仅限模块内部冗余消除，不改数据流向与全局装配)
- [x] 单模块特性演进 (Single-Module Feature - 单一模块业务增量或修复)
- [ ] 跨领域架构重构 (Cross-Domain Rewiring - 触及应用全局装配、生命周期或跨域流向，必须升 Tier 3)

## 3. 期望达成效果 (Proposed Outcome)
1. **脚手架与基础工程初始化 (`miniprogram/`)**：
   - 基于 uni-app + Vue 3 (Composition API) + Vite 5 + TypeScript 构建；
   - 依赖与组件库：引入并配置 `wot-design-uni`，完成 SCSS 变量与 Design Tokens 深度适配（对齐 `docs/DESIGN.md` 色盘与参数）；
   - 配置严格代码规范与测试套件：ESLint, Prettier, TypeScript (vue-tsc), Vitest 单测工具链；
   - 目录结构分层：严格划分 `pages/`, `subpackages/`, `components/`, `composables/`, `stores/`, `api/`, `utils/`, `types/`。
2. **网络请求层 (`src/api/` & `src/utils/request.ts`)**：
   - 封装 uni.request / Promise 统一网络客户端；
   - 双令牌机制：存储与携带 Access Token；当遇到 401 且未在刷新中时，触发 `/api/v1/auth/refresh` 进行静默刷新，利用请求队列锁排队重放待发请求；刷新失败或过期则清理凭据并重定向至登录页；
   - 业务错误码拦截：将 10xxx, 20xxx, 30xxx, 40xxx, 50xxx 统一映射为前端用户友好提示，严格遵循 `docs/DESIGN.md` 的零度描写文案字典。
3. **Pinia 4-Store 严格收敛 (`src/stores/`)**：
   - 严格限定仅有 4 个 Store：
     - `useUserStore`: 管理用户状态、登录态、Token、用户画像；
     - `useMaterialStore`: 管理跨页面的当前活跃资料、版本与分页列表；
     - `usePracticeStore`: 管理当前练习会话、题目线性队列、当前作答进度与已选选项；
     - `useReportStore`: 管理当前练习产出的诊断报告与掌握度概要数据；
   - 架构铁律：Store 内严禁直接调用接口，数据拉取与提交由外部或 Store 引用 `src/api` 标准模块；跨页面数据才允许进入 Store。
4. **本地存储 Storage 白名单安全封装 (`src/utils/storage.ts`)**：
   - 严格白名单键限制（仅限 3 类）：
     - `auth_tokens`: 存储 Access/Refresh Token 及版本；
     - `practice_drafts`: 存储离线作答草稿队列；
     - `user_settings`: 存储用户界面与音效偏好；
   - 任何向 Storage 写入未在白名单中键（或试图写入资料全文、题目全文）的行为直接抛错拦截；
   - 单元测试覆盖白名单校验与读写隔离。

## 4. 波及工程分面 (Affected Architectural Layers)
- [ ] 核心领域与计算逻辑 (Domain & Core Business Logic)
- [x] 外部接口与协议入口 (Public Ingress & Controllers & Protocols)
- [x] 数据持久化与状态存储 (Database & Storage & Schemas)
- [x] 全局装配与应用入口 (Bootstrap & Lifecycle & Service Wiring)

## 5. 边界与硬性约束 (Constraints & Boundaries)
* **硬性技术制约**:
  - 单文件代码行数必须 $\le 300$ 行；
  - 主包体积规划与基础依赖控制在 $2.0\text{MB}$ 以内；
  - 严禁在页面或组件中使用任何 Unicode Emoji（对齐 `docs/DESIGN.md` 第 1 节）；
  - 色彩与设计令牌严格对齐 `docs/DESIGN.md`（如冷灰背景 `#F8FAFC`、主色 `#2563EB` 等）；
  - 质量门禁基线必须通过：`pnpm run lint`、`pnpm run type-check`、`pnpm run test:unit` 均通过。
* **明确非目标 (Non-Goals / Out-of-Scope)**:
  - 不实现具体的业务页面复杂交互（资料上传重拍组件在 ZL-132，知识点与出题页面在 ZL-133，答题与交卷组件在 ZL-134，判题与报告在 ZL-135，错题在 ZL-136）；本任务聚焦于脚手架、网络请求层、Pinia 4-Store 底座与 Storage 白名单工具。
  - 不修改后端代码。
* **完成判定条件 (Definition of Done)**:
  - `miniprogram/` 脚手架目录完整建立并可执行编译构建；
  - `wot-design-uni` 依赖安装并完成主题覆盖配置；
  - `src/utils/storage.ts` 白名单防护函数与单测通过；
  - `src/utils/request.ts` 双令牌刷新队列机制与单测通过；
  - 4 个 Pinia Store 建立并有单元测试验证状态流转；
  - `pnpm run lint`、`pnpm run type-check`、`pnpm run test:unit` 全部通过。

## 6. 未决疑问与待探讨点 (Open Questions)
- 微信小程序端网络请求在测试环境中如何 Mock：Vitest 中可使用轻量全局 stub 模拟 `uni.request` 与 `uni.getStorageSync`。

---

## 7. 阶段准出签批 (Gate 1 Sign-off)
- [x] 场景与问题已客观复现并达成共识
- [x] 边界、非目标与约束清晰明确
- [x] 初始 Change Tier 评定合理
- **准出结论**: Accepted
- **签批人 / 日期**: TechLead (人类授权模式) / 2026-09-25 01:15
