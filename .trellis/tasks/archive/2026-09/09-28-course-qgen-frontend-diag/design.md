# 技术设计：课程创建与生题流程修复（父任务）

> 本文件锁定跨子任务契约。子任务可在各自 `design.md` 细化，但不得违背此处契约（除非回改本文件）。
> 架构基线不变：router / service / repository 三层 + 「资料 + 版本」解析模型；前端 uni-app + Vue3 + Pinia，请求统一经 `src/api/`，Store 不发请求。

## 1. 边界与总览

三个子任务覆盖相互独立的交付，但共享两处基础设施：`material_folders` 与 `questions` 的迁移，以及 `utils/request.ts`/`utils/questionGeneration.ts` 等公共前端工具。

```
C1 课程创建与列表健壮化   (B1/B6/B7)  迁移 0007
C2 课程生题链路选题/跳转/批次 (B2/B4/B5)  迁移 0008
C3 知识点树加载性能与三态 (B3)       无迁移
```

迁移编号顺序：**0007（C1，folders 部分唯一索引）→ 0008（C2，questions.batch_id）**。若实际落地顺序相反，后落地者必须顺延编号并在其 `design.md` 记录，禁止两分支各自占用 0007。

## 2. C1 设计：课程创建与列表健壮化

### 2.1 后端：归档同名复用（B1/B6）

- **判定放宽**：`FolderRepository.name_exists(user_id, name, exclude_id=None)` 增加 `archived_at IS NULL` 条件——只与**活跃**同名课程冲突（`backend/app/repositories/folder.py:234-240`）。
- **唯一约束放宽（迁移 0007）**：把 `uq_material_folders_user_name` 改为**部分唯一索引** `uq_material_folders_user_name_active`，`postgresql_where`/`sqlite_where` 均为 `archived_at IS NULL`。`upgrade()` 先 drop 约束/旧索引再建部分唯一索引；`downgrade()` 反向。
  - SQLite 与 PostgreSQL 双支持：SQLAlchemy `Index(..., unique=True, sqlite_where=..., postgresql_where=...)`。
  - 模型 `MaterialFolder.__table_args__` 同步：移除 `UniqueConstraint`，改为部分唯一 `Index`（`backend/app/models/material.py:244-247`）。
- **回归**：`create_folder` 仍要求活跃同名冲突抛 409（40021）；恢复（restore）若与活跃课程重名则仍 409（保持既有语义），由前端提示。

### 2.2 前端：防重复提交 + 409 识别（B1/B6）

- `CourseCreateDialog.vue`：新增 `submitting` prop，提交中禁用「创建」按钮（同时禁用取消以避免中途关闭造成悬挂）。
- `CourseListSection.vue:handleCreateConfirm`：改为「提交中锁」——`submitting` 状态下直接 return；成功用**服务端返回的 `FolderItem` 乐观插入**并 `emit('changed')`；失败按错误码分流：`AppError.code === 40021`（或 `status === 409`）→ toast「课程名称已存在」并保留对话框；其它 → 通用失败文案。
- 复用 `utils/error.ts` 的错误类型；禁止把 409 当网络错误。

### 2.3 前端：列表与课程页三态（B7）

- **课程页** `subpackages/material/pages/course/index.vue`：`listData` 渲染改为三态——`loading`（骨架/文案）、`error`（失败 + 重试按钮）、`empty`（确实无资料）。`loadMaterials` 失败置 `error=true` 并保留错误信息，禁止再静默落到空态。
- **移动/归类后确定性刷新**：`handleMoveSelect` 成功后调用 `refreshAll()`（而非仅本地剔除以 `loadFolder`），确保以服务端为准。
- **首页课程列表兜底**：`pages/index/index.vue:loadDashboardData` 在 `fetchFolderList` 被拒绝时，保留 `folderStore` 既有值并给一次轻量错误提示/可重试，禁止静默清空为 `[]`。
- **真机确认项**（不阻塞编码）：`GET /materials?folder_id=<course>` 返回是否非空；若为空则说明移动未命中，需在课程页错误态中暴露。

### 2.4 C1 验收锚点

- 连点创建仅 1 个 POST；无"创建失败"误报。
- `POST /folders` 同名活跃 → 409 且前端提示"已存在"；同名已归档 → 201（复用）。
- 迁移 0007 `upgrade → downgrade → upgrade` 对称通过。
- 课程页在列表请求失败时显示错误态与重试，不显示"课程暂无资料"。

## 3. C2 设计：课程生题链路（选题 / 跳转 / 批次）

### 3.1 后端：课程考点列表接口（B4）

- 新增 `GET /api/v1/folders/{folder_id}/knowledge-points`（挂在 `folders.py`，或 `questions.py` 下 `knowledge-points`——采用 folders 资源更贴合）。
- 返回按资料分组的考点列表：`[{ material_id, material_title, knowledge_points: [{id, name, level, parent_id}] }]`；数据源复用 `QuestionRepository.list_knowledge_points_for_folder(user_id, folder_id)`（`repositories/question.py:288-319`）并按 `material_id` 分组、补齐 `material.title`。
- 归档课程 → 404；无 ready 资料/无考点 → 返回空分组列表（200，前端据此提示）。
- 需要 `FolderService.list_knowledge_points_for_folder` 编排 + 新 schema。

### 3.2 后端：`questions.batch_id` 落库（B5，迁移 0008）

- 模型 `Question` 增加 `batch_id: Mapped[str | None]`（`String(64)`, nullable, index），`backend/app/models/question.py`。
- 迁移 0008：`add_column questions.batch_id` + 索引；`downgrade` drop。
- **批次号贯通（单一批次号）**：
  - `generate_questions(..., batch_id: str | None = None, defer_commit=False)`：缺省内部生成；写入 `Question(batch_id=...)`（两处实体构造 `:958-976,992-1010`）与 `QuestionQualityCheck(batch_id=...)`。
  - `generate_questions_for_knowledge_points(..., batch_id=None, defer_commit=False)`：透传给每个考点调用，聚合结果沿用同一批次。
  - `generate_questions_for_folder(...)`：在入口生成一个 `batch_id`（现有 `:1233`）并**透传**给其下所有组，替换目前"各层各自新建"的做法。
  - `MultiKnowledgePointGenerationResult.batch_id` 与 `QuestionGenerateResponse.batch_id` 语义统一为"本次请求的批次号"。
- **DTO/查询**：`QuestionDetailResponse` 增加可选 `batch_id`；`QuestionListQuery`/`repositories.question.list_questions` 增加可选 `batch_id` 过滤；`GET /questions` 路由透传。
- **兼容**：`batch_id` 可空，历史数据为 NULL；未传过滤时行为不变（零回归）。

### 3.3 前端：选题 + 进度 + 跳转（B2/B4）

- **课程考点选择**：`CourseGenerateDrawer.vue` 新增按资料分组的考点多选区块（拉取 `GET /folders/{id}/knowledge-points`）；请求体在选中时携带 `knowledge_point_ids`，未选时保持"缺省=全部"并在 UI 明确标注。
  - 组件体积控制：选择区块抽为子组件 `CourseKnowledgePointPicker.vue`（≤500 行）。
- **跳转与空结果（统一两个入口）**：
  - 成功（含部分产出）：`emit('success', folderId)` → 课程页 `navigateTo` 题目页（已有）。
  - **空结果不再锁死**：toast 明确"未产出合格题目"，**关闭抽屉**并允许用户改配置重试；可选提供"去题目列表看看"入口。
  - **生成中可离开**：抽屉保留进度面板，且允许关闭（后台请求照常完成，回调仍以 `folderId` 为准；或至少提供明确的"可返回"提示）——不阻塞用户离开。实现采用"允许关闭 + 请求结果以页面级 toast 反馈"。
  - 单资料 `QuestionConfigDrawer.vue:294-298`：同步改为空结果不 `return` 锁死（改为提示后可关闭，成功路径保持跳转）。
- **进度**：课程抽屉补齐 `progress-panel`（复用单资料的 `useGenerationProgress` 形态）。
- **超时**：`GENERATE_QUESTIONS_TIMEOUT` 保持 180s；超时错误经 `resolveGenerateErrorMessage` 给出网络文案，且不锁死。

### 3.4 前端：题目列表按课程/批次分类（B5）

- `types/question.ts`：`QuestionItem` 增加可选 `batch_id`；`QuestionListQueryParams` 增加可选 `batch_id`。
- 题目列表页 `questions/index.vue`：资料/课程范围内按 `batch_id` 分组渲染（分组头显示批次与时间），支持按批次筛选；课程范围显示课程名。
- 既有"空态范围引导""开始答题"契约不变。

### 3.5 C2 验收锚点

- 课程出题可选考点，生成的题目只落在所选考点（显式 `knowledge_point_ids` 路径）。
- 一次生成的所有题目（跨资料、跨考点）共享同一 `batch_id`；列表按批次分组可见。
- 两个入口空结果/失败均不锁死，成功均跳转。
- 迁移 0008 对称；单资料出题/组卷/列表零回归。

## 4. C3 设计：知识点树加载性能与三态（B3）

### 4.1 渲染去二次方

- `KnowledgeTreeNode.vue:81` 的 `checkStatus` 逐行调用 `getNodeCheckStatus(node, new Set(selectedIds))`：每次新建 Set 且重走整棵子树。
- 改为**页面级预计算**：在 `knowledge-tree/index.vue` 用一次遍历把「选中集合」转成 `Set`，并预计算每个节点的 `selectedDescendantCount`/`descendantCount`（或在 `tree.ts` 提供 `buildCheckStatusMap(nodes, selectedSet)` 一次遍历返回 `Record<nodeId, 'checked'|'indeterminate'|'unchecked'>`），行组件只读 map，不再自算。
- 纯函数放 `utils/tree.ts`，保持现有 `getNodeCheckStatus` 作为单节点兜底（测试兼容）。
- 折叠/全选/覆盖率逻辑不变；`flattenVisibleTree` 仍为 O(N)。

### 4.2 三态与超时

- 树页补 `error` 态与重试按钮；`loadKnowledgeTree` 失败置 `error=true` 并渲染可重试；`loading` 超时给出提示。
- `request.ts` 的 `executeRefreshToken` 增加显式 `timeout`（如 15s），避免刷新挂起导致后续请求永久排队（`utils/request.ts:122-128,232-241`）。

### 4.3 C3 验收锚点

- 大规模节点 + 全选时不出现长时间卡顿；`buildCheckStatusMap` 单测覆盖 checked/indeterminate/unchecked/空输入。
- 加载失败可重试；刷新队列不再永久挂起。

## 5. 兼容性与权衡

- **迁移可回滚**：0007/0008 均提供对称 `downgrade()`。
- **向后兼容**：`batch_id` 可空；城市课程考点接口为新增只读接口；同名复用仅放宽归档行，活跃同名仍 409。
- **规范回改**（Phase 3）：现有 `frontend/quality-guidelines.md:567` 规定"课程出题不传 `knowledge_point_ids`"，本任务改为"可传"；`backend/quality-guidelines.md` 的批次语义需从"仅 quality_check"更新为"题目行持久化"。冲突处按本设计回改规范。
- **权衡**：出题仍为同步长请求，本任务用进度态 + 超时文案缓解，不引入异步任务队列（明确 Out of Scope）。

## 6. 回滚与运维

- C1/C2 迁移独立可回滚；前端为增量改动，可按页面回退。
- 唯一索引放宽可独立回退（重建普通唯一约束，但需先处理可能的活跃同名数据——回退前校验）。
- 非功能：复用现有 `distribute_count`、`list_knowledge_points_for_folder`、`resolveGenerateErrorMessage` 等，禁止重复实现。
