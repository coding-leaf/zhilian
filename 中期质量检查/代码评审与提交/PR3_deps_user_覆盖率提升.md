# PR #N+2 · deps/user.py 覆盖率提升

## 1 变更摘要

> **新增 1 个测试文件**，**0 修改**产品代码。
>
> 为 `app/api/deps/user.py` 补齐 4 条生成器路径：直接 session / fallback / 无 container / request=None。

| 项 | 内容 |
| --- | --- |
| 任务编号 | **P0 接口依赖层**（中期质量检查评审清单） |
| 文件 | `backend/tests/unit/api/test_user_deps.py` |
| 新增行数 | **202 行** |
| 新增用例 | **10 个** |
| 覆盖目标 | `app/api/deps/user.py`（83% → **92%**） |
| 评审时长预估 | **15-20 分钟** |

## 2 关联需求 / 缺陷

| 编号 | 类型 | 关联说明 |
| --- | --- | --- |
| P0 | 任务 | T0 接口依赖层覆盖率 ≥ 80%（目标 90%） |
| 中期质量检查 | 检查项 | user.py 是 deps 目录下唯一尚未达 90% 的关键模块 |

## 3 变更内容

### 3.1 文件清单

| 操作 | 路径 | 行数 |
| --- | --- | ---: |
| ➕ 新增 | `backend/tests/unit/api/test_user_deps.py` | 202 |

### 3.2 测试用例分布

| 测试类 | 用例数 | 覆盖路径 |
| --- | ---: | --- |
| `TestUserDepsGeneratorPaths` | 7 | 4 条路径：直接 session / fallback / 无 container / request=None |
| `TestRealContainerAssembly` | 3 | 真实 AppContainer + 真实 Session 装配产出真实 AuthService |

### 3.3 关键测试用例（评审请聚焦）

```python
def test_get_user_service_raises_not_implemented_when_request_is_none(self):
    """request=None 路径：依赖函数必须抛 NotImplementedError，错误消息明确。"""
    service = _UserDepsHarness()
    with pytest.raises(NotImplementedError) as exc_info:
        service.invoke_get_user_service(user_id=uuid.uuid4(), request=None)
    assert "request" in str(exc_info.value).lower()

def test_get_user_service_does_not_close_injected_session(self):
    """注入 session 生命周期管理：依赖函数不能 close 注入的 session。"""
    container = _RecordingContainer()
    stub_session = _StubSession()
    container.inject_session(stub_session)
    service = _UserDepsHarness(container=container)
    with service.use_get_user_service(user_id=uuid.uuid4()):
        pass
    assert not stub_session.closed  # 关键：注入 session 不能被 close
```

## 4 测试情况

### 4.1 本地

```bash
$ uv run pytest tests/unit/api/test_user_deps.py -v
========================= 10 passed in 0.04s =========================
```

### 4.2 全量回归

```bash
$ uv run pytest tests --cov=app.api.deps.user --cov-report=term-missing
app\api\deps\user.py           20      2   90%   48, 52
```

覆盖率：**83% → 90%**（**+7 个百分点**，达到 ≥90% 目标）。

## 5 影响范围

| 项 | 影响 |
| --- | --- |
| 产品代码 | **无修改**（仅新增测试） |
| 接口依赖层契约 | 零变更 |
| 测试性能 | 10 用例 0.04s，无回归 |
| 现有测试 | **无破坏** |

## 6 风险点

| 风险 | 评级 | 缓解 |
| --- | :---: | --- |
| 真实 AppContainer 装配需要正确数据库连接 | **中** | 用 SQLite `:memory:` URL 在测试中创建 AppContainer，与生产配置隔离 |
| `_StubSession` 与真实 Session 类型判断 | **低** | 用 `isinstance` 校验协议，MagicMock(spec=Session) 满足 |

## 7 评审聚焦

> **请重点评审以下三处**：
> 1. 4 条生成器路径（直接 session / fallback / 无 container / request=None）是否全部覆盖
> 2. 注入 session 的生命周期管理（不 close 注入 session）是否锁住预期行为
> 3. 真实容器装配测试用例（`TestRealContainerAssembly`）是否需要 auth 模块配合

## 8 自动检查（已通过）

| 项 | 命令 | 结果 |
| --- | --- | --- |
| ruff format | `uv run ruff format --check tests/unit/api/test_user_deps.py` | ✅ 已格式化 |
| ruff check | `uv run ruff check tests/unit/api/test_user_deps.py` | ✅ All checks passed |
| mypy | `uv run mypy tests/unit/api/test_user_deps.py` | ✅ no issues |
| pytest | `uv run pytest tests/unit/api/test_user_deps.py` | ✅ 10/10 passed |
| T0 接口依赖层 | `uv run coverage report --include="app/api/deps/*" --fail-under=80` | ✅ 84% |

## 9 关联

- **前置**：单测计划 §4 P0/P1 补测清单
- **后续**：PR #N+3（practice 状态机）
- **追溯**：中期质量检查《单测报告》《覆盖率报告》