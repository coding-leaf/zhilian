# PR 描述：dev → master（中期质量检查收口）

> **用途**：本机无 `gh` CLI 且无 GitHub Token，无法自动创建 PR。
> 请在网页创建：**https://github.com/coding-leaf/zhilian/compare/master...dev?expand=1**
> 标题建议：`中期质量检查收口：门禁 + 评审闭环 + 覆盖补强 + 标准符合性（GB/T 15532 & 19001）`
> 描述：复制下方「PR 正文」全文粘贴。

---

## PR 正文（复制以下内容）

## 关联

- 任务：中期质量检查（2026-10-03 ~ 2026-10-04，全 12 步）+ M1-001 首批覆盖补强
- 关联缺陷：`docs/后续待解决问题.md` P0-2 关联项、P1-4 回归保护；新增 PYSEC-2026-4141（已闭环）
- 依赖 / 被依赖：无新增运行时依赖；`pyjwt` 由 2.14.0 升至 2.15.1

## 改了什么

**产品修复（3 处，+31/-6 行）**
- `app/core/errors.py`：BUG-01 — 3 个错误类不再向父类传 `detail` 别名，修复参数注入被覆盖的合并语义
- `app/services/practice.py`：BUG-02/03 — `retry_grading` 二次校验纳入回滚路径（防状态泄漏）；`except Exception` 收紧为 `(QueueError, SQLAlchemyError)`
- `backend/uv.lock`：pyjwt 2.14.0 → 2.15.1（PYSEC-2026-4141，pip-audit 复扫 0 漏洞）

**测试补强（7 个文件，+~2300 行）**
- PR1~PR4 补测：material repo 过滤、错误契约 41 项映射、deps/user、practice 状态机
- M1-001 覆盖补强：CLI 层（入口/报告/夹具/5 个子命令处理器/doctor）+ deps 层（container/db/folder）

**规范与文档（`docs/` 4 份 + `中期质量检查/` 7 个目录）**
- `docs/测试设计规范.md` / `评审清单.md` / `Mock与Stub规范.md` / `异常捕获规范.md`
- 中期质量检查全阶段产出：计划 / 门禁 / 评审 / 修复 / 总结 / 归档 / 标准符合性检查

## 为什么

- 中期质量检查执行中发现 3 个产品缺陷（错误契约覆盖、状态泄漏、异常过宽），全部**仅人工评审发现**，机器门禁无法捕获；
- 覆盖率数据出现口径失真事故（局部运行残留数据被误读为全量 98%，实为 91%），本次一并勘误并建立口径纪律；
- 对齐 GB/T 15532-2008 与 GB/T 19001-2016 的准出要求，CLI 层（原 0~63%）与 deps 层（原 44~50%）为最大覆盖缺口。

## 怎么验证

| 项 | 命令 | 结果 |
| --- | --- | --- |
| 后端门禁 | `task verify-backend`（等价 9 项） | 退出码 0；全量覆盖率 **93%**（12705 stmts / 552 miss） |
| 测试 | `uv run pytest tests` | **1619 passed / 0 failed / 3 skipped**（3 项为环境性跳过） |
| T0 核心覆盖率 | `--include=algorithms/security/errors --fail-under=90` | **99%** |
| T0 deps 覆盖率 | `--include=app/api/deps/*` | **95%**（原 84%） |
| 静态门禁 | ruff format / check + mypy + lint-imports | 263 files formatted / All checks passed / 135 files no issues / 5 kept |
| 依赖漏洞 | `uv run pip-audit` | **0 漏洞**（含 bandit 0 HIGH） |
| CI | GitHub Actions `verify`（本 PR 触发） | **以 Actions 实跑为准** |
| 增量覆盖率 | `diff-cover --compare-branch=origin/master --fail-under=80` | CI 端执行 |
| 新增用例 | — | 本轮 **+91 条**（M1-001 补强，88 个函数实例化为 91 例）；累计 1496 → 1619（净增 123），全过 |

**覆盖率提升明细（综合口径，语句+分支）**

| 模块 | 补强前 | 补强后 |
| --- | ---: | ---: |
| `app/cli/commands/practice.py` | 33% | **100%** |
| `app/cli/commands/question.py` | 42% | **99%** |
| `app/cli/commands/material.py` | 63% | **100%** |
| `app/cli/commands/grading.py` | 55% | **100%** |
| `app/cli/commands/doctor.py` | 78% | **100%** |
| `app/api/deps/container.py` | 44% | **100%** |
| `app/api/deps/folder.py` | 47% | **95%** |
| `app/api/deps/db.py` | 50% | **88%** |
| **全量** | 91% | **93%** |

## 影响面 / 风险

- 契约变更：**无**（Schema / 路由 / 迁移均未变；errors.py 修复使 `details` 变为超集，向后兼容）
- 迁移：**无**
- 回滚：`git revert` 对应提交即可；产品修复 3 处均为独立小提交（`3331ccf` / `f6826fc` / `fe7c6e1`）
- 风险：pyjwt 小版本升级（2.14→2.15）已过 auth 专项 + 全量回归；CLI 测试均为离线（零网络、零外部依赖）

## 评审要点

- [x] T0 模块已评审（正式评审 4 PR + 三方复评签字）
- [x] 增量覆盖率达标（T0 ≥90%，其余 ≥80%）
- [x] 阈值 / 参数类改动附回归证据（回归报告 + 覆盖率快照）
- [x] 无真实姓名（仓库公开，统一角色代号）
- [x] 文档与代码同批（4 份规范 + 7 个目录产物）

## Checklist

- [x] 提交 scope 在词表内
- [x] `task verify-backend` 等价门禁全绿（退出码 0，逐段输出无错误）
- [x] 新增 / 改动代码有测试锁住
- [x] 无静默吞错（`except Exception` 已收紧 + bandit 扫描）
- [x] 一个 PR 含连贯改动单元（中期质量检查收口，含配套修复与补强）

---

## 创建步骤（网页）

1. 打开 https://github.com/coding-leaf/zhilian/compare/master...dev?expand=1
2. 标题粘贴上方「标题建议」
3. 描述粘贴「PR 正文」全文
4. 右侧 Reviewers 按 `中期质量检查/代码评审与提交/评审人分配方案.md` 勾选
5. Create pull request → CI `verify` 自动运行（9 项门禁）
6. CI 全绿后合并（保留合并提交，不用 squash）

> **推送状态（2026-10-04 20:50）**：`git push origin dev --follow-tags` 已完成
> （`192c060..290055a dev -> dev` + tag `midterm-baseline-2026-10-04`）。
