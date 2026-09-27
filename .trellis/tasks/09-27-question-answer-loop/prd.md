# 前端·出题→答题闭环

## Goal

打通「课程内出题 → 题目列表 → 开始答题 → 组卷 → 进入答题页」的前端闭环，修复 `createPractice` 全库零调用的断链；支持课程范围（`folder_id`）出题与组卷，判题沿用既有客观秒判/主观 LLM 分流展示。依赖 C2 后端与 C3 课程 IA。

## 依赖与前置

- **依赖 C2**（`09-27-folder-scope-generation`，已归档）：`POST /questions/generate` 支持 `folder_id`（跨资料联合、缺省考点为全课程 ready 考点）；`GET /questions?folder_id=`；`POST /practices` 支持 `folder_id`（考点可缺省、`material_id` 可空）。
- **依赖 C3**（`09-27-course-ia-frontend`，已归档）：课程详情页（含「课程题目」入口）、`folderStore`、`src/api/folder.ts`。
- 上位契约：父任务 `design.md` §4.2、§4.3。

## Requirements

- R1 类型：`QuestionGenerateRequest` 的 `material_id` 改可选并新增 `folder_id?`；`QuestionListQueryParams` 增 `folder_id?`；`QuestionGenerateResponse` 的 `material_id/version_id/knowledge_point_id` 改可选；`CreatePracticePayload` 的 `material_id` 改可选、新增 `folder_id?`、`knowledge_point_ids?` 可选；`PracticeSession`/`RawPracticeSession` `material_id` 可选 + `folder_id?`。
- R2 课程内出题入口：课程详情页新增「智能出题」，打开 `CourseGenerateDrawer`（题量/题型/难度）→ `generateQuestions({ folder_id, count, question_types, difficulty })` → 成功后跳转题目列表（`folder_id`）；失败按空结果/网络/业务分类可重试。
- R3 题目列表课程化：`subpackages/material/pages/questions/index` 兼容 `folder_id`（与既有 `material_id` 并存，零回归）；空态按范围给出「去出题/去知识树」引导。
- R4 开始答题：题目列表（课程范围且有可用题）新增吸底「开始答题」→ `createPractice({ folder_id, question_count, question_types, mode })` → `practiceStore.initSession` → `uni.navigateTo('/subpackages/practice/pages/session/index?id=<id>')`（带 `fail` 兜底）。**消除 `createPractice` 死代码**。
- R5 材料范围零回归：不传 `folder_id` 时，单资料出题/组卷与既有行为一致。
- R6 判题分流展示：沿用既有 `practice/session` → 报告链路（客观秒判、主观 `pending_regrade` 处理中/回填），不新增答题节奏。
- R7 组件 ≤300 行；零 Emoji；导航统一 `material_id`/`folder_id` 且带 `fail` 兜底。
- R8 门禁：`pnpm run lint`/`type-check`/`test:unit`/`build:mp-weixin` 全绿；关键交互有单测。

## Acceptance Criteria

- [ ] AC1：课程详情「智能出题」可按课程范围生成题目并进入题目列表（跨资料）。
- [ ] AC2：题目列表（课程范围）显示该课程题目；「开始答题」成功创建练习并跳转答题页。
- [ ] AC3：答题页可完成作答并交卷；判题按题型分流展示（客观即判、主观处理中/回填）。
- [ ] AC4：单资料出题/组卷路径零回归。
- [ ] AC5：`createPractice` 不再是死代码（有调用点与单测覆盖）。
- [ ] AC6：前端四门禁全绿；真机手动 E2E 覆盖 AC1–AC3。

## Out of Scope

- 课程内按知识点多选（MVP 用课程缺省范围＝全部 ready 考点；按考点筛选留后续）。
- 刷题/模考双节奏（父任务 D3 明确不做）。
- 多层嵌套、批量移动。

## Notes

- `CourseGenerateDrawer` 复用既有出题配置的题型/题量/难度控件风格；不重复实现 `QuestionConfigDrawer` 的考点树逻辑。
- 生成的题目仍归属各自来源资料；答题快照由后端组卷落库。
