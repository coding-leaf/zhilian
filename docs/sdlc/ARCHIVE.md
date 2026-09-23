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
