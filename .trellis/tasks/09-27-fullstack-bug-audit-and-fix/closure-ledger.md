# 修复关闭台账（Parent Closure Ledger）

> 本文件是父任务下所有已修复功能性 bug 的权威关闭记录。归档审计 `bug-ledger.md` 为只读证据，不再回写。

## 已关闭（P0/P1）

| Bug | 级别 | 子任务 | 关键改动 |
|---|---|---|---|
| BUG-PRAC-001~004 | P0/P1 | `09-27-fix-prac-p0p1` | 练习响应适配层、交卷幂等键持久化 |
| BUG-AUTH-001~003 | P0/P1 | `09-27-fix-auth-p0p1` | 密钥经 Settings 读取、生产 fail-fast、匿名 401 |
| BUG-MAT-001~004 | P1 | `09-27-fix-mat-p1` | `retake_required`、OCR 分页、去重不共享存储、重拍重建知识树 |
| BUG-QGEN-001, 007 | P1 | `09-27-fix-qgen-p1` | 选项 `content→text` 适配、多考点单事务原子 |
| BUG-GRADE-001, 002 | P1 | `09-27-fix-grade-p1` | 重批同步语义回传新分、练习项 `grading_status` 三态 + pending `score=None` |
| BUG-DIAG-001, 002 | P1 | `09-27-fix-diag-read-p1` | 诊断报告适配层（`weak_points`/`overall_score`/`mastery_rate`） |
| BUG-DIAG-007, 008 | P1 | `09-27-fix-diag-read-p1` | 掌握度全景缺省资料聚合全部、`score_delta = current - previous` |
| BUG-DIAG-003, 004 | P1 | `09-27-fix-diag-wrongbook-p1` | 错题真实 total、攻克可切换（`is_mastered` 可选体） |
| BUG-DIAG-005, 006 | P1 | `09-27-fix-diag-wrongbook-p1` | 错题 `user_answer` 下发、`source_type=wrong_record` + `material_id` 可选解析 |

## 已关闭（P2）

| Bug | 级别 | 子任务 | 关键改动 |
|---|---|---|---|
| BUG-AUTH-004~011 | P2 | `09-27-fix-auth-p2` | 画像更新端点、刷新同步 store、401 重试上限、UTF-8 字节阈值、登录真源水合、service 返回值透传、微信登录线程池、fallback 会话托管 |

## 待处理

- **P1 剩余**：无（GRADE/DIAG 全部 P1 已关闭）。
- **P2 待办（剩余 59 条）**：`fix-mat-p2a`(7)、`fix-mat-p2b`(7)、`fix-qgen-p2`(6)、`fix-prac-p2a`(7)、`fix-prac-p2b`(6)、`fix-grade-p2a`(6)、`fix-grade-p2b`(6)、`fix-diag-p2a`(7)、`fix-diag-p2b`(7)。已关闭：AUTH 8 条。
- **非功能性**：31 条（重复造轮子/死代码）→ 独立重构任务，不在本轮。

## 口径

- 关闭依据：子任务 `pytest` + `pnpm test:unit` 全绿 + 回归先红后绿 + `trellis-check` 复核通过。
- 每批修复同时沉淀 `.trellis/spec/backend/quality-guidelines.md` 契约场景。
