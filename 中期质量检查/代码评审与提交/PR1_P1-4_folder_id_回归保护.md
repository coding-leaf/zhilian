# PR #N · P1-4 folder_id 聚合回归保护

## 1 变更摘要

> **新增 1 个测试文件**，**0 修改**产品代码。
>
> 为 `app/repositories/material.py` 补齐 P1-4「个人页学习足迹统计口径漏算」回归保护与状态聚合 + 移仓越权测试。

| 项 | 内容 |
| --- | --- |
| 任务编号 | **P1-4**（中期质量检查评审清单） |
| 文件 | `backend/tests/unit/repositories/test_material_repo_filter.py` |
| 新增行数 | **323 行** |
| 新增用例 | **17 个** |
| 覆盖目标 | `app/repositories/material.py`（97% → **100%**） |
| 评审时长预估 | **15-20 分钟** |

## 2 关联需求 / 缺陷

| 编号 | 类型 | 关联说明 |
| --- | --- | --- |
| **P1-4** | 缺陷回归 | 个人页学习足迹聚合查询时 `folder_id IS NULL` 谓词被错误改写，导致未分类资料被漏算 |
| P0-3 | 任务 | 中期质量检查 P0 核心模块覆盖率 ≥ 90% |
| FR-58 | 需求 | 资料按课程文件夹聚合（详见 `docs/PRD.md`） |

## 3 变更内容

### 3.1 文件清单

| 操作 | 路径 | 行数 |
| --- | --- | ---: |
| ➕ 新增 | `backend/tests/unit/repositories/test_material_repo_filter.py` | 323 |

### 3.2 测试用例分布

| 测试类 | 用例数 | 覆盖路径 |
| --- | ---: | --- |
| `TestApplyFolderFilter` | 4 | `_apply_folder_filter` 三分支：unclassified / folder_id / 默认 |
| `TestStatusAggregationFilter` | 3 | `statuses` 多状态聚合 vs `status` 单值过滤互斥 |
| `TestMoveFolder` | 4 | `move_folder` 主路径 + 越权拒访问 + 实体不存在 |
| `TestP1BugRegression` | 2 | **P1-4 回归保护**：未分类聚合严格按 NULL 谓词匹配 |
| `TestSingleStatusCounting` | 2 | `list_materials_by_user` 单值 status count_stmt 路径 |
| `TestListSnippetsByIds` | 2 | `list_snippets_by_ids` 空集合早返回 |

### 3.3 关键测试用例（评审请聚焦）

```python
def test_p1_4_regression_unclassified_aggregate_must_not_miss_null_folder(self, session):
    """P1-4 回归：未分类聚合查询必须严格返回 folder_id IS NULL 的所有行，不能漏算。"""
    factory = _TestDataFactory(session)
    user_id = uuid.uuid4()
    folder = factory.create_folder(user_id=user_id, name="高数")
    unclassified_mats = [
        factory.create_material(user_id=user_id, title=f"未分类{i}.pdf", folder_id=None)
        for i in range(6)
    ]
    classified_mats = [
        factory.create_material(user_id=user_id, title=f"已归属{i}.pdf", folder_id=folder.id)
        for i in range(4)
    ]
    items, total = factory.repo.list_materials_by_user(user_id=user_id, unclassified=True)
    item_ids = {item.id for item in items}
    assert len(items) == 6
    assert all(m.id in item_ids for m in unclassified_mats)
    assert all(m.id not in item_ids for m in classified_mats)
    assert total == 6
```

## 4 测试情况

### 4.1 本地

```bash
$ uv run pytest tests/unit/repositories/test_material_repo_filter.py -v
========================= 17 passed in 0.57s =========================
```

### 4.2 全量回归

```bash
$ uv run pytest tests --cov=app.repositories.material --cov-report=term-missing
app\repositories\material.py     207      0   100%
```

覆盖率：**97% → 100%**（**+3 个百分点**，6 行未覆盖 → 0 行未覆盖）。

### 4.3 未覆盖行（已全部消灭）

| 行 | 内容 | 覆盖用例 |
| --- | --- | --- |
| L157 | `status` 单值过滤 | `test_status_single_value_filter` |
| L198 | `_apply_folder_filter(unclassified=True)` 分支 | `test_unclassified_only_returns_materials_with_null_folder` |
| L200 | `_apply_folder_filter(folder_id=<uuid>)` 分支 | `test_folder_id_filters_materials_to_specific_folder` |
| L268 | `count_stmt` 单值 status 过滤 | `test_single_status_count_total_matches_filtered_items` |
| L306 | `move_folder` 主路径 | `test_move_material_into_folder` |
| L721 | `list_snippets_by_ids` 空集合早返回 | `test_list_snippets_by_ids_with_empty_collection_returns_empty` |

## 5 影响范围

| 项 | 影响 |
| --- | --- |
| 产品代码 | **无修改**（仅新增测试） |
| 数据库 schema | **无修改** |
| API 接口 | **无变更** |
| 性能 | 测试 17 用例 0.57s，无回归 |
| 现有测试 | **无破坏**（全量 1496 用例 0 失败） |

## 6 风险点

| 风险 | 评级 | 缓解 |
| --- | :---: | --- |
| 与既有 `tests/unit/repositories/test_material_repo.py` 重复 | **低** | `_TestDataFactory` 命名隔离，无 fixture 冲突 |
| 测试断言对 `count_stmt` 路径有依赖 | **低** | 用 SQLite 内存库跑真实 SQL 引擎，无 mock |
| P1-4 回归用例与原 bug 描述一致性 | **低** | 用例注释明确「P1-4 回归」标记，便于后续审计 |
| `_apply_folder_filter` 内部 SQL 变更影响 | **极低** | 仅测试仓储层，不触及 SQLAlchemy 版本依赖 |

## 7 评审聚焦

> **请重点评审以下三处**：
> 1. `TestP1BugRegression` 两个用例是否锁住 P1-4 修复后的正确行为
> 2. `TestMoveFolder::test_move_folder_returns_none_for_other_user_material` 是否覆盖越权防御
> 3. `TestStatusAggregationFilter::test_statuses_takes_priority_over_single_status` 是否准确反映「`statuses` 优先于 `status`」的契约

## 8 自动检查（已通过）

| 项 | 命令 | 结果 |
| --- | --- | --- |
| ruff format | `uv run ruff format --check tests/unit/repositories/test_material_repo_filter.py` | ✅ 已格式化 |
| ruff check | `uv run ruff check tests/unit/repositories/test_material_repo_filter.py` | ✅ All checks passed |
| mypy | `uv run mypy tests/unit/repositories/test_material_repo_filter.py` | ✅ no issues |
| pytest | `uv run pytest tests/unit/repositories/test_material_repo_filter.py` | ✅ 17/17 passed |
| 全量覆盖率门禁 | `uv run coverage report --fail-under=80` | ✅ 91% |
| import-linter | `uv run lint-imports` | ✅ 5/5 KEPT |

## 9 关联

- **前置**：单测计划 §4 P0/P1 补测清单
- **后续**：PR #N+1（错误契约补测）、PR #N+2（deps/user.py 覆盖率）、PR #N+3（practice 状态机）
- **追溯**：中期质量检查《单测报告》《覆盖率报告》《缺陷单》《通过记录》