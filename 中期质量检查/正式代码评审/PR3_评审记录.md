# PR3 评审记录 · deps/user.py 覆盖率提升

| 项 | 内容 |
| --- | --- |
| PR 编号 | #N+2 |
| 文件 | `backend/tests/unit/api/test_user_deps.py` |
| 行数 | 202 |
| 用例数 | 10 |
| 评审日期 | 2026-10-04 |
| 评审时长 | 20 分钟 |

---

## 1 作者讲解（5 min）

> **作者**：本期提交 4 个补测文件中的 PR3，主题是 `app/api/deps/user.py` 的 4 条生成器路径覆盖。

**讲解要点**：
1. **目标**：把 `app/api/deps/user.py` 覆盖率从 83% 提升至 ≥90%
2. **测试架构**：内部 stub（`_StubSession`、`_FakeUserService`、`_RecordingContainer`）+ 真实容器集成（`test_*_real_*`）
3. **关键覆盖**：注入 session 复用、fallback 路径、NotImplementedError 兜底
4. **作者提醒**：`_StubSession` 是 SQLAlchemy Session 子类但跳过 `__init__`，已加注释说明

---

## 2 评审走查（15 min）

### 2.1 正确性 🔍

**问题 3.1（🔴 阻塞）**：`_StubSession` 跳过 `Session.__init__` 是不严谨的反模式

```python
class _StubSession(Session):
    def __init__(self) -> None:
        # 跳过父类 __init__ 的实际绑定逻辑，仅维持 identity 用途。
        self._closed = False

    def close(self) -> None:  # pragma: no cover - 桩方法
        self._closed = True
```

- **问题**：
  - SQLAlchemy `Session.__init__` 执行 `_initialize_state` 等绑定逻辑，跳过后内部状态机不一致
  - 桩 `close()` 与真实 Session 关闭机制不同，可能影响「依赖函数是否 close 注入 session」的断言可靠性
  - `isinstance(stub, Session)` 之所以能通过，**仅因为继承关系**——但 stub 缺乏 `Session` 内部协议
- **评审意见**：
  - 🔴 **阻塞**：这是技术债务。任何调用 `stub.bind(...)` 或 `stub.flush()` 的代码都会抛 `AttributeError`，未来扩展风险高。
  - 应改用 `unittest.mock.MagicMock(spec=Session)` —— **spec=Session 会校验方法签名，且自动满足 isinstance 判定**。

**问题 3.2（🟠 重要）**：`_FakeUserService` 不是 `AuthService` 子类，可能误导真实契约

```python
class _FakeUserService:
    def __init__(self, session: object, marker: str) -> None:
        self.session = session
        self.marker = marker
```

- L98 `assert isinstance(service, _FakeUserService)` 通过，但**与生产代码契约无关**
- `AuthService` 有完整接口契约（`get_user_by_id`、`create_user` 等），`_FakeUserService` 是「最小 stand-in」
- ⚠️ **重要**：这可能导致「测试通过但生产报错」。应让 `_FakeUserService` 继承 `AuthService` 或用真实容器
- L120-143 已有真实容器测试，但仅 1 项覆盖真实路径，**其他 9 项都是 stub**

**问题 3.3（🟠 重要）**：测试用例 `test_get_user_service_does_not_close_injected_session` 的断言可靠性

```python
def test_get_user_service_does_not_close_injected_session(self) -> None:
    ...
    gen.close()
    # 注入的 session 在依赖生命周期内不能被关闭
    assert injected_session._closed is False
```

- 真实 `Session.close()` 会调用 `_close_impl` 等机制，但 `_StubSession.close()` 只设置 `self._closed = True`
- **生产代码中**，`with container.get_session() as managed_session:` 会调用**真实** Session 的 `close()`，与 stub 行为不一致
- 🟠 **重要**：应使用 `MagicMock(spec=Session)` + 断言 `injected_session.close.assert_not_called()` —— 直接验证方法未调用，比验证内部状态更可靠

### 2.2 设计 📐

**问题 3.4（🟠 重要）**：`_RecordingContainer` 内部状态管理与生产 `AppContainer` 行为差异

```python
class _RecordingContainer:
    def __init__(self) -> None:
        self.created_services: list[tuple[object, str]] = []
        self.managed_session_factory_calls = 0
        self._session_pool: list[_StubSession] = []
        self._marker_cycle = iter(["marker-A", "marker-B", "marker-C"])

    @contextmanager
    def get_session(self) -> Generator[_StubSession, None, None]:
        self.managed_session_factory_calls += 1
        stub = _StubSession()
        self._session_pool.append(stub)
        try:
            yield stub
        finally:
            stub.close()
```

- **优点**：完整 mock 容器行为，便于隔离测试
- **问题**：
  - `_marker_cycle = iter(["marker-A", "marker-B", "marker-C"])` 用迭代器驱动 marker，但 `next()` 在第 4 次会抛 `StopIteration`——**隐式错误**。
  - `_session_pool.append(stub)` 仅记录，**无并发安全**，但生产中 `AppContainer.get_session()` 是 contextmanager，**多个 session 不能共享**。
- 🟠 **重要**：建议 `_marker_cycle` 改为循环迭代（`itertools.cycle`），避免隐式 StopIteration

**问题 3.5（🟡 建议）**：3 个测试类 + 多个内部辅助类导致文件结构复杂

- 当前 202 行内含 4 个内部辅助类 + 3 个测试类
- ⚠️ **建议**：可考虑抽取到 `tests/unit/api/conftest.py` 或 `tests/unit/api/_deps_helpers.py`，便于其他 deps 测试复用

### 2.3 可读性 📖

**问题 3.6**：类名 / 方法名是否清晰？

- ✅ 类名 `TestGetUserServiceDirectSessionPath`、`TestGetUserServiceFallbackPath` 主题清晰
- ✅ 方法名含「4 条路径」明示
- ⚠️ **建议**：L120 `test_get_user_service_returns_real_auth_service_when_session_is_real_session` 名字含「real」但内部有 stub（`fake_request`），可考虑改为 `..._with_real_container_and_real_session`

**问题 3.7**：L11-12 注释「`test_app_lifespan.py` 已经覆盖了路径 2、3」需核实

```python
"""`test_app_lifespan.py` 已经覆盖了路径 2、3；本文件专门补全 路径 1 与 路径 4，
并对路径 2 的 fallback 行为做更严格的契约校验（session 复用、Session 生命周期）。"""
```

- ⚠️ **建议**：评审时检查 `test_app_lifespan.py` 实际覆盖范围，确认依赖性，避免重复或缺失

### 2.4 健壮性 🛡️

**问题 3.8**：异常路径覆盖

- ✅ `test_get_user_service_raises_not_implemented_when_request_is_none`（路径 4）
- ✅ `test_get_user_service_raises_not_implemented_when_app_state_lacks_container`（路径 3）
- ✅ `test_get_user_service_raises_not_implemented_when_app_attr_is_none`（路径 3 变体）
- ⚠️ **建议**：缺 `request.app.state.container` 是另一用户 session 的越权场景（虽然 deps 层不直接处理越权，但应明确边界）

**问题 3.9（🟠 重要）**：路径 3 中 `del fake_request.app.state.container` 的隐式行为

```python
def test_get_user_service_raises_not_implemented_when_app_state_lacks_container(self) -> None:
    fake_request = MagicMock(spec=Request)
    del fake_request.app.state.container  # ← 删除 container 属性
    with pytest.raises(NotImplementedError):
        next(get_user_service(request=fake_request, session=None))
```

- `del fake_request.app.state.container` 是 **MagicMock 的隐式行为**——删除后 `hasattr(...)` 返回 False
- 🟠 **重要**：测试依赖 MagicMock 的内部行为，**生产代码中** `request.app.state.container` 在 AppLifespan 中**必须**挂载，否则 NIE 异常
- 评审时检查 `app/api/app_lifespan.py::lifespan` 是否确保挂载

### 2.5 安全与性能 🔐

**问题 3.10**：性能开销？

- ✅ 10 个用例 < 0.5s 完成，**性能优异**

**问题 3.11**：依赖函数是否安全处理恶意 input？

- 当前测试**未覆盖** `session` 是恶意对象（如 pickle 序列化数据）的场景
- ⚠️ **建议**：增加 `session` 是异常对象（如 `MagicMock(spec=...)` 不通过 isinstance 校验）的用例

### 2.6 测试充分性 🧪

| 维度 | 覆盖情况 | 评价 |
| --- | :---: | --- |
| 路径 1（注入 Session） | 3 项 | ✅ 完整 |
| 路径 2（fallback） | 2 项 | ✅ 完整 |
| 路径 3（无 container） | 2 项 | ✅ 完整 |
| 路径 4（request=None） | 1 项 | ✅ 完整 |
| 集成（真实容器） | 2 项 | ✅ 完整 |
| session 生命周期 | 3 项 | ✅ 完整 |

### 2.7 可维护性 🔧

**问题 3.12**：`_StubSession` 维护成本

- 🔴 一旦 SQLAlchemy 升级或 Session 内部机制变更，stub 可能与真实 Session 行为脱节
- ⚠️ **建议**：改用 `MagicMock(spec=Session)`，spec 自动跟随 SQLAlchemy 接口变更

### 2.8 文档与追溯 📚

**问题 3.13**：是否关联 P 编号 / 缺陷编号？

- ✅ 文件 docstring 明示「四条关键路径」
- ⚠️ **建议**：类名/方法名可加入 P0-3（接口依赖层覆盖率提升）编号

---

## 3 问题清单

| ID | 级别 | 维度 | 描述 | 建议处理 |
| ---: | :---: | --- | --- | --- |
| **PR3-01** | **🔴 阻塞** | 正确性 | `_StubSession` 跳过 `Session.__init__` 是反模式，与真实 Session 状态机不一致 | 必须改用 `MagicMock(spec=Session)` |
| **PR3-02** | **🟠 重要** | 正确性 | `_FakeUserService` 不是 `AuthService` 子类，9/10 用例未覆盖真实契约 | 改用真实容器或 stub 继承 `AuthService` |
| **PR3-03** | **🟠 重要** | 正确性 | `assert injected_session._closed is False` 依赖 stub 内部状态而非 close 方法调用 | 改用 `injected_session.close.assert_not_called()` |
| **PR3-04** | **🟠 重要** | 设计 | `_RecordingContainer._marker_cycle` 用 `iter([...])` 隐式 StopIteration | 改用 `itertools.cycle` |
| **PR3-05** | **🟠 重要** | 健壮性 | `del fake_request.app.state.container` 依赖 MagicMock 行为，需核实生产 AppLifespan | 评审时检查 lifespan 代码 |
| PR3-06 | 🟡 建议 | 设计 | 多个内部辅助类可抽取到 conftest | M1 里程碑 |
| PR3-07 | 🟡 建议 | 可读性 | `real_auth_service` 测试名含「real」但内部用 stub | 重命名为 `_with_real_container` |
| PR3-08 | 🟡 建议 | 可维护性 | `_StubSession` 对 SQLAlchemy 升级敏感 | 改用 MagicMock(spec=Session) 后消除 |

---

## 4 评审结论

> **❌ 不通过（必须修复 1 个阻塞 + 4 个重要问题）**

### 4.1 不通过理由

1. **PR3-01（🔴 阻塞）**：`_StubSession` 是反模式，与真实 SQLAlchemy Session 状态机不一致。
   一旦 SQLAlchemy 升级或 Session 内部机制变更，stub 行为可能与生产脱节，且当前对 `close()` 的断言**不严格**。

### 4.2 修改后通过建议

修复阻塞与重要问题后，本 PR 可重新提交评审：

1. **PR3-01 修复**：删除 `_StubSession`，改用 `MagicMock(spec=Session)`：

```python
# 之前
class _StubSession(Session):
    def __init__(self) -> None:
        self._closed = False
    def close(self) -> None:
        self._closed = True

injected_session = _StubSession()
# ...
assert injected_session._closed is False

# 之后
injected_session = MagicMock(spec=Session)
# ...
injected_session.close.assert_not_called()
```

2. **PR3-02 修复**：`_FakeUserService` 继承 `AuthService` 或增加更多真实容器测试（最少 5/10 用例用真实容器）。

3. **PR3-03 修复**：close 断言改用 `assert_not_called()`。

4. **PR3-04 修复**：`_marker_cycle = itertools.cycle([...])`。

5. **PR3-05 修复**：评审时同步审 `app/api/app_lifespan.py::lifespan` 是否确保 container 挂载（作为评审联动）。

### 4.3 合并授权

- 主评审 SecLead：❌ 不通过
- 副评审 TechLead：❌ 不通过（同意阻塞意见）
- **不可合并，需作者修改后重新评审**

### 4.4 关键评审讨论点

> 「**`_StubSession` 是否可接受**」是核心争论点：
> - 支持方：测试隔离、性能、便于控制
> - 反对方：与生产 Session 状态机不一致、扩展风险高、断言不严格
>
> 评审人建议**采用反方意见**——`MagicMock(spec=Session)` 在保留测试隔离的同时，避免与真实 Session 行为脱节。这是 pytest 标准用法。