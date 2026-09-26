# Intent: 掌握度时间衰减与聚合算法 (aggregate_mastery_scores)

- **任务编号**: ZL-112
- **提出人**: Dev
- **创建时间**: 2026-09-23 22:42
- **初始 Change Tier**: Tier 2
- **当前状态**: Accepted

---

## 1. 问题与现状背景 (Problem)
智练系统以知识点掌握度为核心驱动自适应练习与诊断报告生成：
- 遗忘曲线客观存在：学生做对了一道题，若长时间（数天乃至数月）未复习练习，其对该知识点的掌握度必然随时间衰减；
- 判题来源可信度不同：客观题/离线精确规则判题置信度最高（权重 1.0），AI 智能判题置信度次之（权重 0.8），用户自评与申诉重判置信度偏主观（权重 0.5）；
- 掌握度聚合必须是**确定性、可测试、零时钟漂移风险的纯函数**：若在算法内部调用 `datetime.now()`，将导致函数产生隐藏时间状态，破坏纯函数可重放性，且无法进行跨时间维度的精确单元测试（如模拟 3/7/30/300 天衰减）。
- 需要在纯函数计算核层实现基于半衰期 30 天指数衰减模型与来源加权正确率的掌握度聚合纯函数 `aggregate_mastery_scores`。

## 2. 变更性质分类 (Change Archetype - 单选)
- [ ] 局部结构精简 (Local Cleanup - 仅限模块内部冗余消除，不改数据流向与全局装配)
- [x] 单模块特性演进 (Single-Module Feature - 单一模块业务增量或修复)
- [ ] 跨领域架构重构 (Cross-Domain Rewiring - 触及应用全局装配、生命周期或跨域流向，必须升 Tier 3)

## 3. 期望达成效果 (Proposed Outcome)
1. **纯函数计算核**：实现 `backend/app/core/algorithms/mastery.py`，导出核心函数 `aggregate_mastery_scores` 及相关辅助纯函数。
2. **时间衰减模型（艾宾浩斯/半衰期）**：
   - 默认半衰期 $T_{1/2} = 30$ 天；
   - 衰减系数 $\lambda = \frac{\ln(2)}{30} \approx 0.0231049$（保留注释依据）；
   - 时间衰减因子：$\text{decay\_factor} = e^{-\lambda \times \Delta t}$，其中 $\Delta t$ 为距当前评估时间的间隔天数（支持浮点天数，负数时间差或未来时间防御性钳制为 0 天衰减因子 1.0）；
   - 算法入口必须显式传入 `current_timestamp`（或 `evaluated_at`），禁止在函数内部读取系统时间。
3. **判题来源与难度加权**：
   - 离线规则判题 (`OFFLINE_RULE`)：基础置信权重 1.0；
   - AI 判题 (`LLM_GRADING` / `AI_GRADING`)：基础置信权重 0.8；
   - 用户自评 / 申诉重判 (`SELF_ASSESSMENT` / `USER_APPEAL`)：基础置信权重 0.5；
   - 每一条作答记录的有效贡献权重为：$\text{weight} = \text{source\_weight} \times \text{decay\_factor}$；
   - 知识点最终掌握度得分为加权平均分：$\text{score} = \frac{\sum (\text{item\_score} \times \text{weight})}{\sum \text{weight}}$，保留 4 位小数并截断在 $[0.0, 1.0]$。
4. **4 级掌握度档次映射 (Mastery Level)**：
   - 无任何作答记录：返回 `UNLEARNED`（未学，score 设为 0.0）；
   - $0.0 \le \text{score} < 0.40$：`WEAK`（薄弱）；
   - $0.40 \le \text{score} < 0.70$：`DEVELOPING`（进阶中）；
   - $0.70 \le \text{score} \le 1.00$：`MASTERED`（掌握）；
   - 严格覆盖 0.40 与 0.70 临界档次判定。
5. **复杂度与门禁**：
   - McCabe 环路复杂度 $V(G) \le 8$；
   - 行覆盖率 $\ge 95\%$，分支覆盖率 100%；
   - 覆盖 3/7/30/300 天衰减测试、临界值测试、多记录聚合、空记录短路、异常防御测试。

## 4. 波及工程分面 (Affected Architectural Layers)
- [x] 核心领域与计算逻辑 (Domain & Core Business Logic)
- [ ] 外部接口与协议入口 (Public Ingress & Controllers & Protocols)
- [ ] 数据持久化与状态存储 (Database & Storage & Schemas)
- [ ] 全局装配与应用入口 (Bootstrap & Lifecycle & Service Wiring)

## 5. 边界与硬性约束 (Constraints & Boundaries)
* **硬性技术制约**:
  - 位于 `backend/app/core/algorithms/`，遵守纯函数计算核铁律，严禁导入 `fastapi`, `sqlalchemy`, `httpx`, `redis`, `boto3` 等；
  - 缩写白名单仅限 8 个（`api`, `id`, `url`, `ocr`, `llm`, `db`, `config`, `env`）；
  - 全英文命名，Google 风格 Docstring，阈值与公式常量附显式注释依据；
  - 零系统调用、零时区敏感 I/O。
* **明确非目标 (Non-Goals / Out-of-Scope)**:
  - 不负责从数据库中查询历史作答记录（该职责归 `PracticeRepository`）；
  - 不负责向数据库写入掌握度汇总快照（归 `ReportService` / `ZL-124`）；
  - 不负责根据薄弱掌握度自动推荐题目（由练习编排处理）。
* **完成判定条件 (Definition of Done)**:
  - `backend/app/core/algorithms/mastery.py` 实现完整且通过分层依赖检查；
  - `backend/tests/unit/core/algorithms/test_mastery.py` 单测全绿，分支覆盖率 100%；
  - 覆盖闲置 3/7/30/300 天衰减测试、0.40/0.70 临界判定、空记录未学档次；
  - 静态检查 `ruff`, `mypy`, `bandit` 0 报错；
  - SDLC 工件完整归档。

## 6. 未决疑问与待探讨点 (Open Questions)
- 无未决阻塞项，公式与参数在 `AGENTS.md` 和 `ROADMAP.md` 中已全面明确。

---

## 7. 阶段准出签批 (Gate 1 Sign-off)
- [x] 场景与问题已客观复现并达成共识
- [x] 边界、非目标与约束清晰明确
- [x] 初始 Change Tier 评定合理
- **准出结论**: Accepted
- **签批人 / 日期**: Dev / 2026-09-23 22:43
