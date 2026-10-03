# 设计：第3次实验课交付收尾

本文件只写**技术设计**：产物落位、真名隔离机制、截图流水线、CI 与分支流程的落地方式、
风险与回滚。需求与验收标准见 `prd.md`。

## 1 产物落位（边界设计）

核心边界：**真名与非真名产物物理分离**，且分离发生在仓库边界上，而不是靠约定。

| 产物 | 落位 | 进公共仓库 | 依据 |
| --- | --- | --- | --- |
| 根 `README.md` | `zhilian/README.md` | 是 | R1.1 |
| 开发过程文档 | `zhilian/docs/开发过程文档.md` | 是 | R1.2 |
| 后续待解决问题 | `zhilian/docs/后续待解决问题.md` | 是 | R1.3 |
| 界面截图 | `zhilian/docs/screenshots/*.png` | 是 | R2.1 |
| 截图清单 | `zhilian/docs/screenshots/README.md` | 是 | R2.2 |
| 代号版分工 | `zhilian/docs/团队分工.md` | 是 | R3.2 |
| **真名版分工与个人小结** | **`D:\code\Workspace\zhilian-lab3-deliverables\`** | **否** | R3.1 / C-1 |
| 截图工具与脚本 | `D:\code\Workspace\zhilian-lab3-tools\` | **否** | D-7 |
| CI 工作流 | `.github/workflows/verify.yml` | 是 | R4.1 |
| CODEOWNERS | `.github/CODEOWNERS` | 是 | R4.2 |
| LICENSE | `LICENSE` | 是 | R4.5 |
| 防泄露钩子 | `.git/hooks/pre-commit`（`.git/` 本身不被跟踪） | 否 | R3.3 |

选**仓库外同级目录**而不是「仓库内 + .gitignore」的理由：`.gitignore` 只防 `git add -A`，
一次 `git add -f` 或一条错误的 `!` 反忽略规则就会把真名写进**永久且公开**的历史。仓库外目录
不存在这条路。代价是产物分两处，用一份索引说明弥补。

## 2 真名隔离：三层防线

| 层 | 机制 | 拦截时机 | 覆盖 |
| --- | --- | --- | --- |
| L1 落位隔离 | 真名产物写在仓库外目录 | 写文件时 | 结构性，无法绕过 |
| L2 提交拦截 | `.git/hooks/pre-commit` 扫描**暂存内容**，命中真名即非零退出 | `git commit` | 本机所有提交 |
| L3 收口核验 | `git grep` 全量被跟踪文件 + `git log -p` 抽查提交信息 | 推送前 / 收尾验收 | 兜底 |

L2 的实现约束：

- 钩子文件位于 `.git/hooks/`，**不被 git 跟踪**，因此可以安全地包含真名字面量——
  这是它优于「仓库内检查脚本」的地方（后者会把真名本身提交上去）。
- 扫描对象是 `git diff --cached` 的内容，而不是工作区文件：只拦将要入库的内容。
- 命中时输出命中的文件名与行号，**不回显命中姓名本身**，避免在终端历史与日志中二次泄露。
- 真名单从钩子内的字面量读取；本文件与 `prd.md` 同样**不写出真名**，只以「四个真名」指代。
- 钩子可被 `--no-verify` 绕过，故它只是 L2，不能替代 L3。

已知盲区（如实记录，不假装覆盖）：L2 拦不住**图片内的姓名**（截图水印、界面里的用户名）
与**已推送历史**。前者靠 R2 的截图规范约束（不截含真实姓名的界面），后者由 C-2 明确不做。

## 3 截图流水线

### 3.1 技术路径

```
微信开发者工具 CLI (D:\computerstudy\...\cli.bat)
        ↑ automator.launch({ cliPath, projectPath })
miniprogram-automator  ── 驱动 ──→  小程序自动化端口
        ↓ page.screenshot()
    PNG 产物 → zhilian/docs/screenshots/
```

- `projectPath` 指向**已有构建产物** `miniprogram/dist/dev/mp-weixin`，不重新构建；
  若产物过期，先跑 `pnpm build:mp-weixin` 刷新。
- `appid: touristappid` 免登录，不需要开发者工具账号。
- 依赖后端在 `localhost:8000` 运行（当前已满足），且前端请求基址为
  `miniprogram/src/utils/request.ts` 的默认值 `http://localhost:8000/api/v1`。
- `miniprogram-automator` 装在**仓库外**的 tools 目录，用 `NODE_PATH` 或脚本内绝对路径
  引用，不写进 `miniprogram/package.json`。

### 3.2 截图清单（目标覆盖）

| # | 页面 | 要体现的状态 | 路由 |
| --- | --- | --- | --- |
| 1 | 登录 | 未登录初始态 | `pages/auth/login` |
| 2 | 工作台首页 | 有课程与资料的真实数据态 | `pages/index/index` |
| 3 | 课程文件夹 | 资料归属与归档 | `subpackages/material/pages/course/index` |
| 4 | 资料上传 | 上传入口与格式约束 | `subpackages/material/pages/upload/index` |
| 5 | 资料解析 | 解析中就绪态（含进度与出口） | 同上 / 工作台卡片 |
| 6 | 出题核对 | 考点选择 + 生成反馈 + 题目预览 | `subpackages/material/pages/questions/index` |
| 7 | 答题会话 | 作答中的选项交互 | `subpackages/practice/pages/session/index` |
| 8 | 判题结果 | 判对 / 判错反馈横幅 | 同上（交卷后） |
| 9 | 学情 / 题库 | 批次分组与错题区块 | `pages/review/index` |
| 10 | 错题本 | 错题列表与举一反三入口 | 同上 |
| 11 | 个人中心 | 学习足迹统计 | `pages/profile/index` |
| 12 | 诊断报告 | 掌握度四档与薄弱点 | `subpackages/report/pages/detail/index` |

抓不到的态按 R2.3 在清单里标注原因（如需真机、需手工造数据、需等待异步任务）。

### 3.3 失败预案

自动化不可用时（工具链不兼容、DevTools 版本不匹配、需要人工登录等）**不伪造截图**，
降级为：产出「页面 × 状态 × 要点」的拍摄清单交给用户手工补拍，并在收尾说明中如实记录
哪一部分是自动化产出、哪一部分是人工补拍。

## 4 CI 工作流设计

### 4.1 结构

两个并行 job，**精确复用 `Taskfile.yml` 里的命令**，不另立一套门禁：

| job | 步骤 |
| --- | --- |
| `backend` | checkout → `astral-sh/setup-uv` → `uv python install 3.13` → `uv sync --frozen --extra dev` → `ruff format --check` → `ruff check` → `mypy app` → `lint-imports` → `pytest tests --cov=app --cov-branch --cov-fail-under=80` |
| `frontend` | checkout → `pnpm/action-setup` → `actions/setup-node`（开 pnpm 缓存）→ `pnpm install --frozen-lockfile` → `lint` → `type-check` → `test:unit` |

触发：`push` 到 `master`、`pull_request` 目标为 `master`。

### 4.2 版本选型依据（实测）

| 项 | 取值 | 依据 |
| --- | --- | --- |
| Python | 3.13 | `backend/.venv` 实为 3.13.14；`requires-python = ">=3.12"` |
| uv | 0.12.x（由 action 提供） | 本地 `uv 0.12.1` |
| Node | 22 | 本地 `node v22.22.3` |
| pnpm | 10（需实测校准） | `pnpm-lock.yaml` 为 `lockfileVersion: '9.0'`；本地 pnpm 报 12.4.1 |

**未定项**：仓库无 `.python-version`、无 `.nvmrc`、`package.json` 无 `packageManager` 字段。
CI 版本只能写在工作流里。为避免「锁文件版本与 CI pnpm 版本不匹配导致 `--frozen-lockfile`
失败」，实现期必须先跑通一次再定版本号，而不是照抄本地版本。

### 4.3 主要风险：墙钟微基准

`tests/unit/core/algorithms/` 有 4 处墙钟阈值断言（200 / 50 / 20 / 100 ms）。
`AGENTS.md` 已留档：全量套件在 CPU 争用下会失败，单独跑全过，属**既有测试设计问题**。

处理原则（承接 `AGENTS.md`，不放宽阈值、不把测试改到通过）：

1. 首跑照全量执行，拿到真实结论；
2. 若失败，先判定归因——用「单独跑该文件是否全过」区分抖动与真回归；
3. 确认为既有抖动后，在 CI 中**精确排除**该文件并在工作流内写明排除理由与出处，
   同时把该决定同步进 `AGENTS.md`，使排除是**留痕的例外**，不是静默的绿灯。

## 5 分支与合并请求流程

### 5.1 本次交付物走一遍真实流程（D-2）

```
master ──→ feature/ZL-143-lab3-delivery ──(提交 N 次)──→ PR ──(合并提交)──→ master
```

- 分支名采用文档 3.2 节的格式 `类型/任务编号-短描述`：**`feature/ZL-143-lab3-delivery`**。
  任务编号沿用项目既有 ZL 序列（既有最大 ZL-142），ZL-143 分配给本任务。
  历史分支（`feat/question-bank-tab`、`codex/*`）未用该格式，**不追溯改名**；
  过程文档记明「自 ZL-143 起按 3.2 节收敛」，使偏差是**有起点的历史**而非长期违规。
- 新增提交的 scope 只取 3.2 节词表内的值（`docs` / `ci`），不再引入词表外的 scope。
- PR 用**合并提交**而非 squash（D-5），使 `master` 历史上出现真实的合并提交，
  `git log --graph` 能看到分支结构——这正是课程「版本控制」要看的东西。
- PR 正文写清覆盖的 4 条课程要求与验收证据。

### 5.2 分支保护配置（D-4 的自锁论证）

账号为单账号（`permissions.admin = true`，但仓库只有一个协作者）。GitHub **不允许
PR 作者批准自己的 PR**，因此若启用 `required_pull_request_reviews`，本次 PR 将永远
无法满足条件，等于把 `master` 锁死。

故 `master` 保护启用以下项，**不启用** `required_pull_request_reviews`：

| 配置项 | 取值 | 作用 |
| --- | --- | --- |
| `required_status_checks` | 严格模式 + CI 两个 job | 门禁不过不许合并 |
| `enforce_admins` | **true** | 取证推翻了初版设计，见下方「5.3」 |
| `required_pull_request_reviews` | **不设置** | 单账号自锁，见上 |
| `allow_force_pushes` | false | 禁止强推 |
| `allow_deletions` | false | 禁止删除 |
| `restrictions` | 不设置 | 无多用户可限 |

### 5.3 取证推翻的设计：`enforce_admins` 必须为 true

初版本节的设计是 `enforce_admins: false`，理由是「保留管理员应急通道」。**实测证明这个取值
等于没有保护**，已改为 `true`。

取证过程（2026-09-29，在本仓库实测）：

1. 按初版配置（`enforce_admins: false`）在本地 `master` 造一个空提交并直接推送；
2. 推送**成功**，远端返回的原文就写明了原因：

   ```
   remote: Bypassed rule violations for refs/heads/master:
   remote: - 2 of 2 required status checks are expected.
   ```

   `Bypassed rule violations` 意为**规则被绕过**，不是「规则不存在」。管理员身份直接穿透了
   必需状态检查。
3. 改为 `enforce_admins: true` 后重测，同一操作被真实拒绝：

   ```
   remote: error: GH006: Protected branch update failed for refs/heads/master.
   remote: - 2 of 2 required status checks are expected.
   ! [remote rejected] master -> master (protected branch hook declined)
   ```

**教训**：`enforce_admins: false` 看起来像「留一条应急通道」，实际效果是**对管理员完全失效**。
配置项的名字容易被读成「是否对管理员更严格」，而它的真实语义是「保护规则是否也约束管理员」。
凡是「配置成功 ≠ 约束生效」的场合，都必须**用一次真实的违规操作去验证**——
这与本项目在 `AGENTS.md` 里记下的「退出码与覆盖率都会骗人」是同一条纪律。

另有一处需要知道的副作用：本轮清理误推的空提交时发现，**`required_status_checks` 的严格模式
会连管理员的历史回退一起挡住**。也就是说，一旦 master 上出现不合意的提交，正常流程下**只能靠
新增提交来纠正，不能靠回退**。这是启用严格模式的真实代价，不是缺陷。

**偏差留痕**：文档 3.1 表 3-1 要求 `main`/`develop`「需 1 名代码所有权人批准」。
本仓库以 `master` 为集成分支、单账号运作，评审要求**在组织层面不可执行**。
该偏差写入 `docs/开发过程文档.md` 的「版本控制」章节与本设计的偏差表，不隐瞒、不假装已满足。

### 5.3 推送已有分支（R4.4）

只推 `feat/question-bank-tab`、`feat/material-delete-entry` 两个有语义的 feature 分支
（二者 `ahead=0`，推送后 GitHub 会显示为已并入 master 的分支，用于佐证「确实用过功能分支」）。
`codex/*` 与 `worktree-agent-*` 是工具生成的机器名分支，推送只增加噪音，不推。

## 6 兼容性、风险与回滚

| 风险 | 影响 | 回滚 |
| --- | --- | --- |
| CI 首次运行红 | AC-10 不满足；公开仓库挂红叉 | 修工作流或按 4.3 留痕排除；不含业务代码改动，回滚成本低 |
| 分支保护配错（如误开必需评审） | `master` 无法合并 | `DELETE /branches/master/protection` 或改配置，API 可逆 |
| 推送分支/合并 PR 后想撤回 | 公开可见，**不可完全撤销**（分支可删，PR 记录与合并提交不可删） | 合并提交用 `git revert` 可回退内容，但历史痕迹保留；此为用户已授权的对外动作 |
| 截图引入真名（界面里的用户名） | 违反 C-1 | 删除该图并重拍；L3 核验兜底 |
| `miniprogram-automator` 与 DevTools 版本不兼容 | 截图流水线不可用 | 按 3.3 降级为人工拍摄清单 |
| 仓库外目录被误 git add | 真名入库 | L2 钩子拦截；L3 核验 |

## 7 实现期必须先核实的未定项

以下项**留到实现期用实测结论定**，不在此处猜：

1. CI 的 pnpm 版本号（4.2 未定项）。
2. `uv sync` 需要 `--extra dev` 还是默认组即可覆盖 import-linter。
3. `page.screenshot()` 在 `touristappid` 下是否需要额外的自动化端口授权。
4. LICENSE 类型选择（需用户确认，或默认 MIT 并以账号 handle 署名）。
5. ~~5.2 的偏差修正是否需修订基线文档~~ → 已定案（D-9）：**不改基线文档**，
   偏差只在 `docs/开发过程文档.md` 内留痕。
