# PR4 评审记录 · practice 状态机与强幂等补测

| 项 | 内容 |
| --- | --- |
| PR 编号 | #N+3 |
| 文件 | `backend/tests/unit/services/test_practice_state_machine_supplemental.py` |
| 行数 | 194 |
| 用例数 | 12 |
| 评审日期 | 2026-10-04 |
| 评审时长 | 20 分钟 |

---

## 1 作者讲解（5 min）

> **作者**：本期提交 4 个补测文件中的 PR4，主题是 `app/services/practice.py` 状态机迁移 + 强幂等并发锁。

**讲解要点**：
1. **目标**：覆盖 TIMEOUT/NOT_STARTED/COMPLETED/IN_PROGRESS 状态拦截 + 强幂等并发锁语义
2. **测试架构**：mock 策略——绕过 `__init__` 直接构造桩服务（`PracticeService.__new__(PracticeService)`）
3. **理由**：避免繁重的实体装配（fixture 链）
4. **覆盖**：状态机 4 项 + 参数校验 3 项 + 实体不存在 1 项 + 并发竞态 1 项 + 入队失败回滚 1 项 + 幂等锁 2 项 = 12 项

---

## 2 评审走查（15 min）

### 2.1 正确性 🔍

**问题 4.1（🟠 重要）**：发现产品代码 bug——状态跃迁成功后实体消失时**未回滚**

> 测试**未覆盖**此场景（`TestRetryGradingNotFoundGuard` 只测**初始**实体不存在），但评审人发现 `retry_grading` 实现存在状态泄漏风险。

**位置**：`app/services/practice.py:1317-1351`

```python
try:
    transitioned = self.practice_repo.try_transition_status(
        practice_id, user_id,
        from_status=PracticeStatus.PARTIALLY_GRADED.value,
        to_status=PracticeStatus.SUBMITTED.value,
    )
    if not transitioned:
        raise PracticeStatusError(...)
    task_id = self.queue.enqueue(...)
    self.session.commit()              # ← 状态已提交到 SUBMITTED
except Exception:
    self.session.rollback()
    raise

practice = self.practice_repo.get_practice_by_id(practice_id, user_id, include_items=False)
if practice is None:
    raise PracticeNotFoundError(...)    # ← 抛错时没有 rollback！
```

**风险**：
1. 状态已从 `partially_graded` → `submitted`
2. `session.commit()` 已持久化
3. 此时**并发删除**实体，`get_practice_by_id` 返回 None
4. 抛 `PracticeNotFoundError` 但**没有 rollback**
5. **结果**：练习永久停在 `SUBMITTED` 状态，无法重试也无法恢复——「永久判题中」入口被堵死

- 🟠 **重要**：这是与 PR4 强幂等场景同源的真实风险。**应新增一条测试**锁住该行为。
- 🟠 **重要**：评审应建议**修复产品代码**：将 `get_practice_by_id` 后的 None 检查也纳入 try/except，或 rollback 后再抛。

**问题 4.2（🟠 重要）**：`except Exception:` 太宽，可能掩盖非预期异常

```python
except Exception:
    # 入队失败必须回滚状态
    self.session.rollback()
    raise
```

- 评审意见：
  - 应该捕获**更具体的异常**：`QueueError`、`SQLAlchemyError`、`ConnectionError`
  - 当前实现会捕获 `KeyboardInterrupt`、`SystemExit` 等——**不推荐**
- 🟠 **重要**：建议改为 `except (QueueError, SQLAlchemyError):`

**问题 4.3（🟠 重要）**：测试 mock 断言可能掩盖真实 bug

```python
def test_rolls_back_status_when_queue_enqueue_fails(self) -> None:
    ...
    service.queue.enqueue.side_effect = RuntimeError("queue broker down")
    with pytest.raises(RuntimeError, match="queue broker down"):
        service.retry_grading(practice.user_id, practice.id)
    service.session.rollback.assert_called_once()
```

- ⚠️ **问题**：
  - 用 `RuntimeError` 模拟 queue 失败，但生产中 `queue.enqueue` 应抛 `QueueError` 或其子类（如 `RedisError`）
  - `pytest.raises(RuntimeError, match="queue broker down")` 是宽匹配——任何 `RuntimeError` 子类都通过
- 🟠 **重要**：应改用 `QueueError` 或生产中真实抛出的异常类型，验证 rollback 是**针对 queue 失败**而非任何异常

### 2.2 设计 📐

**问题 4.4**：`PracticeService.__new__(PracticeService)` 反模式 hack 是否可接受？

```python
service = PracticeService.__new__(PracticeService)
service.session = MagicMock()
service.practice_repo = MagicMock()
service.idempotency = MagicMock()
service.queue = MagicMock()
```

- ✅ 优点：避免复杂 fixture 装配
- ⚠️ **建议**：
  - 当前 4 个测试类都用了 `__new__` hack，应该抽取到 `_make_practice_service_stub(...)` 工厂函数
  - 每个测试类内部重复 `_make_service`、`_make_service_and_practice` 等辅助方法
- ⚠️ **建议**：`_make_service_and_practice(status)` 是 17 行重复代码，**4 个状态拦截测试都用了它**——可考虑参数化（`@pytest.mark.parametrize`）

**问题 4.5**：状态拦截测试的覆盖度

- 当前覆盖：TIMEOUT / NOT_STARTED / COMPLETED / IN_PROGRESS（4 项）
- ⚠️ **建议**：
  - 缺 `PAUSED` 状态拦截（按状态机定义，PAUSED 也不应重判）
  - 缺 `SUBMITTED` 状态拦截（理论上 retry_grading 不应接受 SUBMITTED，因为已经有任务在飞——但可能测试想覆盖）

### 2.3 可读性 📖

**问题 4.6**：类名 / 方法名是否清晰？

- ✅ 类名 `TestRetryGradingTimeoutGuard`、`TestRetryGradingRaceCondition`、`TestStrongIdempotencyReplay` 主题清晰
- ⚠️ **建议**：方法名 `test_retry_grading_rejects_not_started_status` 与 `test_retry_grading_rejects_completed_status` 高度相似，可用 `parametrize` 合并

### 2.4 健壮性 🛡️

**问题 4.7（🟠 重要）**：mock 策略的边界风险

- `service = PracticeService.__new__(PracticeService)` 绕过 `__init__`，**未初始化依赖注入**
- 如果未来 `retry_grading` 实现增加新的依赖（如 `logger`、`metrics`），**测试不会失败但生产会失败**
- 🟠 **重要**：建议至少 mock 一下 `logger`，避免未来回归

**问题 4.8**：幂等并发测试的真实性

```python
def test_idempotency_lock_raises_conflict_on_duplicate_key(self) -> None:
    adapter = MemoryIdempotencyAdapter()
    adapter.acquire_lock(key="key-1", user_id="user-A")
    with pytest.raises(IdempotencyConflictError):
        adapter.acquire_lock(key="key-1", user_id="user-A")  # 同 user_id, 同 key
```

- ⚠️ **建议**：缺**跨 user_id 的同 key 场景**——生产中 user A 用 `key-1` 后，user B 是否能用 `key-1`？
- 当前 `MemoryIdempotencyAdapter` 的实现未明确，可能存在 user 隔离漏洞

### 2.5 安全与性能 🔐

**问题 4.9**：性能开销？

- ✅ 12 个用例 0.96s 完成（mock 策略下更快），**性能优异**

**问题 4.10**：mock 是否泄露生产敏感字段？

- 测试中 `practice.user_id`、`practice.id` 都是 `uuid.uuid4()`，**无敏感数据**

### 2.6 测试充分性 🧪

| 维度 | 覆盖情况 | 评价 |
| --- | :---: | --- |
| 状态机迁移拦截 | 4/8 状态 | ⚠️ 不完整（缺 PAUSED、SUBMITTED） |
| 参数校验 | 3/3 组合 | ✅ 完整 |
| 实体不存在 | 1 项 | ⚠️ 不完整（缺「跃迁后消失」） |
| 并发竞态 | 1 项 | ✅ 完整 |
| 入队失败回滚 | 1 项 | ⚠️ 不完整（缺事务其他失败） |
| 强幂等锁 | 2 项 | ⚠️ 不完整（缺跨用户同 key） |

### 2.7 可维护性 🔧

**问题 4.11**：未来重构时是否易于调整？

- 🔴 `service = PracticeService.__new__(PracticeService)` 是技术债务
- 🔴 测试一旦新增 `retry_grading` 依赖，必须同步修改所有 5 个 mock 工厂方法

### 2.8 文档与追溯 📚

**问题 4.12**：是否关联 P 编号 / 缺陷编号？

- ✅ 文件 docstring 明示「P1 状态机迁移与幂等重派」
- ✅ 类名 `TestRetryGradingTimeoutGuard` 含守卫意图

---

## 3 问题清单

| ID | 级别 | 维度 | 描述 | 建议处理 |
| ---: | :---: | --- | --- | --- |
| PR4-01 | 🟠 重要 | 正确性 | **发现产品代码 bug**：状态跃迁成功后实体消失未 rollback | 本 PR 新增测试 + 评审联动修复 |
| PR4-02 | 🟠 重要 | 正确性 | `except Exception:` 太宽，建议捕获具体异常类型 | 评审联动修复产品代码 |
| PR4-03 | 🟠 重要 | 健壮性 | mock 断言 `RuntimeError` 与生产 `QueueError` 不一致 | 改用 `QueueError` 或生产异常类型 |
| PR4-04 | 🟠 重要 | 健壮性 | 缺 `PAUSED` / `SUBMITTED` 状态拦截测试 | 后续 PR 补充 |
| PR4-05 | 🟡 建议 | 设计 | 5 个 `_make_service*` 工厂方法重复，建议抽取 | 本 PR 内合并或后续 PR 优化 |
| PR4-06 | 🟡 建议 | 健壮性 | 缺跨用户同 idempotency_key 场景测试 | 后续 PR 补充 |
| PR4-07 | 🟡 建议 | 可读性 | 状态拦截 4 项可用 parametrize 合并 | 本 PR 内合并 |
| PR4-08 | 🟡 建议 | 可维护性 | `PracticeService.__new__` 是技术债务 | 长期优化 |

---

## 4 评审结论

> **🟡 修改后通过（必须解决 1 个重要问题 + 评审联动修复产品代码）**

### 4.1 修改后通过理由

1. **无阻塞问题**：mock 策略虽然 hack 但可接受
2. **正确性**：PR4-01（🟠 重要）发现产品代码 bug，应在**同一 PR 或紧邻 PR 修复**
3. **PR4-02/03**：与产品代码强相关，建议**评审联动修复**
4. **PR4-04**：状态覆盖不完整，建议补充 `PAUSED` / `SUBMITTED` 状态

### 4.2 修改路径

1. **PR4-01 修复**：新增 `test_retry_grading_rolls_back_when_practice_disappears_after_transition` 测试锁住现状（**没有 rollback**）。然后评审联动修复产品代码。
2. **PR4-02 修复**：评审联动修复 `except Exception:` 为具体异常类型。
3. **PR4-03 修复**：将 `RuntimeError` 改为 `QueueError`。
4. **PR4-04 修复**：增加 `test_retry_grading_rejects_paused_status` 与 `test_retry_grading_rejects_submitted_status`。

### 4.3 评审联动建议

> **建议联动评审**：`app/services/practice.py::retry_grading` 方法（评审人：SecLead + TechLead）。
>
> 该方法存在 2 个产品代码缺陷：
> 1. L1346-1351 状态跃迁后实体消失未 rollback（PR4-01）
> 2. L1341 `except Exception:` 太宽（PR4-02）
>
> 应在 M1 里程碑单独 PR 修复，并增加回归测试。

### 4.4 合并授权

- 主评审 Reviewer：🟡 修改后通过
- 加签 SecLead：🟡 修改后通过
- **修改 PR4-01/02/03/04 后可合并**

---

## 5 评审特别讨论

### 5.1 mock 策略 vs 真实装配的权衡

> **讨论**：状态机拦截测试为何不用真实 DB 装配？

**作者观点**：
- 真实装配需要 user / folder / question / practice 等 6+ 个 fixture
- 12 个用例 0.96s 完成，比真实装配快 10x
- 状态机迁移逻辑与 DB 弱耦合，mock 足够锁住契约

**评审人观点**：
- mock 策略**确实快**，但**不能验证** SQL 谓词正确性（如 `try_transition_status` 的 CAS 语义）
- 既有 `tests/unit/services/test_practice_service.py` 已用真实 DB 覆盖了主路径
- **本次 mock 补测** + **既有真实装配测试** = 互补，**评审接受**

### 5.2 PR4-01 是否算评审「越界」

> **讨论**：评审补测文件时发现产品代码 bug，是否属于评审范围？

**评审原则**：
- ✅ 「**通过人工评审发现自动测试发现不了的问题**」是评审的核心目标
- ✅ PR4-01 是真实风险（持久化泄漏），自动覆盖率、运行数据均不能发现
- ✅ 评审人记录问题，**不要求作者当场修复**，但应在评审结论中明示

**结论**：评审记录 PR4-01 为「🟠 重要」问题，作者可在 M1 里程碑修复或紧邻 PR 修复。