# 实施计划：课程创建与生题流程修复（父任务）

> 父任务负责跨子任务的契约、集成验收与最终收口；实现落到子任务。执行顺序：C1 → C2 → C3（迁移号 0007 → 0008）。

## 0. 前置校验（编码前）

- [ ] 阅读父任务 `prd.md` + `design.md`；确认迁移号分配（0007/0008）。
- [ ] 确认工作区分支与基线：`git status`、`git log --oneline -5`。
- [ ] 后端质量门禁命令：`task verify-backend`（`ruff format --check`、`ruff check`、`mypy app`、`lint-imports`、`pytest --cov-fail-under=80`）。
- [ ] 前端质量门禁命令：`task verify-frontend`（`pnpm run lint`、`pnpm run type-check`、`pnpm run test:unit`）。

## 1. C1 课程创建与列表健壮化（B1/B6/B7）

### 后端
- [ ] `FolderRepository.name_exists` 增加 `archived_at IS NULL`（`repositories/folder.py`）。
- [ ] 模型改为部分唯一索引（`models/material.py`）。
- [ ] 迁移 0007：drop 旧唯一约束 → 建部分唯一索引；对称 `downgrade`；SQLite/PG 双 where。
- [ ] 单测：活跃同名 409、归档同名可创建；迁移 upgrade/downgrade/upgrade。
- [ ] 校验：`task test-backend` → `task verify-backend`。

### 前端
- [ ] `CourseCreateDialog.vue` 增加 `submitting` 禁用；`CourseListSection.vue` 提交锁 + 乐观插入 + 409 文案分流。
- [ ] 课程页三态（loading/empty/error+retry）+ 移动后 `refreshAll()`。
- [ ] 首页课程列表失败兜底（保留旧值 + 提示/重试）。
- [ ] 单测：防重复提交、409 提示、课程页错误态、移动后刷新。
- [ ] 校验：`task verify-frontend`。

## 2. C2 课程生题链路（B2/B4/B5）

### 后端
- [ ] `GET /folders/{id}/knowledge-points` 接口 + service + schema（按资料分组）。
- [ ] 迁移 0008：`questions.batch_id` 列 + 索引；对称 `downgrade`。
- [ ] `batch_id` 贯通（`generate_questions` / `_for_knowledge_points` / `_for_folder`）+ 写入题目行与质检行。
- [ ] `QuestionDetailResponse.batch_id` + `QuestionListQuery.batch_id` + 仓储过滤 + 路由透传。
- [ ] 单测：批次一致性（多考点/课程范围共享同一 batch_id）、list 按 batch 过滤、迁移对称、课程考点接口（归档 404/空分组）。
- [ ] 校验：`task verify-backend`。

### 前端
- [ ] `CourseKnowledgePointPicker.vue`（按资料分组多选，≤500 行）。
- [ ] `CourseGenerateDrawer.vue`：选题区块 + 进度面板 + 空结果不锁死 + 成功跳转；携带 `knowledge_point_ids`。
- [ ] `QuestionConfigDrawer.vue`：空结果不锁死。
- [ ] `types/question.ts` + `questions/index.vue`：`batch_id` 分组/筛选。
- [ ] 单测：选题 payload、空结果/失败可重试、成功跳转、批次分组渲染、单资料零回归。
- [ ] 校验：`task verify-frontend`。

## 3. C3 知识点树加载性能与三态（B3）

- [ ] `utils/tree.ts` 新增 `buildCheckStatusMap(nodes, selectedSet)`（单次遍历）；`KnowledgeTreeNode.vue` 改为读 map。
- [ ] 树页三态（loading/empty/error+retry）。
- [ ] `request.ts` 的 `executeRefreshToken` 增加显式 timeout。
- [ ] 单测：`buildCheckStatusMap` 边界、树页错误态重试、刷新队列超时。
- [ ] 校验：`task verify-frontend`。

## 4. 集成验收（父任务）

- [ ] 全部子任务归档后，跑 `task verify`（后端 + 前端全量）。
- [ ] 按父 `prd.md`「Cross-Child Acceptance Criteria」逐条核对。
- [ ] 真机/手工核对项：B7 移动后列表（`GET /materials?folder_id=` 是否非空）、B3 大树不卡、B2 两入口跳转。
- [ ] 规范回改（Phase 3）：更新 `frontend/quality-guidelines.md:567`、`backend/quality-guidelines.md` 批次语义。
- [ ] 归档子任务与父任务；记录 journal。

## 5. 风险与回滚点

| 风险 | 缓解 |
|---|---|
| 迁移号冲突（两子任务） | 固定 0007/0008，后落地者顺延并记录 |
| 部分唯一索引在 SQLite 行为差异 | 显式 `sqlite_where` + 迁移三向单测 |
| 批次贯通遗漏某条生成链路 | 单测覆盖单/多考点/课程范围三链路一致性 |
| 出题同步长请求仍可能超时 | 进度态 + 超时文案（异步队列明确 Out of Scope） |
| 前端三态改动影响既有空态断言 | 更新既有单测，保留"确实无资料"空态 |
