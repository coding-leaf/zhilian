# 技术设计：判题落库的事务边界

> 前置阅读：本目录 `prd.md`（现象、证据、验收标准）。本文件只回答**怎么改、为什么这么改**。

---

## 1. 结论摘要

`GradingService` 的三个写库方法各自**已经是**最外层 service 编排，按项目既定约定应当自己提交，
却只 `flush()`。修复 = 在这三处的事务边界补上 `self.session.commit()`。

**不是新引入事务模式，是让 `grading.py` 回归 `.trellis/spec/backend/database-guidelines.md`
已经写明的约定**——这条性质决定了它风险低、且不需要任何新抽象。

---

## 2. 事实核对（本次重新逐行核实，行号为准）

PRD 写于上下文压缩前，本设计在动笔前把每条断言重新对过代码。结论：**全部成立**，并有一处**扩大**。

### 2.1 提交缺失——成立

```
backend/app/services/grading.py     commit=0   flush=3   (:294 / :729 / :920)
```

三个 `flush()` 恰好是三个写库方法各自的**唯一持久化动作**，也恰好都在**返回之前最后一步**：

| 方法 | 定义 | `flush()` | 谁调用 |
| --- | --- | --- | --- |
| `grade_practice` | `:197` | `:294` | worker `grading_jobs` / CLI `grading grade` |
| `self_evaluate_attempt` | `:579` | `:729` | `POST /api/v1/grading/self-evaluate` |
| `regrade_attempt` | `:747` | `:920` | `POST /api/v1/grading/regrade` |

### 2.2 调用路径——**比 PRD 记的更宽**

```
backend/app/worker.py:53-58          _grade_practice → get_session() → 不提交
backend/app/api/deps/db.py:20-33     get_db_session → container.get_session() → 不提交
backend/app/api/deps/grading.py:21   get_grading_service → 同上
backend/app/cli/commands/grading.py:74   get_session() → 不提交
```

**四条路径无一提交。** 因此受影响的**不止 `grade_practice`**：
**用户自评（`self-evaluate`）与申请重判（`regrade`）同样不落库。**
这两个端点走的是 HTTP 请求，用户点一下界面就会即时感到"点了没反应"，
而它们的会话同样在 `close()` 时丢掉整个事务。

> PRD 的 AC-5 原本只要求"复核其他写库方法并列出结论"。复核结果是把它们**一并修**——
> 同一文件、同一根因、同一改法，拆开反而制造"修了一半"的假象。

### 2.3 为什么只有 `grading.py`——成立，且是硬证据

各 service 显式 `commit()` 出现次数（本次实测）：

```
auth.py        5        folder.py      6        knowledge.py   2
material.py   16        practice.py    8        question.py    5
grading.py     0   ← 唯一的 0；且不是只读文件，它写 3 处
source_snippets.py 0   （纯函数模块，无 session，非反例）
```

配套事实：

- `GradingRepository`（`app/repositories/grading.py`）**commit 数 = 0**，
  只有 `add` / `flush`。这**是正确写法**——`database-guidelines.md:85` 把
  「仓储内部私自定义 `commit()`」列为禁止项。仓储没做错，是 service 没接上。
- 项目自己的规范原文（`database-guidelines.md`，「Transactions & Session Lifecycle」）：
  - `:58` `AppContainer.get_session()` 是事务上下文管理器：**正常退出不自动 commit**，异常时 `rollback()`，最终始终 `close()`。
  - `:59` **Service 层负责 `self.session.commit()` / `self.session.rollback()`；路由层不得开事务。**
  - `:60` 跨多个子操作的单事务编排：内层传 `defer_commit=True` 仅 `flush()`，**仅由最外层**在全部成功时 `commit()`。

  且 `:85` 的 Common Mistakes 第一条就叫 **`Commit` 边界错位**。

- 最接近的同侪样板 `backend/app/services/practice.py:1135-1155`（交卷入队），
  注释原文就写着 **「4. 事务原子更新练习状态与交卷时间」**，随后 `self.session.commit()`。
  判题是交卷的下游，交卷提交了、判题没提交——**断点正好落在这一步**。

### 2.4 `defer_commit` 不会波及判题——成立

`defer_commit` 全仓只出现在 `app/services/question.py`（`:763/:1087` 两个签名 + 内部转发）。
判题链路不在任何 `defer_commit=True` 编排内，**三个方法都是最外层**，无嵌套提交语义要协调。

### 2.5 私有辅助方法都在这三个边界内——成立

`_grade_attempt_item`(:333) / `_grade_with_llm`(:458) / `_build_pending_regrade_record`(:543)
的调用点全部落在上面三个方法的函数体内（实测 `:450 / :414 / :469 / :536 / :267`）。
**所以只需在三个边界各提交一次，无需在私有方法内插提交点。**

---

## 3. 修复设计

### 3.1 提交点

三处，各自替换既有的末尾 `flush()`：

```python
# app/services/grading.py —— grade_practice (:294 一带)
        # 事务边界：整卷判题结果在此一次性提交。
        #
        # 本方法已是 service 层最外层（worker / API / CLI 三条调用路径都只提供
        # `AppContainer.get_session()` 产出的裸会话，见 container.py:138-152——正常退出
        # **不**自动 commit，只 close）。因此提交责任在这里；漏掉的表现是：
        # 判题全部算完、任务报 `Job OK`、`grading_records` 却为 0。
        #
        # 不要改为让 get_session() 自动提交：那会改变全项目事务语义（含刻意只读、
        # 以及依赖异常回滚的调用点）。见 .trellis/spec/backend/database-guidelines.md
        # 「Transactions & Session Lifecycle」。
        self.session.commit()
```

`self_evaluate_attempt`(:729) 与 `regrade_attempt`(:920) 同形，注释从简并指向本处说明。

### 3.2 为什么**不**包 `try / rollback / raise`

`question.py:1034-1044` 与 `practice.py:1350-1354` 都写了 `try: commit / except: rollback; raise`。
此处**不需要**，理由是具体的而非偷懒：

- 提交是方法体**最后一条**写操作，其后只有日志与 `return`，**没有需要撤销的后续动作**；
- 提交失败时异常向上抛，`get_session()` 的 `except` 分支（`container.py:148-150`）已经 `rollback()` + `raise`，
  语义与内联 `try` 完全一致；
- `practice.py:1350` 需要 `try` 是因为它**提交之后还有事要做**（重新查询并返回），
  `question.py` 需要 `try` 是因为它要区分 `defer_commit` 两种模式。**两个理由此处都不成立。**

结论：bare `self.session.commit()`，与 `material.py` 的 16 处写法一致。**改动面 = 3 行。**

### 3.3 `expire_on_commit` 的影响——已知且可接受

`sessionmaker` 用默认 `expire_on_commit=True`，提交后会话内对象过期。提交点之后仍有读：

- `_log_metric(extra={"final_status": practice.status})`（`:307`）
- `PracticeGradingSummary(...)` 里读 `r.status` / `r.attempt_item_id`（`:317-320`）

这些读会触发**刷新查询**。行为正确（行确实已落库），代价是几条 SELECT。
**这与 `practice.py:1262` `mark_grading_failed` 提交后仍返回 `practice` 是同一模式**，
不是新问题。刻意**不**改成 `expire_on_commit=False`：那是会话工厂级别的全局改动，
为了省几条本地 SELECT 去动它不划算。

### 3.4 返回值的 ORM 载荷——**不改**，但要写进测试约定

`PracticeGradingSummary.records` 持有 ORM 对象，提交后即过期、
会话关闭后即 detached。三条调用路径都**不依赖**它：

- `worker._grade_practice`（`worker.py:53-58`）直接丢弃返回值；
- CLI（`grading.py:77-88`）只读 `summary` 上的**标量**字段
  （`practice_id` / `status` / `total_score` / `max_score` / `total_items` /
  `graded_items` / `pending_regrade_count`），**不碰 `.records`**；
- API 的两个端点读的是 `record` 上的属性，且都在会话存活期内完成。

所以无需改动 DTO。**但新增的回归用例必须遵守**：断言走**新会话查询**，
不得读 `summary.records`——见 §5。

---

## 4. 提交粒度决策：整卷一次

### 4.1 决策

**整卷一次性提交**（即 §3.1 的三处）。

### 4.2 逐题提交的真实优势（比 PRD 里记的更强，此处如实升级）

PRD 只说了「逐题更耐故障」。重新核对代码后，**理由比这更硬**：

`grade_practice:243-264` 的幂等重放，判据是
`grading_repo.list_final_records_by_practice(practice_id, user_id)`——

> **这个查询读的是数据库，不是本次调用的内存状态。**

推论：**逐题提交能让崩溃后的重放跳过已判成功的题**，只补判剩余部分；
而整卷提交下，一次中途崩溃 = 整卷记录全部不存在 = 重放时 `existing_records` 为空 =
**所有主观题重新调用大模型**（每道都有 20s 超时的 LLM 调用）。
在「主观题多、模型按 token 计费」的现实里，这个差距是实打实的钱和时间。

### 4.3 为什么仍然选整卷

1. **引入一个系统不认识的新状态**。逐题提交后崩溃，库里会留下
   `practices.status = 'submitted'` + **部分** `grading_records`。
   现有状态机里没有这个形态：`PARTIALLY_GRADED` 的语义是
   「有记录处于 `pending_regrade`」（`:286-288`），**不等于**「只判了一半」。
   报告页、诊断、错题本都按状态机取数，凭空多一个中间态需要逐处确认。
2. **整卷提交的崩溃恢复路径已经存在且被验证过**：RQ 重试 + 重试耗尽后的
   `handle_job_terminal_failure` → `mark_grading_failed`（`worker.py:137-186`）
   把练习推进到 `PARTIALLY_GRADED`，用户可经 `retry_grading` 重入。
   走这条路不需要新代码；逐题提交反而要重新验证这些恢复路径在新中间态下是否仍成立。
3. **改动面 3 行 vs 一个待评估的状态机扩展**。本任务是 P0 阻断项，
   目标是让闭环成立，不是在判题引擎里引入耐久性机制。

### 4.4 留档：逐题提交作为后续可选优化

若将来主观题占比高、重放成本成为实际痛点，可按下述形态做，且**不需要改外部契约**：

- 在 `grade_practice` 的 item 循环内，`_grade_attempt_item` 成功返回后提交一次；
- 循环结束后再做状态/总分汇总的**最后一次**提交（`:277-294` 那段逻辑不动）；
- 需要给「部分完成」定名：或复用 `PARTIALLY_GRADED` 并扩展其语义，
  或新增状态——**这是产品决策，不是实现细节**，故不在本次范围。

---

## 5. 测试设计：唯一能拦住本缺陷的用例

### 5.1 既有用例为什么拦不住（精确到行）

`tests/unit/services/test_grading_service.py:50-58`：

```python
@pytest.fixture
def session() -> Generator[Session, None, None]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as sess:
        yield sess
    engine.dispose()
```

单个会话贯穿"造数据 → 跑判题 → 断言"，且断言全部落在 **`summary.records` 这些内存对象**上
（如 `:216-227`、`:249-250`）。`flush()` 足以让同一会话内的查询与这些对象可见，
**`commit()` 是否发生对该文件里任何一个断言都不产生影响。**

⇒ **这不是"覆盖不足"，是"测了但测的是另一件事"**：这些用例验证的是**判题算法与状态机**，
它们在这件事上依然有效、依然要保留。缺的是**提交边界**这一维，
而这一维**只有跨会话才可观测**。

### 5.2 新用例的形态

在同一个测试文件内新增**恰好一条**，物理上复现「写 → 关会话 → 开新会话查」：

```python
def test_grade_practice_commits_across_session_boundary(tmp_path: Path) -> None:
    """判题结果必须跨越会话边界存活（提交边界回归，AC-3）。"""
    # 文件型 SQLite（理由见 §5.4，不是"内存库测不出来"——恰恰不是那个原因）。
    engine = create_engine(f"sqlite:///{tmp_path / 'grading.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    with factory() as writer:                      # ── 会话 1：写
        env = _build_practice_env(writer)
        writer.delete(env["item_sub"])             # 只留 4 道客观题，不触发 LLM
        writer.flush()
        writer.commit()                            # 造的数据本身要先落库
        practice_id, user_id = env["practice"].id, env["user_id"]

        summary = GradingService(session=writer).grade_practice(
            user_id=user_id, practice_id=practice_id
        )
        assert summary.status == PracticeStatus.COMPLETED.value   # 内存里当然是对的

    # writer 已关闭。修复前：未提交事务在此被丢弃。

    with factory() as reader:                      # ── 会话 2：查
        records = reader.execute(
            select(GradingRecord).where(GradingRecord.practice_id == practice_id)
        ).scalars().all()
        assert len(records) == 4                   # ← 修复前是 0，本用例在此变红

        practice = reader.get(Practice, practice_id)
        assert practice is not None
        assert practice.status == PracticeStatus.COMPLETED.value   # 修复前仍是 submitted
        assert practice.total_score == 10.0                        # 修复前是 None
```

**三条硬约束（写进 implement.md，不许打折扣）**：

1. **必须用文件型 SQLite（或真实 PG），不得用 `:memory:`**。
   **理由不是"内存库测不出缺陷"**——会话关闭时未提交事务被回滚，这件事与存储介质无关；
   只要连接仍被复用，`:memory:` 同样能暴露本缺陷。真正的理由是**稳健性**：
   内存库一旦遇到连接变动（线程切换、池回收），会连库带表整个消失，
   用例就以 `no such table` 这种**错误理由**变红。**假红比不红更坏**——
   它会让人误判缺陷更严重，或在修复已生效时仍看到红色而回退修复。
   实测依据见 §5.4。
2. **断言必须走新会话的查询，不得读 `summary.records`**。读返回的 ORM 载荷
   **正是既有用例的盲区本身**，用它来验证提交边界等于把缺陷复制进新用例。
3. **必须先红后绿**。修复前跑一次，贴出失败输出（预期 `len(records) == 0`）；
   再修复、再跑、贴出通过输出。没有红色阶段的"回归用例"无法证明它锁住了这个缺陷。

### 5.3 复用既有造数逻辑的最小重构

`setup_practice_env`（`:68-184`，约 115 行）需要被新用例复用，但它现在被绑成 fixture。
把它抽成接受 `session` 参数的普通函数，fixture 退化为一行转发：

```python
def _build_practice_env(session: Session) -> dict[str, Any]:
    ...   # 原 fixture 主体，逐字不动

@pytest.fixture
def setup_practice_env(session: Session) -> dict[str, Any]:
    return _build_practice_env(session)
```

**行为不变性如何证明**：抽取只改签名、不改函数体；该函数**一个字节的造数逻辑都不动**
（包括它末尾的 `session.flush()` —— **不要在抽取时顺手改成 commit**，
那会改变既有 30+ 个用例的会话状态，属于未被要求的改动）。
证明方式 = 既有用例全绿（`task verify-backend`，AC-6），一条都不许调整断言。

### 5.4 机制实测（规划阶段已跑，不是推断）

上面关于"跨会话能否观测"的说法是**本用例判别力的全部依据**，故在写代码前先用独立探针实测，
不靠"SQLAlchemy 应该是这样"。探针手法：会话 1 关闭后 **`engine.dispose()`**，
强制会话 2 重新建立连接——不 dispose 的话连接池会把同一条连接复用给会话 2，
内存库"看起来"还活着，结论就是假的。

| 问题 | 结果 |
| --- | --- |
| `sqlite:///:memory:` + `commit`，换连接后查 | **`no such table: probe`（库整个消失）** |
| 文件型 SQLite + `commit`，换连接后查 | 查到 1 行（库仍在） |
| 文件型 SQLite **只 `flush` 不 `commit`** | **查到 0 行** ← 缺陷可观测 |
| 文件型 SQLite 显式 `commit` | 查到 1 行 ← 修复可观测 |

⇒ 两条关键结论都由实测支撑：**缺陷跨会话确实可见**（否则用例没有判别力），
**且文件型是唯一不会产生假红的载体**。

---

## 6. 风险与回滚

| 风险 | 评估 | 应对 |
| --- | --- | --- |
| 提交后读 ORM 对象触发刷新，失败 | 低。行已在本事务内落库，刷新必命中 | 门禁全量跑；失败则退化为 §3.3 的替代方案 |
| 既有用例因 `expire_on_commit` 行为变化而红 | 低。用例主要在提交点**之前**读数据 | 若真发生，说明该用例依赖了"未提交"的隐含状态，需**单独判断**是补提交还是修用例——不许为了让门禁变绿而回退修复 |
| 提交使 `retry_grading` 等既有恢复路径语义变化 | 极低。改动只让原本丢失的写入不再丢失，不改变任何状态跃迁条件 | `practice.py` 零改动 |
| 真实库上重判用户数据消耗 LLM 配额 | 中。AC-2 要重判 `b5fa06ed-…`（12 题，含主观题） | 执行 AC-2 前先查该练习的题型构成并告知用户，**由用户点头再跑**；优先用不带主观题的路径验证 |

**回滚**：把三处 `self.session.commit()` 改回 `self.session.flush()` 即回到现状，
无数据迁移、无 schema 变更、无外部契约变更。

---

## 7. 明确不做

- **不改 `AppContainer.get_session()`**（`container.py:138-152`）。规范 `:58` 已把它
  "正常退出不自动 commit" 写成**既定语义**，改它等于全项目事务语义变更。
- **不改 `GradingRepository`**。它 `add`/`flush` 不 `commit` 是规范 `:85` 的要求，现状正确。
- **不改 `worker.py` 的 `_grade_practice`**（不在 worker 侧补提交）。那样只修好四条路径里的一条，
  自评/重判与 CLI 依旧丢数据；且会把"提交"这一 service 层职责外泄到执行器层。
- **不改前端「判题中」文案**、**不改客观题「秒出」的时机设计**（PRD Out of scope，理由见 PRD）。
- **不改 `dashboard`/学情取数**。本任务只让数据存在，学情口径问题归 `09-29-fix-learning-stats`。
  （副作用提示：本任务落地后与 `learning-stats` 是**叠加**关系——判题落库让学情有数据可算，
  统计口径仍需单独修，两者不可互相顶替。）

---

## 8. 遗留观察（本任务不处理，登记备查）

`app/api/deps/grading.py:43-45`：

```python
actual_session = (
    session if isinstance(session, Session) else container.session_factory()
)
```

`else` 分支经 `container.session_factory()` **新建一个永不关闭的会话**（泄漏连接池资源），
且它同样不提交。当前不可达——`Depends(get_db_session)` 在其之前就会抛或正常供值——
但这是个"看起来像兜底、实际是陷阱"的分支。**不在本任务修**（未授权范围、且当前不可达），
登记供后续单独立项时一并清理。
