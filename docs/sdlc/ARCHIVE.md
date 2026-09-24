# SDLC Archive (已归档成果与变更审计)

> **定位说明**：  
> 本文件是已交付任务的成果索引大表。  
> 本表仅作成果与证据索引，不重复记录任务的完整设计细节（完整过程由对应的 `docs/sdlc/<task-id>/` 目录留存）。

---

| Task | Outcome | Final Stage | Commit/PR | Verification | Completed |
|---|---|---|---|---|---|
| ZL-102 | 系统化提炼《代码管理工作介绍 V1.0》并对齐写入 AGENTS.md 与 REVIEW.md，形成 35 个原子任务 ROADMAP.md 及 LEADER_ALIGNMENT.md 对齐函 | Deploy | `working-tree` | check_sdlc_integrity 0 errors, 14 unit tests passed | 2026-09-23 |
| ZL-107 | 实现资料分块纯函数核与ChunkingResult封装，三级标点降级/120重叠/短段合并/3000截断保护全部覆盖 | Deploy | `working-tree` | 22 tests passed, 100% branch cov, 0 layer violations | 2026-09-23 |
| ZL-103 | 实现用户实体(users)、TenantModelMixin多租户基类、JWT双令牌体系与版本吊销、10维越权负向拦截测试及uv虚拟环境依赖闭环 | Deploy | `working-tree` | 63 tests passed, 100% branch cov, 0 layer violations | 2026-09-23 |
| ZL-104 | 实现资料主表/版本表/切片表(含pgvector 1024维向量与HNSW索引)/页级OCR表，完成Alembic对称迁移与多租户级联约束 | Deploy | `working-tree` | 75 tests passed, 100% branch cov, 0 layer violations | 2026-09-23 |
| ZL-105 | 实现知识点自引用树模型/切片关联模型/题目主实体(7大题型+HNSW向量查重)/质检记录表/修改痕迹审计日志表，通过双向对称迁移与多租户隔离验证 | Deploy | `working-tree` | 91 tests passed, 99.1% coverage, 0 layer violations | 2026-09-23 |
| ZL-106 | 实现练习主表/答卷作答表(题目快照解耦)/判题记录表(两阶段状态机)/掌握度表/诊断报告表/错题本表，完成Alembic对称迁移与强幂等约束 | Deploy | `working-tree` | 105 tests passed, 99.35% coverage, 0 layer violations | 2026-09-23 |
| ZL-108 | 实现 OCR 识别质量门禁纯函数计算核 verify_ocr_quality 与批次仲裁评估 | Deploy | `ZL-108` | pytest tests/unit/core/algorithms/test_ocr_quality.py 26通过 100%覆盖率, ruff/mypy/bandit/check_layers 全绿 | 2026-09-23 |
| ZL-109 | 实现知识点质检门禁算法 verify_knowledge_points 与四项一票否决决策矩阵 | Deploy | `ZL-109` | pytest 44用例通过，100%分支覆盖率，ruff/mypy/bandit/check_layers 全绿 | 2026-09-23 |
| ZL-110 | 实现题目质检与待处理过滤算法 filter_qualified_questions 与四类一票否决流水线 | Deploy | `ZL-110` | pytest 59用例通过，分支覆盖率98.7%，ruff/mypy/bandit/check_layers 全绿 | 2026-09-23 |
| ZL-111 | 实现纯函数判题阈值与匹配算法 match_and_grade_answer、客观题秒判规则核与主观题双阈值分流及4类转AI仲裁引擎 | Deploy | `ZL-111` | pytest 40用例全绿，行覆盖率100%，分支覆盖率100%，ruff/mypy/bandit/check_layers全绿 | 2026-09-23 |
| ZL-112 | 实现纯函数掌握度时间衰减与聚合算法 aggregate_mastery_scores、艾宾浩斯30天半衰期模型与四级档次映射 | Deploy | `ZL-112` | pytest 49用例全绿，行覆盖率100%，分支覆盖率100%，ruff/mypy/bandit/check_layers全绿 | 2026-09-23 |
| ZL-113 | 实现纯函数诊断规则合成算法 synthesize_diagnosis_report、四类成因优先级归因树与退步0.05判定引擎 | Deploy | `ZL-113` | pytest 42用例全绿，行覆盖率100%，分支覆盖率100%，McCabe V(G)<=7，ruff/mypy/bandit/check_layers全绿 | 2026-09-23 |
| ZL-114 | 实现 StorageProtocol 抽象、并发安全 MemoryStorageAdapter、S3StorageAdapter 与工厂函数及 30001~30003 存储异常体系 | Deploy | `ZL-114` | pytest 42用例全绿，代码覆盖率100%，ruff/mypy/bandit/check_layers全绿 | 2026-09-23 |
| ZL-115 | 实现 OCRProtocol 抽象、并发安全 FakeOCRAdapter、TencentOCRAdapter (指数退避重试与凭证脱敏)、工厂函数及 30004~30006 异常体系 | Deploy | `ZL-115` | pytest 23用例全绿，代码覆盖率98%，ruff/mypy/bandit/check_layers全绿 | 2026-09-23 |
| ZL-116 | 实现 EmbeddingProtocol 抽象、确定性 FakeEmbeddingAdapter、OpenAICompatible 生产适配器 (指数退避与掩码脱敏)、SearchProtocol 混合检索契约、PgvectorHybridSearchAdapter (租户隔离、Top20余弦粗排、BM25精排、RRF/加权打分与Top4截断) 及 30007~30010 异常体系 | Deploy | `ZL-116` | pytest 487全用例全绿，全局代码覆盖率99.29%，纯算法覆盖率100%，ruff/mypy/bandit/check_layers全绿 | 2026-09-23 |
| ZL-117 | 引入 LangGraph 作为核心 Agent 图编排底座，实现 LLMProtocol、FakeLLMAdapter (多线程安全纯内存假实现)、OpenAICompatibleLLMAdapter (指数退避与掩码脱敏)、基于 StateGraph 的生成-校验-自愈-降级 Agent 工作流引擎及 30011~30014 异常体系 | Deploy | `ZL-117` | pytest 533用例全绿，全局代码覆盖率99.36%，LLM及图引擎覆盖率100%，ruff/mypy/bandit/check_layers全绿 | 2026-09-23 |
| ZL-118 | 实现 QueueProtocol、MemoryQueueAdapter (支持同步即时与优先级排队)、RedisQueueAdapter (指数退避与掩码脱敏)、IdempotencyProtocol、MemoryIdempotencyAdapter (原子抢占与TTL快照回放)、RedisIdempotencyAdapter、工厂函数及 30015~30018 统一异常体系 | Deploy | `ZL-118` | pytest 607用例全绿，全局代码覆盖率99.09%，队列及幂等模块覆盖率98%，ruff/mypy/bandit/check_layers全绿 | 2026-09-24 |
| ZL-119 | 实现 MaterialRepository 仓储（强租户隔离阻断越权）、MaterialService 编排服务（魔数校验、MinIO隔离存储、异步任务排队、OCR质检门禁、重拍3次熔断、纯函数分块、批量向量化持久化、软删除与级联物理清理联动MinIO）及 40001~40004 业务异常体系 | Deploy | `ZL-119` | pytest 635用例全绿，全局代码覆盖率98.41%，MaterialService覆盖率96%，MaterialRepository覆盖率100%，ruff/mypy/bandit/check_layers全绿 | 2026-09-24 |
| ZL-120 | Success | Deploy | `pending-commit` | 654 tests passed, 99.06% coverage, check_layers 0 violations, 3-Pass Approved | 2026-09-24 |
| ZL-121 | Success | Deploy | `pending-commit` | 680 tests passed, 97% coverage, check_layers 0 violations, 3-Pass Approved | 2026-09-24 |
| ZL-122 | Success | Deploy | `pending-commit` | 705 tests passed, 91% service coverage, 100% algorithm/repo coverage, check_layers 0 violations, 3-Pass Approved | 2026-09-24 |
| ZL-123 | Success | Deploy | `pending-commit` | 732 tests passed, 100% repo coverage, 88% service coverage, check_layers 0 violations, 3-Pass Approved | 2026-09-24 |
| ZL-124 | Success | Deploy | `pending-commit` | 771 tests passed, 97% repo coverage, 92% service coverage, check_layers 0 violations, 3-Pass Approved | 2026-09-24 |
