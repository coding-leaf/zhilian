# 课程创建与资料列表健壮化（C1）

> 子任务，隶属父任务 `09-28-course-qgen-frontend-diag`。技术设计与跨子契约见父 `design.md` §2；报障 B1/B6/B7 事实见父 `prd.md`。

## Goal

让"创建课程"不再因连点/同名误报失败，并在归档反悔期内可复用同名；同时让课程内资料列表与首页课程列表在失败/移动后不丢数据、状态可辨。

## Requirements

- **R1.1（B1/B6）防重复提交**：创建按钮在途禁用；重复请求不产生"创建失败"误报；成功用服务端返回乐观插入列表。
- **R1.2（B1/B6）409 识别**：识别 `code=40021`/`status=409` → 明确"课程名称已存在"并保留对话框；不与网络错误混淆。
- **R1.3（B1/B6）归档同名复用**：同名判定与数据库唯一约束排除已归档行（部分唯一索引）。
- **R2.1（B7）课程页三态**：loading / empty / error(可重试) 分离；请求失败不得渲染成"课程暂无资料"。
- **R2.2（B7）移动后确定性刷新**：归类/移动到课程后以服务端结果刷新。
- **R2.3（B7）首页列表兜底**：`GET /folders` 失败时不得静默清空，保留旧值并可重试。

## Acceptance Criteria

- [ ] 快速连点"创建课程"仅产生 1 个课程，无"创建失败"误报。
- [ ] 活跃同名创建 → 报"名称已存在"；已归档同名 → 创建成功。
- [ ] 迁移 0007 `upgrade → downgrade → upgrade` 对称通过（SQLite）。
- [ ] 课程页列表请求失败显示错误态与重试；成功返回空才显示"课程暂无资料"。
- [ ] 首页快捷上传 → 移动到课程 → 进入课程可见该资料（真机为准）。
- [ ] 既有课程 CRUD / 归档 / 移动单测零回归。

## Dependencies & Ordering

- 迁移编号固定 **0007**；若 C2 的 0008 先落地，本任务迁移须顺延并在本文件更新。
- 不依赖其他子任务。

## Notes

- 后端：`repositories/folder.py`、`models/material.py`、迁移 `0007`。
- 前端：`components/course/CourseCreateDialog.vue`、`components/home/CourseListSection.vue`、`subpackages/material/pages/course/index.vue`、`pages/index/index.vue`。
