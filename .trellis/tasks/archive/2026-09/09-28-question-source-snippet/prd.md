# 题目响应补切片正文以支撑核对页来源展示

## Goal

让「出题核对页」能展示题目来源（章节 / 页码 / 原文正文），落实 `09-28-frontend-ui-redesign-review` 的 PRD R3「核对页展示题干、选项和来源」。当前后端题目响应只返回切片主键与 id 级元数据，前端来源框恒为空。

## Background

本任务由 `09-28-frontend-ui-redesign-review` 的验收检查中发现的挂账缺口单开而来。原因：修复需要改动共享响应模型与切片装配路径，风险高于收益，且 `09-28-frontend-ui-redesign-review` 的 AC-3 验收条文并不包含「来源」项，故当时决定挂账。

已核实的事实（以源码为事实源，行号基于挂账时的 HEAD）：

- `backend/app/services/question.py:428` `aggregate_snippet_context` 选取 Top 4 切片，写入 `Question.source_snippet_ids` 的元数据只有 `{snippet_id, similarity, index}`，**不含切片正文**。
- `backend/app/models/question.py:221` `Question.source_snippet_ids` 是 JSON/JSONB 列，注释为「多切片出题上下文列表 (含切片ID与相似度加权元数据)」。
- `backend/app/schemas/question.py:87-113` `QuestionDetailResponse`（同时服务 `POST /questions/generate` 与 `GET /questions/{id}`）只有 `source_snippet_id`（单个）与 `source_snippet_ids`（id 级元数据），**从不返回章节 / 页码 / 正文**。
- 前端 `miniprogram/src/api/adapters/question.ts:58` 取 `question.source_snippet?.snippet_content` 作为 `source_quote`；因为生产响应没有该字段，`source_quote` 恒为 `undefined`，`QuestionPreviewCard.vue` 的来源框永不渲染。
- **对照：练习侧已有可用实现。** `backend/app/services/practice.py:712` `_attach_source_snippets`（BUG-GRADE-004）按 `source_snippet_id` 批量装配 `SourceSnippetDTO`（`backend/app/schemas/practice.py:141-152`，含 `chapter_title` / `page_index` / `snippet_content`），在 `services/practice.py:664` 被详情查询路径调用。本任务应**复用这条既有做法**，而不是另造一套。
- 契约测试曾因 fixture 手工补了服务端不返回的 `source_snippet` 而产生假通过；该假通过在 `09-28-frontend-ui-redesign-review` 中已修（题目侧 fixture 去掉伪造字段、练习侧改用真实 fixture）。本任务的目标是让「题目侧也能真实返回来源」，届时可把来源断言正当地加回题目侧。

## Requirements

- 题目响应（`POST /questions/generate` 与 `GET /questions/{id}`，共用 `QuestionDetailResponse`）增加可展示的来源对象：章节标题、页码、切片正文，字段形状与练习侧 `SourceSnippetDTO` 保持一致，避免前端出现两套来源模型。
- 装配方式复用练习侧既有模式：按 `source_snippet_id`（必要时含 `source_snippet_ids`）**批量**关联切片，避免逐题查询造成 N+1。
- 不破坏既有响应字段与既有测试；新增字段必须可选并有默认值，保证旧数据（`source_snippet_id` 为空）仍可序列化。
- 前端 `adapters/question.ts` 已按 `source_snippet.snippet_content` 取值，确认接通后核对页来源框正常渲染；如字段名与既有 adapter 不一致，应调整后端或 adapter 之一并补契约测试。
- 补契约测试：用**后端 Pydantic 真实序列化样本**固定该字段，覆盖「有来源」与「无来源」两种情形。不得再用手工拼接的伪造 fixture 让断言通过。

## Acceptance Criteria

- [x] AC-1：`POST /questions/generate` 与 `GET /questions/{id}` 的响应真实包含来源对象（章节 / 页码 / 正文），有 `source_snippet_id` 的题目返回正确内容。
      *证据*：`tests/integration/test_p0_full_chain_e2e.py` 端到端断言 generate/detail/list/update 四条路径的 `source_snippet` 内容一致且 `snippet_content` 非空；`tests/unit/services/test_question_service.py::TestQuestionSourceSnippetAssembly` 覆盖投影内容与字段名。
- [x] AC-2：无来源切片的历史题目仍可正常序列化与展示，前端给出准确空态，不伪造来源。
      *证据*：字段可空默认 `null`；服务用例 `test_without_source_keeps_none_and_serializes_null` + schema 用例 `test_question_detail_response_source_snippet_defaults_to_null`；前端用例 `keeps source_quote empty when the question has no source snippet`；E2E 断言无来源项保持 `null`。
- [x] AC-3：关联切片为批量查询，无 N+1；`GET /questions` 列表等高频路径不受负面影响（或明确说明取舍）。
      *证据*：装配走 `MaterialRepository.list_snippets_by_ids` 单次 `IN` 查询（用例断言 1 题与 2 题均为 1 次、无来源为 0 次）；列表路径同样装配，**取舍已在 design.md §3.3 与规范中写明**（该端点本就返回题干/答案/解析全量字段，代价是每响应一次批量查询）。另修掉实施中发现的惰性加载 N+1（见 design.md §3.6）。
- [x] AC-4：前端出题核对页能展示来源正文，且**作答前仍不展示标准答案与解析**（保持 PRD R3 的另一半约束）。
      *证据*：后端接通后 `adapters/question.ts` 的 `source_quote` 有值（前端用例断言真实正文）；`QuestionPreviewCard.vue` 仅有题干/选项/来源三类节点，**不含答案与解析**。说明：未在微信真机上跑一遍，验证止于单测与代码路径。
- [x] AC-5：契约测试使用真实序列化样本，覆盖有/无来源两态；`task verify` 全绿（既有 wall-clock 计时用例的负载抖动除外，需在证据中注明）。
      *证据*：前端 fixture 的 `source_snippet` 取值由后端 `model_dump()` 真实输出生成并注明事实源；`task verify` 退出码 0（后端 1378 passed / 覆盖率 91.16%，前端 41 passed），无负载抖动豁免项。

## 交付结果补充（超出 PRD 的发现）

- 实施中新写的装配用例当场暴露一处**真实缺陷**：ORM 关系 `Question.source_snippet` 与响应字段同名，`from_attributes` 会读到实体本身 —— 既给出半空投影（正文空串），又对每题多一次惰性加载（列表页 N+1）。已把关系改名 `primary_source_snippet` 并加「裸映射零查询」回归用例，细节见 `design.md` §3.6。
- 装配实现按规范「原文装配只有一个实现」抽为跨域共享模块 `app/services/source_snippets.py`，练习侧改为委托，未新增第二份投影逻辑。

## Out of Scope

- 练习侧来源装配的改造（已实现，本任务只复用其模式）。
- 出题链路对「来源正文」做二次加工、富文本渲染或引用高亮。
- 与本缺口无关的题目质量、判题、诊断改动。

## 依赖与顺序

- 依赖 `09-28-frontend-ui-redesign-review` 的修复成果（`QuestionSnapshotDTO` 已补 `knowledge_point_id`、题目侧契约 fixture 的假通过已修）先落地。
