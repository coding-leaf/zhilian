# Intent: 判题反馈、主观题自评/重判与诊断报告组件

- **任务编号**: ZL-135
- **提出人**: TechLead
- **创建时间**: 2026-09-25 11:05
- **初始 Change Tier**: Tier 2
- **当前状态**: Draft / In-Review / Accepted

---

## 1. 问题与现状背景 (Problem)
在智练系统自适应闭环中，后端已完成混合判题服务（ZL-123）、掌握度衰减与诊断合成（ZL-124）以及学情诊断与自评重判端点（ZL-130），前端小程序也完成了答题会话与交卷流程（ZL-134）。然而，学生在交卷后亟需即时、可信且具备溯源能力的判题反馈与深度诊断界面，目前存在以下业务与工程痛点：
1. **判题结果与深度诊断界面缺失**：学生交卷后无法查看综合得分、总耗时、卷面得分率及艾宾浩斯四档掌握度变化，缺乏直观感知自身学习成效与掌握进度的页面载体（FR-48, FR-49）。
2. **待重新判题缺乏清晰容灾与黄色告警呈现**：根据需求规范（FR-42 与《LEADER_ALIGNMENT.md》技术决策 1），大模型超时降级时主观题会被标记为待重新判题（`pending_regrade`），此时正式诊断报告处于阻断或降级状态。前端缺少醒目的黄色状态告警条与针对性提示，易导致学生产生“系统判分卡死或判错”的误解。
3. **主观题自评覆盖与申请重判交互链路断链**：针对主观题及降级题型，缺乏对照评分细则（`grading_rubric`）进行自主打分覆盖（`user_self` 渠道，FR-44）与申请后台 AI 重新判题（FR-42）的人性化交互弹窗，无法闭环审计和提升评分可信度。
4. **解析缺乏原文切片溯源与高亮定位**：学生查看错题解析时，需要回溯出题依据与知识点来源（FR-37~43）。当前缺少原文切片（Snippet）的抽屉展示与关键词高亮能力，无法快速定位知识根源。
5. **薄弱与退步知识点缺乏归因与行动指导**：诊断报告未能结构化展现薄弱知识点（强关联本次错题证据，FR-50）、退步预警（$\Delta \ge 0.05$，FR-51）以及艾宾浩斯衰减与认知盲区归因（FR-53），无法向学生提供明确的针对性复习建议。
6. **小程序架构与性能红线制约**：根据 AGENTS.md 与 DESIGN.md，报告模块必须以独立分包 `subpackages/report/` 组织，主包体积需控制在 2MB 内；单组件文件强制 $\le 300$ 行；严禁 Unicode Emoji；遵循 Wot Design Uni 规范与设计色彩矩阵（精通 `#7C3AED`、良好 `#059669`、需巩固 `#B45309`、未学 `#64748B`；判对 `#10B981`、判错 `#EF4444`、待确认/需巩固 `#F59E0B`）。

## 2. 变更性质分类 (Change Archetype - 单选)
- [ ] 局部结构精简 (Local Cleanup - 仅限模块内部冗余消除，不改数据流向与全局装配)
- [x] 单模块特性演进 (Single-Module Feature - 单一模块业务增量或修复)
- [ ] 跨领域架构重构 (Cross-Domain Rewiring - 触及应用全局装配、生命周期或跨域流向，必须升 Tier 3)

## 3. 期望达成效果 (Proposed Outcome)
1. **分包页面与路由交付**：在独立分包 `subpackages/report/pages/detail/index.vue` 交付完整的判题反馈与诊断报告主页面，在 `pages.json` 替换原有临时占位页面，确保小程序分包隔离与主包体积合规。
2. **诊断概览与状态告警（DiagnosisSummaryCard）**：展示总分、总用时、卷面得分率，动态渲染四档掌握度等级徽章；当存在 `pending_regrade_count > 0` 时醒目展示黄色告警栏（提示待重判状态），若存在 `is_structure_degraded=True` 时展示低可信度黄色标签。
3. **薄弱与退步知识点呈现（WeakKnowledgeCard）**：结构化展示薄弱知识点列表、退步标记（$\Delta \ge 0.05$）、掌握度变化进度条、认知归因（盲区/衰减等）及可执行建议，严格遵循无错题时的历史衰减特殊说明规范（FR-50, FR-51, FR-53）。
4. **逐题判题结果列表（GradingResultList）**：呈现逐题作答卡片，清晰区分判对（绿色）、判错（红色）、待重新判题（黄色）状态；展示参考答案、题目解析、命中关键词（`hit_keywords`）与遗漏要点（`missing_keywords`）。
5. **原文切片溯源抽屉（OriginalSnippetDrawer）**：支持点击单题解析中的“查看原文依据”，抽屉展示题目关联的切片内容、页码与章节，并对解析中的核心词段进行高亮渲染。
6. **自评与重判模态交互（SelfGradeModal & RegradeModal）**：提供主观题对照评分细则进行 0~满分滑块评分及心得录入并提交覆盖（FR-44）；提供申请重新判题理由录入并提交后台重试（FR-42），提交后本地即时刷新状态。
7. **Pinia 状态收敛与质量达标**：严格由 `reportStore` 管理诊断报告与掌握度数据，单组件 $\le 300$ 行，无 Emoji，单测覆盖完整，`vue-tsc` 与 `eslint` 0 error。

## 4. 波及工程分面 (Affected Architectural Layers)
- [x] 核心领域与计算逻辑 (Domain & Core Business Logic)
- [x] 外部接口与协议入口 (Public Ingress & Controllers & Protocols)
- [ ] 数据持久化与状态存储 (Database & Storage & Schemas)
- [ ] 全局装配与应用入口 (Bootstrap & Lifecycle & Service Wiring)

## 5. 边界与硬性约束 (Constraints & Boundaries)

### 7 维动态风险扫描 (7-Dimensional Risk Scan)
1. **Affected Files (改动文件数量与跨模块广度)**：预计新增/改动 10~12 个前端文件，集中在 `miniprogram/src/subpackages/report/`、`miniprogram/src/pages.json`、`miniprogram/src/types/report.ts` 及单元测试文件，不修改后端 Python 代码。
2. **Public API (对外接口契约变动)**：零后端破坏性修改，完全复用后端已有接口：`GET /api/v1/practices/{id}/diagnosis`、`POST /api/v1/grading/self-evaluate`、`POST /api/v1/grading/regrade`、`GET /api/v1/mastery/overview`、`GET /api/v1/knowledge/{id}/snippets`。
3. **Data Schema (持久化与数据模型)**：不修改后端表结构；前端本地 Storage 严禁存储诊断报告或原题文本（不在白名单内），所有报告数据驻留于内存 Pinia Store 中，刷新通过 API 获取。
4. **Auth & Security (权限与租户隔离)**：沿用已有的 Bearer Token 机制；自评与重判接口由后端强校验所属租户与用户归属，防范水平越权。
5. **Dependencies (第三方外部依赖)**：零新增第三方 npm 依赖，完全依托 Vue 3、Pinia 与 Wot Design Uni 已有组件体系。
6. **Rollback Difficulty (状态变更可逆性与回滚代价)**：回滚成本极低，仅需在 `pages.json` 卸载或降级路由入口，无数据库回滚风险。
7. **Blast Radius (爆炸半径与破坏面)**：仅影响练习交卷后的报告查看与自评重判交互，对登录、资料解析及正在作答中的练习会话无任何破坏性影响。

### 核心约束与判定
* **硬性技术制约**:
  - 单个 `.vue` 文件代码行数强制 $\le 300$ 行，超过必须抽离子组件或 SCSS 样式；
  - 零 Unicode Emoji 规范，所有状态指示一律使用低饱和色盘或矢量图标；
  - 掌握度四级离散矩阵色彩规范：精通 `#7C3AED`、良好 `#059669`、需巩固 `#B45309`、未学 `#64748B`；
  - 判题反馈色彩规范：判对 `#10B981`、判错 `#EF4444`、待确认/需巩固 `#F59E0B`；
  - 状态管理：Pinia `reportStore` 严禁直接调用 API，由页面/组合式函数发起请求后写入 Store；
  - 本地 Storage 白名单约束：诊断报告与题目全文绝对严禁进入 Storage。
* **明确非目标 (Non-Goals / Out-of-Scope)**:
  - 不包含错题本分页检索、状态筛选与错题集中消灭练习（由 ZL-136 承载）；
  - 不包含诊断报告末尾的“一键继续练习”防重合并后端出题调度（由 ZL-136 承载）；
  - 不修改后端判题匹配算法（ZL-111）、掌握度计算（ZL-112）或接口定义。
* **完成判定条件 (Definition of Done)**:
  - 诊断报告主页面在分包路由 `subpackages/report/pages/detail/index` 正常注册并挂载渲染；
  - 包含四档掌握度徽章、总分用时、薄弱知识点、逐题卡片、原文溯源抽屉、自评与重判弹窗全部就绪；
  - 针对待重新判题题目能够正常弹出自评与重判模态框并成功调用接口完成状态回显；
  - 前端全套自动化检查通过：`pnpm run lint`、`pnpm run type-check`、`pnpm run test:unit` 全部 0 error 退出；
  - 门禁合规检查 `python3 tooling/check_sdlc_integrity.py` 退出码 0。

## 6. 未决疑问与待探讨点 (Open Questions)
1. **大模型超时降级题目（pending_regrade）是否阻断薄弱知识点生成**：后端架构规范规定练习在未完全判分（`PARTIALLY_GRADED`）时阻断生成正式诊断报告，但前端仍可展示卷面已判题目结果卡片，并顶部置顶黄色待重判告警横幅，引导用户先行对主观题进行自评或等待后台异步重判完成。
2. **切片原文溯源高亮算法**：由于小程序端不宜引入复杂富文本解析库，关键词高亮可通过正则分割纯文本为 Text 节点片段（`<text :class="{ 'highlight': isMatch }">{{ part }}</text>`）轻量实现，兼顾跨端性能与防 XSS 安全。

---

## 7. 阶段准出签批 (Gate 1 Sign-off)
- [x] 场景与问题已客观复现并达成共识
- [x] 边界、非目标与约束清晰明确
- [x] 初始 Change Tier 评定合理
- **准出结论**: Accepted
- **签批人 / 日期**: TechLead / 2026-09-25 11:05
