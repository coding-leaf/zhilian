# PR1 评审记录 · P1-4 folder_id 回归保护

| 项 | 内容 |
| --- | --- |
| PR 编号 | #N |
| 文件 | `backend/tests/unit/repositories/test_material_repo_filter.py` |
| 行数 | 323 |
| 用例数 | 17 |
| 评审日期 | 2026-10-04 |
| 评审时长 | 20 分钟 |

---

## 1 作者讲解（5 min）

> **作者**：本期提交 4 个补测文件中的 PR1，主题是 `app/repositories/material.py`
> 的 folder_id 聚合路径与状态过滤路径补测。

**讲解要点**：
1. **目标**：补齐 `app/repositories/material.py` 中 P1-4 修复后的回归保护 + 状态过滤未覆盖分支
2. **测试架构**：使用内存 SQLite + 真实 SQLAlchemy 引擎（不 mock SQL 谓词）
3. **覆盖目标**：97% → 100%
4. **关键测试**：`TestP1BugRegression` 锁住 P1-4 修复后的 NULL 谓词聚合行为

---

## 2 评审走查（15 min）

### 2.1 正确性 🔍

**问题 1.1**：第 102 行 `items_total` 是否反映 `list_materials_by_user` 真实行为？

- ✅ `list_materials_by_user(user_id, unclassified=True)` 返回 `(items, total)` 元组
- ✅ P1-4 修复后 `count_stmt` 走 `_apply_folder_filter` 严格保留 `folder_id IS NULL`
- ⚠️ **建议**：第 102 行 `factory.repo.list_materials_by_user(user_id=user_id, unclassified=True)` 返回 `(items, total)`，但 L107 只断言 `total == 1`，未断言 `items` 的元素次序是否稳定

**问题 1.2**：P1-4 修复回归用例是否真的锁住了正确行为？

- ✅ `TestP1BugRegression.test_p1_4_regression_unclassified_aggregate_must_not_miss_null_folder` 创建 6 个 `folder_id=None` + 4 个 `folder_id=<some_uuid>`，断言返回 6 个
- ⚠️ **建议**：可以补充一个「10 个全部已归属资料」的负向用例，确保返回 0 个，避免后续误改谓词导致「未分类+已归属混合场景」通过而「纯已归属」用例失败

### 2.2 设计 📐

**问题 1.3**：`_TestDataFactory` 内部辅助类是否应该作为 conftest fixture？

- 当前在文件内嵌套定义 `_TestDataFactory`，**不污染全局 fixture**
- ⚠️ **建议**：若后续还有 material 测试需要复用，建议抽取到 `tests/unit/repositories/conftest.py`
- 当前设计**可接受**，不阻塞

**问题 1.4**：`session` fixture 是否应该使用 `scope="function"` 共享？

- 当前 `session` 是 function-scope fixture，每个测试创建独立 SQLite 引擎
- ✅ 测试隔离性更好
- ⚠️ **建议**：可考虑提升为 module-scope fixture 减少引擎创建开销（但当前 17 个用例只跑 0.57s，无性能问题）

### 2.3 可读性 📖

**问题 1.5**：命名是否清晰？

- ✅ 类名 `TestApplyFolderFilter`、`TestP1BugRegression`、`TestSingleStatusCounting` 主题清晰
- ✅ 方法名 `test_p1_4_regression_unclassified_aggregate_must_not_miss_null_folder` 含 P 编号 + 期望行为
- ⚠️ **建议**：第 90 行 `test_unclassified_only_returns_materials_with_null_folder` 与第 288 行 `test_p1_4_regression_unclassified_aggregate_must_not_miss_null_folder` 命名相似，但前者是分支测试、后者是回归测试——**容易混淆**

### 2.4 健壮性 🛡️

**问题 1.6**：异常路径覆盖是否完整？

- ✅ `TestMoveFolder.test_move_folder_returns_none_when_material_missing` 覆盖实体不存在
- ✅ `TestMoveFolder.test_move_folder_returns_none_for_other_user_material` 覆盖跨租户越权
- ⚠️ **建议**：缺少 `archived=True` 资料与 `move_folder` 的交互测试（当前 `archived` 资料仍能被移动？）

**问题 1.7**：边界用例是否覆盖？

- ⚠️ **建议**：缺 `folder_id` 是 `archived=True` 课程的归属资料是否被移仓的用例
- ⚠️ **建议**：缺 `move_folder(material_id=..., folder_id=<另一用户 archived_folder_id>`) 越权测试

### 2.5 安全与性能 🔐

**问题 1.8**：SQL 注入风险？

- ✅ 所有 SQL 通过 SQLAlchemy ORM 参数化查询，**无 SQL 注入风险**

**问题 1.9**：性能开销？

- ✅ 17 个用例 0.57s 完成，**性能合理**

### 2.6 测试充分性 🧪

**问题 1.10**：等价类 / 边界值 / 错误推测覆盖度？

| 维度 | 覆盖情况 | 评价 |
| --- | :---: | --- |
| 等价类（unclassified/folder_id/default） | 3/3 | ✅ 完整 |
| 边界（空集合 / 空 tuple） | 2/2 | ✅ 完整 |
| 错误推测（实体不存在 / 跨租户） | 2/2 | ✅ 完整 |
| 路径覆盖（3 个分支 + 越权） | 5/5 | ✅ 完整 |
| 状态过滤（单值/多值/互斥） | 3/3 | ✅ 完整 |

### 2.7 可维护性 🔧

**问题 1.11**：未来重构时是否易于调整？

- ✅ 用 `_TestDataFactory` 抽象创建逻辑，未来修改 Model 字段时只需改一处
- ⚠️ **建议**：`_TestDataFactory.create_material` 硬编码 `file_format="pdf"` 与 `file_size=1024`，未来如需测试其他格式需修改

### 2.8 文档与追溯 📚

**问题 1.12**：是否关联 P 编号 / 缺陷编号？

- ✅ 文件 docstring 明示「P1-4 关键路径」「未覆盖行（实测 6/207）」
- ✅ 类名 `TestP1BugRegression` 与方法名 `test_p1_4_regression_*` 含 P 编号

---

## 3 问题清单

| ID | 级别 | 维度 | 描述 | 建议处理 |
| ---: | :---: | --- | --- | --- |
| PR1-01 | 🟡 建议 | 正确性 | 缺「全部已归属资料」负向用例 | 后续 PR 补充 |
| PR1-02 | 🟡 建议 | 设计 | `_TestDataFactory` 与 `session` fixture 可抽取到 conftest | M1 里程碑考虑 |
| PR1-03 | 🟡 建议 | 可读性 | L90 与 L288 命名相似，容易混淆 | 在 L288 docstring 中明示「P1-4 回归」 |
| PR1-04 | 🟡 建议 | 健壮性 | 缺 `archived=True` 课程资料被移动的用例 | 后续 PR 补充 |
| PR1-05 | 🟡 建议 | 可维护性 | `_TestDataFactory.create_material` 硬编码 file_format/file_size | 提升为参数 |

> **无阻塞问题（🔴）**，**无重要问题（🟠）**。

---

## 4 评审结论

> **✅ 通过（with minor suggestions）**

### 4.1 通过理由

1. **0 阻塞 / 0 重要问题**——5 条建议均不阻塞
2. **正确性**：P1-4 回归用例 `test_p1_4_regression_unclassified_aggregate_must_not_miss_null_folder` 锁住了正确行为
3. **安全**：跨租户越权测试覆盖（`test_move_folder_returns_none_for_other_user_material`）
4. **设计**：`_TestDataFactory` 抽象创建，可维护性好
5. **追溯**：P1-4 编号贯穿文件、方法、注释

### 4.2 后续行动

| 建议 ID | 责任方 | 时机 |
| --- | --- | --- |
| PR1-01 / PR1-04 | SecLead | M1 里程碑 |
| PR1-02 / PR1-05 | SecLead | M1 里程碑 |
| PR1-03 | 作者（可立即修改） | 本次 PR 后微调 |

### 4.3 合并授权

- 主评审 SecLead：✅ 已 approve
- 副评审 TechLead：✅ 已 approve
- **可合并**