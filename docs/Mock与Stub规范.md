# Mock 与 Stub 规范（中期质量检查 · 增量规范）

| 项 | 值 |
| --- | --- |
| 编制时间 | 2026-10-04 |
| 编制来源 | 中期质量检查 M1-005 改进项 |
| 适用范围 | 所有 Python 单测 mock/stub 使用 |
| 维护责任 | Reviewer |

---

## 1 总则

> **Mock 的本质**：测试**契约**而非**实现**。
> 自定义 stub 是**反模式**，`MagicMock(spec=Class)` 是 pytest 标准用法。

---

## 2 等级与决策树

```
需要桩化某个对象？
├── 是真实类的实例吗？
│   ├── 是：用 MagicMock(spec=Class)
│   └── 否：桩化目的是什么？
│       ├── 类型判定（isinstance）：用 MagicMock(spec=Class)
│       ├── 行为模拟（多方法交互）：谨慎使用自定义 stub（评审批准）
│       └── 仅占位：用 SimpleNamespace
└── 涉及 SQLAlchemy Session / FastAPI Request / Auth 类等关键类型？
    └── 是：必须用 MagicMock(spec=Class)
```

---

## 3 反模式（禁止）

### 3.1 自定义 stub 跳过父类 `__init__`

```python
# ❌ 禁止
class _StubSession(Session):
    def __init__(self) -> None:
        # 跳过父类 __init__ 的实际绑定逻辑
        self._closed = False
    def close(self) -> None:
        self._closed = True
```

**问题**：
- 与真实 Session 状态机脱节
- 未来 SQLAlchemy 升级会瞬间崩溃
- `_closed` 是私有字段，断言依赖内部状态

**正确做法**：
```python
# ✅ 正确
injected_session = MagicMock(spec=Session)
injected_session.close.assert_not_called()
```

---

### 3.2 `iter([...])` 隐式 StopIteration

```python
# ❌ 禁止
self._marker_cycle = iter(["marker-A", "marker-B"])
# 第 3 次 next() 会抛 StopIteration
```

**正确做法**：
```python
# ✅ 正确
self._marker_cycle = itertools.cycle(["marker-A", "marker-B", "marker-C"])
```

---

### 3.3 私有字段断言

```python
# ❌ 禁止
assert injected_session._closed is False
```

**正确做法**：
```python
# ✅ 正确
injected_session.close.assert_not_called()
```

---

### 3.4 `# pragma: no cover` 豁免

```python
# ❌ 禁止
def legacy_method(self) -> None:  # pragma: no cover
    ...
```

**正确做法**：
```python
# ✅ 正确：补测试用例
def test_legacy_method(self) -> None:
    ...
```

---

## 4 推荐的 mock 模式

### 4.1 `MagicMock(spec=Class)`

```python
from unittest.mock import MagicMock
from sqlalchemy.orm import Session

# 桩化 Session
session = MagicMock(spec=Session)
session.close.assert_not_called()  # 类型与方法签名校验
```

### 4.2 `MagicMock(spec=Class)` + 自定义方法

```python
service = MagicMock(spec=AuthService)
service.session = injected_session  # 让 service.session 指向注入的 session
service.get_user_by_id.return_value = mock_user
```

### 4.3 `AsyncMock(spec=AsyncClass)`

```python
from unittest.mock import AsyncMock

# 桩化异步函数
queue = AsyncMock(spec=QueueAdapter)
await queue.enqueue(...)  # 模拟异步调用
```

---

## 5 自定义 stub 的边界（仅复杂行为）

> 自定义 stub **必须**有 docstring + 评审批准 + 提交时在 PR 描述中明示。

### 5.1 允许场景

| 场景 | 例子 |
| --- | --- |
| 多方法 + 状态机交互 | `_RecordingContainer`（PR3 修复后改为 MagicMock） |
| 实现具体协议类 | `MemoryIdempotencyAdapter`（生产代码也是该实现） |
| 复杂 fixture | `conftest.py::factory_create_session_with_data` |

### 5.2 不允许场景

| 场景 | 反模式 |
| --- | --- |
| 跳父类 `__init__` | `_StubSession(Session)` |
| 私有字段断言 | `assert obj._closed` |
| `iter([...])` 隐式错误 | 计数器 |
| 复杂手动装配 | `_make_service_with_everything()` |

---

## 6 反模式的「**为什么**」

> 评审时**必须**问这个问题：「如果 mock 的实现细节变更，测试会失败吗？」

### 6.1 私有字段断言的反模式根源

```python
# ❌ 这种测试「**只有写的人懂**」
assert injected_session._closed is False
```

测试的稳定性应来自**接口契约**，而非**实现细节**。`_closed` 是 SQLAlchemy 的实现细节，未来升级到 2.x 时会被替换。

### 6.2 跳 `__init__` 的反模式根源

```python
class _StubSession(Session):
    def __init__(self):
        # 跳过父类 __init__
        self._closed = False
```

SQLAlchemy Session 的 `__init__` 执行 `_initialize_state`、`_new_state`、`_connections_for_bidder_bidder` 等复杂逻辑。**手动跳过的 stub 不知道父类做了什么**。

---

## 7 Mock 使用约束

### 7.1 spec 必须

> 任何 mock **必须**有 `spec=` 参数。

```python
# ✅ 正确
m = MagicMock(spec=Session)

# ❌ 错误（spec 缺失）
m = MagicMock()
```

### 7.2 contextmanager mock

```python
@contextmanager
def get_session(self) -> Generator[MagicMock, None, None]:
    """contextmanager stub 必须保留 enter/exit 语义。"""
    stub = MagicMock(spec=Session)
    try:
        yield stub
    finally:
        stub.close.assert_not_called()
        stub.close()
```

### 7.3 fixture 复用

```python
@pytest.fixture
def session() -> Generator[MagicMock, None, None]:
    """共用 Session mock fixture。"""
    yield MagicMock(spec=Session)
```

---

## 8 评审检查项（与 `docs/评审清单.md` §3 对应）

| 检查项 | 是 | 否 |
| --- | :---: | :---: |
| mock 是否配置 `spec=`？ | ✅ | ❌ |
| 是否避免了 `_StubXxx` 反模式？ | ✅ | ❌ |
| 是否避免了 `_private_field` 断言？ | ✅ | ❌ |
| 是否避免了 `iter([...])` 隐式错误？ | ✅ | ❌ |
| 是否避免了 `# pragma: no cover`？ | ✅ | ❌ |
| contextmanager 桩是否保留 enter/exit？ | ✅ | ❌ |
| 自定义 stub 是否有 docstring + 评审批准？ | ✅ | ❌ |

---

## 9 修复案例：`_StubSession` → `MagicMock(spec=Session)`

**修复前（评审 🔴 阻塞）**：
```python
class _StubSession(Session):
    def __init__(self) -> None:
        self._closed = False
    def close(self) -> None:
        self._closed = True
```

**修复后**：
```python
session = MagicMock(spec=Session)
# 断言验证方法调用次数而非内部状态
session.close.assert_not_called()
session.close.assert_called_once()
```

**评审复评结论**：✅ 通过

---

## 10 配套规范

| 文档 | 关联 |
| --- | --- |
| `docs/测试设计规范.md` | 测试设计流程 + mock 决策树 |
| `docs/评审清单.md` | 评审检查项 §3 |
| `docs/异常捕获规范.md` | mock 异常的捕获纪律 |