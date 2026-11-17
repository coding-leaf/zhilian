# 代码评审与提交（中期质量检查）

> **执行时间**：2026-10-04 16:08（北京时间）
> **总体结论**：**9/9 自动检查通过**，**4 个聚焦 PR 待评审**
> **核心 KPI**：83 用例 / 0 修改产品代码 / 每个 PR ≤ 400 行

## 🎯 评审目标

> **让评审高效、聚焦，而不是变成形式主义**。

- ✅ 每个 PR 200-400 行（聚焦主题，避免一次评审上千行）
- ✅ PR 描述完整（变更内容 / 关联需求 / 测试情况 / 影响范围 / 风险点）
- ✅ 自动检查全部通过（CI / 单测 / Lint / 静态扫描）
- ✅ 评审人按所有权目录分配（双人评审必填路径 + 加签机制）
- ✅ 不变量：作者**不自评**自合、机器门禁**不绕过**

## 📋 文档索引

| 文档 | 路径 | 内容 |
| --- | --- | --- |
| **自检记录** | [`自检记录.md`](./自检记录.md) | 8 维自检（命名/注释/日志/异常/安全/性能/重复/单测） |
| **PR1** | [`PR1_P1-4_folder_id_回归保护.md`](./PR1_P1-4_folder_id_回归保护.md) | P1-4 回归 + folder_id 聚合（323 行） |
| **PR2** | [`PR2_错误契约补测.md`](./PR2_错误契约补测.md) | 错误契约补测（291 行） |
| **PR3** | [`PR3_deps_user_覆盖率提升.md`](./PR3_deps_user_覆盖率提升.md) | deps/user.py 覆盖率（202 行） |
| **PR4** | [`PR4_practice_状态机与幂等.md`](./PR4_practice_状态机与幂等.md) | 状态机与强幂等（194 行） |
| **评审人分配方案** | [`评审人分配方案.md`](./评审人分配方案.md) | 按 `docs/团队分工.md` §4 分配评审人 |
| **自动检查报告** | [`自动检查报告.md`](./自动检查报告.md) | 9 项自动检查全通过 |

## 🚪 4 个聚焦 PR 一览

| PR | 主题 | 文件 | 行数 | 用例 | 评审要求 | 主评审 | 加签人 |
| ---: | --- | --- | ---: | ---: | --- | --- | --- |
| **#N** | P1-4 folder_id 回归保护 | `test_material_repo_filter.py` | **323** | 17 | 双人 | **SecLead** | **TechLead** |
| **#N+1** | 错误契约补测 | `test_errors_supplemental.py` | **291** | 44 | 单人 + 加签 | **Reviewer** | **SecLead** |
| **#N+2** | deps/user.py 覆盖率提升 | `test_user_deps.py` | **202** | 10 | 双人 | **SecLead** | **TechLead** |
| **#N+3** | practice 状态机与幂等 | `test_practice_state_machine_supplemental.py` | **194** | 12 | 单人 + 加签 | **Reviewer** | **SecLead** |
| **合计** | — | — | **1010** | **83** | — | — | — |

> **不变量**：
> - 4 个 PR 全部**单文件**，无产品代码变更（**纯测试提交**）
> - 每个 PR ≤ 400 行（满足「避免一次评审上千行」原则）
> - 评审人**不重叠**：SecLead 在 3 个 PR 出现（主评审 2 + 加签 1），TechLead 在 2 个 PR 出现，Reviewer 在 2 个 PR 出现
> - 作者**不出现在评审人列表中**

## 🚦 合并门禁

> **PR → master 的合并必须有 4 道机器门禁全部 green + 双人评审人 approve**

```
PR 提交
   ↓
[1] ruff format --check .      ←── 本地+CI 双重验证
[2] ruff check .             ←── 本地+CI 双重验证
[3] mypy app                 ←── CI 端验证
[4] lint-imports             ←── 本地+CI 双重验证
[5] pytest tests             ←── 全量 1496 必须通过
[6] coverage ≥ 80%           ←── 全量 91% 已通过
[7] T0 核心覆盖率 ≥ 90%      ←── 99% 已通过
[8] T0 deps 覆盖率 ≥ 80%     ←── 84% 已通过
[9] diff-cover 增量 ≥ 80%    ←── CI 端验证
   ↓
主评审人 Reviewer/SecLead approve
   ↓
副评审人/加签人 TechLead/SecLead approve
   ↓
GitHub 允许合并按钮
```

> 详细门禁语义见 [`通过记录.md`](../单测门禁执行/通过记录.md) §3。

## 🎯 评审聚焦（每个 PR 3 个聚焦问题）

| PR | 聚焦问题 |
| ---: | --- |
| PR1 | 1. `TestP1BugRegression` 锁住 P1-4 修复后行为；2. 越权测试；3. `statuses` vs `status` 优先级 |
| PR2 | 1. 14 项 error_code ↔ status 映射是否覆盖所有错误；2. `raise from` 链路保留；3. 已知缺陷是否需修复产品代码 |
| PR3 | 1. 4 条生成器路径全覆盖；2. 注入 session 不 close；3. 真实容器装配 |
| PR4 | 1. 4 状态拦截全覆盖；2. rollback 语义；3. 同 key 跨用户冲突 |

## 📁 原始日志

- `auto_check_format.log`
- `auto_check_ruff.log`
- `auto_check_mypy.log`
- `auto_check_lint_imports.log`
- `auto_check_pytest_coverage.log`
- `auto_check_diff_cover.log`

## 🚀 提交与评审流程

```bash
# 1. 提交准备（4 次提交，每次一个 PR）
cd backend

# PR1
git checkout -b fix/p1-4-folder-id-aggregate
git add tests/unit/repositories/test_material_repo_filter.py
git commit -m "test(material): P1-4 regression for folder_id IS NULL aggregation"
git push origin fix/p1-4-folder-id-aggregate
gh pr create --base master --title "PR1: P1-4 folder_id 回归保护"

# PR2
git checkout -b fix/error-contract-coverage
# ... 类似 PR1

# PR3 / PR4 类似

# 2. CI 自动跑门禁（与本地一致）
# 3. 评审人 approve（依据评审人分配方案）
# 4. 合并到 master
```

## 📌 关键不变量

- **本地跑绿即 CI 跑绿**——CI 命令**精确镜像** `Taskfile.yml`，**不另立第二套门禁**
- **机器门禁 + 人工评审互补**——机器管「人容易漏的」（静态、类型、单测、覆盖率），人管「机器看不见的」（接线、命名、文档）
- **0 修改产品代码**——本次提交全部为补测，**不擅自改动任何产品行为**
- **评审不流于形式**——每个 PR 都有 3 个聚焦评审问题，评审时长预估 15-25 分钟
- **变更可追溯**——每个 PR 描述含「关联需求/缺陷」段，指向 P1-4 / P0-2 等具体编号