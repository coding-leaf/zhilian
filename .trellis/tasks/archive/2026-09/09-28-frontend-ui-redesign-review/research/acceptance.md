# 验收记录：测试证据与外部服务限制

本文件对应 `implement.md` 第 10 步的「记录测试证据与未能验证的外部服务条件」，供归档与后续人工验收使用。

## 门禁证据（2026-09-29 实测）

| 命令 | 结果 |
| --- | --- |
| `task verify` | **exit 0**（后端 + 前端全链路） |
| `backend: uv run ruff format --check .` | 247 files already formatted |
| `backend: uv run ruff check .` | All checks passed |
| `backend: uv run mypy app` | Success: no issues found（134 source files） |
| `backend: uv run lint-imports` | Contracts: 5 kept, 0 broken |
| `backend: uv run pytest tests` | **1365 tests / 0 failures / 0 errors**，覆盖率 **91.15%** |
| `miniprogram: pnpm run lint` | exit 0（无输出） |
| `miniprogram: pnpm run type-check` | exit 0（无输出） |
| `miniprogram: pnpm run test:unit` | 7 files / **39 tests** 全通过 |

后端计数经 `--junit-xml` 独立统计确认（`<testcase` 计数 1365、`failures="0"`、`errors="0"`）。

### 已知既有抖动（与本任务无关，未放宽断言）

- `tests/unit/core/algorithms/test_ocr_quality.py::test_tc_ocr_18_large_batch_throughput_performance`（wall-clock 阈值 100ms）
- mastery 性能用例（阈值 20ms）

两者在机器负载下会偶发失败（观测到 104.86ms），单独重跑即通过；两文件自 `828d6b0` / `b00df4d` 起未被本任务触碰。因此 **AC-8 按「除既有 wall-clock 计时抖动外 `task verify` 全绿」记录**，该表述已经用户确认。

## 验收结论（AC-1 ~ AC-9）

| AC | 结论 | 说明 |
| --- | --- | --- |
| AC-1 昵称/头像/课程 | 通过 | 头像改为选图上传（魔数校验 + 对象键持久化 + 预签名续期），课程创建/重命名/归档入口齐备 |
| AC-2 手动解析闭环 | 通过 | 上传零调度、版本 `not_started`、`/parse` 与 `/retry` 派发经条件更新，失败可见可重试 |
| AC-3 多考点多题型组卷与核对 | 通过（来源项见下） | 七题型、分批上限、覆盖缺口门控、核对页不展示答案与解析 |
| AC-4 七题型作答与草稿 | 通过 | 串行草稿队列、失败可见、交卷前 flush、稳定幂等键、按用户隔离的本地草稿 |
| AC-5 判题进度与复查 | 通过 | 未判项不显示零分/答错；全判完才生成诊断；自评与 AI 复查可刷新生效结果 |
| AC-6 错题归类与再生 | 通过 | 按课程/未分类分组，再生题强制单一范围，不跨课程混卷 |
| AC-7 AI 助教 | 通过 | 题目级读 `reply/suggestions`；课程级授权检索 + 引用校验 + 至多修复一次或拒答 |
| AC-8 契约测试与门禁 | 通过（附条件） | 见「门禁证据」；真实微信端到端未执行，见「未验证的外部条件」 |
| AC-9 后台任务真实执行 | 部分 | 受控任务注册、有限重试、终态回写、只读巡检均已落地；**worker 存活探测未实现**，见「挂账与遗留」 |

## 未验证的外部条件（未伪造任何端到端证据）

以下均只做到单测/静态校验层，需人工在真实环境确认：

1. **微信真机端到端**：上传 → 手动解析 → 出题核对 → 七题型作答 → 交卷判题 → 诊断 → 复查 → 错题再生 → 助教追问的完整链路未在微信开发者工具/真机跑过。`miniprogram` 无 e2e 驱动（仅 vitest 单测），本环境也无法运行微信模拟器。
2. **真实 Redis + RQ 跨进程消费**：未启动 Redis 与 `app/worker.py` 实际消费过解析/判题任务。特别地，**「RQ worker 在重试耗尽后确实调用 `on_failure` 回调」这一行为未被验证**——现有测试只用替身 job 覆盖了回调自身的分支逻辑。
   人工验证步骤：`docker compose up redis` → `cd backend && ZHILIAN_QUEUE__PROVIDER=redis uv run python -m app.worker` → 前端交卷 → 人为让 `grading_jobs` 持续抛错 → 观察日志依次出现「按退避策略重试」与「重试耗尽并进入终态失败」→ `GET /practices/{id}` 的 `status` 变为 `partially_graded` 且 `completed_at` 为 null → 结果页出现「待重判」→ 点「重试判题」返回 200 并重新入队。
3. **真实 LLM**：出题、判题、复查、课程助教的引用校验（拒答与一次修复）未连真实模型验证。
4. **对象存储**：`/users/me/avatar` 真实选图上传、预签名 URL 续期、旧对象清理未在真实 S3/MinIO 上验证。
5. **PostgreSQL**：迁移 `0009_avatar_object_key` 未在真实 PG 应用；`queue stalled` 的巡检 SQL 在 SQLite 上通过，PG 侧返回类型仅做了归一化处理而未实测冒烟。
6. **后端性能阈值**：见「已知既有抖动」。

## 挂账与遗留

1. **R3「核对页展示来源」未达成**（已挂账为独立子任务 `.trellis/tasks/09-28-question-source-snippet/`）：
   `backend/app/services/question.py::aggregate_snippet_context` 写入的元数据只有 `{snippet_id, similarity, index}`，不含切片正文；`QuestionDetailResponse` 同样只有 `source_snippet_id`。前端来源框因此恒空。用户决定不在本任务修复。
   关联修正：本任务已修掉该处**假通过的契约测试**（题目侧 fixture 曾手工补了服务端不返回的 `source_snippet` 字段），原文溯源断言改挂到**真实返回正文**的练习侧 fixture。
2. **worker 存活探测 / 队列积压告警未实现**（AC-9 后半）：`QueueProtocol` 不暴露队列深度与 worker 注册表，探测需绕过该边界直接读 RQ registry；本任务的只读巡检 `queue stalled` 已覆盖「业务记录永久待处理」的可定位性。
3. **`submitted` 长期滞留时用户无法自助重试**：`retry_grading` 刻意只接受 `partially_graded`（`submitted` 视为判题进行中），放开会在 worker 积压场景造成同一练习并发双判。若要放开，需先给整卷判题加练习粒度的幂等/互斥。
4. **前端测试不在类型检查范围内**（既有配置缺口）：`miniprogram/tsconfig.json` 的 `include` 仅含 `src/**`，`vue-tsc` 不检查 `tests/**`，因此 `tests/practice.spec.ts` 中的 `status: 'IN_PROGRESS'`、`submitted_count` 等不符合领域类型的写法不会被门禁发现。
5. **既有规范债（本任务未引入，仅部分触碰）**：`pages/index/index.vue` 865 行、`subpackages/material/pages/course/index.vue` 728 行、`pages/profile/index.vue` 440 行、`components/AiCoachDrawer.vue` 392 行、`subpackages/report/pages/detail/index.vue` 343 行超出 `.vue <= 300 行` 约定；组件内含 Emoji；`src/api/index.ts`(424)、`src/types/index.ts`(441)、`stores/practice.ts`(302) 单文件偏大。另 `subpackages/material/pages/upload/index.vue` 是 32 行空占位页（真实上传入口在工作台），出题页题量 `slider :max="15"` 与后端单批上限 20 不一致。

## 提交

| Hash | Message |
| --- | --- |
| `609e7f1` | feat(backend): 接入 RQ 进程外任务执行、终态失败回写与运维巡检 |
| `15a621e` | fix(backend): 修复资料解析、判题诊断与助教闭环断点（含并发派发竞态） |
| `2e8a45d` | feat(frontend): 重建 API 归一化层并打通作答→判题→诊断→错题闭环 |
| `32fd0a2` | docs(spec): 纠正前端规格失配并沉淀后端闭环契约 |
