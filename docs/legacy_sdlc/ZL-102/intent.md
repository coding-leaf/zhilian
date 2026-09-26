# Intent: 代码管理规范提炼与工程协议对齐

- **任务编号**: ZL-102
- **提出人**: Dev
- **创建时间**: 2026-09-23 18:02
- **初始 Change Tier**: Tier 2
- **当前状态**: Draft / In-Review / Accepted

---

## 1. 问题与现状背景 (Problem)
项目已形成基线规格文档《智练自主学习平台_代码管理工作介绍_V1.0.md》，其中系统定义了团队在代码规范、源代码管理、测试工具、持续集成与缺陷跟踪五个维度的工程约定。
然而，当前工程仓库中虽然已建立基础 SDLC 任务生命周期脚手架与基础规范，但尚未系统性地将《代码管理工作介绍 V1.0》中明确约定的关键工程约束提炼并对齐到 AI-Native 研发体系中：
1. **代码规范与架构约束待对齐**：五层架构依赖方向（API -> Services -> Repositories、Algorithms 纯函数计算核隔离、Integrations 协议适配）及其自动化规则校验（如 `check_layers.py`）、命名白名单、统一业务异常 `AppError`（五位错误码分类）与日志脱敏标准尚未形成落地执行契约；
2. **分支模型与评审机制待落地**：精简 Git Flow（main/develop/feature/release/hotfix）、ZL-xxx 提交规范、MR 模板及七项影响面自查高风险判定规则、3-Pass 代码评审与 5 条 Nit 上限、CODEOWNERS 代码所有权等机制需与现有工程协议和分支门禁统一；
3. **测试分层与门禁阈值待对齐**：五大必测纯函数计算核（资料分块、知识点质检、题目质检、判题阈值匹配、掌握度计算）的覆盖率要求（行覆盖 >= 95% / 分支覆盖 >= 90% / 环路复杂度上限）、分模块覆盖率硬门槛（`check_coverage.py`）、容器化集成测试隔离策略需固化；
4. **CI/CD 与缺陷跟踪规范待衔接**：GitHub Actions 五阶段流水线、pre-commit 本地前置检查、S1-S4 缺陷分级与时限响应、发布前 S1/S2 缺陷清零门槛等需形成统一的技术方案与实施计划输入。

因此，亟需通过本任务系统性提炼代码管理规范，对齐工程协议，明确各模块与工具链的落地实施契约。

## 2. 变更性质分类 (Change Archetype - 单选)
- [ ] 局部结构精简 (Local Cleanup - 仅限模块内部冗余消除，不改数据流向与全局装配)
- [x] 单模块特性演进 (Single-Module Feature - 单一模块业务增量或修复)
- [ ] 跨领域架构重构 (Cross-Domain Rewiring - 触及应用全局装配、生命周期或跨域流向，必须升 Tier 3)

## 3. 期望达成效果 (Proposed Outcome)
1. **全面提炼规范核心要素**：系统提炼《代码管理工作介绍 V1.0》全篇规范，形成结构化、无歧义的工程约定，作为后续 Design（技术契约）与 Build（工程实施）的基准输入；
2. **对齐工程协议与分层边界**：确立五层架构依赖规则、命名约定、统一错误码分段、日志脱敏范围、前端代码拆分与性能约束（setData 合并、2MB 主包体积限制等）；
3. **固化质量门禁与测试标准**：明确五大纯函数计算核覆盖率标准、全局与关键模块覆盖率门槛（全局行覆盖 >= 80% / 分支覆盖 >= 70%、algorithms >= 95%、services >= 85% 等）、代码评审 3 维独立扫描与 Nit 上限（<= 5 条）；
4. **明确持续集成与缺陷生命周期**：固化 GitHub Actions 流水线阶段、pre-commit 本地钩子检查项、S1-S4 缺陷响应/修复时限与发布阻断门槛；
5. **顺利准入 SDLC 下一阶段**：完成意图澄清与边界界定，通过阶段准出检查，为进入 Design 阶段输出完整的架构设计规格（spec.md）打下扎实基础。

## 4. 波及工程分面 (Affected Architectural Layers)
- [x] 核心领域与计算逻辑 (Domain & Core Business Logic)
- [x] 外部接口与协议入口 (Public Ingress & Controllers & Protocols)
- [ ] 数据持久化与状态存储 (Database & Storage & Schemas)
- [ ] 全局装配与应用入口 (Bootstrap & Lifecycle & Service Wiring)

## 5. 边界与硬性约束 (Constraints & Boundaries)
* **硬性技术制约**:
  - 必须严格以《智练自主学习平台_代码管理工作介绍_V1.0.md》和《智练自主学习平台_概要设计说明书_V1.0.md》为事实依据，严禁随意篡改既定技术选型、指标阈值或自造非白名单缩写；
  - 严格保持与项目全局工程协议（AGENTS.md）一致，坚守 AI-Native SDLC 工件生命周期与防偷跑约束；
  - 规范中的所有门槛和指标必须具备可落地性与客观可验证性（具备明确命令与退出码判定）。
* **明确非目标 (Non-Goals / Out-of-Scope)**:
  - 本任务聚焦于代码管理规范与工程协议的提炼与落地准备，不涉及具体业务功能业务代码（如题目生成、判题执行等业务逻辑）的开发；
  - 不涉及超出项目一期范围的非目标系统（如教务对接、班级管理、在线授课、支付结算、社区及内容审核后台）；
  - 本阶段不提前创建 `spec.md` 或 `plan.md`，严格遵循防跳步铁律，需待人类签批 Gate 1 后推进。
* **完成判定条件 (Definition of Done)**:
  - 意图工件 `intent.md` 完整清晰，无任何未替换的占位符；
  - Gate 1 保持未勾选/待人类签批状态；
  - 运行 `python3 tooling/check_sdlc_integrity.py` 退出码为 0，门禁合规检查通过；
  - 运行 `python3 -m unittest discover tests` 退出码为 0，所有单元测试通过。

## 6. 未决疑问与待探讨点 (Open Questions)
- 待在 Design 阶段探讨 `tooling/check_layers.py` 与 `tooling/check_coverage.py` 脚本的具体落地实现与集成到 `check_sdlc_integrity.py` 的协同机制；
- 探讨 pre-commit 钩子在本地环境与跨平台（Windows / Linux / macOS）环境中的安装与无缝执行体验。

---

## 7. 阶段准出签批 (Gate 1 Sign-off)
- [ ] 场景与问题已客观复现并达成共识
- [ ] 边界、非目标与约束清晰明确
- [ ] 初始 Change Tier 评定合理
- **准出结论**: Pending
- **签批人 / 日期**: [待人类签批] / 2026-09-23 18:02
