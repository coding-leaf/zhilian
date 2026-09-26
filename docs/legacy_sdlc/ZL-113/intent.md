# Intent: 诊断规则合成算法 (synthesize_diagnosis_report)

- **任务编号**: ZL-113
- **提出人**: Dev
- **创建时间**: 2026-09-23 23:02
- **初始 Change Tier**: Tier 2
- **当前状态**: Accepted

---

## 1. 问题与现状背景 (Problem)
智练系统完成一次自适应练习后，需要为用户实时生成客观、确定且具备闭环指导意义的学情诊断报告（FR-50, FR-51, FR-53）：
- **薄弱点必须有据可查**：传统诊断报告经常泛泛罗列薄弱点，但未关联具体错题，导致说服力不足；根据规范，提取的每一个薄弱知识点**必须强关联具体错题证据**（错题题干摘要与错题标识）；
- **退步判定必须具备量化界限**：知识点掌握度随时间衰减或因新错题下降，必须定义明确的退步门槛（$\Delta \text{score} \ge 0.05$ 判定为退步知识点，产生预警标签）；
- **成因归因必须可解释**：需要针对作答表现自动匹配四类规则成因（概念盲区、计算/细节失误、易混淆概念、长期未复习衰减），并生成可执行的复习与强化练习建议；
- **算法纯函数化**：为了支撑前端秒级响应与单元测试 100% 覆盖，诊断报告的薄弱提取、退步研判与成因归因必须作为纯函数核实现，零外部 I/O 与零时钟隐式依赖。

## 2. 变更性质分类 (Change Archetype - 单选)
- [ ] 局部结构精简 (Local Cleanup - 仅限模块内部冗余消除，不改数据流向与全局装配)
- [x] 单模块特性演进 (Single-Module Feature - 单一模块业务增量或修复)
- [ ] 跨领域架构重构 (Cross-Domain Rewiring - 触及应用全局装配、生命周期或跨域流向，必须升 Tier 3)

## 3. 期望达成效果 (Proposed Outcome)
1. **纯函数计算核**：实现 `backend/app/core/algorithms/diagnosis.py`，导出核心函数 `synthesize_diagnosis_report` 及相关辅助纯函数。
2. **薄弱知识点提取与错题强关联** (FR-50)：
   - 筛选掌握度处于 `WEAK`（$<0.40$）或 `DEVELOPING`（$<0.70$ 且本次产生错题）的知识点；
   - 提取的每个薄弱项必须强绑定对应的错题列表（题目 ID、题干摘要、用户错误答案/要点缺失）；
   - 若某知识点虽得分低但本次练习中无对应错题数据，必须显式标记证据来源（如历史衰减）。
3. **退步知识点判定与量化** (FR-51)：
   - 接收历史掌握度基线快照与当前计算掌握度；
   - 当 $\Delta = \text{previous\_score} - \text{current\_score} \ge 0.05$ 时，严格判定为“退步知识点”（`is_regressed=True`，记录降幅与严重等级）；
   - 当 $\Delta < 0.05$ 或分数上升时，判定为平稳或进步。
4. **四类成因规则匹配与建议生成** (FR-53)：
   - **成因 1: 概念盲区 (CONCEPT_BLIND_SPOT)**：掌握度未学或极低（$<0.30$），且主客观题均答错；
   - **成因 2: 细节/粗心失误 (CARELESS_MISTAKE)**：历史掌握度较高（$\ge 0.70$），本次仅个别细节错误或部分填空错；
   - **成因 3: 概念易混淆 (CONCEPT_CONFUSION)**：在成对/相似概念题中反复选错特定干扰项或否定词反转；
   - **成因 4: 长期未练遗忘衰减 (TIME_DECAY_FORGOTTEN)**：作答正确但距上次练习超过 30 天导致衰减因子 $<0.50$；
   - 根据成因自动匹配清晰的结构化学习与练习建议。
5. **复杂度与门禁**：
   - McCabe 环路复杂度 $V(G) \le 8$；
   - 行覆盖率 $\ge 95\%$，分支覆盖率 100%；
   - 覆盖 4 类成因用例、退步边界 0.05（0.0499 平稳，0.0500 退步）、空错题防御、全掌握全优报告生成。

## 4. 波及工程分面 (Affected Architectural Layers)
- [x] 核心领域与计算逻辑 (Domain & Core Business Logic)
- [ ] 外部接口与协议入口 (Public Ingress & Controllers & Protocols)
- [ ] 数据持久化与状态存储 (Database & Storage & Schemas)
- [ ] 全局装配与应用入口 (Bootstrap & Lifecycle & Service Wiring)

## 5. 边界与硬性约束 (Constraints & Boundaries)
* **硬性技术制约**:
  - 位于 `backend/app/core/algorithms/`，遵守纯函数计算核铁律，严禁导入 `fastapi`, `sqlalchemy`, `httpx`, `redis`, `boto3` 等；
  - 缩写白名单仅限 8 个（`api`, `id`, `url`, `ocr`, `llm`, `db`, `config`, `env`）；
  - 全英文命名，Google 风格 Docstring，阈值常量附注释依据；
  - 纯内存数据结构流转，零外部 I/O。
* **明确非目标 (Non-Goals / Out-of-Scope)**:
  - 不负责调用数据库读取历史报告记录或错题表；
  - 不负责直接向客户端返回 HTTP 响应（由 API 路由完成）；
  - 不负责向大模型请求生成长文本段落总结（大模型润色属于服务编排可选流）。
* **完成判定条件 (Definition of Done)**:
  - `backend/app/core/algorithms/diagnosis.py` 实现完整且通过分层依赖检查；
  - `backend/tests/unit/core/algorithms/test_diagnosis.py` 覆盖 4 类成因与退步边界，分支覆盖率 100%；
  - 静态检查 `ruff`, `mypy`, `bandit` 0 报错；
  - SDLC 工件完整归档。

## 6. 未决疑问与待探讨点 (Open Questions)
- 无未决阻塞项，退步门槛 0.05 与成因规则在 `AGENTS.md` 和 `ROADMAP.md` 中已全面明确。

---

## 7. 阶段准出签批 (Gate 1 Sign-off)
- [x] 场景与问题已客观复现并达成共识
- [x] 边界、非目标与约束清晰明确
- [x] 初始 Change Tier 评定合理
- **准出结论**: Accepted
- **签批人 / 日期**: Dev / 2026-09-23 23:03
