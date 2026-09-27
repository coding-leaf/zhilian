# 实施计划：课程文件夹与出题-答题闭环重构

> 父任务实施通过子任务推进。每个子任务独立规划/实现/校验/归档；依赖顺序写在下方，不靠树位置隐式表达。

## 0. 前置

- [ ] 用户对父任务 `prd.md` / `design.md` / 本文的最终方案给出**明确批准**后，方可 `task.py start` 与进入实现。
- [ ] 依 `design.md §2.4 / D5` 清空现有测试数据（`materials / material_versions / material_snippets / material_ocr_pages / knowledge_points / knowledge_point_snippets / questions / question_quality_checks / question_audit_logs / practices / attempt_items / grading_records / mastery_records / diagnosis_reports / wrong_records`）。
- [ ] 建立子任务树（父任务下 4 个子任务），并逐个子任务补 `prd.md`（复杂者补 `design.md`/`implement.md`）。

## 1. 子任务顺序与依赖

```
C1 后端·文件夹实体/归档/资料归属 ──┬─→ C2 后端·文件夹范围出题与组卷 ─┐
                                     └─→ C3 前端·课程 IA/未分类/归档 ──┴─→ C4 前端·出题→答题闭环
```

- C1 无前置。C2 依赖 C1。C3 依赖 C1。C4 依赖 C2 + C3。
- 先做 C1（解锁 C2/C3）；C2 与 C3 可并行；C4 最后集成。

## 2. 各子任务实施清单

### C1 后端 · 课程文件夹实体、归档与资料归属（迁移 0005）

- [ ] `app/models/material.py` 新增 `MaterialFolder`（含 `archived_at`、`parent_id` 预留）；`Material` 加 `folder_id`（可空 FK）。
- [ ] `migrations/versions/0005_*.py`：建 `material_folders`、加 `materials.folder_id`（可空 FK、SET NULL）+ 索引；写对称 `downgrade()`。
- [ ] `app/schemas/folder.py`：`FolderCreateRequest / FolderUpdateRequest / FolderDetailResponse / FolderListResponse`（含 `is_archived/archived_at/purge_after`）。
- [ ] `app/repositories/folder_repository`：CRUD + 聚合计数 + 归档过滤 + 逾期列表（`archived_at < now-7d`）。
- [ ] `app/services/folder_service`：名称唯一、租户校验、归档/恢复、**惰性清理**（查询时物理删除逾期课程，级联复用 `hard_delete_material`）。
- [ ] `app/api/v1/folders.py` + 注册路由；`deps/folder.py`（POST/GET/PATCH/DELETE + `/restore` + `/purge`）。
- [ ] 扩展 `materials`：上传 Form `folder_id`（可选）、列表 Query `folder_id`（含 `__none__` 未分类）、响应加 `folder_id`、`PATCH /materials/{id}/folder` 移动。
- [ ] 单测：repository/service/router（含越权、重名、归档隐藏、恢复、逾期清理、移动、未分类过滤）。

### C2 后端 · 文件夹范围出题与组卷（依赖 C1）

- [ ] `QuestionGenerateRequest` 加可选 `folder_id`（material_id 可缺省）。
- [ ] `question_service`：按 `(material_id, version_id)` 分组考点、逐组生成、题量均分；无 kp 时取该文件夹全部 ready 考点。
- [ ] `QuestionListQuery`/`list_questions` 加 `folder_id`（join `materials.folder_id`）。
- [ ] `PracticeCreateRequest` 加可选 `folder_id`；`Practice.material_id` 改可空（迁移 0006 或并入 0005）。
- [ ] `practice_service.create_practice` 支持文件夹范围抽题；`PracticeDetailResponse` 加 `folder_id`。
- [ ] 单测：跨资料分组生成、folder 过滤、folder 范围组卷、material_id 空值路径。

### C3 前端 · 课程 IA、未分类/归档与控制台改版（依赖 C1）

- [ ] `src/api/folder.ts` + `src/types/folder.ts`；`src/api/material.ts` 加 `folder_id` 与 `moveMaterialFolder`。
- [ ] `materialStore` 扩展或新增 course 状态（Store 不发请求）。
- [ ] 控制台 `pages/index/index.vue`：移除 `MasteryDashboardBar`，改为课程列表入口（含「未分类」+ 已归档入口）+ 快捷上传 + 最近学习。
- [ ] 新增课程详情页 `subpackages/material/pages/course/index` + `pages.json` 注册（material 分包）。
- [ ] 文件夹增删改 UI（新建/重命名/归档/恢复）；归档项显示剩余反悔时间。
- [ ] 未分类资料列表 + 「移动到课程」UI；课程内资料亦可移动。
- [ ] 上传归属课程（`MaterialUpload` 传 `folder_id`，可缺省落未分类）；资料列表按课程过滤。
- [ ] 组件 ≤300 行；零 Emoji；复用 DESIGN.md token。
- [ ] 单测：course store、课程列表/详情组件、去总分卡断言、移动/归档交互。

### C4 前端 · 课程内出题→答题闭环（依赖 C2、C3）

- [ ] 课程内出题入口：跨资料选考点 → `generateQuestions({folder_id,...})`。
- [ ] 题目列表（`folder_id`）加「开始答题」按钮 → `createPractice({folder_id, knowledge_point_ids, question_types, count, mode})`。
- [ ] 跳转 `/subpackages/practice/pages/session/index?id=...`（带 `fail` 兜底）。
- [ ] 判题分流展示（`grading_status` 三态）复用现有 `GradingResultList`/`reportFormat`。
- [ ] 单测：出题服务调用、组卷接线（`createPractice` 不再为死代码）、跳转参数。
- [ ] 真机手动 E2E：AC1–AC5。

## 3. 验证命令

后端（在 `backend/`）：
```
uv run ruff format --check .
uv run ruff check .
uv run mypy app
uv run lint-imports
uv run pytest tests --cov=app --cov-branch --cov-fail-under=80
```
前端（在 `miniprogram/`）：
```
pnpm run lint
pnpm run type-check
pnpm run test:unit
pnpm run build:mp-weixin
```

## 4. 评审门禁

- [ ] 每个子任务：回归测试**先红后绿** + 该端全工具链绿。
- [ ] C4 完成后：父任务最终全量跨层 check（两端全绿）+ 真机 E2E AC1–AC8 截图/记录。
- [ ] 归档前更新 `.trellis/spec/`（folder 契约、归档/恢复/惰性清理约定、未分类语义、跨资料出题分组约定、前端课程导航契约）。

## 5. 风险与回滚点

- **风险 1**：`Practice.material_id` 改可空可能影响既有读取/索引 → C2 需全量检索 `material_id` 使用点并回归。
- **风险 2**：跨资料出题分组若某资料未 ready → 明确跳过并提示，不整体失败（C2 定义）。
- **风险 3**：控制台改版影响首页概览（`fetchMasteryOverview` 仍在报告页使用）→ 仅移除展示卡，不删后端能力（C3）。
- **风险 4**：归档过滤遗漏——所有涉及 `materials` / `questions` / `practices` 的查询需考虑归档课程下的资料是否应隐藏；C1 需明确过滤口径并在 spec 记录。
- **回滚点**：C1 迁移 `downgrade()`；归档/惰性清理可单独关停；前端各页面改动可独立回退。
