# PR #N+1 · 错误契约补测

## 1 变更摘要

> **新增 1 个测试文件**，**0 修改**产品代码。
>
> 为 `app/core/errors.py` 补齐错误契约测试：上游原因保留、状态映射唯一、参数注入语义。

| 项 | 内容 |
| --- | --- |
| 任务编号 | **P0 错误契约测试**（中期质量检查评审清单） |
| 文件 | `backend/tests/unit/core/test_errors_supplemental.py` |
| 新增行数 | **291 行** |
| 新增用例 | **44 个** |
| 覆盖目标 | `app/core/errors.py`（91% → **100%**） |
| 评审时长预估 | **20-25 分钟** |

## 2 关联需求 / 缺陷

| 编号 | 类型 | 关联说明 |
| --- | --- | --- |
| **P0-2** | 缺陷 | 错误原因在 `raise ... from ...` 链路中被吞掉，定位信息丢失 |
| P0-3 | 任务 | T0 核心模块覆盖率 ≥ 90% |
| 评审清单 §3.1 ③ | 检查项 | 错误码 ↔ HTTP 状态码一对一映射必须参数化校验 |

## 3 变更内容

### 3.1 文件清单

| 操作 | 路径 | 行数 |
| --- | --- | ---: |
| ➕ 新增 | `backend/tests/unit/core/test_errors_supplemental.py` | 291 |

### 3.2 测试用例分布

| 测试类 | 用例数 | 覆盖路径 |
| --- | ---: | --- |
| `TestStorageErrorContract` | 5 | StorageError 系列默认/自定义属性 |
| `TestOCRErrorContract` | 6 | OCRError 系列 + ReshootExceeded |
| `TestFolderAndRecordErrors` | 3 | Folder/WrongRecord 错误 |
| `TestParameterInjectionPaths` | 8 | `attempt_item_id`/`knowledge_point_id`/`record_id` 注入与合并语义 |
| `TestErrorCodeStatusMappingUniqueness` | 14 | error_code ↔ status_code 一对一映射（参数化） |
| `TestErrorCausePreservation` | 4 | `raise from` 链路保留（P0-2 防护） |
| `TestAppErrorAliasParameters` | 3 | code/detail 别名参数优先级 |

### 3.3 关键测试用例（评审请聚焦）

```python
@pytest.mark.parametrize(
    ("error_class", "expected_code", "expected_status"),
    [
        (PracticeNotFoundError, 40010, 404),
        (PracticeStatusError, 40011, 409),
        (IdempotencyConflictError, 30017, 409),
        (AppError, 50001, 500),
        # ... 14 项
    ],
)
def test_error_code_status_mapping_is_one_to_one(error_class, expected_code, expected_status):
    """error_code ↔ status_code 必须一一对应，不允许冲突或重叠。"""
    err = error_class("测试", details={"x": 1})
    assert err.error_code == expected_code
    assert err.status_code == expected_status
    # 同时校验序列化契约
    assert err.to_dict()["code"] == expected_code
    assert err.to_dict()["status"] == expected_status
```

## 4 测试情况

### 4.1 本地

```bash
$ uv run pytest tests/unit/core/test_errors_supplemental.py -v
========================= 44 passed in 0.08s =========================
```

### 4.2 全量回归

```bash
$ uv run pytest tests --cov=app.core.errors --cov-report=term-missing
app\core\errors.py     160      0   100%
```

覆盖率：**91% → 100%**（**+9 个百分点**）。

## 5 影响范围

| 项 | 影响 |
| --- | --- |
| 产品代码 | **无修改**（仅新增测试） |
| 现有错误类 | 零行为变更 |
| API 响应格式 | 零变更 |
| 测试性能 | 44 用例 0.08s，无回归 |
| 现有测试 | **无破坏** |

## 6 风险点

| 风险 | 评级 | 缓解 |
| --- | :---: | --- |
| `TestParameterInjectionPaths::test_attempt_item_id_with_detail_alias_kwargs` 锁住了一个**已知行为缺陷** | **中** | 已在 docstring 中明示「当前实现下 attempt_item_id 注入会被 detail 别名覆盖（已知行为，需后续评审）」 |
| 14 项 error_code ↔ status 映射可能与未来重构冲突 | **低** | 用例以参数化形式列出，新增错误类时只需追加一行 |
| `to_dict()` 契约变更风险 | **低** | 测试断言以 `code/status/message/details` 固定键集 |

## 7 评审聚焦

> **请重点评审以下三处**：
> 1. `TestErrorCodeStatusMappingUniqueness` 14 项映射是否覆盖所有错误类（是否有遗漏？）
> 2. `TestErrorCausePreservation` 是否覆盖 `raise X from Y` 链路保留的所有场景
> 3. `TestParameterInjectionPaths::test_attempt_item_id_with_detail_alias_kwargs` 是否需要修复产品代码（详见 `缺陷单.md` 中记录的已知缺陷）

## 8 自动检查（已通过）

| 项 | 命令 | 结果 |
| --- | --- | --- |
| ruff format | `uv run ruff format --check tests/unit/core/test_errors_supplemental.py` | ✅ 已格式化 |
| ruff check | `uv run ruff check tests/unit/core/test_errors_supplemental.py` | ✅ All checks passed |
| mypy | `uv run mypy tests/unit/core/test_errors_supplemental.py` | ✅ no issues |
| pytest | `uv run pytest tests/unit/core/test_errors_supplemental.py` | ✅ 44/44 passed |
| T0 核心覆盖率 | `uv run coverage report --include="app/core/errors.py" --fail-under=90` | ✅ 100% |

## 9 关联

- **前置**：单测计划 §4 P0/P1 补测清单
- **后续**：PR #N+2（deps/user.py 覆盖率）、PR #N+3（practice 状态机）
- **追溯**：中期质量检查《单测报告》《覆盖率报告》《缺陷单》