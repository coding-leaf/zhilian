# 知识点树加载性能与三态（C3）

> 子任务，隶属父任务 `09-28-course-qgen-frontend-diag`。技术设计与跨子契约见父 `design.md` §4；报障 B3 事实见父 `prd.md`。

## Goal

消除单份资料知识点树在大规模节点/全选时的近似二次方渲染开销，并补齐加载/空/错误三态与超时重试，使加载可感知、可恢复。

## Requirements

- **R4.1 去二次方**：勾选态不再逐行重走整棵子树并新建 Set；改为单次遍历预计算 `nodeId → checked/indeterminate/unchecked` 映射，行组件只读。
- **R4.2 三态**：树页区分 loading / empty / error；失败可重试；loading 过长有提示。
- **R4.3 刷新队列超时**：`executeRefreshToken` 增加显式 timeout，避免请求永久排队。

## Acceptance Criteria

- [ ] 大规模节点 + 全选时无长时间卡顿；勾选/半选行为与既有语义一致。
- [ ] `buildCheckStatusMap` 单测覆盖 checked/indeterminate/unchecked/空/畸形输入。
- [ ] 加载失败显示错误态并可重试；刷新队列不再永久挂起。
- [ ] 既有树页单测（折叠/全选/覆盖率）零回归。

## Dependencies & Ordering

- 独立，无迁移，不依赖其他子任务。

## Notes

- 前端：`subpackages/material/utils/tree.ts`、`subpackages/material/components/KnowledgeTreeNode.vue`、`subpackages/material/pages/knowledge-tree/index.vue`、`utils/request.ts`。
