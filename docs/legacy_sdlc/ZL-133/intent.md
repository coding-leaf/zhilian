# Intent: 知识点层级树与出题配置页面

- **任务编号**: ZL-133
- **提出人**: TechLead
- **创建时间**: 2026-09-25 03:07
- **初始 Change Tier**: Tier 2
- **当前状态**: Accepted

---

## 1. 问题与现状背景 (Problem)
在前期迭代中：
1. **基础底座已就绪**：ZL-131 完成了微信小程序基础脚手架、Pinia 4-Store 架构、网络请求客户端与 Storage 白名单安全封装；ZL-132 实现了资料列表展示、资料上传、解析状态轮询与单页重拍抽屉；
2. **后端能力契约已完备**：ZL-128 / ZL-120 / ZL-121 提供了完整的知识树拓扑查询（`GET /api/v1/materials/{id}/knowledge-tree`）、出题生成流水线与质检门禁（`POST /api/v1/questions/generate`）、题目多条件检索（`GET /api/v1/questions`）、题目人工修改与痕迹留存（`PUT /api/v1/questions/{id}`）、题目软删除（`DELETE /api/v1/questions/{id}`）以及修改审计日志查询（`GET /api/v1/questions/{id}/edit-logs`）。

然而，当前微信小程序端存在以下关键业务缺口：
1. **缺少知识点层级树展示**：资料切片解析完成后，用户在资料详情页点击“查看考点知识树”无实际目标承载页；无法层级化浏览 2~5 级知识点大纲；
2. **缺少低可信度降级告警展示**（FR-18）：当资料因重抽超限触发熔断降级标记（`is_low_confidence=True`）时，前端缺少醒目的黄色警示提示，未能明确向用户传达“该知识结构可信度较低，已自动降级”的客观事实；
3. **缺少出题范围与参数配置能力**（FR-27）：用户无法自主勾选目标知识点集合，无法在 1~50 题量区间内灵活配置出题数量、多选筛选题型（单选、多选、判断、简答）与调整难度等级；
4. **缺少题目即时预览、行内编辑与审计展示**（FR-26）：出题生成后，用户无法即时查看题目卡片并进行行内修改（必须登记修改原因 `reason`）、软删除或重新生成，也无法查看题目修改前后的快照审计日志。

## 2. 变更性质分类 (Change Archetype - 单选)
- [ ] 局部结构精简 (Local Cleanup - 仅限模块内部冗余消除，不改数据流向与全局装配)
- [x] 单模块特性演进 (Single-Module Feature - 微信小程序资料分包核心页面与组件增量演进)
- [ ] 跨领域架构重构 (Cross-Domain Rewiring - 触及应用全局装配、生命周期或跨域流向，必须升 Tier 3)

## 3. 期望达成效果 (Proposed Outcome)
1. **注册分包主路由**：在 `miniprogram/src/pages.json` 中配置 `subpackages/material/pages/knowledge-tree/index`，保证主包体积不受影响；
2. **知识点层级树展示与多选联动 (FR-14, FR-18)**：
   - 采用递归树节点组件（`KnowledgeTreeNode.vue`），支持 2~5 级节点展开/折叠；
   - 节点展示规范考点名称、层级标签及概念简述；
   - 严格落实 FR-18 低可信度黄色告警提示（横幅与节点徽章），采用 DESIGN.md 收敛的警告黄色（`--wot-color-warning: #F59E0B`、背景 `#FFFBEB`、边框 `#FDE68A`）；
   - 支持考点复选勾选联动（全选、反选、已选计数统计）；
   - 严格遵循 FR-14：界面绝对不提供知识点人工新增、改名、删除入口。
3. **出题配置抽屉组合面板 (FR-27)**：
   - 封装 `QuestionConfigDrawer.vue` 底部弹窗，集成 Wot Design Uni 规范组件；
   - 题数步进器严格限定在 1 至 50 题（默认 5 题，边界非法值即刻防御并提示）；
   - 题型胶囊多选切换（单选 `single_choice`、多选 `multiple_choice`、判断 `true_false`、简答 `short_answer`）；
   - 难度 1~5 级与出题调用集成，显示自然文案（“正在智能定制题目...”），完成出题后平滑切换到题目预览区。
4. **题目管理、行内编辑与修改审计 (FR-26)**：
   - 列表展示生成题目卡片（题干、题型标签、选项、参考答案、解析、难度）；
   - 题目行内编辑抽屉（`QuestionEditDrawer.vue`）：支持修改题干、选项、答案与解析，强制必填修改原因（`reason`，$\le 255$ 字符）；
   - 题目软删除二次确认弹窗；
   - 修改痕迹审计抽屉（`QuestionAuditDrawer.vue`）：展示该题目所有修改历史版本的时间线、操作动作、变更字段标签与前后快照对比。
5. **规范与质量硬性指标**：
   - 严格落实 DESIGN.md：零 Emoji 原则、低饱和色盘、Squircle 圆角、无裸 Hex；
   - **单组件文件行数严格 $\le 300$ 行**；
   - Pinia 4-Store 铁律：严禁 Store 内直接发起 API 请求；
   - Storage 白名单铁律：严禁向本地 Storage 写入知识点或题目全文；
   - 单元测试与类型门禁：覆盖核心交互，`pnpm run lint`、`pnpm run type-check`、`pnpm run test:unit` 毫秒级通过。

## 4. 波及工程分面 (Affected Architectural Layers)
- [ ] 核心领域与计算逻辑 (Domain & Core Business Logic)
- [x] 外部接口与协议入口 (Public Ingress & Controllers & Protocols) - 前端 API 客户端与 DTO 契约补齐
- [ ] 数据持久化与状态存储 (Database & Storage & Schemas)
- [x] 全局装配与应用入口 (Bootstrap & Lifecycle & Service Wiring) - pages.json 路由与 Pinia Store 状态流转

## 5. 边界与硬性约束 (Constraints & Boundaries)
* **硬性技术制约**:
  - 单 `.vue` 文件代码行数强制 $\le 300$ 行，超限必须拆分子组件；
  - 页面置于 `subpackages/material/` 分包中，主包体积严禁膨胀；
  - 严禁向本地持久化 Storage 写入任何知识点大纲或题目数据；
  - 严格遵守 8 个缩写白名单与全英文标识符，零 Unicode Emoji；
  - 严格拦截非法题量输入（0 或 >50 时强校验阻断提交）；
  - 知识点本期无人工增删改入口（只读树拓扑）。
* **明确非目标 (Non-Goals / Out-of-Scope)**:
  - 不包含练习在线连续作答、倒计时与交卷流转（由 ZL-134 专职承载）；
  - 不包含判题结果与学情诊断报告展示（由 ZL-135 专职承载）；
  - 不修改后端 Python 代码或数据库 Schema。
* **完成判定条件 (Definition of Done)**:
  - `subpackages/material/pages/knowledge-tree/index.vue` 及 4 个解耦子组件全部创建；
  - 知识点 2~5 级树展示、展开折叠、低可信度黄色告警、全选/反选正常运行；
  - 出题抽屉 1~50 题量步进器与题型筛选正常工作，能正确调用后端出题接口并返回结果；
  - 题目行内编辑（含原因必填）与修改痕迹审计日志正常展示；
  - 单元测试覆盖新增组件，`pnpm run lint && pnpm run type-check && pnpm run test:unit` 全部通过。

## 6. 未决疑问与待探讨点 (Open Questions)
- 知识树默认展开层级：推荐默认展开 1~2 级根节点与直接子节点，3 级及以下默认折叠，防止超长资料节点导致首次渲染白屏或卡顿。

---

## 7. 阶段准出签批 (Gate 1 Sign-off)
- [x] 场景与问题已客观复现并达成共识
- [x] 边界、非目标与约束清晰明确
- [x] 初始 Change Tier 评定合理
- **准出结论**: Accepted
- **签批人 / 日期**: TechLead (人类授权模式) / 2026-09-25 03:07
