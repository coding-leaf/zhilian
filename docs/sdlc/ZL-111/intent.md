# Intent: 判题阈值与匹配算法 (match_and_grade_answer)

- **任务编号**: ZL-111
- **提出人**: Dev
- **创建时间**: 2026-09-23 22:11
- **初始 Change Tier**: Tier 2
- **当前状态**: Accepted

---

## 1. 问题与现状背景 (Problem)
智练系统支持多种题型练习（单选、多选、判断、填空、主观问答题）。在作答提交时：
- 客观题（选择题、判断题、填空题）具有确定或半确定的标准答案，若全部送往大语言模型（LLM）进行判分，不仅响应延迟高达数秒、消耗高额 API 成本，还会受到网络波动与幻觉影响；
- 主观问答题若单纯依赖字符比对或固定规则，无法有效识别语义等价表达，但全量调用 LLM 同样成本昂贵。
- 此外，主观题作答中存在“否定词反转”（例如用户作答加上“不”、“并非”、“没有”，表面字符高度重合但语义完全相反）、要点遗漏、歧义等复杂情况。
- 需要在纯函数计算核层实现一套高性能、确定性的离线判题与双阈值语义分流算法核 `match_and_grade_answer`，支撑客观题极速精准判定与主观题分流（双阈值判定：$\ge 0.82$ 离线判对，$\le 0.45$ 离线判错，中间区间转 AI 评判）。

## 2. 变更性质分类 (Change Archetype - 单选)
- [ ] 局部结构精简 (Local Cleanup - 仅限模块内部冗余消除，不改数据流向与全局装配)
- [x] 单模块特性演进 (Single-Module Feature - 单一模块业务增量或修复)
- [ ] 跨领域架构重构 (Cross-Domain Rewiring - 触及应用全局装配、生命周期或跨域流向，必须升 Tier 3)

## 3. 期望达成效果 (Proposed Outcome)
1. **纯函数计算核**：实现 `backend/app/core/algorithms/grading.py`，导出核心函数 `match_and_grade_answer` 及相关辅助纯函数。
2. **客观题规范化与离线精准判题**：
   - 单选题、多选题：选项字母、空格、标点及大小写标准化，精准比对；
   - 判断题：支持多种中英文真假表达（T/F, True/False, 正确/错误, 对/错, √/×, 1/0）映射归一化比对；
   - 填空题：支持前后空白修剪、标点符号归一化、全半角转换、同义容差比对；
   - 客观题直接得出明确得分（`is_correct` 为 `True` 或 `False`，分数 1.0 或 0.0，`grading_method="OFFLINE_RULE"`）。
3. **主观题双阈值分流与要点语义合成**：
   - 结合参考答案与得分要点（Key Points / Scoring Criteria）提取关键词与语义覆盖度；
   - 支持传入可选的作答向量/参考答案向量计算余弦相似度；若无向量则降级为加权 Jaccard + 核心实词覆盖率语义分值；
   - **双阈值规则**：
     - 综合语义相似度 $\ge 0.82$：离线判对（满分或高分判定，`grading_method="OFFLINE_RULE"`）；
     - 综合语义相似度 $\le 0.45$：离线判错（0分判定，`grading_method="OFFLINE_RULE"`）；
     - 落在 $(0.45, 0.82)$ 之间：转大模型智能判题（`requires_llm=True`，`grading_method="PENDING_LLM"`）。
4. **4 类转 AI 条件决策表覆盖**：
   - 综合相似度处于中间过渡区间 $(0.45, 0.82)$；
   - 触发“否定词反转”风险（作答与参考答案在否定词维度存在相反倾向，如含“不/非/无/未/没有”等关键否定修饰词导致极性反转）；
   - 主观题包含多个独立得分要点且部分覆盖冲突；
   - 关键概念实词缺失但表面字符重叠度高。
5. **复杂度与质量门禁**：
   - 判题匹配决策函数 McCabe 环路复杂度 $V(G) \le 10$；
   - 纯函数无网络、无 ORM、无外部 I/O；
   - 判定覆盖率 100%，分支覆盖率 $\ge 90\%$，通过成对否定词反转测试（仅否定词不同时得分方向严格相反或安全转 AI）。

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
  - 单用例毫秒级执行，网络阻断环境下运行。
* **明确非目标 (Non-Goals / Out-of-Scope)**:
  - 不负责调用实际的 LLM API（该能力属于 `GradingService` 和 `LLMProvider`，由 `ZL-123` 实现）；
  - 不负责数据库作答记录的持久化或事务提交；
  - 不负责生成用户报告或更新知识点掌握度（掌握度由 `ZL-112` 计算）。
* **完成判定条件 (Definition of Done)**:
  - `backend/app/core/algorithms/grading.py` 实现完整且通过分层依赖检查；
  - `backend/tests/unit/core/algorithms/test_grading.py` 单测全绿，分支覆盖率 $\ge 90\%$；
  - 包含边界值测试（恰等于 0.45、0.82、在区间内等）、4 类转 AI 决策表全覆盖、成对否定词反转测试；
  - 静态检查 `ruff`, `mypy`, `bandit` 0 报错；
  - SDLC 工件完整归档。

## 6. 未决疑问与待探讨点 (Open Questions)
- 无未决阻塞项，阈值与判分规则已在 `AGENTS.md` 和 `ROADMAP.md` 中严格规定。

---

## 7. 阶段准出签批 (Gate 1 Sign-off)
- [x] 场景与问题已客观复现并达成共识
- [x] 边界、非目标与约束清晰明确
- [x] 初始 Change Tier 评定合理
- **准出结论**: Accepted
- **签批人 / 日期**: Dev / 2026-09-23 22:12
