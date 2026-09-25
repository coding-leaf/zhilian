# Intent: 真实基础设施容器化编排与分层提供商注册中心

- **任务编号**: ZL-139
- **提出人**: Dev
- **创建时间**: 2026-09-25 20:45
- **初始 Change Tier**: Tier 3
- **当前状态**: In-Review

---

## 1. 问题与现状背景 (Problem)
目前智练后端 `backend/app/main.py` 的依赖装配写死了 SQLite 纯内存库与内存/假适配器 (`MemoryStorageAdapter`, `FakeOCRAdapter`, `FakeLLMAdapter`, `FakeEmbeddingAdapter`, `MemoryQueueAdapter`, `FakeSearchAdapter`)。
虽然单元测试与 P0 端到端测试已全部自闭环，但平台需要过渡到真实基础设施运行。
同时，用户明确要求：**将外部 AI 与 OCR 服务彻底抽象为统一兼容层，严禁在业务层零散使用 `os.environ`**，并需配合容器化基础设施提供可一键拉起并验证的真实拓扑。

## 2. 变更性质分类 (Change Archetype - 单选)
- [ ] 局部结构精简 (Local Cleanup - 仅限模块内部冗余消除，不改数据流向与全局装配)
- [ ] 单模块特性演进 (Single-Module Feature - 单一模块业务增量或修复)
- [x] 跨领域架构重构 (Cross-Domain Rewiring - 触及应用全局装配、生命周期或跨域流向，必须升 Tier 3)

## 3. 期望达成效果 (Proposed Outcome)
1. **基础设施编排**：在 `deploy/docker-compose.yml` 中编排标准 PostgreSQL 16 (含 pgvector 扩展)、Redis 7 与 MinIO 容器服务；
2. **适配器统一兼容层与注册中心**：在 `backend/app/integrations/container.py` 中实现强类型 `ProviderRegistry`，集中管理与装配 Protocol 实例（LLM, OCR, Storage, Queue, Idempotency, Search），彻底解耦环境变量；
3. **应用装配容器**：在 `backend/app/container.py` 中实现 `AppContainer`，聚合数据库引擎连接池与领域服务编排，严格遵循 `AGENTS.md` 架构单向依赖；
4. **生命周期接管**：改造 `backend/app/main.py`，使用现代 FastAPI `lifespan` 机制托管 `AppContainer`，掌控连接池与异步客户端的启动预热与优雅关闭；
5. **迁移与联调验证**：确保 Alembic 标准迁移顺利执行；补充真实容器基础设施连通性集成测试。

## 4. 波及工程分面 (Affected Architectural Layers)
- [ ] 核心领域与计算逻辑 (Domain & Core Business Logic)
- [ ] 外部接口与协议入口 (Public Ingress & Controllers & Protocols)
- [x] 数据持久化与状态存储 (Database & Storage & Schemas)
- [x] 全局装配与应用入口 (Bootstrap & Lifecycle & Service Wiring)

## 5. 边界与硬性约束 (Constraints & Boundaries)
* **硬性技术制约**:
  - 严格遵循 `AGENTS.md` 五层单向依赖架构，`tooling/check_layers.py` 必须 100% 通过；
  - 严禁在 `app/core` 中反向导入业务服务；
  - 外部服务配置一律收敛于强类型配置契约，严禁在业务代码中散落 `os.environ`；
  - 数据库迁移必须通过 Alembic 版本化脚本保持幂等。
* **明确非目标 (Non-Goals / Out-of-Scope)**:
  - 本任务不修改既有 5 块核心纯函数计算核算法逻辑；
  - 本任务不修改现存小程序前端接口与业务状态；
  - 本任务不修改已归档的 P0 领域业务模型字段与契约。
* **完成判定条件 (Definition of Done)**:
  - `docker-compose.yml` 文件语法正确，包含 PG16(pgvector)、Redis 7、MinIO 健康检查；
  - `ProviderRegistry` 与 `AppContainer` 实现并通过单元/集成测试；
  - `backend/app/main.py` 接入 Lifespan 且原有测试与接口兼容性 100% 保持；
  - SDLC 全部门禁与架构分层依赖检查 100% 通过。

## 6. 未决疑问与待探讨点 (Open Questions)
- 无（已在 Grill-Me 环节全部分支对齐闭环）。

---

## 7. 阶段准出签批 (Gate 1 Sign-off)
- [x] 场景与问题已客观复现并达成共识
- [x] 边界、非目标与约束清晰明确
- [x] 初始 Change Tier 评定合理
- **准出结论**: Accepted
- **签批人 / 日期**: User / 2026-09-25 20:50
