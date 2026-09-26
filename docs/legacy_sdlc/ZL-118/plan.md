# Plan: 异步任务队列与幂等拦截中间件 - 实施计划

- **关联 Spec**: ZL-118
- **实施执行人 / Agent**: Dev
- **当前状态**: Draft / Approved / In-Execution / Completed

---

## 1. 变更文件清单 (Files that change)

### 1.1 修改文件 (Modify)
* `backend/app/core/errors.py`:
  - 扩充 30015~30018 统一业务异常：
    - `QueueError` (`error_code=30015`, `status_code=500`): 异步任务队列服务异常
    - `QueueTimeoutError` (`error_code=30016`, `status_code=504`): 异步任务调度响应超时
    - `IdempotencyConflictError` (`error_code=30017`, `status_code=409`): 请求正在并发处理中，请勿重复提交
    - `IdempotencyKeyInvalidError` (`error_code=30018`, `status_code=400`): 幂等键格式不合法
  - 维护文件底部的 `__all__` 导出列表（保持严格 ASCII 字典序排序）。

### 1.2 新增文件 (New)
* **异步任务队列适配包 (`backend/app/integrations/queue/`)**:
  - `backend/app/integrations/queue/__init__.py`: 模块入口，规范导出 `TaskMessage`, `TaskResult`, `QueueProtocol`, `MemoryQueueAdapter`, `RedisQueueAdapter`, `create_queue_adapter`；
  - `backend/app/integrations/queue/protocol.py`: 强类型数据契约 (`TaskMessage`, `TaskResult`) 与抽象协议 (`QueueProtocol`)；
  - `backend/app/integrations/queue/memory.py`: `MemoryQueueAdapter` 纯内存 Fake 实现，支持即时同步执行模式与并发队列模式，提供单测延迟与故障注入桩，强校验 `user_id`；
  - `backend/app/integrations/queue/redis.py`: `RedisQueueAdapter` 生产实现，封装基于 Redis 的入队、状态查询与取消，支持 20s 超时、退避重试与凭据掩码；
  - `backend/app/integrations/queue/factory.py`: `create_queue_adapter(adapter_type="memory", ...)` 工厂分发。
* **幂等拦截组件包 (`backend/app/integrations/idempotency/`)**:
  - `backend/app/integrations/idempotency/__init__.py`: 模块入口，规范导出 `IdempotencyProtocol`, `MemoryIdempotencyAdapter`, `RedisIdempotencyAdapter`, `create_idempotency_adapter`；
  - `backend/app/integrations/idempotency/protocol.py`: 抽象协议 (`IdempotencyProtocol`) 与合法性校验纯函数；
  - `backend/app/integrations/idempotency/memory.py`: `MemoryIdempotencyAdapter` 纯内存 Fake 实现，基于 `threading.Lock` + 过期时间戳，模拟原子抢占与结果缓存；
  - `backend/app/integrations/idempotency/redis.py`: `RedisIdempotencyAdapter` 生产实现，基于 Redis `SET NX EX` 分布式锁抢占与响应体快照读写；
  - `backend/app/integrations/idempotency/factory.py`: `create_idempotency_adapter(adapter_type="memory", ...)` 工厂分发。
* **单元测试与质量闭环 (`backend/tests/unit/`)**:
  - `backend/tests/unit/core/test_errors_queue_idempotency.py`: 异常继承体系与错误码映射断言测试；
  - `backend/tests/unit/integrations/queue/test_queue.py`: 队列协议契约、Memory 适配器即时/排队模式、租户越权拦截、延迟/故障注入、多线程并发入队测试、Redis 适配器凭据脱敏与 ClientError 模拟测试；
  - `backend/tests/unit/integrations/idempotency/test_idempotency.py`: 幂等协议契约、Key 合法性校验、Memory 适配器原子争抢 (50 线程并发竞争仅 1 成功)、TTL 过期失效、结果回放与异常释放测试、Redis 适配器脱敏与连接异常模拟测试。

---

## 2. 伴随式分步实施与验证 (Step-by-Step Implementation Loops)

### Milestone 1: 统一异常体系扩展与测试先行 (Fail-repro First)
* **操作目标**: 编写针对 30015~30018 异常的测试用例，并在 `app/core/errors.py` 中扩充实现，维护 `__all__` 字典序。
* **涉及文件**:
  - `backend/tests/unit/core/test_errors.py` (Modify / 追加测试)
  - `backend/app/core/errors.py` (Modify)
* **局部验证命令**:
  ```bash
  cd backend && pytest tests/unit/core/test_errors.py -v
  ```
* **预期判据**: 错误码 30015~30018 及其对应的 HTTP 状态码、默认文案与别名属性全部断言通过（Pass）。

### Milestone 2: 异步任务队列抽象与 MemoryQueueAdapter 落地
* **操作目标**:
  1. 在 `app/integrations/queue/protocol.py` 中定义 `TaskMessage`、`TaskResult` 与 `QueueProtocol`；
  2. 实现 `MemoryQueueAdapter`，提供线程安全排队、即时执行模式（`immediate_mode=True`）、故障延迟注入桩与租户隔离校验；
  3. 实现 `create_queue_adapter` 工厂并规范导出；
  4. 编写并运行单元测试覆盖即时模式、排队模式、租户越权查询阻断及并发入队。
* **涉及文件**:
  - `backend/app/integrations/queue/protocol.py` (New)
  - `backend/app/integrations/queue/memory.py` (New)
  - `backend/app/integrations/queue/factory.py` (New)
  - `backend/app/integrations/queue/__init__.py` (New)
  - `backend/tests/unit/integrations/queue/test_queue.py` (New)
* **局部验证命令**:
  ```bash
  cd backend && pytest tests/unit/integrations/queue/test_queue.py -v -k "test_memory_queue"
  ```
* **预期判据**: 内存队列基础流转、租户跨越拦截与多线程测试 100% 变绿（Pass）。

### Milestone 3: 幂等拦截抽象与 MemoryIdempotencyAdapter 落地
* **操作目标**:
  1. 在 `app/integrations/idempotency/protocol.py` 中定义 `IdempotencyProtocol` 与 Key 校验纯函数；
  2. 实现 `MemoryIdempotencyAdapter`，提供原子互斥锁、TTL 过期回收、快照缓存与主动释放；
  3. 实现 `create_idempotency_adapter` 工厂并规范导出；
  4. 编写并运行 50 线程高并发竞争测试，验证仅 1 次抢占成功，其余 49 次精准返回 False。
* **涉及文件**:
  - `backend/app/integrations/idempotency/protocol.py` (New)
  - `backend/app/integrations/idempotency/memory.py` (New)
  - `backend/app/integrations/idempotency/factory.py` (New)
  - `backend/app/integrations/idempotency/__init__.py` (New)
  - `backend/tests/unit/integrations/idempotency/test_idempotency.py` (New)
* **局部验证命令**:
  ```bash
  cd backend && pytest tests/unit/integrations/idempotency/test_idempotency.py -v -k "test_memory_idempotency"
  ```
* **预期判据**: 并发抢占原子性与结果快照回放断言全绿（Pass）。

### Milestone 4: Redis 生产适配器实现与脱敏/容灾测试
* **操作目标**:
  1. 实现 `RedisQueueAdapter`，支持延迟加载 `redis` 依赖、连接超时、退避重试与凭据掩码脱敏；
  2. 实现 `RedisIdempotencyAdapter`，基于 Redis `SET NX EX` 语义实现原子锁，带快照持久化；
  3. 扩充工厂函数对 `"redis"` 模式的分发与参数校验；
  4. 在测试中注入 Mock Redis 客户端，验证绝密脱敏 `__repr__`、连接异常转译与网络超时行为。
* **涉及文件**:
  - `backend/app/integrations/queue/redis.py` (New)
  - `backend/app/integrations/idempotency/redis.py` (New)
  - `backend/tests/unit/integrations/queue/test_queue.py` (Modify / 追加 Redis 桩测试)
  - `backend/tests/unit/integrations/idempotency/test_idempotency.py` (Modify / 追加 Redis 桩测试)
* **局部验证命令**:
  ```bash
  cd backend && pytest tests/unit/integrations/queue/ tests/unit/integrations/idempotency/ -v
  ```
* **预期判据**: 全量队列与幂等测试用例全部通过，零外部网络连接（Pass）。

---

## 3. 全局质量门禁核验 (Global Quality Gate)
* **架构分层依赖检查**:
  ```bash
  python3 tooling/check_layers.py --root backend/app
  ```
  判据: 扫描全部文件，0 违规导入。
* **SDLC 流程完整性检查**:
  ```bash
  python3 tooling/check_sdlc_integrity.py
  ```
  判据: 检查通过，工件完整无占位符。
* **后端全套静态检查与覆盖率门禁**:
  ```bash
  cd backend && \
  ruff format --check . && \
  ruff check . && \
  mypy app && \
  bandit -r app -ll && \
  pytest tests --cov=app --cov-branch --cov-fail-under=80
  ```
* **核验结果**: 静态分析零警告，`app/integrations/queue` 与 `app/integrations/idempotency` 测试覆盖率 $\ge 90\%$，全量测试 100% 绿灯。

---

## 4. 实施偏差记录 (Deviations Log)
*实施过程严格对齐 spec.md，无破坏性契约偏差。*
* 记录：按规划平稳实施，各组件严格遵守 AGENTS.md 规范与缩写白名单。

---

## 5. 阶段准出签批 (Gate 3 Sign-off)
- [ ] 所有分步实施项与验证断言均已就地执行并通过
- [ ] 全局质量门禁（Lint / Type / Regression）全部绿灯
- [ ] 变更文件与 plan.md 清单完全吻合，无越权修改
- **验收结论**: Pending
- **验证人 / 日期**: [待人类确认] / 2026-09-24 08:23
