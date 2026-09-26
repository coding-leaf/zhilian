# Intent: 异步任务队列与幂等拦截中间件

- **任务编号**: ZL-118
- **提出人**: Dev
- **创建时间**: 2026-09-24 08:19
- **初始 Change Tier**: Tier 2
- **当前状态**: Draft / In-Review / Accepted

---

## 1. 问题与现状背景 (Problem)
智练自主学习平台在资料解析下发 (FR-04)、练习交卷结算 (FR-35) 以及继续练习防重 (FR-58) 等高频业务场景中，面临两大基础设施痛点：
1. **耗时异步任务缺乏统一轻量调度抽象**:
   资料 OCR 抽取、LLM 知识建树与题目生成等流水线耗时达到 10s~60s 级别，若在 HTTP 请求生命周期内同步阻塞，会导致连接超时、工作线程耗尽及用户端阻塞。当前缺少标准异步队列协议（`QueueProtocol`）与任务状态跟踪机制（`TaskResult`），且单元测试无法在 0 外部依赖与零网络环境下验证异步任务的生命周期、状态机与重试流程。
2. **写操作接口缺乏原子并发幂等防护**:
   移动端弱网环境下的网络抖动、用户快速连击、自动重试机制极易导致交卷请求、练习创建或资料下发出现重复提交与并发穿透。缺少统一基于 `Idempotency-Key` (UUIDv4) 的原子锁拦截、防重排队与安全结果回放机制（NFR-08），存在重复创建练习、重复计算掌握度以及多线程并发数据错乱风险。

## 2. 变更性质分类 (Change Archetype - 单选)
- [ ] 局部结构精简 (Local Cleanup - 仅限模块内部冗余消除，不改数据流向与全局装配)
- [x] 单模块特性演进 (Single-Module Feature - 单一模块业务增量或修复)
- [ ] 跨领域架构重构 (Cross-Domain Rewiring - 触及应用全局装配、生命周期或跨域流向，必须升 Tier 3)

## 3. 期望达成效果 (Proposed Outcome)
1. **标准化统一异步任务队列抽象与双模适配 (`app/integrations/queue`)**:
   - 定义不可变 `TaskMessage`、`TaskResult` 契约及 `@runtime_checkable class QueueProtocol(Protocol)`；
   - 提供 `MemoryQueueAdapter`: 支持纯内存零网络单测环境，提供即时同步执行模式 (`immediate_mode=True`) 与线程安全队列模式，支持单测中的延迟注入与故障注入，严格强制 `user_id` 多租户边界隔离；
   - 提供 `RedisQueueAdapter`: 面向生产提供基于 Redis 的原子入队、出队、状态追踪与生命周期管理，支持连接超时与退避降级，敏感配置绝密脱敏；
   - 提供 `create_queue_adapter` 统一工厂函数。
2. **分布式原子幂等拦截适配层 (`app/integrations/idempotency`)**:
   - 定义 `@runtime_checkable class IdempotencyProtocol(Protocol)`，规范 `acquire_lock`、`set_result`、`get_result`、`release_lock` 标准动作；
   - 提供 `MemoryIdempotencyAdapter`: 并发安全 (`threading.Lock`) 内存实现，精准模拟锁原子抢占、状态持久化与 TTL 自动失效，供自动化单测闭环；
   - 提供 `RedisIdempotencyAdapter`: 基于 Redis `SET NX EX` 实现分布式抢占锁，存储响应体快照与安全回放；
   - 提供 `create_idempotency_adapter` 统一工厂函数。
3. **统一异常体系扩展 (`app/core/errors.py`)**:
   - 扩充 30015~30018 标准错误码（`QueueError`, `QueueTimeoutError`, `IdempotencyConflictError`, `IdempotencyKeyInvalidError`），并维护导出列表字典序。
4. **质量门禁与单测 100% 覆盖**:
   - 保证单元测试 0 网络外联，适配器代码行覆盖率与分支覆盖率达标，McCabe 复杂度合规，无跨层导入。

## 4. 波及工程分面 (Affected Architectural Layers)
- [x] 核心领域与计算逻辑 (Domain & Core Business Logic)
- [x] 外部接口与协议入口 (Public Ingress & Controllers & Protocols)
- [ ] 数据持久化与状态存储 (Database & Storage & Schemas)
- [ ] 全局装配与应用入口 (Bootstrap & Lifecycle & Service Wiring)

## 5. 边界与硬性约束 (Constraints & Boundaries)
* **硬性技术制约**:
  - 严格遵循 `AGENTS.md` 架构单向依赖：`app/integrations` 严禁反向导入 `app/services`，严禁导入 `app/repositories`；
  - 缩写白名单仅限 8 个（`api`, `id`, `url`, `ocr`, `llm`, `db`, `config`, `env`），严禁自造简写；
  - 纯函数计算核严禁导入外部网络库；
  - 单元测试严禁真实联网（`conftest.py` 全局网络阻断），外部依赖在单测中必须完全基于 Memory Fake 验证；
  - 绝密脱敏红线：`__repr__` 严禁暴露 Redis 密码凭据或业务敏感载荷。
* **明确非目标 (Non-Goals / Out-of-Scope)**:
  - 本任务不引入 Celery、RabbitMQ 或 Kafka 等重型外部中间件；
  - 本任务不包含具体业务服务（如 `MaterialService`, `PracticeService`）的全面异步重构（由后续具体业务任务挂载调用）；
  - 本任务不修改现有的数据库表结构（Alembic Migration）。
* **完成判定条件 (Definition of Done)**:
  - `backend/app/core/errors.py` 成功增设 30015~30018 异常并完全通过单元测试；
  - `backend/app/integrations/queue/` 与 `backend/app/integrations/idempotency/` 实现完整且通过静态分层依赖检查；
  - 单测套件覆盖率满足：适配层覆盖率 $\ge 90\%$，并发竞争测试 100% 绿灯；
  - `tooling/check_layers.py --root backend/app` 检查 0 违规；
  - `tooling/check_sdlc_integrity.py` 检查通过。

## 6. 未决疑问与待探讨点 (Open Questions)
- 幂等拦截组件在 FastAPI 中未来是否提供专用 Dependency / Middleware 封装，或由上层 Service 显式编排？（设计决策：在适配层提供纯适配器，同时在 spec 中明确 Service 推荐调用范式，确保不破坏分层架构）。

---

## 7. 阶段准出签批 (Gate 1 Sign-off)
- [ ] 场景与问题已客观复现并达成共识
- [ ] 边界、非目标与约束清晰明确
- [ ] 初始 Change Tier 评定合理
- **准出结论**: Pending
- **签批人 / 日期**: [待人类签批] / 2026-09-24 08:19
