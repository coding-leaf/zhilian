# 全项目 Bug 总清单（Master Bug Ledger）

- 任务：`.trellis/tasks/09-27-read-only-bug-audit`
- 日期：2026-09-27
- 方法：工具链实测（`research/toolchain-baseline.md`，8 项门禁全绿）+ 6 切片静态/跨层审阅 + 非功能性普查。
- 明细：`research/slice-{AUTH,MAT,QGEN,PRAC,GRADE,DIAG}.md`；跨层矩阵：`research/cross-layer-matrix.md`；坏味道：`research/code-smells.md`。
- 级别定义：见 `design.md` §4（P0/P1/P2 客观边界；疑似 SR；环境 ENV）。

> 说明：本文件是**汇总索引 + 已复核结论**；每条完整字段（位置/证据/影响/修复方向）在对应切片文件中。P0 与关键项已由主会话独立复核。

---

## 1. 总体统计矩阵

| 切片 | P0 | P1 | P2 | 小计 | 疑似(SR) | 环境(ENV) |
|---|---:|---:|---:|---:|---:|---:|
| AUTH | 1 | 2 | 8 | 11 | 0 | 0 |
| MAT | 0 | 4 | 14 | 18 | 2 | 1 |
| QGEN | 0 | 2 | 6 | 8 | 0 | 0 |
| PRAC | 1 | 3 | 13 | 17 | 0 | 0 |
| GRADE | 0 | 2 | 12 | 14 | 0 | 0 |
| DIAG | 0 | 8 | 14 | 22 | 0 | 0 |
| **合计** | **2** | **21** | **67** | **90** | **2** | **1** |

- 非功能性发现（另册，本轮不改）：31 条（重复实现 5 / 近似重复 13 / 死代码 8 / 规范违背 2 / 冗余抽象 3）。
- 复核撤销：1 条（`BUG-GRADE-015` 空指针不成立）。

**分布特征**：跨层不一致（cross-layer）占绝大多数，集中在**字段命名漂移**与**端点语义错位**两类主因。

---

## 2. P0 明细（必修 · 已独立复核）

### BUG-AUTH-001 — JWT 密钥来源错位（安全）
- 级别：P0 · 层：backend · 状态：✅ 已复核
- 位置：`backend/app/core/security.py:33-41`、`backend/app/core/config.py:398-401,421-426`
- 现象：`get_secret_key()` 读裸 `SECRET_KEY`，忽略强类型配置 `settings.secret_key`（env 名 `ZHILIAN_SECRET_KEY`）。生产按 `ZHILIAN_` 约定注入密钥时被忽略，回退硬编码默认密钥。
- 复核结论：`config.py:422` `env_prefix="ZHILIAN_"`；`security.py:41` `os.getenv("SECRET_KEY", DEFAULT_SECRET_KEY)`。**确证**。
- 影响：可伪造任意用户 JWT，绕过鉴权。
- 修复方向：统一取 `get_settings().secret_key.get_secret_value()`；生产默认密钥 fail-fast。

### BUG-PRAC-001 — 练习会话题目列表恒空（主流程不可用）
- 级别：P0 · 层：cross-layer · 状态：✅ 已复核
- 位置：后端 `backend/app/schemas/practice.py:232-259`（`PracticeDetailResponse.items`）；前端 `miniprogram/src/subpackages/practice/composables/usePracticeSession.ts:54`
- 现象：后端返回 `items`（元素 `{question_snapshot:{...}}`），前端读 `res.data.questions`，无适配层 → 恒为 `undefined` → `|| []`。
- 复核结论：`PracticeDetailResponse` 仅 `items`，`synchronize_detail_fields` 只同步 `practice_id/id`、`total_count/question_count`，**无 `questions` 别名**。**确证**。
- 影响：PRAC 主流程（作答）不可用。
- 修复方向：前端改读 `items` 并适配 `question_snapshot` 结构，或后端增加 `questions` 兼容字段。

---

## 3. P1 索引（必修 · 21 条）

> 现象摘要见 `cross-layer-matrix.md` 各切片表；完整字段见 `slice-*.md`。

| ID | 切片 | 层 | 关键点 |
|---|---|---|---|
| BUG-AUTH-002 | AUTH | cross-layer | 登录固定 `nickname='学员用户'` 覆盖真实昵称 |
| BUG-AUTH-003 | AUTH | cross-layer | 登录 401 被误判会话过期，吞真实失败原因并重定向 |
| BUG-MAT-001 | MAT | backend | 秒传复用他资料 `storage_key`，源资料硬删连带 purge（数据完整性） |
| BUG-MAT-002 | MAT | cross-layer | `retakeMaterialPage` 用 JSON 而非 multipart，真机重拍必失败 |
| BUG-MAT-003 | MAT | backend | 重拍达标后未重建知识树/清理旧知识点，READY 资料知识树空 |
| BUG-MAT-004 | MAT | cross-layer | 后端无 `retake_required` 状态/不合格页接口，重拍链路不可达 |
| BUG-QGEN-001 | QGEN | cross-layer | 选项 `content` vs `text`，客观题选项渲染为空（与 PRAC-002 同根因） |
| BUG-QGEN-007 | QGEN | backend | 多考点生成逐条 commit，非原子，中途失败遗留部分题目 |
| BUG-PRAC-002 | PRAC | cross-layer | 选项 `content` vs `text`（与 QGEN-001 同根因） |
| BUG-PRAC-003 | PRAC | cross-layer | 交卷幂等键每次重生成，重试非幂等 |
| BUG-PRAC-004 | PRAC | frontend | 草稿整写超 `MAX_STORAGE` 静默失败（数据丢失风险） |
| BUG-GRADE-001 | GRADE | cross-layer | 重批后端同步落 `success`，前端硬编码 `pending_regrade` 不回填 |
| BUG-GRADE-002 | GRADE | cross-layer | LLM 降级 `score=0.0` 且不返回判题状态，前端显示"判错" |
| BUG-DIAG-001 | DIAG | cross-layer | `weak_knowledge_points` vs `weak_points`，薄弱知识点不渲染 |
| BUG-DIAG-002 | DIAG | cross-layer | 详见 `slice-DIAG.md` |
| BUG-DIAG-003 | DIAG | cross-layer | 详见 `slice-DIAG.md` |
| BUG-DIAG-004 | DIAG | cross-layer | "取消攻克"无效：`master` 端点无 body 恒置已掌握 |
| BUG-DIAG-005 | DIAG | cross-layer | 详见 `slice-DIAG.md` |
| BUG-DIAG-006 | DIAG | cross-layer | 错题本"一键巩固"非法 `source_type` + 缺 `material_id`，必 422 |
| BUG-DIAG-007 | DIAG | cross-layer | 详见 `slice-DIAG.md` |
| BUG-DIAG-008 | DIAG | cross-layer | 详见 `slice-DIAG.md` |

> DIAG 有多条 P1 摘要未在主会话逐条展开；修复子任务须回读 `slice-DIAG.md` 获取完整字段。

---

## 4. P2 索引（本轮亦清零 · 67 条）

| 切片 | ID 区间 | 数量 |
|---|---|---:|
| AUTH | BUG-AUTH-004 … 011 | 8 |
| MAT | BUG-MAT-005 … 018 | 14 |
| QGEN | BUG-QGEN-002 … 006, 008 | 6 |
| PRAC | BUG-PRAC-005 … 017 | 13 |
| GRADE | BUG-GRADE-003 … 013（`015` 已撤销） | 12 |
| DIAG | BUG-DIAG-009 … 022 | 14 |

完整 P2 字段见 `slice-*.md`。P2 均满足 `design.md` §4 客观可判定边界（空指针/越界、未处理异常与 Promise 挂起、类型漏洞、契约不一致、状态未重置）。

---

## 5. 疑似（SR）/ 环境（ENV）/ 已撤销 单列

| 类型 | 条目 | 说明 |
|---|---|---|
| SR | MAT ×2 | 真机/开发者工具专属渲染或交互，静态无法确证 |
| ENV | MAT ×1 | 环境受限导致，不计产品 bug |
| 撤销 | `BUG-GRADE-015` | 复核判定空指针不成立 |
| ENV（全局） | toolchain-baseline 记录 | `pytest` LSP 误报、Vue 组件解析警告、Sass 弃用警告均非产品 bug |

---

## 6. 同根因去重（修复时合并处理）

| 根因 | 条目 | 处理建议 |
|---|---|---|
| 选项字段 `content` vs `text` | `BUG-QGEN-001`、`BUG-PRAC-002` | 一处统一（建议后端响应加 `text` 别名或前端归一），同时修两切片 |
| 报告字段名漂移 | `BUG-DIAG-001`、`BUG-GRADE-005` | 建立前后端字段命名对照，统一 schema |
| 前端调用不存在的端点 | `BUG-AUTH-004`（PUT /users/me）、`BUG-PRAC-017`（/pause,/resume） | 后端补路由或前端下线下线无效调用 |
| 幂等键每次重生成 | `BUG-PRAC-003`（功能）+ `SMELL-FE-UTIL-001`（重构） | 功能先修；三份实现合并属重构任务 |
| 重拍链路断裂 | `BUG-MAT-002/003/004` | 三条互为因果，需作为一个修复单元 |

---

## 7. 独立复核记录（主会话，防误报）

| 断言 | 复核方式 | 结论 |
|---|---|---|
| AUTH-001 密钥前缀错位 | `git grep` `config.py:422 env_prefix="ZHILIAN_"` vs `security.py:41` | ✅ 成立 |
| PRAC-001 `items` vs `questions` 无别名 | 读取 `schemas/practice.py:232-302` + `usePracticeSession.ts:54` | ✅ 成立 |
| QGEN-001 / PRAC-002 `content`/`text` | `git grep` 后端 `models/question.py:96,190` vs 前端 `QuestionCard.vue:14`、`QuestionRenderer.vue:20/33/46` | ✅ 成立 |
| DIAG-001 `weak_points` 无后端映射 | `git grep` `schemas/diagnosis.py:188,303`（仅 `points` 别名）+ 前端 `reportStore.ts:59`、`types/report.ts:49` | ✅ 成立 |
| store shim 是否死代码 | `git grep -F "stores/material|practice|report|user"` 全库 | ✅ 4 个 shim 0 引用（死代码）；`stores/index.ts` 被 `tests/unit/stores/index.spec.ts` 引用，**非**死代码 |
| `login.vue` 中文乱码 | read 工具读取 | ❌ 伪问题：仅控制台解码，文件无损坏 |

---

## 8. 修复批次建议（供父任务派生修复子任务）

| 批次 | 切片 | 范围 | 优先级依据 |
|---|---|---|---|
| B1 | PRAC | P0 + P1（001/002/003/004） | 主流程不可用 + 同根因 |
| B2 | AUTH | P0 + P1（001/002/003） | 安全 + 登录语义 |
| B3 | MAT | 重拍链路 P1（002/003/004）+ 001 | 功能断裂 + 数据完整性 |
| B4 | QGEN | P1（001/007） | 选项渲染 + 原子性 |
| B5 | GRADE | P1（001/002） | 状态/判级错位 |
| B6 | DIAG | P1×8 | 数量最多 |
| B7 | 全部 | P2 × 67 | 客观项清零 |

> 每批次门禁：回归测试（先红后绿）+ 该包全工具链绿（见 `design.md` §10 / `implement.md`）。

---

## 9. 评审门禁（Gate 1）

- [x] 覆盖全部 6 垂直切片，无遗漏。
- [x] 每条功能性发现含证据与 `file:line`（见各切片文件）。
- [x] P2 均满足客观边界，无主观 UX 混入。
- [x] P0/关键断言已由主会话独立复核，标记误报已剔除（GRADE-015、login 乱码）。
- [ ] **用户确认清单**（本文件）→ 通过后由父任务按批次派生修复子任务。
