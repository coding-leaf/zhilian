# Intent: 知识点抽取建树与质检重抽服务

- **任务编号**: ZL-120
- **提出人**: Dev
- **创建时间**: 2026-09-24 10:25
- **初始 Change Tier**: Tier 2
- **当前状态**: Draft / In-Review / Accepted

---

## 1. 问题与现状背景 (Problem)
系统已完成资料导入、OCR 门禁与知识切片（ZL-119），以及知识点质检纯函数算法（ZL-109: verify_knowledge_points）与大模型网关 AgentGraph 结构化调用引擎（ZL-117）。目前缺乏核心业务编排服务 `KnowledgeService` 与仓储层 `KnowledgeRepository`。
大模型单次抽取知识点时，存在片段过长导致的遗漏、幻觉产生占位词或层级退化、以及多个切片抽取出的知识点存在语义高度冗余等问题；同时缺乏对双向溯源关系（KnowledgePointSnippet）的建立、对质检门禁反馈的动态重抽与自适应降级控制（最大重抽 2 次熔断，标记低可信度），导致下游出题与诊断模块无法获取合规的知识树结构。

## 2. 变更性质分类 (Change Archetype - 单选)
- [ ] 局部结构精简 (Local Cleanup - 仅限模块内部冗余消除，不改数据流向与全局装配)
- [x] 单模块特性演进 (Single-Module Feature - 单一模块业务增量或修复)
- [ ] 跨领域架构重构 (Cross-Domain Rewiring - 触及应用全局装配、生命周期或跨域流向，必须升 Tier 3)

## 3. 期望达成效果 (Proposed Outcome)
1. 实现 `KnowledgeRepository`：封装针对 `knowledge_points` 与 `knowledge_point_snippets` 的数据库持久化与查询，所有方法强制过滤 `user_id`（多租户绝对隔离）；
2. 实现 `KnowledgeService`：
   - 编排切片批次分组（单批次切片数 <= 40）；
   - 基于 `AgentGraph` 驱动大模型执行知识点结构化抽取与 Schema 自愈；
   - 提取知识点并计算嵌入向量，基于余弦相似度（> 0.92）执行跨切片语义去重与来源片段合并；
   - 调度纯函数 `verify_knowledge_points` 执行四项门禁质检（数量区间、层级深度 2~5、命名规范、关键章节覆盖率 >= 80%）；
   - 质检未通过时携带反馈提示词触发重抽（上限 2 次），超过 2 次触发熔断并降级保存且标记 `is_low_confidence=True`；
   - 构建知识树父子拓扑与层级关系（更新 `parent_id`、`level`、`batch_id`），同时建立切片与知识点双向关联并持久化；
3. 单元测试行覆盖率 >= 85%，多租户越权拦截 100%，McCabe 环路复杂度 <= 10。

## 4. 波及工程分面 (Affected Architectural Layers)
- [x] 核心领域与计算逻辑 (Domain & Core Business Logic)
- [ ] 外部接口与协议入口 (Public Ingress & Controllers & Protocols)
- [x] 数据持久化与状态存储 (Database & Storage & Schemas)
- [ ] 全局装配与应用入口 (Bootstrap & Lifecycle & Service Wiring)

## 5. 边界与硬性约束 (Constraints & Boundaries)
* **硬性技术制约**:
  - 五层单向架构：`KnowledgeService` 属于业务服务层，是唯一开启 DB 事务的层；`KnowledgeRepository` 严禁跨层导入 FastAPI 或 Integrations；
  - 租户隔离铁律：所有仓储层方法必须强制接受 `user_id` 并作为 SQL WHERE 条件；
  - 缩写白名单仅限 8 个：`api`, `id`, `url`, `ocr`, `llm`, `db`, `config`, `env`；
  - 8 要素结构化日志脱敏红线：严禁在日志中输出资料全文、切片正文或知识点敏感长文本；
  - 单测环境全隔离：严禁真实外部网络连接，单测使用 FakeLLM 与 FakeEmbedding。
* **明确非目标 (Non-Goals / Out-of-Scope)**:
  - 本任务不包含 HTTP API 路由接口暴露（由 ZL-128 承载）；
  - 本任务不修改底层 ORM 模型定义（已由 ZL-105 完成）；
  - 本任务不包含题目生成服务（由 ZL-121 承载）。
* **完成判定条件 (Definition of Done)**:
  - `backend/app/repositories/knowledge.py` 完整实现并通过租户隔离单测；
  - `backend/app/services/knowledge.py` 完整实现批次抽取、余弦去重、质检重抽、建树持久化全流程；
  - 新增异常错误码在 `backend/app/core/errors.py` 登记并测试；
  - `pytest tests/unit/repositories/test_knowledge_repo.py tests/unit/services/test_knowledge_service.py` 100% 绿灯，服务层行覆盖率 >= 85%；
  - `tooling/check_layers.py` 与 `tooling/check_sdlc_integrity.py` 校验全部通过。

## 6. 未决疑问与待探讨点 (Open Questions)
- 质检未通过重抽时，是全量重新分批抽取还是仅重抽未达标的章节/子树？（根据 PRD FR-17，以版本为粒度全量自适应重抽，重抽轮次 0 降低单批切片数至 20，轮次 1 强化硬性约束）。
- 大模型输出知识点父子结构时，若引用不存在的 parent 名称，树拓扑如何降级容错？（默认将无法匹配父节点的孤立节点提升为根节点或归入所属章节对应的主知识点）。

---

## 7. 阶段准出签批 (Gate 1 Sign-off)
- [ ] 场景与问题已客观复现并达成共识
- [ ] 边界、非目标与约束清晰明确
- [ ] 初始 Change Tier 评定合理
- **准出结论**: Pending
- **签批人 / 日期**: [待人类签批] / 2026-09-24 10:25
