# 后端·文件夹范围出题与组卷

## Goal

把「出题」与「组卷」的范围从「单份资料」扩展到「课程文件夹」：在同一课程内对多份 ready 资料联合综合出题，并支持按课程范围组卷进入答题。落实父任务 D2（资料级知识树 + 出题时跨资料联合）。

## 依赖与前置

- **依赖 C1**（`09-27-folder-backend-model`，已归档）：`MaterialFolder`、`materials.folder_id`、`folder_repository/service`、归档过滤口径。
- 上位契约：父任务 `09-27-course-folder-practice-loop/design.md` §3.3、§3.4、§7。

## Requirements

- R1：`QuestionGenerateRequest` 新增可选 `folder_id`；提供时 `material_id` 可缺省；校验「`material_id` 或 `folder_id` 至少一个」。
- R2：新增 `QuestionService.generate_questions_for_folder(user_id, folder_id, knowledge_point_ids, options)`：
  - 解析文件夹（归属当前用户且未归档，否则 404）；
  - 确定考点集：显式 `knowledge_point_ids` → 校验全部属于该文件夹未归档资料的考点；缺省 → 取该文件夹下所有 ready 资料的全部知识点；
  - 按 `(material_id, version_id)` 分组；题量按组分配（均分 + 余数前置 + 每组至少 1），组内再按考点均分；
  - 每组复用既有单资料生成链路；**跨组单事务原子**（全部成功一次 `commit()`，任一失败整批 `rollback()`）。
- R3：`QuestionGenerateResponse` 的 `material_id/version_id/knowledge_point_id` 改为**可选**（folder 范围无单一资料），单资料路径取值与现状不变。
- R4：`GET /questions` 新增可选 `folder_id` 过滤（按 `materials.folder_id` join，仅未归档课程资料）；与既有 `material_id` 过滤并存。
- R5：`PracticeCreateRequest` 新增可选 `folder_id`；提供时 `knowledge_point_ids` 可为空（取文件夹全部 ready 考点）；`Practice` 新增 `folder_id`（可空）且 `material_id` 放开为**可空**（迁移 `0006`）。
- R6：`PracticeService.create_practice` 支持文件夹范围：`material_id` 可为空、`folder_id` 落库；抽题范围限定该文件夹未归档资料的可用题目；题量不足仍抛 `PracticeEmptyQuestionsError`。
- R7：归档一致性：folder 范围出题与组卷**仅纳入未归档课程**的资料；单资料路径不受归档过滤影响。
- R8：`PracticeDetailResponse.material_id` 改为可选，新增 `folder_id`（可空）；`PracticeSummaryResponse` 同步。

## Acceptance Criteria

- [ ] AC1：对文件夹内多份 ready 资料选定跨资料考点出题，题目分别归属各自来源资料（`material_id/knowledge_point_id` 正确），且为单事务原子（任一组失败 → 零落库）。
- [ ] AC2：文件夹无 ready 资料或无考点 → 返回明确 4xx（不静默成功）。
- [ ] AC3：`GET /questions?folder_id=` 仅返回该课程未归档资料下的题目；与 `material_id` 组合过滤正确。
- [ ] AC4：`POST /practices` 传 `folder_id`（可空 `knowledge_point_ids`）→ 生成的练习 `folder_id` 落库、`material_id` 为空，可正常作答。
- [ ] AC5：归档课程不出现在 folder 范围出题/组卷中。
- [ ] AC6：单资料出题/组卷路径**零回归**（不传 `folder_id` 行为与现状一致）。
- [ ] AC7：后端全工具链绿。

## Out of Scope

- 课程级合并知识树（父任务 D2 明确不做）。
- 前端入口与 UI（属 C4）。

## Notes

- 复用既有能力：`distribute_count`、`generate_questions_for_knowledge_points`、`PracticeEmptyQuestionsError`、`question_repo.list_questions_by_knowledge_point`。
- 为跨组单事务，需给 `generate_questions_for_knowledge_points` 增补 `defer_commit: bool = False`（默认 False 零回归）。
