# 课程创建与生题流程问题排查修复（父任务）

## Goal

对用户报出的 7 个小程序问题（B1–B7）做根因定位，并在确认范围内修复，使「课程创建 → 导入/归类资料 → 课程内选考点生题 → 按课程/批次查看题目 → 答题」主链路可用、可解释、不丢数据，且加载/失败态可感知。

本文件是父任务需求总集，拥有全部原始报障、跨子任务验收标准与集成验收；实现落到子任务 C1–C3。

## Background（已确认事实）

前端 `miniprogram/`（uni-app + Vue3 + Pinia），后端 `backend/app`（FastAPI），迁移至 `0006`。历史相关任务：`09-27-course-folder-practice-loop`（C1–C4）、`09-27-question-gen-*`、`09-27-fix-knowledge-tree-recursion`。既有规范已固化大量契约（`.trellis/spec/backend/quality-guidelines.md:742-843`、`.trellis/spec/frontend/quality-guidelines.md:479-598`），本次修复须在不破坏既有契约的前提下增量演进。

### 报障与根因

- **B1 无法创建课程 / 连续点击显示"创立失败"**
  - 创建按钮无在途禁用、无幂等锁，重复点击重复 `POST /folders`：首次 201、其余 409，最后一条"创建失败，请重试"覆盖成功提示（`components/course/CourseCreateDialog.vue:15,57-63`、`components/home/CourseListSection.vue:105-114`、`api/folder.ts:58-64`；Create 返回体被丢弃、无乐观插入）。
  - 附带：`name_exists` 与唯一约束 `uq_material_folders_user_name` **不排除已归档行**，归档后 7 天内无法复用同名（`repositories/folder.py:234-240`、`models/material.py:244-247`、`services/folder.py:85-90`）。
- **B6 `POST /api/v1/folders 409 (Conflict)`** — 服务端同名预检 `FolderNameConflictError`（40021/409，`core/errors.py:1242-1264`、`services/folder.py:85-90`）。前端从不识别 409/40021（全仓 grep 无命中），只给通用失败提示。
- **B7 建课并快速上传、再归类到课程后，课程内资料列表为空**（课程卡片仍在）
  - 用户路径：**首页快捷上传（落未分类）→ 再移动到课程**。
  - 已排除：服务端未归档/删除课程（导入只读课程，`services/material.py:407-410,456-465`）；`onLoad`→`onMounted` 时序（`onLoad` 映射 `created`，早于映射 `mounted` 的 `onReady`）；入口参数（`pages/index/index.vue:144-150` 正确带 `folder_id`）；上传归属（`services/material.py:407-410` 缺失/归档课程抛 `FolderNotFoundError`，不静默改归属）；后端列表过滤/分页（`repositories/material.py:176-201`、`api/v1/materials.py:272-327`）；移动 API 服务端会 commit（`services/folder.py:313-316`）。
  - 主假设（真机确认其一）：①`moveMaterialFolder` 成功但页面未刷新/失败被吞，课程页仅区分"空态"却把请求失败渲染为"课程暂无资料"（`subpackages/material/pages/course/index.vue:26-31,118-138`）；②移动请求实际未命中目标课程（UI 语义/交互误导）。修复以**消除三态混淆 + 移动后确定性刷新 + 归属校验**兜住。
- **B2 点击"生题"后不让跳转页面（两个入口都发生）**
  - 共享根因：两个抽屉**空结果直接 `return`，不 emit、不跳转**（`components/course/CourseGenerateDrawer.vue:224-259`、`subpackages/material/components/QuestionConfigDrawer.vue:294-298`）；且生成期间**禁止关闭抽屉**（`CourseGenerateDrawer.vue:208-214`、`QuestionConfigDrawer.vue:249-255`），用户被锁在抽屉里 → "不让你跳转"。
  - 课程抽屉额外：无进度面板（单资料有 `progress-panel`）；同步长请求 + 180s 超时（`api/question.ts:28-29`）；后端按考点串行多次 LLM（`services/question.py:1240-1258`、`distribute_count:395-416` 每考点至少 1 题）易超时。
- **B4 课程里生题不能自选必选知识点** — 课程抽屉无考点 UI、请求不带 `knowledge_point_ids`（`CourseGenerateDrawer.vue:9-76,238-243`）；后端缺省取课程全部 ready 资料全部考点（`api/v1/questions.py:133-144`、`services/question.py:1303-1345`、`repositories/question.py:288-319`）。后端**已支持**显式考点；缺前端 UI + 课程考点列表 API（`list_knowledge_points_for_folder` 未暴露为 HTTP 接口）。既有前端契约 D2/规范明确"不合并知识树"（`frontend/quality-guidelines.md:567`）。
- **B5 生题没有按批次和课程分类** — `questions` 表无 `batch_id`、无 `folder_id`（`models/question.py:116-267`）；`batch_id` 仅存于 `QuestionQualityCheck`，且 folder/多考点/单考点三层各自新建、folder 层批次号从不落库（`services/question.py:775,1101,1233`，题目实体构造 `:958-976,992-1010` 从不写 `batch_id`）。DTO/列表查询/前端类型均无批次维度（`schemas/question.py:87-110,163-178`、`repositories/question.py:182-260`、`miniprogram/src/types/question.ts:25-44`）。课程维度仅隐式经 `folder_id` 过滤（`repositories/question.py:262-286`），无分组 UI。
- **B3 知识点树卡加载** — 未发现 `loading` 卡死控制流（`subpackages/material/pages/knowledge-tree/index.vue:136-150` 完整 `try/finally`；`onLoad` 前唯一 early return）。且不存在"多份资料树"路径，故"单份"非代码分支差异。候选：①每行 `getNodeCheckStatus` 重走整棵子树并新建 Set，全选后近似二次方，行未虚拟化（`components/KnowledgeTreeNode.vue:81`、`utils/tree.ts:113-137,80-95`）；②后端返回整棵嵌套树、无分页/上限（`services/knowledge.py:638-702`）；③资料长期 `parsing` 时详情页一直转圈（`detail/index.vue:252-260`、`useMaterialPolling.ts:24,86-97`）；④刷新队列 `executeRefreshToken` 无显式超时（`utils/request.ts:122-128`）；⑤真机 `CUSTOM_API_BASE_URL`/域名白名单或旧构建（`config/env.ts:6,34`）。

## Requirements

- **R1 课程创建健壮化**（B1/B6）
  - 创建请求在途期间禁用提交并防重复提交；重复请求不得让"失败"提示覆盖成功结果。
  - 前端识别 409/40021："课程名称已存在"，保留对话框，不与网络错误混淆。
  - 归档反悔期内**允许复用同名**创建（判定与唯一约束排除 `archived_at IS NOT NULL`）。
- **R2 课程资料列表不丢且状态可辨**（B7）
  - 课程页区分**加载中 / 确实无资料 / 加载失败可重试**三态；请求失败不得渲染成"课程暂无资料"。
  - 移动/归类到课程后确定性刷新，并以服务端结果为准。
  - 首页课程列表刷新失败时不得静默清空（保留上一份或显式报错重试）。
- **R3 课程生题可跳转、可观测**（B2）
  - 两个出题入口：生成中可感知进度；成功必跳转到题目页；空结果/失败给出明确反馈与出路（可重试，不得把用户锁在抽屉且无下文）。
  - 课程范围长任务避免静默超时（进度态 + 明确超时文案）。
- **R4 课程内可自选必出考点**（B4）
  - 新增"课程考点选择"交互（按资料分组可勾选）；生成请求携带 `knowledge_point_ids`；未选时的默认行为明确。
  - 新增"课程考点列表"接口（按资料分组的考点树/列表）。
- **R5 生题按批次与课程分类**（B5）
  - 新增迁移把 `batch_id` 持久化到 `questions`；同一次生成的所有题目共享同一 `batch_id`（含单资料/多考点/课程范围链路一致）。
  - 题目列表/记录可按课程与批次分类/筛选；DTO 与前端类型补齐 `batch_id`（课程可由 `material→folder` 派生）。
- **R6 知识点树加载性能与容错**（B3）
  - 前端消除逐行子树重算（近似二次方），并补齐加载/空/错误三态与超时提示/重试。
  - 刷新队列的令牌刷新补显式超时，避免请求永久排队。

## Task Map

| 子任务 | slug | 覆盖报障 | 交付 | 依赖 / 次序 |
|---|---|---|---|---|
| C1 课程创建与列表健壮化 | `course-create-list-resilience` | B1/B6/B7 | 防重复提交 + 409 文案 + 归档同名复用（迁移 0007 部分唯一索引）+ 三态（首页/课程页）+ 移动后确定性刷新 | 独立；迁移号 0007 |
| C2 课程生题链路（选题/跳转/批次） | `course-qgen-flow` | B2/B4/B5 | 课程考点列表接口 + 出题抽屉选题/进度/跳转 + `questions.batch_id` 迁移 0008 + 题目列表按课程/批次分组 | 迁移号 0008；若先于 C1 完成迁移，须顺延编号避免冲突 |
| C3 知识点树加载性能与三态 | `kptree-load-perf` | B3 | 树勾选态与渲染去二次方 + 三态/超时/重试 + 刷新队列超时 | 独立 |

父/子非依赖系统：上述次序与横向约束须分别写入各子任务 `prd.md` / `implement.md`。

## Cross-Child Acceptance Criteria（集成验收）

- [ ] 快速连点"创建课程"只创建一个课程，无误报"创建失败"；同名创建提示"名称已存在"；归档同名可复用。
- [ ] 首页快捷上传 → 移动到课程 → 进入课程能看到该资料；弱网/失败时课程页显示错误态与重试，而非"暂无资料"。
- [ ] 两个出题入口：生成中可见进度、可感知；成功必跳题目页；空结果/失败有明确可重试反馈，不锁死。
- [ ] 课程出题仅出所选考点；未选时的默认行为符合约定。
- [ ] 同一次生成题目共享同一 `batch_id`；题目列表可按课程与批次分组/筛选。
- [ ] 单份资料知识点树在大规模节点下不卡，加载失败可见可重试。
- [ ] 全链路真机 E2E：建课 → 传资料 → 归类 → 课程选考点生题 → 按批次查看 → 答题。
- [ ] 既有单资料出题/组卷/列表零回归；既有规范契约不被破坏（冲突处按计划回改规范）。

## Key Decisions

- **D1 范围 = 全栈修复**（用户确认）：含必要后端与数据库迁移。
- **D2「批次」= 出题生成批次**（用户确认）：每次生成一个 `batch_id`，持久化到 `questions`，列表按「课程 → 批次」分组/筛选。
- **D3 课程选考点粒度 = 按资料分组可勾选**（用户确认）：新增课程考点列表接口 + 按资料分组的选择 UI，符合既有"不合并知识树"决策。
- **D4 归档同名 = 允许复用**（用户确认）：同名判定与唯一约束排除已归档行（部分唯一索引）。
- **D5 B7 用户路径 = 快捷上传后再归类到课程**（用户澄清）：按"移动后确定性刷新 + 三态"修复，并保留真机数据/网络确认。
- **D6 B2 = 两个入口都修**（用户确认）：单资料与课程两个出题入口统一"空结果/失败不锁死、成功必跳转、过程可见"。

## Out of Scope

- 合并知识树 / 跨资料统一树（沿用父任务 `09-27-course-folder-practice-loop` D2）。
- 引入解析批次实体（沿用 D2/D6）。
- 异步任务队列化改造出题（本任务以进度态 + 超时文案缓解，不重构为后台任务）。
- 未在 Key Decisions / Requirements 明确的其他重构。

## Open Questions

- 无阻塞项。剩余待真机确认项（不阻塞规划）：B3 的具体触发资料规模；B7 移动请求的真机返回（`GET /materials?folder_id=<course>` 是否 200 非空）。
