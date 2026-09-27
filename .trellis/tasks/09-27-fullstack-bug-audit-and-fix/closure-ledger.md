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
| BUG-MAT-005~011 | P2 | `09-27-fix-mat-p2a` | 文件大小上限双端对齐、重拍类型统一、知识树状态重置、父子半选推导、列表分页去重、首屏单触发（006 判为设计收窄·非缺陷） |
| BUG-MAT-012~018 | P2 | `09-27-fix-mat-p2b` | 上传读取前体积门禁（413）、考点/页数统计字段、H5 渠道来源、snippet 关联去重、temp_id 防坍缩、重拍旧对象清理 |
| BUG-QGEN-002~006,008 | P2 | `09-27-fix-qgen-p2` | 出题上限对齐 1–20、删除原因走 query（后端 body 兜底）、质检类型字段对齐、删除后重置首页防跳题、跨题型答案域守卫、空/非法题型校验 |
| BUG-PRAC-005~011 | P2 | `09-27-fix-prac-p2a` | 回放标记、paused/timeout 入枚举+跃迁、作答白名单、交卷清草稿、draft 单一 schema、timeout 映射、mode 落库+completed_count 派生（含迁移 0004） |
| BUG-PRAC-012~017 | P2 | `09-27-fix-prac-p2b` | 卸载 flush（身份令牌防竞态）、快照失败容错+DB 回放、主观题型兜底、耗时聚合与真实计时、多选 JSON 序列化、pause/resume API |
| BUG-GRADE-003~008 | P2 | `09-27-fix-grade-p2a` | 要点/原文契约透传（生效记录+批量切片）、移除报告死分支、首屏单加载、主观题集合对齐、未作答禁重判 |
| BUG-GRADE-009~013,016 | P2 | `09-27-fix-grade-p2b` | 确定性 half-up 0.5 舍入、LLM/重批粒度统一、`is_correct` 透传、细则结构化渲染、理由上限 500、判题记录顺序与异常降级 |
| BUG-DIAG-009~015 | P2 | `09-27-fix-diag-p2a` | 掌握度计数同步、error_type/question_type/material_id 过滤下推（去掉 1000 截断）、删除 `removed` 字段、报告页单加载、重置单触发（014 与 GRADE-006 重叠已修） |

## 待处理

- **P1 剩余**：无（GRADE/DIAG 全部 P1 已关闭）。
- **P2 待办（剩余 7 条）**：`fix-diag-p2b`(016-022)。已关闭：AUTH 8、MAT-A 7（含 1 非缺陷）、MAT-B 7、QGEN 6、PRAC-A 7、PRAC-B 6、GRADE-A 6、GRADE-B 6、DIAG-A 7。
- **非功能性**：31 条（重复造轮子/死代码）→ 独立重构任务，不在本轮。

## 口径

- 关闭依据：子任务 `pytest` + `pnpm test:unit` 全绿 + 回归先红后绿 + `trellis-check` 复核通过。
- 每批修复同时沉淀 `.trellis/spec/backend/quality-guidelines.md` 契约场景。
