# Intent: 错题本与一键继续练习交互模块

- **任务编号**: ZL-136
- **提出人**: TechLead
- **创建时间**: 2026-09-25 11:42
- **初始 Change Tier**: Tier 2
- **当前状态**: Draft / In-Review / Accepted

---

## 1. 问题与现状背景 (Problem)
在智练系统自适应闭环中，后端已实现错题本持久化模型、错题列表检索与攻克端点（ZL-106, ZL-128）、判题服务（ZL-123）与掌握度诊断（ZL-124），前端也完成了答题会话与交卷流程（ZL-134）以及判题反馈与诊断报告组件（ZL-135）。然而，在错题复盘与巩固刷题闭环中，当前仍存在以下关键业务与工程痛点：
1. **错题本页面与多维筛选界面缺失 (FR-54~56)**：学生在练习中答错的题目虽已沉淀至后端 `wrong_records` 表，但在前端缺乏专属错题本页面（FR-54）。学生无法按知识点、题型、四类错误类型（概念性错误、表述不全、审题偏差、未作答）与攻克状态进行多维组合筛选查看，无法快速定位高频错题与薄弱根源（FR-55, FR-56）。
2. **攻克状态流转与标记交互断链 (FR-57)**：需求规定当学生重做答对或自主掌握错题后，题目需移出待练列表但历史记录与错误次数仍然保留可查。当前前端缺少一键标记攻克/取消攻克的手动与自动流转机制，无法直观反映错题消除进度。
3. **继续练习缺乏防抖防重与合并流转机制 (FR-58, NFR-07)**：需求与架构基线明确要求，诊断报告与继续练习入口必须具备重复合并能力（存在未开始同来源练习时不得重复创建），且前端在弱网与高频连击下极易因网络抖动触发重复创建请求。当前诊断报告页底部的继续练习逻辑缺乏防抖（500ms）、UUID v4 幂等键防重与按钮加载态锁定。
4. **错题巩固练习到答题会话未能无缝衔接**：错题本缺乏勾选指定错题或一键按知识点生成巩固专项练习并直接跳转练习会话（`subpackages/practice/pages/session/index`）的平滑流转通道，学习闭环存在断裂。
5. **小程序架构与性能红线制约**：根据 AGENTS.md 与 DESIGN.md，错题本属于分析报告领域，必须置于分包 `subpackages/report/` 组织以保护主包体积（<= 2MB）；单个 `.vue` 文件代码行数强制 <= 300 行；严禁 Unicode Emoji；遵循 Wot Design Uni 规范与设计色彩矩阵；本地 Storage 白名单严格禁止持久化错题或题目全文。

## 2. 变更性质分类 (Change Archetype - 单选)
- [ ] 局部结构精简 (Local Cleanup - 仅限模块内部冗余消除，不改数据流向与全局装配)
- [x] 单模块特性演进 (Single-Module Feature - 单一模块业务增量或修复)
- [ ] 跨领域架构重构 (Cross-Domain Rewiring - 触及应用全局装配、生命周期或跨域流向，必须升 Tier 3)

## 3. 期望达成效果 (Proposed Outcome)
1. **错题本分包主页面交付 (WrongBookPage)**：在 `subpackages/report/pages/wrong-book/index.vue` 交付完整的错题本主页面，在 `pages.json` 注册，支持下拉刷新、触底分页加载、空状态引导与骨架屏。
2. **多维筛选栏组件 (WrongRecordFilterBar)**：实现攻克状态 Tab（全部 / 待攻克 / 已攻克）、知识点联动选择、题型胶囊筛选与四类错误类型胶囊筛选，支持单选与多维条件组合过滤（FR-56）。
3. **错题简报卡片组件 (WrongRecordCard)**：结构化呈现题型徽章、四类错误类型标签（低饱和色盘）、累计答错次数徽章（`error_count`）、首次与最近答错时间、题干快照、用户历史作答与标准答案比对、答案解析折叠展开，并提供一键攻克状态切换按键与错题多选框（FR-54, FR-55, FR-57）。
4. **吸底防抖防重继续练习栏 (ContinuePracticeBar)**：独立封装通用的吸底操作栏组件，内置 500ms 纯函数防抖、UUID v4 幂等键生成、按钮防重锁与加载态，支持诊断报告详情页与错题本页面两处复用（FR-58）。
5. **诊断报告详情页重构接驳**：在 `subpackages/report/pages/detail/index.vue` 中引入 `ContinuePracticeBar` 替换原行内按钮，使该页面代码行数由 297 行优化缩减至 250 行以内，彻底规避 300 行超限红线。
6. **错题专项巩固练习无缝流转**：支持在错题本中勾选多道错题或一键提取未攻克错题的知识点，调用后端接口生成巩固练习，由 `practiceStore` 承接并直接无缝跳转练习作答页。
7. **纯函数计算核与 Pinia 状态管理**：交付 `wrongBookFormat.ts` 纯函数计算核（错误类型映射、攻克色彩映射、防抖幂等算法）；`reportStore` 维护错题列表缓存与筛选状态，严禁 Store 内直接发起 API 调用；错题数据严禁进入本地 Storage。

## 4. 波及工程分面 (Affected Architectural Layers)
- [x] 核心领域与计算逻辑 (Domain & Core Business Logic)
- [x] 外部接口与协议入口 (Public Ingress & Controllers & Protocols)
- [ ] 数据持久化与状态存储 (Database & Storage & Schemas)
- [ ] 全局装配与应用入口 (Bootstrap & Lifecycle & Service Wiring)

## 5. 边界与硬性约束 (Constraints & Boundaries)

### 7 维动态风险扫描 (7-Dimensional Risk Scan)
1. **Affected Files (改动文件数量与跨模块广度)**：预计新增/改动 10~12 个前端文件，集中在 `miniprogram/src/subpackages/report/`、`miniprogram/src/pages.json`、`miniprogram/src/types/report.ts`、`miniprogram/src/api/diagnosis.ts`、`miniprogram/src/stores/reportStore.ts` 以及单元测试文件，不修改后端 Python 代码。
2. **Public API (对外接口契约变动)**：零后端破坏性修改，完全复用后端已有接口：`GET /api/v1/wrong-records`（多维检索）、`POST /api/v1/wrong-records/{id}/master`（攻克标记）、`DELETE /api/v1/wrong-records/{id}`（错题移除）、`POST /api/v1/practices`（继续练习与同来源防重合并）。
3. **Data Schema (持久化与数据模型)**：不修改后端数据库表结构；前端本地 Storage 严格遵守白名单（仅持久化登录态、未交卷草稿与用户偏好），错题记录与题干全文绝对严禁进入 Storage，所有错题数据驻留于内存 Pinia Store 中，页面刷新重新请求。
4. **Auth & Security (权限与租户隔离)**：沿用已有的 Bearer Token 鉴权机制；所有错题查询与状态更新均由后端强校验当前登录租户与用户归属（`current_user.id`），有效防御水平越权。
5. **Dependencies (第三方外部依赖)**：零新增第三方 npm 依赖，完全依托 Vue 3、Pinia 与 Wot Design Uni 已有组件体系。
6. **Rollback Difficulty (状态变更可逆性与回滚代价)**：回滚成本极低，若出现前端交互异常仅需还原前端分包路由与组件代码，后端无数据迁移回滚风险。
7. **Blast Radius (爆炸半径与破坏面)**：仅影响学情报告分包内的错题查看与继续练习创建流转，对主包登录、资料管理、正常练习作答与交卷流程无任何破坏性影响。

### 核心约束与判定
* **硬性技术制约**:
  - 单个 `.vue` 文件代码行数强制 <= 300 行，超过必须抽离子组件或 SCSS 样式；
  - 零 Unicode Emoji 规范，所有状态指示一律使用低饱和色盘或矢量图标；
  - 四类错误类型低饱和色盘规范：概念性错误 `#EF4444`（浅红底 `#FEF2F2`）、表述不全 `#F59E0B`（浅黄底 `#FFFBEB`）、审题偏差 `#3B82F6`（浅蓝底 `#EFF6FF`）、未作答 `#64748B`（浅灰底 `#F1F5F9`）；
  - 攻克状态色彩规范：已攻克 `#10B981`（浅绿底 `#ECFDF5`）、待攻克 `#F59E0B`（浅黄底 `#FFFBEB`）；
  - 交互体验规范：按钮点击态必须添加 `transform: scale(0.985)` 微动效；
  - 状态管理：Pinia `reportStore` 严禁直接调用 API，由页面/组合式函数发起请求后写入 Store；
  - 防重防抖机制：继续练习触发必须具备 500ms 纯函数防抖与 UUID v4 幂等键防并发。
* **明确非目标 (Non-Goals / Out-of-Scope)**:
  - 不包含错题导出 PDF 或 Markdown 功能（属于 P1 需求 FR-65）；
  - 不修改后端组卷分发算法或判题逻辑；
  - 不修改用户端答题卡与选项交互底层组件（已在 ZL-134 固化）。
* **完成判定条件 (Definition of Done)**:
  - 错题本页面在分包路由 `subpackages/report/pages/wrong-book/index` 正常注册并支持分页与下拉刷新；
  - 多维筛选栏、错题卡片、吸底继续练习栏全部就绪并正常联动；
  - 错题攻克标记切换能够调用后端接口并乐观更新列表界面；
  - 诊断报告页成功接入 `ContinuePracticeBar`，继续练习防抖与防重创建验证通过；
  - 前端全套自动化检查通过：`pnpm run lint`、`pnpm run type-check`、`pnpm run test:unit` 全部 0 error 退出；
  - 门禁合规检查 `python3 tooling/check_sdlc_integrity.py` 退出码 0。

## 6. 未决疑问与待探讨点 (Open Questions)
1. **错题本中发起巩固练习的题目来源优先级**：当用户在错题本点击“一键巩固错题”时，若用户勾选了具体错题，系统优先取所选题目对应的知识点范围（`knowledge_point_ids`）；若用户未勾选，则默认提取当前筛选条件下全部待攻克错题的知识点集合，调用 `continuePractice` 接口进行智能同源组卷。
2. **防重合并与 UUID 幂等键的协同**：继续练习入口采用两层防重设计：前端第一层通过 500ms 防抖函数与按钮 loading 锁定阻止物理连击；第二层每次点击生成唯一的 UUID v4 幂等请求头，并传递 `source_report_id`，后端服务根据 FR-58 检查是否存在未开始的同来源练习进行幂等合并复用，双重杜绝重复组卷。

---

## 7. 阶段准出签批 (Gate 1 Sign-off)
- [x] 场景与问题已客观复现并达成共识
- [x] 边界、非目标与约束清晰明确
- [x] 初始 Change Tier 评定合理
- **准出结论**: Accepted
- **签批人 / 日期**: TechLead / 2026-09-25 11:42