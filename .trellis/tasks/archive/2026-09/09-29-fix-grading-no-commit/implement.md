# 执行计划：判题落库的事务边界

> 需求见 `prd.md`，技术设计见 `design.md`。本文件是**有序清单**：按序执行，每步有可验证产物。
> 括号内是 `design.md` / `prd.md` 的对应条目。

---

## 0. 前置

```bash
cd backend
sed -n '55,70p' ../.trellis/spec/backend/database-guidelines.md   # Transactions & Session Lifecycle
```

必须确认自己认同这条既有约定：**Service 层负责 commit；`get_session()` 正常退出不提交。**
若对这条有异议，**停下来回到 Plan 阶段**，不要带着异议动代码——本任务的正确性完全建立在这条约定上。

---

## 1. `[先红]` 补跨会话回归用例（对应 design §5、prd AC-3）

**顺序不可颠倒：用例必须先失败。** 先改实现再补用例，就无法证明用例真的拦得住这个缺陷。

### 1.1 抽造数函数（纯签名重构，函数体逐字不动）

`backend/tests/unit/services/test_grading_service.py`

- 把 `setup_practice_env`（`:68-184`）的函数体抽成
  `def _build_practice_env(session: Session) -> dict[str, Any]:`
- fixture 退化为一行：`return _build_practice_env(session)`
- **函数体一个字节都不改**。特别是它末尾的 `session.flush()`（`:184`）——
  **不要顺手改成 `commit()`**，那会改变同文件 30+ 个既有用例的会话状态，属未授权改动。
- 新增 `from pathlib import Path`、`from sqlalchemy import select` 等所需导入。

### 1.2 新增用例

按 `design.md` §5.2 的代码形态加入 `test_grade_practice_commits_across_session_boundary`。
三条硬约束（**违反任一条则该用例无效**）：

1. `tmp_path` + **文件型 SQLite**，**禁止 `:memory:`**；
2. 断言**只走新会话查询**，**禁止读 `summary.records`**；
3. 测试内先 `writer.commit()` 落造数，再跑判题——否则分不清是造数没落还是判题没落。

### 1.3 跑，**必须看到红色**

```bash
cd backend
PYTHONIOENCODING=utf-8 uv run pytest tests/unit/services/test_grading_service.py::test_grade_practice_commits_across_session_boundary -q
```

**预期失败**：`assert len(records) == 4` 实际为 `0`（或 `practice.status` 仍为 `submitted`）。

- ✅ 失败原因必须是"新会话查不到记录"，**不是**导入错误 / 语法错误 / fixture 报错。
  若是后者，修到能正确变红为止再继续。
- ⛔ **把这次输出留存**——AC-3 要求贴出修复前后的两次实测输出。
  如失败形态与预期不符，回到 Plan 阶段复核根因，不要直接进入第 2 步。

---

## 2. `[补提交]` 三处事务边界（对应 design §3、prd R1）

`backend/app/services/grading.py`，只改这三处，**每处把末尾的 `self.session.flush()` 换成
`self.session.commit()`**：

| # | 方法 | 行 | 方法名锚点 |
| --- | --- | --- | --- |
| 1 | `grade_practice` | `:294` | 在 `practice.status` 状态机决策之后 |
| 2 | `self_evaluate_attempt` | `:729` | 在 `practice.status` 回写之后 |
| 3 | `regrade_attempt` | `:920` | 同上 |

- 第 1 处按 `design.md` §3.1 写完整注释（**含"不要改为让 `get_session()` 自动提交"这条警示**——
  后人最容易"顺手优化"的方向就是它）。
- 第 2、3 处注释从简，指向第 1 处。
- **不包 `try / rollback / raise`**，理由见 `design.md` §3.2（提交后无可撤销动作，
  外层 `get_session()` 已负责回滚）。
- **不加 `defer_commit` 参数**：判题不在任何延迟提交编排内（`design.md` §2.4）。

自检：

```bash
cd backend
grep -n "session\.\(commit\|flush\)" app/services/grading.py   # 期望：3 个 commit，0 个 flush
```

---

## 3. `[变绿]` 用例通过（对应 prd AC-3）

```bash
cd backend
PYTHONIOENCODING=utf-8 uv run pytest tests/unit/services/test_grading_service.py -q
```

- 新用例**通过**，且同文件既有用例**零回归**。
- 留存通过输出，与第 1.3 步的红色输出配对（AC-3 证据）。

若既有用例红了 → 见 `design.md` §6 风险表第二行：**先判断该用例是否依赖了"未提交"的隐含状态**。
不许为了让门禁变绿而回退第 2 步。

---

## 4. `[复核]` 其余写库方法的提交边界（对应 prd AC-5）

结论已在 `design.md` §2.5 得出（私有辅助方法全部落在三个边界内，无需额外提交点）。
**执行时用命令复验一遍并把结果写进任务 Notes**，不要只引用设计文档：

```bash
cd backend
for m in _grade_with_llm _build_pending_regrade_record _grade_attempt_item; do
  echo "--- $m ---"; grep -rn "$m" app/ --include=*.py
done
grep -n "    def " app/repositories/grading.py      # 仓储只 add/flush，无 commit（正确）
grep -n "session\.commit()" app/services/grading.py  # 期望 3 处
```

---

## 5. `[门禁]` 后端全量（对应 prd AC-6、父任务 XAC-5）

```bash
cd backend
PYTHONIOENCODING=utf-8 uv run ruff format --check . && \
PYTHONIOENCODING=utf-8 uv run ruff check . && \
PYTHONIOENCODING=utf-8 uv run mypy app && \
PYTHONIOENCODING=utf-8 uv run lint-imports && \
PYTHONIOENCODING=utf-8 uv run pytest tests --cov=app --cov-branch --cov-fail-under=80
```

或直接 `task verify-backend`。**必须全量跑**：改动在共享模块，且新用例的 fixture 抽取
影响同文件全部用例。本任务不动前端，前端门禁一并跑一次以确认父任务 XAC-5 不被破坏即可。

---

## 6. `[真实库]` AC-2 与 AC-7（对应 prd AC-2 / AC-7）

### 6.1 AC-2：用户真实数据复判

目标练习 `b5fa06ed-9270-4db3-ac23-daa11a1ae57c`（12 条作答，`grading_records` = 0）。

**⛔ 硬性前置：先查题型构成，再决定是否直接跑。**

```bash
# 该练习的题型分布（含主观题则重判会真实调用大模型、消耗配额与费用）
cd backend && PYTHONIOENCODING=utf-8 uv run python -c "
from app.container import AppContainer
from sqlalchemy import text
c = AppContainer.create()
with c.get_session() as s:
    for row in s.execute(text('''
        select ai.question_snapshot->>'question_type' as qt, count(*)
        from attempt_items ai where ai.practice_id = :p group by 1
    '''), {'p': 'b5fa06ed-9270-4db3-ac23-daa11a1ae57c'}):
        print(row)
"
```

- 若**含主观题** → 先把题型分布与预计的 LLM 调用次数告知用户，**得到确认再跑**。
  （父任务 XAC 与 prd AC-2 都要求用真实数据核对，但消耗真实配额属对外部服务的副作用，
  须用户点头。）
- 若**全为客观题** → 直接跑，无外部副作用。

执行判题（CLI 路径与 worker 是同一 service 方法）：

```bash
cd backend
PYTHONIOENCODING=utf-8 uv run python -m app.cli grading grade \
  --practice-id b5fa06ed-9270-4db3-ac23-daa11a1ae57c \
  --user-id 9b6b2855-4a0a-4fd3-aabf-9e481376ffff
```

**然后用新会话查（不要在同一会话里看）**：

```bash
cd backend && PYTHONIOENCODING=utf-8 uv run python -c "
from app.container import AppContainer
from sqlalchemy import text
c = AppContainer.create()
with c.get_session() as s:
    print('grading_records =', s.execute(text(
        'select count(*) from grading_records where practice_id = :p'
    ), {'p': 'b5fa06ed-9270-4db3-ac23-daa11a1ae57c'}).scalar())
    print('practice =', s.execute(text(
        'select status, total_score from practices where id = :p'
    ), {'p': 'b5fa06ed-9270-4db3-ac23-daa11a1ae57c'}).one())
"
```

**通过判据**：`grading_records` = 12（或与题型构成一致），`practices.status` 离开 `submitted`，
`total_score` 非 `None`。

### 6.2 AC-7：端到端（**阻塞于用户**）

要求 worker 在容器内运行（用户自行 `docker compose up -d worker`），
然后在开发者工具里交卷一次，确认界面显示**逐题判分结果**而非永久「判题中」。

- **本条待用户确认，不得由我方代签。** 若用户此时未启动 worker，如实记为"未验证"，
  不要把 AC-2 的 CLI 结果当成 AC-7 的替代。
- 若 Docker 仍因网络拉不到镜像，不得为此改 Docker 代理配置（用户在开 xray TUN），
  记为"环境阻塞 + 原因"。

---

## 7. `[收口]` spec 更新与提交（Phase 3.3 / 3.4）

### 7.1 spec（`trellis-update-spec`）

- `database-guidelines.md` 的 Transactions 段**已经写明了正确约定**（`:58-60`），
  本次缺陷是**违反既有规范**而非规范缺失 ⇒ **不新增规则**。
- 但值得补一条**可执行的判别方式**到 Common Mistakes 的 `Commit` 边界错位条目下，
  因为现有条目只写了「仓储不得**多**提交」这一个方向，
  **反方向（service 漏提交）没有症状描述**，实测正是它漏过了评审。补写要点：
  - 症状：worker 报 `Job OK`、耗时正常、但目标表零行；
  - 判别：`grep -c "session.commit()" app/services/<x>.py` 与同目录同侪对比；
  - 观测盲区：**共享会话的用例看不见提交缺失**——跨会话查询才是唯一判据。
- 前端 spec 不动（本任务零前端改动）。

### 7.2 提交

- 提交信息按 Conventional Commits，中文正文，说明：**根因 + 影响面（三条路径/三个方法）+
  为什么在 service 层提交而不改 `get_session()`**。
- 结尾附 attribution 行（见会话内 attribution 要求）。
- 提交后把 AC 勾选状态、红色/绿色两次输出摘要、AC-2 实测数值写进本任务 `prd.md` 的 Notes。

---

## 回滚点

| 阶段 | 回滚动作 |
| --- | --- |
| 第 1 步后（用例已加、实现未改） | 保留用例（它此时正是"红"的，有诊断价值），或 `git checkout` 该测试文件 |
| 第 2 步后门禁红 | `git checkout backend/app/services/grading.py` 回到 flush 版；**用例保留** |
| 第 6 步真实库异常 | 无 schema/数据迁移，无需回滚；仅需说明未能验证 |

全任务**不涉及**：数据库迁移、外部接口契约、前端产物、部署配置。
