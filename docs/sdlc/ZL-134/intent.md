# Intent: 练习作答、本地草稿队列与交卷确认组件

- **任务编号**: ZL-134
- **提出人**: TechLead
- **创建时间**: 2026-09-25 03:44
- **初始 Change Tier**: Tier 2
- **当前状态**: Draft / In-Review / Accepted

---

## 1. 问题与现状背景 (Problem)
在智练平台的学生端核心答题闭环中，后端已完成组卷出题（ZL-121）、练习持久化（ZL-122）与路由端点（ZL-129），但前端小程序侧尚缺失完整的练习作答与交卷交互组件（FR-29~36、NFR-09、NFR-21）。具体面临以下痛点：
1. **多题型连续作答与沉浸式交互缺失**：学生端缺少承载题干渲染、题号进度指示、单选/多选/判断/填空/简答 5 大题型交互的界面载体，且缺少快速跳转与全局览卷的答题卡抽屉。
2. **移动端弱网/断网丢答与竞态隐患**：移动端网络波动频繁，若每题作答仅依赖实时 HTTP 同步，断网或网络超时会导致作答内容丢失或卡顿；缺乏合规的本地草稿暂存队列（Storage 白名单限制）与断网自动重试补发能力（FR-34, NFR-09）。
3. **未答题误交与非幂等提交风险**：交卷操作缺乏未答题盘点与二次阻断确认弹窗（FR-36），极易导致误触提前交卷且未答题被判零分；交卷未对齐后端强幂等键（`Idempotency-Key`），弱网连击可能导致重复创建判题任务（FR-35）。
4. **前端性能与规范红线约束**：根据 AGENTS.md 与 DESIGN.md，主包体积需控制在 2MB 内（练习必须以分包 `subpackages/practice` 组织）、单组件文件行数必须 $\le 300$ 行、禁止 Emoji 表情、按钮与卡片必须满足人体工程学最小触控尺寸与微交互规范。

## 2. 变更性质分类 (Change Archetype - 单选)
- [ ] 局部结构精简 (Local Cleanup - 仅限模块内部冗余消除，不改数据流向与全局装配)
- [x] 单模块特性演进 (Single-Module Feature - 单一模块业务增量或修复)
- [ ] 跨领域架构重构 (Cross-Domain Rewiring - 触及应用全局装配、生命周期或跨域流向，必须升 Tier 3)

## 3. 期望达成效果 (Proposed Outcome)
1. **分包与页面交付**：在独立分包 `subpackages/practice/pages/session/index.vue` 中构建完整练习会话页面，在 `pages.json` 完成分包声明，确保小程序主包体积维持在 2MB 以下。
2. **多题型无缝渲染**：拆分高内聚组件（`PracticeHeader`, `QuestionRenderer`, `OptionCard`, `AnswerSheetDrawer`, `SubmitConfirmModal`, `BottomActionBar`），原生支持 5 种题型（单选、多选、判断、填空、简答），严格遵循 Wot Design Uni 规范、零 Emoji、按压缩放 `scale(0.985)`、卡片最小高度 96rpx。
3. **断网离线草稿队列与自动重试**：利用 `utils/storage.ts` 白名单中的 `practice_drafts` 进行本地毫秒级落盘，配合 `subpackages/practice/utils/draft.ts` 纯函数处理离线入队与网络恢复/交卷前自动刷新同步（FR-34）。
4. **答题卡与未答题二次确认阻断**：答题卡底部抽屉支持“已答/当前/未答”三种状态高亮与即刻跳题；交卷前精确盘点未答题目数，未答数 > 0 时弹出阻断确认弹窗，强制二次确认后方可携带 `confirm_unanswered=true` 提交，全部答完直接发起提交（FR-36）。
5. **客户端交卷强幂等**：交卷请求自动生成客户端 UUIDv4 `Idempotency-Key` 请求头，并发拦截防重（FR-35）。

## 4. 波及工程分面 (Affected Architectural Layers)
- [x] 核心领域与计算逻辑 (Domain & Core Business Logic)
- [x] 外部接口与协议入口 (Public Ingress & Controllers & Protocols)
- [x] 数据持久化与状态存储 (Database & Storage & Schemas)
- [ ] 全局装配与应用入口 (Bootstrap & Lifecycle & Service Wiring)

## 5. 边界与硬性约束 (Constraints & Boundaries)

### 7 维动态风险扫描 (7-Dimensional Risk Scan)
1. **Affected Files (改动文件数量与跨模块广度)**：预计改动/新增约 8~10 个前端文件，集中在 `miniprogram/src/subpackages/practice/`、`miniprogram/src/pages.json` 与测试目录，不波及后端与外部系统。
2. **Public API (对外接口契约变动)**：零后端契约修改，完全对齐后端已交付的 `POST/GET /api/v1/practices`、`PUT /api/v1/practices/{id}/answers` 与 `POST /api/v1/practices/{id}/submit`。
3. **Data Schema (持久化与数据模型)**：不修改任何后端数据库模型；前端本地 Storage 严格限定在白名单 key `practice_drafts`，且严禁存入题目题干、答案或资料全文，杜绝敏感内容泄漏。
4. **Auth & Security (权限与租户隔离)**：沿用已有的 Bearer Token 机制；单题暂存与交卷通过 HTTP Headers 鉴权；严格保证学生仅能提交自身 session。
5. **Dependencies (第三方外部依赖)**：零新增第三方 npm 依赖，完全依托项目已集成的 Vue 3、Pinia 与 Wot Design Uni。
6. **Rollback Difficulty (状态变更可逆性与回滚代价)**：回滚成本极低，若需降级仅需从 `pages.json` 卸载分包或隐藏练习入口，无不可逆数据迁移。
7. **Blast Radius (爆炸半径与破坏面)**：仅影响练习作答流程，对资料管理、登录与后续判题模块无直接破坏风险。

### 核心约束与判定
* **硬性技术制约**:
  - 单个 `.vue` 文件代码行数强制 $\le 300$ 行；
  - 零 Unicode Emoji 规范；
  - 触控热区最小尺寸 $\ge 88\text{rpx} \times 88\text{rpx}$，选项卡片最小高度 $\ge 96\text{rpx}$；
  - 吸底操作栏必须适配安全区 `padding-bottom: env(safe-area-inset-bottom)`；
  - Pinia `practiceStore` 内严禁直接调用 API，网络调用由统一请求层承载；
  - 本地 Storage 仅能使用 `practice_drafts` 且不可存储题干文本。
* **明确非目标 (Non-Goals / Out-of-Scope)**:
  - 不包含练习判题结果反馈、主观题自评与诊断报告展示（由 ZL-135 承载）；
  - 不包含错题本消灭练习与筛选交互（由 ZL-136 承载）；
  - 不新增或修改后端 Python 接口及数据库结构。
* **完成判定条件 (Definition of Done)**:
  - 分包注册与答题页面在真机/模拟器正常渲染；
  - 5 种题型均能正常完成答案录入与状态回显；
  - 断网离线草稿暂存及恢复在线后补发逻辑通过 100% 覆盖率纯函数单测与组件测试；
  - 答题卡抽屉正常联动切题与状态展示；
  - 未答题弹窗二次确认阻断生效；
  - 前端全套自动化检查通过：`pnpm run lint`、`pnpm run type-check`、`pnpm run test:unit` 全部 0 error 退出；
  - 门禁合规检查 `python3 tooling/check_sdlc_integrity.py` 退出码 0。

## 6. 未决疑问与待探讨点 (Open Questions)
1. **输入型题型（填空/简答）网络防抖时间设定**：建议本地 Pinia 与 Storage 维持无防抖即时更新，向后端发起的 `PUT /answers` 采用 1000ms 防抖或在切换题目时触发提交，平衡网络开销与实时性。
2. **多选题取消全部选择时的暂存形态**：多选若被用户全部反选，本地草稿与网络保存传空数组 `[]`，服务端识别为已作答但答案为空，未答题校验依据答案是否有效判定。

---

## 7. 阶段准出签批 (Gate 1 Sign-off)
- [ ] 场景与问题已客观复现并达成共识
- [ ] 边界、非目标与约束清晰明确
- [ ] 初始 Change Tier 评定合理
- **准出结论**: Pending
- **签批人 / 日期**: 待人类签批 / 2026-09-25 03:44
