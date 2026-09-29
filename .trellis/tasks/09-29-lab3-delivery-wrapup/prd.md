# 第3次实验课交付收尾：代码实现与版本控制

## Goal

把课程第 3 次实验课的 4 条要求做成**可直接提交的成品**，并让公共仓库
`coding-leaf/zhilian` 的工程实践**与项目自己的文档承诺自洽**；同时保证仓库可见内容中
**不出现任何真实姓名**。

用户价值：老师点开仓库链接即可看懂「项目是什么、怎么跑、怎么开发的」；4 条要求逐条有产物，
不依赖口头补充；「版本控制」这条有可点开验证的实证。

## 需求源（老师原文，保留）

> 第3次实验课：代码实现与版本控制
> 1、项目代码基本完成，并上传代码集；界面截图；开发的过程文档。
> 2、回复代码管理平台，如github或gitee的链接
> 3、代码期间，小组分工和小组完成情况的讲述：每位小组成员做个人工作小结。
> 4、小组后续要解决的问题。

## 硬约束

- **C-1 公共仓库零真名**：仓库公开（GitHub API `"private": false`）。任何进入 `master` 的
  内容都不得含真实姓名。真名只允许出现在**仓库之外**的提交物里。
- **C-2 不改写已公开历史**：250 个提交已推送且公开，不做 rebase / filter 改写。
- **C-3 沿用既有代号**：`docs/specs_extracted/` 三份文档已用
  TechLead / DevOpsLead / SecLead / Reviewer，新增文档沿用同一套，不另造。
- **C-4 不引入业务代码改动**：本任务只出文档、截图、仓库配置；功能缺陷归各自任务。

## 已确认事实（2026-09-29 实测，仓库证据）

### 代码与仓库

| 事实 | 证据 |
| --- | --- |
| 仓库公开、账号有管理权 | GitHub API：`"private": false`；`permissions.admin = true` |
| 本地与远端零差异 | `git rev-list --left-right --count origin/master...master` = `0	0` |
| 提交规模 | 250 commits，2026-09-23 → 2026-09-29 |
| 作者单一 | 全部 `coding-leaf <1526209863xjh@gmail.com>`（账号 handle，非姓名） |
| **无合并提交** | `git log --merges` 计数 **0** |
| **远端仅 master** | `git ls-remote --heads origin` → 只有 `refs/heads/master` |
| **无 PR** | GitHub API `pulls?state=all` 返回空 |
| **无 CI** | `.github/` 目录不存在，0 个 workflow |
| **无 CODEOWNERS** | 三个候选路径均不存在 |
| 仓库门面缺失 | 无根 `README.md`（仅 `backend/README.md` 两行）、`description: null`、无 License、无 topics |
| 本地分支已全部并入 master | `git rev-list --count master..<branch>`：`feat/question-bank-tab` 0、`feat/material-delete-entry` 0、`codex/frontend-ui-loop-repair` 0、`worktree-agent-*` 0、`codex/frontend-vertical-slices` 1 |
| 凭据可用 | `git credential.helper = manager`，`git credential fill` 可取到 token（**不回显、不落盘**） |

### 文档承诺 vs 仓库实证（本任务要消除的落差）

| 文档承诺 | 出处 | 仓库实证 |
| --- | --- | --- |
| 精简 Git Flow：main / develop / feature / release / hotfix 五类分支 | 代码管理工作介绍 3.1 表 3-1 | 远端仅 `master`，无 develop / feature |
| 受保护分支禁止直接推送，必需检查项全绿才可合并 | 同上 | 无分支保护，无 CI |
| 持续集成流水线，任一环节失败即阻断构建 | 同上第 5 章 | `.github/` 不存在 |
| CODEOWNERS 归属与评审要求（表 4-1） | 团队分工 V2.0 第 4 章 | 无 CODEOWNERS 文件 |
| 人员归属以「团队分工文档」为准 | 代码管理工作介绍 1.2 节 | 仓库内**不存在**团队分工文档（悬空引用） |
| 分支名格式 `类型/任务编号-短描述` | 代码管理工作介绍 3.2 节 | 实际为 `feat/question-bank-tab`、`codex/*`，不带任务编号 |

### 截图可行性

| 事实 | 证据 |
| --- | --- |
| 仓库内 0 张截图 | `*.png/*.jpg` 命中项全在 `node_modules/`、`.venv/`、`.trellis/.runtime/` |
| `docs/demo/index.html` 不是界面截图 | 75 KB HTML 交互原型；**不得充当产品截图** |
| 后端正在运行 | `curl localhost:8000/docs` → `200` |
| LLM 凭据已配 | `backend/.env` 含 `API_KEY` 3 处 |
| 开发者工具可用 | `D:\computerstudy\微信web开发者工具\cli.bat` |
| 小程序免登录 | `miniprogram/dist/dev/mp-weixin/project.config.json` → `appid: touristappid` |
| 已有构建产物 | `miniprogram/dist/dev/mp-weixin`、`miniprogram/dist/build/mp-weixin` |

### CI 可行性

| 事实 | 证据 |
| --- | --- |
| 依赖锁定 | `backend/uv.lock`、`miniprogram/pnpm-lock.yaml` 均存在 |
| 测试无外部服务依赖 | `tests/conftest.py` 无数据库夹具；架构自 ZL-114 起统一用 `Fake*` 内存适配器 |
| 无并行测试插件 | 依赖中无 `pytest-xdist`，套件单进程串行 |
| **已知风险** | `tests/unit/core/algorithms/` 有 4 处墙钟阈值断言（200/50/20/100 ms），CPU 争用下会失败（`AGENTS.md` 已留档为既有测试设计问题） |

### 过程文档素材（散在 6 处，无一份可读总稿）

| 位置 | 内容 |
| --- | --- |
| `docs/specs_extracted/` | 软件需求规格说明书 V2.0、概要设计说明书 V1.0、代码管理工作介绍 V1.0 |
| `docs/DESIGN.md` | 前端设计规范（量化参数事实源） |
| `docs/legacy_sdlc/ROADMAP.md` | P0 原子任务拓扑矩阵（35 任务 / 依赖 DAG） |
| `docs/legacy_sdlc/ARCHIVE.md` | 40 条交付台账（每条含验证证据） |
| `docs/legacy_sdlc/{ACTIVE_TASKS,LEADER_ALIGNMENT}.md` + `ZL-*/` | 活跃任务索引、范围对齐函、逐任务 intent/plan/spec |
| `.trellis/tasks/**` | 任务树 PRD / design / implement（含 9 个未收口任务） |
| `.trellis/workspace/coding-leaf/journal-1.md` | 13 次会话开发日志（改动、提交、测试、状态） |

### 后续待解决问题素材

| 来源 | 内容 |
| --- | --- |
| `.trellis/tasks/09-29-field-test-fix-batch-1/prd.md` | 4 个未开工子任务：`fix-parse-stuck`、`fix-qgen-feedback`、`fix-llm-thinking-mode`、`fix-learning-stats` |
| `.trellis/tasks/09-29-question-bank-tab/prd.md` | R1–R6 未做 + 5 条已知问题（含「举一反三高估覆盖率」这一会误导用户的缺陷） |
| `docs/legacy_sdlc/LEADER_ALIGNMENT.md` | 8 节点主链路验收基准、永久排除 / P1 延期清单、3 处文档矛盾决策 |
| `AGENTS.md` | 墙钟微基准抖动属既有测试设计问题，非回归 |

## Key Decisions

| # | 决策 | 理由 |
| --- | --- | --- |
| D-1 | **执行对外动作**：推分支、开 PR、补仓库元信息 | 用户 2026-09-29 明确选择「补齐到自洽」 |
| D-2 | 历史不可回补 → **从现在开始真的走一遍流程**，本次交付物自己走 `feature/* → PR → 合并` | 本地分支已全部并入 master（`ahead=0`），GitHub 不支持对无独有提交的分支开 PR |
| D-3 | 保留 `master` 为集成分支，**不重命名**、**不引入 develop** | 重命名会打断已公开链接与本地工作树；单账号下双长期分支是纯仪式 |
| D-4 | 分支保护**不启用「必需评审」** | 单账号无法批准自己的 PR，启用即自锁。改建「必需状态检查 + 禁止直接推送 + 禁止强推/删除」 |
| D-5 | PR 用**合并提交**（保留分支结构），不用 squash | 课程要的是「分支创建 → 提交 → 合并请求」的完整过程证据 |
| D-6 | 真名版分工稿放**仓库外**，仓库内只放代号版 | C-1；代号版同时消除「团队分工文档」悬空引用 |
| D-7 | 截图工具与脚本放**仓库外**，仓库内只放图片与清单 | 不给课程仓库引入 `miniprogram-automator` 依赖，避免污染 CI |
| D-8 | 墙钟基准若在 CI 上抖动，**精确排除并在文档留痕**，不放宽阈值 | 遵循 `AGENTS.md` 既有结论：改测试到通过不等于修问题 |
| D-9 | 文档冲突**以基线文档为准**，不修改《代码管理工作介绍 V1.0》 | 用户 2026-09-29 决定：「以文档为准」 |
| D-10 | 新分支名与提交 scope **向文档规范收敛**，不追溯改名历史分支 | 用户 2026-09-29 决定：「怎么编的更贴合文档就行」 |

## 需求

### R1 交付文档集（进公共仓库）

- R1.1 根 `README.md`：项目定位、技术栈、主链路、目录结构、本地启动、质量门禁、
  完成度与已知问题入口。面向「点开链接的老师」写。
- R1.2 `docs/开发过程文档.md`：把 6 处散落素材汇成一份可读总稿——时间线、迭代节奏、
  关键决策、缺陷修复史（含「静默失效」型缺陷的根因）、质量证据、版本控制说明。
- R1.3 `docs/后续待解决问题.md`：老师第 4 条的直接产物。

### R2 界面截图集（进公共仓库）

- R2.1 用开发者工具自动化抓真实界面截图，覆盖主链路关键页面与状态。
- R2.2 `docs/screenshots/README.md`：每张图对应哪个页面、哪个状态、在链路中的位置。
- R2.3 抓不到的态（需真机 / 需手工造数据）如实列出，不伪装成已覆盖。

### R3 小组分工与个人工作小结（**不进公共仓库**）

- R3.1 真名版（提交稿）落在仓库之外：四人角色、职责边界、RACI、代码所有权，
  以及**每人个人工作小结**（按仓库真实产物回填，使老师核对提交记录时对得上）。
- R3.2 仓库内只放代号版 `docs/团队分工.md`，消除悬空引用。
- R3.3 防泄露闸门：提交前自动拦截含真名的改动。

### R4 版本控制证据与仓库门面（对外动作）

- R4.1 `.github/workflows/verify.yml`：后端四道门禁 + 前端三件套，push / PR 触发，**必须跑绿**。
- R4.2 `.github/CODEOWNERS`：以实际账号表达所有权，并指向 `docs/团队分工.md` 的矩阵。
- R4.3 `master` 分支保护：必需状态检查 + 禁止直接推送 + 禁止强推/删除（**不含**必需评审，见 D-4）。
- R4.4 推送已有的 `feat/question-bank-tab`、`feat/material-delete-entry`
  两个有语义的功能分支（机器命名的 `worktree-agent-*`、`codex/*` 不推）。
- R4.5 补齐 `description`、`topics`、`LICENSE`。
- R4.6 文档冲突处置：**以《代码管理工作介绍 V1.0》为准**，不修改该基线文档；
  新建的两份团队分工文档按基线对齐小程序端所有权，并在冲突处加一行注记说明取舍依据。
- R4.7 新证据向文档规范收敛：分支名采用 3.2 节的 `类型/任务编号-短描述` 格式
  （`feature/ZL-143-lab3-delivery`，ZL-143 为分配给本任务的编号，既有最大为 ZL-142）；
  新增提交的 scope 只取 3.2 节词表内的值（`docs` / `ci`）。

## Acceptance Criteria

- [ ] AC-1 根 `README.md` 存在，含启动与门禁命令，命令可直接复制执行。
- [ ] AC-2 `docs/开发过程文档.md` 覆盖时间线、任务体系、缺陷修复史、质量证据、版本控制说明；
      每个结论可在仓库中定位出处。
- [ ] AC-3 `docs/后续待解决问题.md` 列全未收口项，每项含现状、影响、下一步。
- [ ] AC-4 `docs/screenshots/` 含 ≥8 张真实界面截图，覆盖「登录 → 工作台/课程 → 上传 →
      解析 → 出题核对 → 作答 → 判题 → 学情/题库 → 错题本」主链路。
- [ ] AC-5 截图清单标注每张图的页面与状态；未覆盖项显式列出。
- [ ] AC-6 真名版分工与个人小结已成稿，位于仓库之外，含四人各自的工作小结。
- [ ] AC-7 `docs/团队分工.md`（代号版）存在且不含真名，消除《代码管理工作介绍》的悬空引用。
- [ ] AC-8 **防泄露闸门生效**：构造含真名的暂存改动被拦住；移除闸门后同一改动可通过。
- [ ] AC-9 `git grep` 四个真名在全部被跟踪文件中 0 命中。
- [ ] AC-10 CI 工作流在 GitHub 上**实际跑绿**（以 Actions 运行结论为准，不以本地模拟为准）。
- [ ] AC-11 公开仓库可见 `feature/ZL-143-lab3-delivery` 分支与**已合并**的 PR，且 `master` 历史出现
      一个**合并提交**。
- [ ] AC-12 `master` 分支保护已生效：直接推送被拒绝（以实际被拒的输出为准）。
- [ ] AC-13 仓库 `description` / `topics` / `LICENSE` 均非空。
- [ ] AC-14 `task verify` 退出码 0（本任务不引入门禁回归）。
- [ ] AC-15 《代码管理工作介绍 V1.0》**零改动**（`git diff` 不含该文件），
  两份新建团队分工文档在冲突处已按基线对齐并留有注记。

## Out of Scope

- **不修业务代码**：`09-29-*` 任务树的功能缺陷属各自任务，本任务只在文档中如实记述。
- **不改写已公开 git 历史**（C-2）。
- **不重命名默认分支**、**不引入 develop**（D-3）。
- **不启用必需评审的分支保护**（D-4）。
- **不把真名写进任何进仓库的文件**，包括注释、提交信息、截图水印、文档修订记录。
- **不处理提交身份** `coding-leaf <1526209863xjh@gmail.com>`：账号 handle 非姓名，且已公开。
- **不追求让文档描述的全部五类分支都出现**：release / hotfix 无对应场景，不造。

## 任务地图

| 子任务 | 覆盖需求 | 交付面 | 排期约束 |
| --- | --- | --- | --- |
| `lab3-process-docs` | R1 | 仓库内文档 | 无 |
| `lab3-ui-screenshots` | R2 | 仓库内截图 | 需后端运行（已满足）；截图清单被 R1.2 引用，宜先行 |
| `lab3-team-roster` | R3 | 仓库外提交稿 + 仓库内代号版 | R3.3 闸门须在**任何提交发生前**就位 |
| `lab3-vc-evidence` | R4 | 对外可见的仓库形态 | 与 R1/R2/R3 同批走 `feature/ZL-143-lab3-delivery` 分支 |

**父子不是依赖系统**：上表「排期约束」是执行顺序建议，各子任务仍须能独立计划、验证、归档。
