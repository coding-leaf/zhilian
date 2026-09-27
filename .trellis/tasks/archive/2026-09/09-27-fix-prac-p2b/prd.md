# 修复 PRAC 切片 P2-B（012-017）

## Goal

修复审计清单 PRAC 切片后半段 6 条 P2 问题（BUG-PRAC-012 至 BUG-PRAC-017）：前端会话卸载未 flush 待同步草稿、交卷事务提交与幂等快照写入顺序异常处理、主观题题型（名词解释/案例分析）渲染兜底、练习累计耗时字段与单题硬编码耗时、多选作答格式跨端规范化、以及前端缺失 pause/resume API 封装。

## 需求来源

上游审计 `09-27-read-only-bug-audit`（已归档）`research/slice-PRAC.md`：

| ID | 级别 | 层 | 现状一句话 |
|---|---|---|---|
| BUG-PRAC-012 | P2 | frontend | 600ms 防抖同步在 `cleanupSession` 时仅 `clearTimeout`，未 flush 待发送项，快速退出导致最后一次作答未即时推到后端 |
| BUG-PRAC-013 | P2 | backend | 交卷 `session.commit()` 之后才执行 `idempotency.set_result`，若写快照异常抛出 5xx，且已提交 COMPLETED，重试无法回放 |
| BUG-PRAC-014 | P2 | frontend | `QuestionRenderer` 仅覆盖 5 类题型，后端判题枚举已支持 `term_explanation` 和 `case_analysis`，快照若包含则无输入控件 |
| BUG-PRAC-015 | P2 | cross-layer | 前端读取 `time_elapsed_seconds` 回填计时但后端 DTO 缺失；前端作答硬编码 `time_spent_seconds: 1` 导致耗时统计失真 |
| BUG-PRAC-016 | P2 | cross-layer | 前端多选提交 `string[]`，后端服务层用 `str(user_answer)` 格式化为非 JSON 的 Python repr 字符串（如 `"['A', 'B']"`） |
| BUG-PRAC-017 | P2 | frontend | 后端已有 `POST /practices/{id}/pause` 与 `/resume`，前端 `api/practice.ts` 缺失封装，且会话层未导出控制方法 |

## Requirements

### 功能要求

1. **PRAC-012（前端卸载 flush 待同步草稿）**：
   - 提取即时同步单项逻辑（`flushCurrentDraft` 或在 `cleanupSession` 中若存在待同步项触发同步）。
   - 提供 `flushPendingDraft()` 方法，在页面 `onUnload` / `onBeforeUnmount` 清理时，若存在挂起的 `syncTimeout` 或未同步草稿，立即清除定时器并触发异步网络暂存（`void syncPendingDrafts()`），确保草稿在离开前尽可能推送到后端。

2. **PRAC-013（交卷幂等快照与异常恢复语义）**：
   - 在 `submit_practice` 流程中，确保当 `session.commit()` 成功后若 `set_result` 抛出异常，捕获该异常记录告警日志，而不让整个请求向上抛出 5xx；同时由于 `practice.submit_idempotency_key` 已事务内持久化到 DB，当客户端重试时，若快照未命中但检查到练习已是 `COMPLETED` 且 `practice.submit_idempotency_key == clean_key`，可从数据库练习记录及其关联任务安全重构回放结果或补写快照返回，避免报 400 阻断。
   - 给出明确判定边界：采用“事务已提交后快照写入容错 + DB 级幂等键兜底回放”，保证客户端网络抖动或 Redis 异常重试时不出现“已交卷却报 400 错误”。

3. **PRAC-014（题型渲染兜底与主观题前向兼容）**：
   - `QuestionRenderer.vue` 为 `term_explanation`（名词解释）与 `case_analysis`（案例分析）以及未知主观题型提供长文本输入框渲染分支（复用类似 `short_answer` 的多行文本输入组件与字数提示）。
   - 在 `questionTypeLabel` 中补齐 `term_explanation: '名词解释'` 和 `case_analysis: '案例分析'`，默认 fallback 为 `'练习题'`。

4. **PRAC-015（耗时字段补齐与前端耗时真实计算）**：
   - **决策采纳：后端补齐 `time_elapsed_seconds` 字段**。在 `PracticeDetailResponse` 中新增附加可选字段 `time_elapsed_seconds: int = 0`，取自所有作答项的 `sum(item.duration_seconds)`（或练习累计耗时），并在 `synchronize_detail_fields` 中映射。
   - 前端 `usePracticeSession.ts` 中消除硬编码 `time_spent_seconds: 1` 与 `duration: 1`：基于题目进入时间戳计算该题真实停留耗时（秒，至少 1 秒），并在作答变更时传入真实用时增量。

5. **PRAC-016（多选作答格式跨端规范化与历史 repr 兼容）**：
   - **后端存储规范化**：`SaveAnswerDTO.user_answer` 在服务层处理时，若输入为列表或 JSON 数组字符串，规范化为标准 JSON 字符串（例如 `json.dumps(sorted(answers))`）；若为字符串则去除首尾空格。
   - **历史数据兼容**：若数据库中已存在 Python repr 格式（如 `"['A', 'B']"`），判题算法（`normalize_objective_token`）既有正则提取字母已能兼容；同时在反序列化或 DTO 输出给前端时，若遇到 Python repr 格式，做容错解析转为标准数组或规范字符串，保证跨端传输格式一致性。

6. **PRAC-017（前端补齐 pause/resume API 封装与会话控制）**：
   - 在 `miniprogram/src/api/practice.ts` 中新增并导出 `pausePractice(practiceId: string)` 与 `resumePractice(practiceId: string)`，请求后端 `POST /api/v1/practices/{id}/pause` 和 `/resume`。
   - 在 `usePracticeSession.ts` 中封装 `pauseSession` 与 `resumeSession` 函数并导出，管理本地计时器的暂停与恢复。
   - **UI 范围明确**：本任务仅补齐 API 与 composable 会话控制层及单元测试，会话页暂不新增强制中断 UI 按钮（避免破坏既有做题页面极简交互规范与 UI 门禁），但在 composable 层暴露能力供后续业务随时挂载。

### 约束

- 契约权威：后端 `backend/app/schemas/practice.py`（`PracticeDetailResponse`、`PracticeStatusResponse`、`SaveAnswerResponse`）。
- 新增字段一律**附加可选**，默认值保持旧行为，存量客户端与单测不被破坏。
- 无 `any`；严格遵循 import-linter 与分层架构规范；前端测试夹具字段名逐字取自后端。
- 不得弱化既有测试；前后端门禁命令全绿。

### 不在范围内

- PRAC 其余切片（P0/P1 已归档或在其他切片处理）。
- 会话页复杂中断弹窗 UI 设计（仅提供 composable 状态控制与 API 支撑）。

## Acceptance Criteria

- [ ] **PRAC-012**：`usePracticeSession` 暴露 `flushPendingDraft`，在 `cleanupSession` 或页面卸载钩子触发时立即同步尚未发出的草稿变更。
- [ ] **PRAC-013**：若交卷时已执行 `session.commit()`，即使 `set_result` 抛出异常，客户端重试相同的 `idempotency_key` 时能安全识别并回放成功结果，不再抛出 40011 错误。
- [ ] **PRAC-014**：`QuestionRenderer.vue` 传入 `question_type="term_explanation"` 或 `"case_analysis"` 时，能正常渲染出多行文本输入框与题型标签，且支持输入更新。
- [ ] **PRAC-015**：后端 `PracticeDetailResponse` 返回 `time_elapsed_seconds`（作答项耗时总和），前端加载会话时正确同步耗时；前端作答记录的不是常量 1 秒而是真实耗时秒数。
- [ ] **PRAC-016**：后端接收多选数组作答时，存储为标准 JSON 字符串；历史 `"['A', 'B']"` 格式可无损解析与规范化。
- [ ] **PRAC-017**：`miniprogram/src/api/practice.ts` 导出 `pausePractice` 和 `resumePractice`；`usePracticeSession` 支持暂停和继续计时。
- [ ] 后端门禁全绿：`ruff format --check .`、`ruff check .`、`mypy app`、`lint-imports`、`pytest tests`。
- [ ] 前端门禁全绿：`pnpm run lint`、`pnpm run type-check`、`pnpm run test:unit`。

## Notes

- 父任务：`09-27-fullstack-bug-audit-and-fix`。
- 完整证据见归档 `archive/2026-09/09-27-read-only-bug-audit/research/slice-PRAC.md`。
