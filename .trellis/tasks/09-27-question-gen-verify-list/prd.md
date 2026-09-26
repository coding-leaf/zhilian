# 生题效果可核验（独立题目页 · 基座）

## Goal

新增独立「题目列表」页并从后端持久加载题目，使其成为**出题成功后的跳转目标**与**生题效果核验入口**，解决「确认不了生题效果」与「退出重进即丢」的问题。

## Requirements

- R1：新增页面 `subpackages/material/pages/questions/index`（标题如「题目列表」），并在 `pages.json` 注册（material 分包）。
- R2：页面 `onLoad` 读取 `material_id`（兼容 `materialId`/`id`），调用 `fetchQuestionList({ material_id, page, page_size })` 拉取**后端已持久化**题目。
- R3：列表项展示：题型徽标、难度、题干、参考答案、解析（可折叠）；主观题隐藏选项。
- R4：复用现有抽屉组件：`QuestionEditDrawer`（编辑）、`QuestionAuditDrawer`（修改痕迹）；删除走 `deleteQuestion`（含确认弹窗与审计原因）。
- R5：提供空状态（「暂无题目，去知识树生成」）与加载态；支持分页/加载更多。
- R6：入口：知识树页提供进入按钮；生成成功后（见 `progress-nav`）跳转本页。
- R7：与全局 Store 隔离（沿用 `listData` 隔离模式），`onShow` 重新拉取以反映最新数据。

## Acceptance Criteria

- [ ] AC1：从知识树页可进入题目页；URL 参数统一为 `material_id`。
- [ ] AC2：题目页数据来自后端（刷新/退出重进后仍在），不再依赖本地 ref。
- [ ] AC3：编辑/删除/修改痕迹入口在题目页可用，操作后列表即时更新。
- [ ] AC4：空列表有明确空状态与引导；加载有 loading。
- [ ] AC5：前端 `lint` / `type-check` / `test:unit` 全绿；新增页面/组件单测。

## Notes

- 类型：`QuestionItem`、`QuestionListQueryParams`（`@/types/question`）；API：`fetchQuestionList`/`deleteQuestion`/`updateQuestion`（`@/api/question`）。
- 参考：知识树页现有题目卡片渲染逻辑（`knowledge-tree/index.vue:80-97`）可迁移。
- 本任务是 `progress-nav` 的跳转目标，**先行**。
