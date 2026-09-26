# Intent: 首页工作台UI重构与状态栏/快捷上传/最近学习流组件

- **任务编号**: ZL-138
- **提出人**: TechLead
- **创建时间**: 2026-09-25 12:52
- **初始 Change Tier**: Tier 2
- **当前状态**: Accepted

---

## 1. 问题与现状背景 (Problem)
在智练系统自适应闭环中，后端已完成从资料上传解析、知识点建树、组卷练习到混合判题及学情诊断的全链路接口，前端各子包（`subpackages/material`, `subpackages/practice`, `subpackages/report`）亦已相继落地。然而作为学生用户每日首个触达的枢纽门户——首页工作台（`miniprogram/src/pages/index/index.vue`），当前存在以下关键问题与体验断层：
1. **信息架构简陋生硬，缺乏仪表盘质感**：当前首页仅由 4 个孤立指标卡片简单平铺（资料总数、练习进度、学情诊断、待巩固错题），视觉与信息层级扁平，缺乏现代学习工作台的聚焦感与实用流转体验。
2. **全局艾宾浩斯掌握度感知断链**：学生进入首页无法快速获知自身宏观综合掌握度（综合得分、当前所处四档档次及精通/良好/需巩固/未学知识点分布比例与数量），无法一眼掌握薄弱盲区，难以形成正向学习驱动力。
3. **资料导入路径过深，首要动作受阻**：快捷上传链路割裂，用户需二级跳转到资料列表页方能发起上传，无法在首页第一屏直接完成资料选定与提交解析，阻碍了首要闭环动作的顺畅发生。
4. **缺乏“智能双轨”学习上下文连贯性**：
   - 针对进行中练习或未交卷作答草稿（暂存本地 Storage）：首页无法智能感知并置顶唤起，导致学生一旦中断答题退出应用后，难以一键恢复作答进度；
   - 针对最近资料流：无法直观展示最近学习资料的解析状态（如已就绪/解析中/需重拍）、核心考点数，更缺乏一键【快捷出题】动作入口。
5. **新手冷启动零数据态引导缺失**：新注册或零资料零练习用户进入首页时，面对全部为 0 的数字无所适从，缺少温和友好的 3 步新手引导指南卡（导入资料 -> AI 萃取考点 -> 自适应出题练习）。
6. **加载体验生硬与工程规范约束**：首屏加载缺少骨架屏过渡，多接口未采用并发容灾机制；且原有页面未拆分组件，亟需按规范拆分为高内聚、代码行数严格 $\le 300$ 行的子组件，遵循零 Emoji 原则与低饱和设计规范。

## 2. 变更性质分类 (Change Archetype - 单选)
- [ ] 局部结构精简 (Local Cleanup - 仅限模块内部冗余消除，不改数据流向与全局装配)
- [x] 单模块特性演进 (Single-Module Feature - 单一模块业务增量或修复)
- [ ] 跨领域架构重构 (Cross-Domain Rewiring - 触及应用全局装配、生命周期或跨域流向，必须升 Tier 3)

## 3. 期望达成效果 (Proposed Outcome)
1. **现代学习仪表盘架构重塑**：重构 `miniprogram/src/pages/index/index.vue` 及其配套样式，建立克制实用、低饱和、信息层级分明的现代学习工作台，废弃无意义装饰胶囊。
2. **掌握度状态栏组件 (`MasteryDashboardBar`)**：
   - 左侧：大号综合得分（如 85分，字号 44rpx，字重 800）与四档掌握度徽章（精通/良好/需巩固/未学）；
   - 右侧：紧凑四档考点分布横条，按百分比清晰映射四档考点色彩与数量占比；
   - 交互：整卡热区点击无缝跳转至学情诊断报告详情页（`/subpackages/report/pages/detail/index`）。
3. **快捷上传行动栏组件 (`QuickUploadBar`)**：
   - 一体化上传横幅卡片，文案直观（“导入学习资料，AI 智能切分考点与出题”），触控热区 $\ge 88\text{rpx}$；
   - 点击横幅唤起底部选单（微信聊天文件 / 拍照与相册），深度集成复用 `MaterialUpload.vue` 业务闭环；
   - 上传成功后自动触发通知并局部刷新资料列表。
4. **最近学习内容流组件 (`RecentLearningSection`)**：
   - 智能双轨动态流：
     - 轨 1【进行中练习置顶卡】：自动检测本地未提交草稿或活跃练习会话，置顶展示答题进度（如已答 4/10 题）与更新时间，提供“继续练习”按钮一键直达 `/subpackages/practice/pages/session/index`；
     - 轨 2【最近学习资料列表】：展示最近 2 份资料卡片，呈现标题、文件类型、解析状态（就绪/解析中等）、考点数，并配有一键【快捷出题】与【查看详情】按钮；
     - 右上角提供“全部资料”无缝跳转至 `/subpackages/material/pages/list/index`。
5. **新手引导指南卡 (`NewbieGuideCard`)**：
   - 零数据状态下温和替代内容流，展示 3 步学习指南（导入资料 -> 智能提炼 -> 自适应练习），附带“立即开始第一次学习”直达上传。
6. **首屏并发容灾与骨架屏**：
   - 采用 `Promise.allSettled` 并发加载掌握度概览与资料列表，单接口故障不阻断其他区块；集成 `wd-skeleton` 优雅过渡；支持下拉刷新 `onPullDownRefresh`。
7. **架构合规底线达标**：
   - 所有 Vue 组件单文件严格 $\le 300$ 行；
   - 零 Unicode Emoji 字符；
   - 样式提取至同名 SCSS 文件，使用 DESIGN.md 规定色盘，零裸 Hex 色值；
   - 状态管理收敛于 Pinia 4-Store，本地 Storage 严格遵守白名单（仅持久化草稿等允许项，严禁缓存资料全文或题目）。

## 4. 波及工程分面 (Affected Architectural Layers)
- [x] 核心领域与计算逻辑 (Domain & Core Business Logic)
- [x] 外部接口与协议入口 (Public Ingress & Controllers & Protocols)
- [ ] 数据持久化与状态存储 (Database & Storage & Schemas)
- [x] 全局装配与应用入口 (Bootstrap & Lifecycle & Service Wiring)

## 5. 边界与硬性约束 (Constraints & Boundaries)

### 7 维动态风险扫描 (7-Dimensional Risk Scan)
1. **Affected Files (改动文件数量与跨模块广度)**：
   - 预计新增 8 个文件：`components/home/MasteryDashboardBar.vue` & `.scss`、`components/home/QuickUploadBar.vue` & `.scss`、`components/home/RecentLearningSection.vue` & `.scss`、`components/home/NewbieGuideCard.vue` & `.scss`，以及配套的 4 个单元测试文件；
   - 预计修改 2 个文件：`pages/index/index.vue`（重构为容器组件）、`pages/index/index.scss`。全量位于前端，不触碰后端代码。
2. **Public API (对外接口契约变动)**：
   - 零后端接口破坏性修改，完全复用后端已有接口：
     - `GET /api/v1/mastery/overview`（宏观掌握度四档统计）
     - `GET /api/v1/materials`（分页资料列表）
     - `POST /api/v1/practices`（快捷出题）
     - `GET /api/v1/practices/{id}`（继续练习会话查询）
3. **Data Schema (持久化与数据模型)**：
   - 零后端表结构变更；
   - 前端本地 Storage 严格白名单防护：仅读取合法的 `practice_drafts`，严禁将资料全文、题目原题等敏感数据写入 Storage。
4. **Auth & Security (权限与租户隔离)**：
   - 未登录与登录态平滑隔离：未登录时掌握度栏与内容流展示未登录/空数据态，引导点击登录；已登录态自动携带 JWT Token 发起并发查询。
5. **Dependencies (第三方外部依赖)**：
   - 零新增第三方 npm 依赖，完全依托已有 Vue 3、Pinia、Wot Design Uni (`wd-skeleton`, `wd-action-sheet`, `wd-tag`)。
6. **Rollback Difficulty (状态变更可逆性与回滚代价)**：
   - 回滚代价极低：纯前端页面重塑，若遇不可抗力仅需 Git 还原 `pages/index/` 目录即可恢复老版首页，无数据结构降级风险。
7. **Blast Radius (爆炸半径与破坏面)**：
   - 仅局限于小程序首页（Tab 1）展示与交互，不破坏正在作答的练习逻辑、交卷幂等逻辑与诊断算法。

### 核心约束与判定
* **硬性技术制约**:
  - 单个 Vue 文件代码行数强制严格 $\le 300$ 行，必须抽离各子组件与独立 SCSS 文件；
  - 零表情包原则 (Zero-Emoji Policy)：严禁出现任何 Unicode Emoji；
  - 触控与人体工程学：最小点击热区 $\ge 88\text{rpx}$，按压缩放动效 `transform: scale(0.985)`；
  - 低饱和色彩规范：精通 `#7C3AED`、良好 `#059669`、需巩固 `#B45309`、未学 `#64748B`，严禁散落裸 Hex 色值；
  - Pinia 4-Store 纯状态管理，网络请求统一走 `src/api/`；
  - 并发加载必须采用 `Promise.allSettled` 进行优雅降级容灾。
* **明确非目标 (Non-Goals / Out-of-Scope)**:
  - 不包含资料列表管理的全量分页多选删除功能（由 `subpackages/material` 独立承载）；
  - 不包含答题过程、题卡切换及交卷逻辑实现（由 `subpackages/practice` 独立承载）；
  - 不包含完整学情诊断报告的复杂图表与错题消灭操作（由 `subpackages/report` 独立承载）。
* **完成判定条件 (Definition of Done)**:
  - 首页工作台各子组件拆分完毕，各单文件行数 $\le 300$ 行；
  - 单元测试覆盖率达标，针对 4 个新组件与首页容器编写单元测试；
  - 执行 `pnpm run lint`、`pnpm run type-check`、`pnpm run test:unit` 全部通过，0 错误；
  - SDLC 门禁 `python3 tooling/check_sdlc_integrity.py` 100% 验证通过。

## 6. 未决疑问与待探讨点 (Open Questions)
- 探讨点 1：关于进行中练习与草稿的唤醒逻辑。当本地 Storage 中存在多个未完成草稿时，首页置顶哪一个？
  - 明确结论：取更新时间戳 `updated_at` 最近的一条草稿予以置顶呈现，并提示“已答 X/Y 题，继续练习”，保持操作最简与直觉连贯。
- 探讨点 2：资料卡片点击“快捷出题”的流向。
  - 明确结论：若该资料已有就绪的知识点树，直接唤起出题配置抽屉或无缝跳转至 `/subpackages/material/pages/knowledge-tree/index?material_id=xxx`，实现从资料到做题的极速闭环。

---

## 7. 阶段准出签批 (Gate 1 Sign-off)
- [x] 场景与问题已客观复现并达成共识
- [x] 边界、非目标与约束清晰明确
- [x] 初始 Change Tier 评定合理
- **准出结论**: Accepted
- **签批人 / 日期**: TechLead / 2026-09-25 13:05
