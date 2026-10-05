# PR2 评审记录 · 错误契约补测

| 项 | 内容 |
| --- | --- |
| PR 编号 | #N+1 |
| 文件 | `backend/tests/unit/core/test_errors_supplemental.py` |
| 行数 | 291 |
| 用例数 | 44 |
| 评审日期 | 2026-10-04 |
| 评审时长 | 25 分钟 |

---

## 1 作者讲解（5 min）

> **作者**：本期提交 4 个补测文件中的 PR2，主题是 `app/core/errors.py` 的错误契约测试。
>
> - 错误码 ↔ 状态码映射唯一性
> - 上游异常链路保留（防 P0-2）
> - 参数注入语义（attempt_item_id / knowledge_point_id / record_id）

**讲解要点**：
1. **目标**：覆盖率从 91% → 100%
2. **测试架构**：纯类实例化（无 IO / 无 DB），跑得快（44 用例 0.08s）
3. **重要发现**：测试中**主动锁住**了一个已知 bug 行为（`AttemptItemNotFoundError` 的 `detail` 别名覆盖 `attempt_item_id` 注入）

---

## 2 评审走查（20 min）

### 2.1 正确性 🔍

**问题 2.1（🔴 阻塞）**：L232-242 `test_attempt_item_id_with_detail_alias_kwargs` **锁住了一个 bug**

```python
def test_attempt_item_id_with_detail_alias_kwargs(self) -> None:
    err = AttemptItemNotFoundError(
        message="明细缺失",
        detail={"context": "retry"},
        attempt_item_id="item-1",
    )
    assert err.details["context"] == "retry"
    # 当前实现下 attempt_item_id 注入会被 detail 别名覆盖（已知行为，需后续评审）
```

- **根本原因**：在 `app/core/errors.py:1042-1051` 中，子类构造 `merged_details = dict(detail or details or {})` 后再注入 `attempt_item_id`，但调用 `super().__init__` 时**同时传入 `details=merged_details` 与 `detail=detail`**。
- **父类 AppError L40**：`actual_details = detail if detail is not None else (details or {})`，**优先用 `detail` 别名**。
- **结果**：子类合并的 `merged_details` 在父类初始化时被 `detail` 覆盖，导致 `attempt_item_id` 注入丢失。
- **评审意见**：
  - 🔴 **阻塞**：测试**不应锁住 bug 行为**。这是「文档化失败」的反模式。
  - 应当：
    1. 修复 `AttemptItemNotFoundError.__init__`（与 `MasteryRecordNotFoundError`、`WrongRecordNotFoundError` 同源问题）
    2. 然后把测试改为「期望合并语义」
  - 或明确归类为「已知缺陷」+ 添加 `pytest.xfail` + 登记 JIRA / 缺陷单，**但不**在 PR 中混入。

**问题 2.2**：14 项参数化映射**仅覆盖 14/44 错误类 = 32%**

| 模块 | 错误类 | 是否覆盖 |
| --- | --- | :---: |
| Auth | AuthenticationError, PermissionDeniedError | ✅ 2/2 |
| Storage | StorageError 系列 | ✅ 3/3 |
| OCR | OCRError 系列 | ✅ 4/5（缺 OCRReshootExceededError 别名检查） |
| Embedding | EmbeddingError 系列 | ❌ 0/3 |
| Search | SearchError | ❌ 0/1 |
| LLM | LLMError 系列 | ❌ 0/4 |
| Queue | QueueError 系列 | ❌ 0/2 |
| Idempotency | IdempotencyConflictError | ✅ 1/2（缺 IdempotencyKeyInvalidError） |
| Material | Material 系列 | ❌ 0/4 |
| Knowledge | Knowledge 系列 | ❌ 0/4 |
| Question | Question 系列 | ❌ 0/2 |
| Practice | PracticeNotFoundError, PracticeStatusError, AttemptItemNotFoundError | ✅ 3/5 |
| Grading | Grading 系列 | ❌ 0/3 |
| Diagnosis | DiagnosisReportNotFoundError | ❌ 0/1 |
| Mastery/Wrong | MasteryRecordNotFoundError, WrongRecordNotFoundError | ✅ 2/2 |
| Folder | Folder 系列 | ✅ 2/2 |

- ⚠️ **重要**：14/44 覆盖度不符合「错误契约完备」目标。建议追加 30 项参数化（最少）。
- 🟡 **建议**：可以分批补，本 PR 优先处理 `detail` 别名 bug 修复 + 增加高优先级错误类（Material / Knowledge / Practice / Question 主链路）

**问题 2.3**：L82 `test_storage_error_serialization` 仅校验 `code` 字段，**未校验完整 `to_dict()` 契约**

- 当前断言 `payload["code"] == 30003` 与 `"endpoint" in payload["details"]`
- ⚠️ **建议**：应同时断言 `payload["message"]` 与 `payload["details"]["endpoint"]` 的精确值

### 2.2 设计 📐

**问题 2.4**：14 项参数化 vs 单用例的权衡

- ✅ 14 项用 `@pytest.mark.parametrize` 表达，单一断言路径
- ⚠️ **建议**：建议增加「错误码冲突检测」测试——遍历所有错误类，确认 `error_code` 唯一

**问题 2.5**：异常链路测试用 `try/except` 包装是否规范？

```python
def test_authentication_error_preserves_cause_chain(self) -> None:
    upstream = ValueError("上游 JWT 库抛出底层异常")
    try:
        raise AuthenticationError(message="凭证签名无效") from upstream
    except AuthenticationError as err:
        assert err.__cause__ is upstream
```

- ✅ 设计合理：用 `try/except` 验证 `__cause__` 链路是 Python 标准用法
- ⚠️ **建议**：可改用 `pytest.raises` 配合 `.value.__cause__` 访问，更符合 pytest 惯例：

```python
with pytest.raises(AuthenticationError) as exc_info:
    raise AuthenticationError(message="凭证签名无效") from upstream
assert exc_info.value.__cause__ is upstream
```

### 2.3 可读性 📖

**问题 2.6**：类名 / 方法名是否清晰？

- ✅ 类名 `TestStorageErrorContract`、`TestOCRErrorContract`、`TestErrorCausePreservation` 主题清晰
- ✅ 方法名 `test_error_code_status_mapping_is_unique` 含期望行为

**问题 2.7**：L286 文档引用「思考模式模型上结构化输出不可用」令人困惑

```python
"""上游异常原因保留契约：防 P0-2「思考模式模型上结构化输出不可用」中的错误原因丢失。"""
```

- 🔴 **阻塞**：与测试用例语义无关的措辞不应出现在 docstring。**重写为与错误契约相关**的描述。
- 评审建议：「防 P0-2 `raise from` 链路中上游原因丢失」即可，无需引用模型相关术语。

### 2.4 健壮性 🛡️

**问题 2.8**：异常类子类的继承关系是否都被测试？

- ✅ `assert isinstance(err, StorageError)` 与 `assert isinstance(err, AppError)` 在多个用例中验证
- ⚠️ **建议**：可以为所有 14 项添加 `isinstance(err, AppError)` 断言，确保多态契约

**问题 2.9**：`to_dict()` 序列化方法是否覆盖所有路径？

- 当前仅 1 项断言（L82）覆盖 `to_dict()`，14 项参数化 L281 仅断言 `payload["code"]`
- ⚠️ **建议**：应增加「`to_dict()` 返回值完整字段校验」测试，断言 `{"code", "message", "details"}` 三个键固定存在

### 2.5 安全与性能 🔐

**问题 2.10**：性能开销？

- ✅ 44 个用例 0.08s 完成（纯类实例化），**性能优异**

**问题 2.11**：是否有信息泄露风险？

- `details` 字典是否允许 PII / 敏感字段？当前测试**没有验证** `details` 内容合法性
- ⚠️ **建议**：可增加一条「`details` 严禁包含 `password`、`token`、`secret` 等敏感字段」的契约测试（基于 AppError 文档声明）

### 2.6 测试充分性 🧪

**问题 2.12**：错误类覆盖率

| 维度 | 覆盖情况 | 评价 |
| --- | :---: | --- |
| 错误类构造 | 14/44 (32%) | ⚠️ 不完整 |
| 错误码 ↔ 状态码映射 | 14 项参数化 | ⚠️ 不完整 |
| 异常链路保留 | 4 项 | ✅ 完整 |
| 参数注入语义 | 8 项 | ✅ 完整 |
| `to_dict()` 序列化 | 1 项 | ⚠️ 不充分 |
| `code` / `detail` 别名 | 3 项 | ✅ 完整 |
| 序列化完整性 | 0 项 | ⚠️ 缺失 |

### 2.7 可维护性 🔧

**问题 2.13**：未来新增错误类时是否易扩展？

- ✅ 参数化形式便于新增（追加一行即可）
- ⚠️ **建议**：将 14 项参数化抽取为常量表（`_ERROR_CODE_MAPPING`），便于跨测试复用

### 2.8 文档与追溯 📚

**问题 2.14**：是否关联 P 编号 / 缺陷编号？

- ✅ 文件 docstring 明示「防 P0-2 错误原因丢失」、「评审清单 3.1：① 算法核 / ③ 错误契约」
- ✅ 类名 `TestErrorCodeStatusMappingUniqueness` 含契约描述

---

## 3 问题清单

| ID | 级别 | 维度 | 描述 | 建议处理 |
| ---: | :---: | --- | --- | --- |
| **PR2-01** | **🔴 阻塞** | 正确性 | `test_attempt_item_id_with_detail_alias_kwargs` 锁住 bug 行为而非期望合并 | 必须修复产品代码或重写测试 |
| **PR2-02** | **🔴 阻塞** | 可读性 | L286 docstring 含「思考模式模型上结构化输出不可用」无关术语 | 必须重写 |
| PR2-03 | 🟠 重要 | 正确性 | 14/44 错误类映射覆盖度仅 32%，不符合契约完备目标 | 至少追加 Material/Knowledge/Practice/Question 主链路 |
| PR2-04 | 🟡 建议 | 正确性 | `to_dict()` 仅 1 项覆盖，缺序列化字段完整性测试 | 后续 PR 补充 |
| PR2-05 | 🟡 建议 | 健壮性 | 缺敏感字段检查（password/token/secret） | 后续 PR 补充 |
| PR2-06 | 🟡 建议 | 设计 | try/except vs pytest.raises.__cause__ 风格统一 | 本次微调 |
| PR2-07 | 🟡 建议 | 可维护性 | 14 项参数化抽取为常量表 | 后续 PR |

---

## 4 评审结论

> **❌ 不通过（必须修复 2 个阻塞问题）**

### 4.1 不通过理由

1. **PR2-01（🔴 阻塞）**：测试锁住 bug 行为（`detail` 别名覆盖 `attempt_item_id` 注入）。
   这是产品代码 bug，不应在测试中「文档化失败」。
2. **PR2-02（🔴 阻塞）**：docstring 含与测试无关的措辞，影响可维护性。

### 4.2 修复方案

**PR2-01 修复路径**（二选一）：
- **方案 A（推荐）**：修复 `AttemptItemNotFoundError.__init__`，让 `merged_details` 真正合并并绕过父类的 `detail` 别名陷阱。例如改为：
  ```python
  super().__init__(
      error_code=error_code,
      message=message,
      status_code=status_code,
      details=merged_details,
      # 不传 detail，让父类用 details
  )
  ```
  注意 `MasteryRecordNotFoundError` 与 `WrongRecordNotFoundError` 同样需要检查。

- **方案 B**：测试改用 `pytest.xfail` + 缺陷单 JIRA-XXX，标注为「已知 bug 待修复」。**不推荐**——会让测试失去「锁住行为」的意义。

**PR2-02 修复路径**：重写 L286 docstring 为「上游异常原因保留契约：防 P0-2 `raise from` 链路中上游原因丢失」。

### 4.3 修改后通过建议

修复上述 2 个阻塞 + 1 个重要问题后，本 PR 可重新提交评审：
1. 修复 `AttemptItemNotFoundError` 等 3 个错误类的 `detail` 别名 bug
2. 重写 docstring
3. 增加至少 Material/Knowledge/Practice/Question 主链路错误类的映射测试（+10 项）

### 4.4 合并授权

- 主评审 Reviewer：❌ 不通过
- 加签 SecLead：❌ 不通过（同意阻塞意见）
- **不可合并，需作者修改后重新评审**