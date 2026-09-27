# 课程生题链路：选题 / 跳转 / 批次分类（C2）

> 子任务，隶属父任务 `09-28-course-qgen-frontend-diag`。技术设计与跨子契约见父 `design.md` §3；报障 B2/B4/B5 事实见父 `prd.md`。

## Goal

课程范围出题支持按资料分组自选必出考点，生成过程可见、成功必跳转、空结果/失败不锁死；同一次生成持久化同一批次号，题目列表按课程与批次分类/筛选。

## Requirements

- **R3.1（B4）课程考点选择**：新增 `GET /folders/{id}/knowledge-points`（按资料分组）；前端按资料分组多选；选中时请求带 `knowledge_point_ids`，未选时缺省=全部且 UI 明确。
- **R3.2（B2）可跳转/不锁死**：两个出题入口（课程抽屉、单资料抽屉）空结果/失败不再 `return` 锁死；成功必跳题目页；生成中可见进度。
- **R3.3（B5）批次落库**：迁移 0008 给 `questions.batch_id`；单资料/多考点/课程范围三链路的题目共享同一批次号；DTO/查询/前端类型补齐 `batch_id`。
- **R3.4（B5）分类展示**：题目列表按课程 + 批次分组/筛选；课程范围显示课程名。

## Acceptance Criteria

- [ ] 课程出题仅生成所选考点的题目（显式 `knowledge_point_ids`）。
- [ ] 一次生成（跨资料/跨考点）的所有题目共享同一 `batch_id`；列表按批次分组可见。
- [ ] 两个入口：空结果/失败可重试不锁死；成功跳转题目页。
- [ ] 迁移 0008 对称通过；历史无 `batch_id` 数据不报错。
- [ ] 单资料出题/组卷/列表零回归。

## Dependencies & Ordering

- 迁移编号固定 **0008**（C1 为 0007）；若落地顺序相反须顺延并更新本文件。
- 不依赖 C1。

## Notes

- 后端：`models/question.py`、迁移 `0008`、`services/question.py`、`schemas/question.py`、`repositories/question.py`、`api/v1/questions.py`、新增 `api/v1/folders.py` 考点接口 + `services/folder.py`。
- 前端：`components/course/CourseGenerateDrawer.vue`、新增 `components/course/CourseKnowledgePointPicker.vue`、`subpackages/material/components/QuestionConfigDrawer.vue`、`types/question.ts`、`api/question.ts`、`api/folder.ts`、`subpackages/material/pages/questions/index.vue`。
- 规范回改：`frontend/quality-guidelines.md:567` 关于"课程出题不传考点"改为"可传"。
