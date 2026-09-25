# Intent: P0 端到端全链路闭环集成与质量门禁审计

- **任务编号**: ZL-137
- **提出人**: Dev
- **创建时间**: 2026-09-25 13:43
- **初始 Change Tier**: Tier 3
- **当前状态**: Draft / In-Review / Accepted

---

## 1. 问题与现状背景 (Problem)
目前智练平台已完成阶段 0 至阶段 6 的所有原子任务（ZL-102 至 ZL-136 及 ZL-138），后端覆盖 5 层单向架构并拥有 1013 个单元测试，前端包含 52 个测试套件与 405 个单测。然而全系统目前缺乏针对 P0 业务闭环的统一端到端集成测试套件，缺少自动化串联“用户鉴权 -> 资料上传 -> 状态轮询/重拍 -> 知识点抽取建树 -> 题目生成与质检编辑 -> 练习会话创建 -> 作答草稿防抖保存 -> 幂等交卷 -> 混合判题 -> 诊断报告生成与掌握度衰减 -> 主观题自评/申请重判 -> 错题本检索与一键继续练习”全业务链路的自动化真实物理校验。同时需要对前后端执行全量质量门禁基线审计（静态类型、分层依赖、安全扫描、测试覆盖率），确保交付质量 100% 达标。

## 2. 变更性质分类 (Change Archetype - 单选)
- [ ] 局部结构精简 (Local Cleanup - 仅限模块内部冗余消除，不改数据流向与全局装配)
- [ ] 单模块特性演进 (Single-Module Feature - 单一模块业务增量或修复)
- [x] 跨领域架构重构 (Cross-Domain Rewiring - 触及应用全局装配、生命周期或跨域流向，必须升 Tier 3)

## 3. 期望达成效果 (Proposed Outcome)
1. 建立端到端全链路集成测试套件（`backend/tests/integration/test_p0_full_chain_e2e.py`），全流程自动化串联 8 大业务节点，验证多租户数据隔离与 100% 越权阻断；
2. 自动化验证 5 块纯函数计算核在真实业务链路调用中的契约输入输出与容错机制；
3. 执行后端质量全量基线：`ruff format`、`ruff check`、`mypy app`、`bandit`、`check_layers.py`、`pytest` 覆盖率门禁（纯函数计算核 >= 90%，全局 >= 80%）；
4. 执行前端质量全量基线：`pnpm run lint`、`pnpm run type-check`、`pnpm run test:unit`、`pnpm run build:mp-weixin`；
5. 验证 SDLC 工具链与生命周期检查（`check_sdlc_integrity.py`）。

## 4. 波及工程分面 (Affected Architectural Layers)
- [x] 核心领域与计算逻辑 (Domain & Core Business Logic)
- [x] 外部接口与协议入口 (Public Ingress & Controllers & Protocols)
- [x] 数据持久化与状态存储 (Database & Storage & Schemas)
- [x] 全局装配与应用入口 (Bootstrap & Lifecycle & Service Wiring)

## 5. 边界与硬性约束 (Constraints & Boundaries)
* **硬性技术制约**: 
  - 端到端集成测试单用例执行时间毫秒级，全局测试必须在 60s 内完成；
  - 严禁自动化测试真实联网，MinIO/OCR/LLM 采用 Fake/Stub 或内存适配器；
  - 严格保持五层单向架构依赖约束，`check_layers.py` 必须 0 违规；
  - 前端单文件行数严格 <= 300 行，主包体积 <= 2MB，零 Emoji。
* **明确非目标 (Non-Goals / Out-of-Scope)**: 
  - 不引入新的外部数据库或生产中间件依赖；
  - 不修改现有已冻结的公共 API 契约和数据库 Schema；
  - 不做超出演示与 P0 需求范围的非核心功能扩展。
* **完成判定条件 (Definition of Done)**: 
  - `backend/tests/integration/test_p0_full_chain_e2e.py` 包含完整正向闭环流与负向越权攻击用例，且 100% 通过；
  - 后端 pytest 全量测试通过，全局覆盖率 >= 80%，算法核覆盖率 >= 90%；
  - 前端 lint、type-check、test:unit、build:mp-weixin 全绿；
  - `check_layers.py` 与 `check_sdlc_integrity.py` 退出码 0。

## 6. 未决疑问与待探讨点 (Open Questions)
- 暂无，所有前置 API 与组件均已完成单元测试与实现。

---

## 7. 阶段准出签批 (Gate 1 Sign-off)
- [x] 场景与问题已客观复现并达成共识
- [x] 边界、非目标与约束清晰明确
- [x] 初始 Change Tier 评定合理
- **准出结论**: Accepted
- **签批人 / 日期**: yezisama / 2026-09-25 17:15
