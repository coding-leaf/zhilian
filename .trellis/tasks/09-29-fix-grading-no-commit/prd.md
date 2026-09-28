# 判题结果不落库：grading 层缺事务提交

## Goal

让整卷判题的结果**真的写进数据库**，从而让「交卷 → 判题 → 学情/错题/掌握度」这条闭环成立。
当前形态是：判题全部算完、任务报成功、结果全部丢弃。

## 现象（2026-09-29 实测）

用户原话：「为啥我选择题都需要判题啊？不该秒出么」——界面上**所有题**永远停在「判题中」。

实测取证（本次侦察，用户账号的真实数据）：

| 观测 | 值 |
| --- | --- |
| `grading_records` 该练习记录数 | **0** |
| `practices.status` | `submitted`（未推进） |
| `practices.total_score` | `None` |
| `attempt_items` 已作答条数 | **12**（用户在作答页确实答了 12 题） |
| `attempt_items.score` 已判分条数 | **0** |
| worker 日志里该判题任务 | `Job OK`，耗时 **0.85 秒** |

**关键对照**：任务报成功、耗时极短、却零产出——不是「判得慢」，是**判完没落库**。

## 根因：**已定案**（代码静态事实 + 实测数据双向印证）

### 事务边界缺一个提交

```python
# app/container.py:138-152
@contextmanager
def get_session(self) -> Generator[Session, None, None]:
    session = self.session_factory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()          # ← 没有 commit()
```

```python
# app/services/grading.py —— 全文件 commit() 出现 0 次
# grade_practice（:197-331）内唯一的持久化动作是：
self.session.flush()
```

**机制**：`grade_practice` 走完 12 条作答的判题、`flush()` 让它们在**会话内**可见并拿到主键、
返回 `PracticeGradingSummary` → RQ 认为任务成功 → `get_session()` 出栈 `close()` →
**未提交的事务被丢弃** → 12 条 `GradingRecord` 与练习状态推进全部消失。

### 为什么只有 grading.py 中招

同一仓库的 `services/material.py` 在关键路径上是**显式提交**的：
派发解析前 `self.session.commit()`（`:1468`）、重试重置后（`:828`）、
`_enqueue_parse` 的失败回写里（`:1496`）。所以这是 `grading.py` **单独漏掉**，
不是全项目的约定问题——**修法应对齐 material.py 的既有写法，不要另创一套事务模式**。

### 为什么门禁全绿却拦不住（**这条比修复本身更值得留档**）

既有判题用例与实现**共享同一个 Session**。`flush()` 之后，同一会话内的查询**看得见**那些记录，
断言全部通过。缺陷只在**会话关闭且未提交**时才暴露——也就是只在真实 worker 进程里。

**这是「测试会话边界」盲区**：测试与生产用了不同的事务生命周期，而测试恰好绕开了故障点。
**因此本任务的验收必须包含一条换会话边界的用例**，否则修完仍然拦不住回归。

（旁证：`_grade_attempt_item` 的「未作答」分支**也会写记录**（`:351-373`），
所以「0 条记录」意味着循环根本没落库，而不是「没有可判的题」——这两者必须区分开，
否则会把本缺陷误诊成「用户没作答」。）

## Change Boundary

### In scope

- `app/services/grading.py`：在判题落库边界补上提交，使整卷判题结果持久化。
- 补一条**换会话边界**的回归用例（见 Requirements R3）。
- 复核 `grading.py` 里其他写库方法的提交边界是否同样缺失（`regrade_attempt`、
  `self_evaluate`、`mark_grading_failed` 等），**一并列出结论**。

### Out of scope

- **不改 `AppContainer.get_session()`**。给上下文管理器加自动提交会改变**全项目**的事务语义
  （包括那些刻意只读或依赖回滚的调用点），风险远大于本缺陷的收益。
  若要动，必须单独立项并逐调用点审计。
- **不改前端的「判题中」呈现**。前端按 `isCorrect === null` 显示「判题中」是**正确行为**——
  它如实反映了「后端没给结果」。本次修的是后端不落库，不是前端文案。
- **不改客观题「秒出」的时机设计**。修好落库后客观题仍走异步判题（秒级延迟）。
  若要改成交卷时同步判客观题，属独立的体验设计决策，另立项。

## Requirements

### R1 — 判题结果持久化

- `grade_practice` 必须在返回前把结果提交，使记录在**会话关闭后**依然可见。
- **提交粒度必须显式决策并写明依据**，两个候选各有代价：
  - **整卷一次性提交**：实现最简，语义最干净（整卷要么全落要么全不落）；
    代价是主观题判题途中崩溃会丢掉已判部分，需整体重判。
  - **逐题提交**：更耐故障，能保留「已判部分 + 待重判」的中间态；
    代价是提交点多、需处理部分完成的状态语义。
  - 倾向：**先取整卷提交**（与 `material.py` 的「边界处提交一次」风格一致，且改动面最小），
    并在 PRD 的 Notes 里记下「逐题提交」这个后续可选优化。
- 不得引入新的 session 或绕过既有 service 层事务约定。

### R2 — 不破坏既有语义

- 失败路径仍必须回滚（`get_session()` 的 `except` 分支不动）。
- 幂等重放语义不变：已由系统判成功且非用户自评的题**不重复判题**
  （`grade_practice` 内既有的 `existing_records` 跳过逻辑，`:243-257`），
  补提交**不得**让这条失效（判题重复消耗 LLM 与分数漂移是它原本要防的）。
- `pending_regrade` 降级路径不变：算法异常时降级为待重判记录、**不中断整卷**。

### R3 — 补一条能拦住本缺陷的用例（**硬性**）

- 用例必须复现「**写 → 关会话 → 开新会话查**」这个边界：
  在一个会话里跑判题（或直接调用落库路径），关闭后**另开一个会话**查询 `grading_records`，
  断言记录存在、练习状态已推进。
- **明确禁止**用「同一会话内 flush 后查询」的写法充当本缺陷的回归覆盖——那正是盲区本身。
- 若既有判题用例都是共享会话的写法，**在 PRD 的 Notes 里如实记录**：
  这些用例对「提交边界」这一类缺陷的覆盖是零，不要假装 R3 补上后整片区域就安全了。

## Acceptance Criteria

- [x] AC-1 复现脚本在修复前失败、修复后通过：跑一次整卷判题 → **新开会话**查
      `grading_records` 有记录、`practices.status` 已推进、`total_score` 非 `None`。
      证据：检查代理从零重做——还原 `grading.py` 到 HEAD 后 `assert 0 == 4`（失败原因正是
      「新会话看不到记录」），恢复后通过；还原用文件备份 + sha256 比对，前后哈希一致
      （`320e8daf…d9d5` / 41240 B）。另做变异测试（断言 `4` 改 `5`）确认用例非空转。
- [x] AC-2 以用户账号的真实数据核对：`b5fa06ed-9270-4db3-ac23-daa11a1ae57c`（12 条作答）
      重新判题后，`grading_records` 出现 12 条、练习状态离开 `submitted`。
      **实测（新会话查）**：`grading_records` 0 → **12**（12 条均 `is_final`）；
      `practices.status` `submitted` → **`completed`**；`total_score` `None` → **4.0**（满分 12.0）；
      `completed_at` 已写；`attempt_items` 已判分 0/12 → **12/12**。整卷耗时 141ms。
- [x] AC-3 R3 的换会话边界用例已加入判题测试文件，且**在修复前能红**（先红后绿，见 AC-1 证据）。
- [x] AC-4 幂等重放不被破坏：对同一练习连续判题两次，第二次不产生重复的最终记录。
      **实测（真实库）**：第二次判题后 `grading_records` 仍为 12（未翻倍）、`is_final` 恰为 12
      （每题一条生效记录）、`total_score` 仍为 4.0（分数不漂移）。
- [x] AC-5 `grading.py` 内其他写库方法的提交边界已逐一核对，结论见 Notes。
- [x] AC-6 `task verify-backend` 全绿，既有判题用例零回归。
      **实测**：ruff format（249 files already formatted）/ ruff check（All checks passed!）/
      mypy strict（135 文件无问题）/ lint-imports（5 contracts kept, 0 broken）/
      pytest（真实退出码 **0**、零 `FAILED`/`ERROR`、覆盖率 **91.16%** ≥ 阈值 80%）。
- [ ] AC-7 端到端：worker 在跑的前提下交卷一次，开发者工具里能看到**逐题判分结果**而非永久「判题中」。
      **此条待用户确认——尚未验证，不得由我方代签。**

## Notes

- **本缺陷是「worker 不可用」之外的第二条独立原因**。二者的关系必须说清，否则下次会误判：
  - worker 缺席 → 判题任务**从未执行**（已由 09-29-fix-parse-stuck 覆盖：worker 改跑在容器里）。
  - 本缺陷 → 判题任务**执行了但结果丢弃**。
  - 修好 worker 之后，用户看到的现象**不会自动好转**，因为本缺陷仍在。实测已证：worker 正常时
    判题任务 0.85 秒 `Job OK`，而 `grading_records` 依然是 0。
- **提交粒度**：本任务先取整卷一次性提交。「逐题提交」作为可选的耐故障优化留档，
  不在本次范围内——它会把「部分完成」变成一个需要状态机支持的新形态，成本不小。
- **既有用例的覆盖盲区**：判题相关用例几乎都在共享会话内断言，对提交边界零覆盖。
  本任务只补一条，不承诺把整片区域的会话边界都测到；若要系统性治理，
  应作为测试基建任务单独立项。
- **`attempt_items.score` 与 `grading_records` 是两个层次**：前者是作答项上的冗余分数，
  后者是判题的权威记录（含 `hit_keywords`/`grading_metadata` 等）。
  排查同类问题时**以 `grading_records` 为准**，否则容易把「冗余字段没回填」误判成「判题没跑」。
  本次侦察一度踩到这个坑，留档备查。

### AC-5 结论：`grading.py` 之外没有遗漏的提交边界

- `mark_grading_failed` **不在本文件**——它在 `app/services/practice.py:1219`，
  **且已经在 `:1262` 提交**，形状与本次三处完全相同（裸 `commit()` 在 `_log_metric` 之前）。
- `grading.py` 内三个私有写库辅助方法（`_grade_attempt_item` / `_grade_with_llm` /
  `_build_pending_regrade_record`）的调用点全部落在三个已修复的边界方法内，
  故**无需**在私有方法里再插提交点。
- `GradingRepository` 自身 0 次提交是**正确**的（规范禁止仓储私自提交），不是遗漏。

### 实测环境观察（与本次改动无关，但会误导下次判断，故留档）

- **并发跑后端测试会产出两条假失败**：本次门禁与检查代理的测试并发执行时，
  `test_migrated_schema_matches_orm_metadata` 与
  `TestMasteryPerformanceBenchmark::test_performance_thousand_records_benchmark` 变红；
  **同一份代码单独重跑退出码为 0、零失败**。下次见到这两条先确认是否有并发运行，
  不要当成回归。性能基准受 CPU 争抢影响是预期内的；迁移一致性那条**同样敏感**，
  这点反直觉，值得记住。
- **`pytest` 汇总行会被 `-qq` 静默关掉**：项目 `backend/pyproject.toml:67` 的
  `addopts = "-ra -q"` 已带一个 `-q`，命令行再加 `-q` 就是 `-qq`，pytest **不再打印**
  `N passed` 汇总行。后果：无法从输出文本判断成败，**只能看退出码**；而
  `cmd | tail` 拿到的 `$?` 是 `tail` 的退出码，恒为 0——这会伪造"全绿"。
  正确姿势：`cmd > out.txt 2>&1; echo $?`，不要接管道。
- **覆盖率达标 ≠ 零失败**：`--cov-fail-under` 通过时照样打印
  `Required test coverage of 80% reached`，**即使有用例失败**。
  本次差点据此误报门禁通过，是 `pytest_cache/v/cache/lastfailed` 暴露了真相。

### 过程留档

本任务的**实现代理未交出报告即消失**，故验证由**另一个**检查代理从零独立重做，
而非采信实现方自述。总结论不变，但证据链是重建的（见 AC-1 的哈希比对与变异测试）。
