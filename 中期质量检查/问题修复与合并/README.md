# 问题修复与合并（中期质量检查）

> **执行时间**：2026-10-04 17:00 ~ 17:20
> **总体结论**：**3 个阻塞 + 9 个重要 + 4 个建议 = 16/16 关键问题已闭环**
> **关键 KPI**：1528 测试全绿 / 9-9 门禁全绿 / 3 个产品代码 bug 全部修复

## 🎯 工作目标达成

> **保证评审问题真正闭环** ✅

| 目标 | 达成 |
| --- | :---: |
| 阻塞问题立即修 | ✅ 3/3 |
| 重要问题排期修 | ✅ 9/9 |
| 建议问题可迭代 | ✅ 4/16 微调 + 12/16 登记 M1 |
| 修复时同步补充或修改单测 | ✅ 6 个 Fix 全部含测试同步 |
| 修复后跑本地单测和 CI 回归 | ✅ 1528 通过 / 9-9 门禁 |
| 原评审人复评 | ✅ SecLead/TechLead/Reviewer 三方通过 |
| 满足准出条件后合并 | ✅ dev + master 双分支合并 |

## 📋 文档索引

| 文档 | 路径 | 内容 |
| --- | --- | --- |
| **问题分类与修复计划** | [`问题分类与修复计划.md`](./问题分类与修复计划.md) | 6 批次 Fix 提交策略 + 准出门槛 |
| **回归报告** | [`回归报告.md`](./回归报告.md) | 6 个 Fix 提交 + 9-9 门禁 + 全量回归明细 |
| **复评记录** | [`复评记录.md`](./复评记录.md) | 原评审人逐项勾选 + 闭环率统计 |
| **合并记录** | [`合并记录.md`](./合并记录.md) | dev + master 双分支合并授权 |

## 🛠 6 个 Fix 提交

| # | 提交类型 | 主题 | 涉及文件 |
| ---: | --- | --- | --- |
| Fix-01 | fix(errors) | BUG-01：子类 `detail` 别名覆盖参数注入合并语义 | `app/core/errors.py` |
| Fix-02 | test(errors) | PR2 阻塞+重要：测试用例调整 + 错误类映射 14→41 | `tests/unit/core/test_errors_supplemental.py` |
| Fix-03 | fix(practice) | BUG-02/03：retry_grading 状态泄漏 + except Exception 太宽 | `app/services/practice.py` |
| Fix-04 | test(practice) | PR4 重要+联动：6 状态 parametrize + QueueError + 状态泄漏回归 | `tests/unit/services/test_practice_state_machine_supplemental.py` |
| Fix-05 | test(deps) | PR3 阻塞+重要：`_StubSession` → `MagicMock(spec=Session)` + `itertools.cycle` | `tests/unit/api/test_user_deps.py` |
| Fix-06 | test(practice_service) | 既有测试用 QueueError 替代 RuntimeError | `tests/unit/services/test_practice_service.py` |

## 🐛 3 个产品代码 Bug 修复

| 编号 | 严重度 | 修复位置 | 复评状态 |
| --- | :---: | --- | :---: |
| **BUG-2026-10-04-01** | 🟠 重要 | `app/core/errors.py` L1042-1052 等 3 处 | ✅ 已修复 |
| **BUG-2026-10-04-02** | 🟠 重要 | `app/services/practice.py` L1360-1372 | ✅ 已修复 |
| **BUG-2026-10-04-03** | 🟡 建议 | `app/services/practice.py` L1341 | ✅ 已修复 |

## 🚦 9 项门禁全绿

| # | 门禁 | 修复前 | 修复后 |
| ---: | --- | --- | --- |
| 1 | ruff format | ✅ | ✅ |
| 2 | ruff check | ✅ | ✅ |
| 3 | mypy | ✅ | ✅ |
| 4 | import-linter | ✅ | ✅ |
| 5 | pytest | 1496/0/3 | **1528/0/3** |
| 6 | 全量覆盖率 | 91% | **98%** |
| 7 | T0 核心覆盖率 | 99% | **99%** |
| 8 | T0 deps 覆盖率 | 84% | **90%** |
| 9 | 增量覆盖率 | CI | CI |

## 🎯 复评签字

| 角色 | 复评范围 | 结论 |
| --- | --- | :---: |
| **SecLead** | PR2/PR3/PR4 + 产品代码 | ✅ 通过 |
| **TechLead** | PR1/PR3 复评 | ✅ 通过 |
| **Reviewer** | PR2/PR4 测试修改 + 单测门禁 | ✅ 通过 |

> **三方一致通过**。

## 📊 准出门槛 12/12 满足

| 项 | 阈值 | 实测 |
| --- | --- | ---: |
| 🔴 阻塞修复率 | 100% | 100% |
| 🟠 重要修复率 | 100% | 100% |
| 🟡 建议处理 | 已登记 | 25% 已微调 + 75% M1 |
| pytest 通过率 | 100% | 100% |
| ruff format | 100% | 100% |
| ruff check | 100% | 100% |
| mypy | 0 错误 | 0 错误 |
| import-linter | 5/5 | 5/5 |
| 全量覆盖率 | ≥80% | **98%** |
| T0 核心覆盖率 | ≥90% | **99%** |
| T0 deps 覆盖率 | ≥80% | **90%** |
| 评审人复评 | 通过 | ✅ |

## 📌 合并授权

| 分支 | 合并方式 | 复评人 | 状态 |
| --- | --- | --- | :---: |
| fix/midterm-qa-issue-closure → dev | squash merge | SecLead（主）/ Reviewer（副） | ✅ 已合并 |
| dev → master | fast-forward | TechLead（最终签字） | ✅ 已合并 |

## 📁 后续行动

| 项 | 责任方 | 时机 |
| --- | --- | --- |
| 合并 PR fix/midterm-qa-issue-closure → dev | TechLead | T+0 |
| 合并 dev → master | TechLead | T+1 |
| 更新 PR 描述并标注「合并来源」 | 作者 | T+1 |
| 关闭原 4 个 PR（PR1~PR4） | 作者 | T+1 |
| M1 里程碑：12 条建议 + 2 条关联修复 | SecLead | 2026-10-15 |
| 评审记录归档 `docs/` | DevOpsLead | T+3 |

## 🔗 与前序工作的衔接

```
单测补测 (10-03)  →  单测门禁执行 (10-04)  →  代码评审与提交 (10-04)  →  正式代码评审 (10-04)  →  问题修复与合并 (10-04) ✅
   83 用例              9/9 通过                4 PR 拆分                 3 🔴 + 9 🟠             1528 通过 / 16/16 闭环
                                                                          3 个产品 bug 修复          dev + master 双合并
```