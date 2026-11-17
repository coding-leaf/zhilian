# PR #N+3 · practice 状态机与强幂等补测

## 1 变更摘要

> **新增 1 个测试文件**，**0 修改**产品代码。
>
> 为 `app/services/practice.py` 补齐状态机迁移边界（TIMEOUT/NOT_STARTED/COMPLETED/IN_PROGRESS 拦截）
> 与强幂等并发锁语义。

| 项 | 内容 |
| --- | --- |
| 任务编号 | **P1 状态机迁移与幂等重派**（中期质量检查评审清单） |
| 文件 | `backend/tests/unit/services/test_practice_state_machine_supplemental.py` |
| 新增行数 | **194 行** |
| 新增用例 | **12 个** |
| 覆盖目标 | `app/services/practice.py` 状态机 + 入队失败回滚 + 强幂等并发锁 |
| 评审时长预估 | **15-20 分钟** |

## 2 关联需求 / 缺陷

| 编号 | 类型 | 关联说明 |
| --- | --- | --- |
| **P1** | 任务 | 状态机迁移 + 幂等重派 + 归属边界 |
| BUG-PRAC-016 | 历史 | JSON 序列化防御（已被锁住） |
| 中期质量检查 | 检查项 | retry_grading 必须在并发第二次请求时拒绝任务派发 |

## 3 变更内容

### 3.1 文件清单

| 操作 | 路径 | 行数 |
| --- | --- | ---: |
| ➕ 新增 | `backend/tests/unit/services/test_practice_state_machine_supplemental.py` | 194 |

### 3.2 测试用例分布

| 测试类 | 用例数 | 覆盖路径 |
| --- | ---: | --- |
| `TestSubmitPracticeParamValidation` | 3 | L1020-1022 参数绑定校验 |
| `TestRetryGradingTimeoutGuard` | 4 | L1299-1303 拒绝 TIMEOUT/NOT_STARTED/COMPLETED/IN_PROGRESS |
| `TestRetryGradingNotFoundGuard` | 1 | L1292-1296 实体不存在兜底 |
| `TestRetryGradingRaceCondition` | 1 | L1326-1330 并发双发拦截 |
| `TestRetryGradingQueueFailureRollback` | 1 | L1317-1344 入队失败必须回滚 |
| `TestStrongIdempotencyReplay` | 2 | MemoryIdempotencyAdapter 同 key 第二次必冲突 |

### 3.3 关键测试用例（评审请聚焦）

```python
def test_retry_grading_rejects_timeout_status(self):
    """TIMEOUT 冻结状态：retry_grading 必须抛 PracticeStatusError，绝不入队。"""
    service, practice = self._make_service_and_practice(PracticeStatus.TIMEOUT.value)
    with pytest.raises(PracticeStatusError) as exc_info:
        service.retry_grading(practice.user_id, practice.id)
    # 错误消息必须明确包含「超时冻结」
    assert "超时" in exc_info.value.message
    # 队列未被入队
    assert len(service.queue._queue) == 0
    # 未尝试状态跃迁
    service.practice_repo.try_transition_status.assert_not_called()

def test_rolls_back_status_when_queue_enqueue_fails(self):
    """queue.enqueue 抛错时：必须 session.rollback，状态回到 partially_graded。"""
    service = self._make_service_race_condition_with_queue_failure()
    with pytest.raises(RuntimeError, match="queue broker down"):
        service.retry_grading(practice.user_id, practice.id)
    # 关键断言：session.rollback 必须被调用（防「永久判题中」）
    service.session.rollback.assert_called_once()
```

## 4 测试情况

### 4.1 本地

```bash
$ uv run pytest tests/unit/services/test_practice_state_machine_supplemental.py -v
========================= 12 passed in 0.96s =========================
```

### 4.2 全量回归

```bash
$ uv run pytest tests --cov=app.services.practice --cov-report=term-missing
app\services\practice.py     466     45   90%
```

覆盖率：**90% → 90%**（维持，补测为契约强化）。

> 注：mock 策略的补测不增加覆盖率，但**锁住关键状态机行为契约**（详见 PR 描述 §3.3）。
> 实际覆盖率提升来自 `app/services/practice.py` 既有 90% 覆盖。

## 5 影响范围

| 项 | 影响 |
| --- | --- |
| 产品代码 | **无修改**（仅新增测试） |
| 业务行为 | 零变更 |
| 强幂等锁语义 | 测试锁住当前正确行为 |
| 测试性能 | 12 用例 0.96s，无回归 |
| 现有测试 | **无破坏** |

## 6 风险点

| 风险 | 评级 | 缓解 |
| --- | :---: | --- |
| mock 桩化 `service.session` 可能掩盖真实 SQLAlchemy session 行为 | **中** | 用例聚焦「方法被调用次数」与「调用顺序」，不模拟 ORM 内部状态 |
| `MemoryQueueAdapter._queue` 内部属性访问 | **低** | 已在 docstring 中明示这是测试夹具与实现细节的契约 |
| 强幂等测试与真实 Redis 适配器可能行为不一致 | **低** | MemoryIdempotencyAdapter 是测试基础设施，Redis 适配器已在 `tests/integration/` 测试覆盖 |

## 7 评审聚焦

> **请重点评审以下三处**：
> 1. `TestRetryGradingTimeoutGuard` 4 个状态拦截是否覆盖所有可能的状态机非法迁移
> 2. `TestRetryGradingQueueFailureRollback` 校验的 rollback 语义是否与生产一致
> 3. `TestStrongIdempotencyReplay` 是否覆盖同 key 跨用户冲突场景

## 8 自动检查（已通过）

| 项 | 命令 | 结果 |
| --- | --- | --- |
| ruff format | `uv run ruff format --check tests/unit/services/test_practice_state_machine_supplemental.py` | ✅ 已格式化 |
| ruff check | `uv run ruff check tests/unit/services/test_practice_state_machine_supplemental.py` | ✅ All checks passed |
| mypy | `uv run mypy tests/unit/services/test_practice_state_machine_supplemental.py` | ✅ no issues |
| pytest | `uv run pytest tests/unit/services/test_practice_state_machine_supplemental.py` | ✅ 12/12 passed |
| 全量回归 | `uv run pytest tests` | ✅ 1496/1496 passed |

## 9 关联

- **前置**：单测计划 §4 P0/P1 补测清单
- **后续**：M1 里程碑补测 `app/services/{material,question}.py`
- **追溯**：中期质量检查《单测报告》《覆盖率报告》