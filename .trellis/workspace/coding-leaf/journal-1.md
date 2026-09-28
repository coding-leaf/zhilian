# Journal - coding-leaf (Part 1)

> AI development session journal
> Started: 2026-09-26

---

## 2026-09-26 - 清理旧框架残留与工作区代码质量优化 (cleanup-legacy-sdlc-and-optimize)

- **背景**: 旧自研 SDLC 框架废弃卸载后，工作区残留大量已失效的脚本（根目录 `task.py` 严重干扰 Trellis 的 `.trellis/scripts/task.py`）、`tooling/`、旧 skills 及未被 gitignore 覆盖的缓存文件。
- **清理动作**:
  - 彻底移除根目录冲突的 `task.py`。
  - 清理并暂存删除旧 SDLC 脚本（`tooling/*.py`）、单测（根目录 `tests/test_*.py`）及废弃技能/prompt。
  - 完善 `.gitignore`（忽略 `*.db`, `.coverage.*`, `.ruff_cache/`, `.mypy_cache/`, `.pytest_cache/`, `.import_linter_cache/`）。
  - 将历史 SDLC 规范与任务完整移入 `docs/legacy_sdlc/` 备查。
  - 完善 `.trellis/spec/backend/quality-guidelines.md` 与 `.trellis/spec/frontend/quality-guidelines.md`，替换原有占位符，固化项目工程门禁标准。
- **验证成果**:
  - 后端通过 `ruff format`、`ruff check`、`mypy`、`lint-imports`（5 contracts kept）、`pytest`（1080 passed, 覆盖率 94.39%）。
  - 前端通过 `eslint`、`vue-tsc`、`vitest`（410 passed）。

---

## 2026-09-26 - 资料列表为空/解析进度/鉴权画像修复 (fix-material-and-auth)

- **背景**: 用户实机反馈三大端到端缺陷——「全部」标签返回空、上传后解析无进度提示、怀疑登录授权丢态。
- **根因**:
  - 列表页在 `all` 标签传 `status=undefined`，后端 `Material.status == status` 恒假导致空结果；`ready` 因精确匹配才可见。
  - 列表页与首页共享 Store，分页结果全量覆盖首页概览切片；且只在 `onMounted` 加载，二级返回白屏。
  - 冷启动只恢复 `auth_tokens`，`profile` 受 3-key 白名单限制未持久化，导致「已登录却显示未登录」假象。
- **实现**:
  - 前后端双向清洗空状态参数；Service 统一状态语义（`parsing`→`pending+parsing`、`ready/completed`→`ready`、`retake_required`→空）。
  - 响应新增 `parse_status`/`progress_percentage`；卡片展示进度并提供手动【开始解析/重新解析】按钮 + 自适应退避轮询。
  - `userStore.hydrateProfile()` 在 `onLaunch`/`onShow`/登录后静默水合画像；列表页 `listData` 与全局 Store 隔离，`onShow` 保活。
  - 修复质检阶段发现的 N+1：`selectinload(Material.versions)` 批量预加载，列表版本查询 O(N)→固定 1 次（实测 3 条 SQL）。
- **遗留（新任务范围）**: 「待重拍」Tab 恒空——后端 `MaterialStatus` 无 `retake_required` 状态，需模型层改造才能真正支持。
- **验证成果**:
  - 后端 `ruff`/`format`/`mypy`(109 files)/`lint-imports`(5 kept)/`pytest`（1090 passed）。
  - 前端 `lint`/`type-check` 全绿、`vitest`（52 files / 424 passed）。
  - 提交 `86bc24e`；规范沉淀《Material Status Filter & Parse Progress Contract》写入前端 quality-guidelines。

---

## 2026-09-26 - Headless CLI 与真实链路闭环验证 (headless-cli-closed-loop)

- **背景**: 缺少可被 AI/开发者脚本化驱动、并对真实功能做端到端断言的验证通道；mock 单测全绿 ≠ 真机可用。
- **实现**（分 3 Stage，每阶段设评审门）:
  - 新增 `backend/app/cli/`（`python -m app.cli`，标准库 argparse）：`doctor/db/auth/material/question/practice/grading/diagnosis/smoke`。
  - 真实链路硬门禁：`fake/memory/sqlite` 回落 → 退出码 3（业务前中止）；基础设施不可达 → 4；断言失败 → 2；密钥/token/DB 密码全脱敏。
  - `smoke` 编排 11 阶段（preflight→login→import→parse→snippets→tree→questions→practice→grading→report→summary），逐阶段 JSON 归因。
  - `fixtures.py`：中文讲义 TXT + 真实最小 DOCX（zipfile）生成。
- **真实链路暴露并修复的缺陷**:
  1. **出题检索门禁分数错配（致命）**：`_retrieve_and_gate_snippets` 用 RRF `final_score`（≈0.016）比相似度阈值 0.35 → 真实检索命中亦被拒；改用 `vector_score`（余弦 0–1）。铁证：真实候选 `vector_score=0.88 / final_score=0.035`，而 mock 预置假的 `final_score=0.91`。
  2. **DOCX/PPTX 解析**：原裸 `content.decode(errors="ignore")` 对 ZIP 容器必失败；改 `zipfile + ElementTree`（按 localname 抽 `w:t`/`a:t`，损坏抛 `MaterialInvalidError`）。
  3. **子 Agent 派发不稳**：`implement.jsonl` 注入巨型通用指南 + 派发 prompt 重复粘贴工件 → 载荷超限触发上游 `Bad Request`；精简清单 + `.trellis/config.yaml` 加 `context_injection` 上限。
- **实现修复**: 真实 `smoke` 由退出码 2 → **0（11/11 阶段全绿，~52s）**，证据存于任务归档 `stage3-real-smoke-success.json`。
- **验证成果**:
  - 后端 `ruff`/`format`(214)/`mypy`(125)/`lint-imports`(5 kept)/`pytest`（1113 passed）。
  - 提交 `cd628ab`；规范沉淀《Headless CLI 契约》《检索打分语义 RRF vs 余弦》写入 backend quality-guidelines。
- **遗留**: `smoke --image` 的 OCR 子链路仍为 `skipped`（需用户提供真实含字图片）；`context._probe_*` 极端异常串建议后续统一过滤。

---

## 2026-09-26 - 真实链路复验：定位弱模型 schema 不遵从并换模型闭环 (cli real verification)

- **背景**: 归档后用 CLI 做真实验证，复现 `smoke` 在 `questions` 阶段失败。
- **排查过程（3 次真实运行 + 1 次定向复现）**:
  - run #2 `smoke`：`failed_stage=questions`，`Expecting value: line 1 column 1 (char 0)`（LLM 返回空内容），questions 耗时 304s。
  - run #3 `question generate`（用落库实体定向复现）：`LLMResponseFormatError`，模型返回 `options: [true,false]`（应为 `[{"key":"A","content":"..."}]`）。
  - run #4 `smoke`（原配置重跑）：错误与 #3 **字节级一致** → 排除偶发，判定为**系统性**。
  - 排查确认 prompt（`question.py:452-461`）与 schema 均明确正确 → **非代码缺陷**，是模型对 tool schema 不遵从。
- **根因定位**: 结构化路径虽用 `tool_choice` 强制 Function Calling，但 `pydantic_to_tool_schema`（`agent_graph.py:42-55`）**未开 `strict:true`**，非严格模式只“强制调用”不“约束参数”，弱模型即可违约。
- **解法（配置，零代码）**: 探明中转站可用模型（`GET /v1/models`）后，将 `ZHILIAN_LLM__MODEL` 由 `gemini-3.5-flash-lite` 改为 `gemini-3.8-flash-high` → `smoke` **exit 0，11/11 阶段全绿，57s**（run `e87e48b9`，生成 3 题）。
- **重要澄清**: 上次修的 RRF/余弦检索门禁修复**在真实数据上有效**（每次失败都已穿过检索进入 LLM 调用），不必回调。
- **规范沉淀**: backend quality-guidelines 新增《LLM Structured Output Adherence（模型选择与 strict 缺口）》：优先强模型、弱模型需开 strict、失败归因方法。
- **遗留/可选**: 若需兼容弱模型，可开新任务实现 `strict:true` + `additionalProperties:false` 规范化，或扩展 `response_format` 支持 `json_schema`（当前仅支持字符串 `{"type": ...}`）。

---

## 2026-09-27 - 出题体验前端闭环与可核验 (question-gen-frontend-ux)

- **背景**: 用户实机反馈——点击生题原地不动、无进度、无法确认生题效果；多选考点未生效；跳转/入口逻辑混乱。
- **侦察定位的真实缺陷**:
  - 生成后仅关闭抽屉 + 同页切 Tab（无跳转/无进度，失败只弹 toast）。
  - `QuestionConfigDrawer` 只发 `selectedKnowledgeIds[0]`，其余已选考点被静默丢弃，UI 却显示「已选 N 项」。
  - 题目仅存本地 ref，从不调 `fetchQuestionList`，退出重进即丢，无独立题目入口。
- **任务结构（父 + 3 子，逐个评审门）**:
  - `verify-list`：新增独立题目页 `subpackages/material/pages/questions/index`，`fetchQuestionList` 持久加载、本地 `listData` 隔离、复用编辑/痕迹抽屉、分页去重；抽出 `QuestionCard` 并迁移知识树卡片。
  - `progress-nav`：抽屉内「进行中面板」（阶段轮播+计时）、全表单禁用防重复、成功后跳题目页（`material_id` + fail 兜底）、空结果/网络/业务错误分类可重试、出题接口超时 180s；移除知识树页本地题目 Tab（消除双数据源）。
  - `multi-kp`：后端 `knowledge_point_ids` 可选字段 + `distribute_count`（均分+余数前置+每考点≥1）+ `generate_questions_for_knowledge_points` 编排（聚合、fail-fast）+ 路由分流；前端传全部已选考点 + 分布提示。
- **规范沉淀**:
  - 前端：《Material Subpackage Navigation Param Contract》（统一 `material_id`、`navigateTo` 必带 `fail`、生成成功跳转目标统一、页面本地 `listData`）。
  - 后端：《Multi-Knowledge-Point Question Generation》（向后兼容、分配规则、聚合、fail-fast、纯函数无 IO）。
- **验证成果**:
  - 后端 `ruff`/`format`(216)/`mypy`(125)/`lint-imports`(5 kept)/`pytest`（1130 passed）。
  - 前端 `lint`/`type-check`/`test:unit`（54 files / 444 passed）。
  - 提交：`95f89bf`(verify-list) → `48fb3cc`(progress-nav) → `3fce14f`(multi-kp)；三个子任务与父任务均已归档。
- **遗留/待确认**:
  - OQ-1：用户「很多跳转逻辑有问题」的具体复现未提供，未针对性修复（已统一分包导航参数契约）。
  - AC6：多考点真实链路覆盖未跑（CLI 未扩展多考点，建议真机验证）。
  - 历史不一致（非本任务）：前端题量上限 50 vs 后端 `count le=20`（输入 >20 会 422）。
  - 另开后端任务：知识树节点数量偏少 / 出题质量调优。

---

## 2026-09-27 - 修复知识点树递归组件渲染崩溃（去递归扁平化） (fix-knowledge-tree-recursion)

- **背景**: 用户在微信开发者工具导入 `miniprogram/dist/dev/mp-weixin` 后，资料「知识点树」页整页崩溃：`TypeError: Cannot read properties of undefined (reading 'children')`，并伴随 `Setting data field "uP" to undefined is invalid`，考点树完全不可用，阻断「选考点 → 生成题目」链路。
- **根因定位（证据驱动）**:
  - 编译产物 `KnowledgeTreeNode.js` 中 `hasChildren = Array.isArray(props.node.children)` 是渲染最先求值的计算属性；`props.node === undefined` 时首抛即为 `reading 'children'`。
  - uni-app mp-weixin 通过单一 `u-p`/`uP` 字符串 + 模块级 `propsCaches[父uid]` 透传 props（`common/vendor.js` 的 `renderProps`/`findComponentPropsData`）；`uP` 丢失即回退 `{}`，子组件全部 props 为 `undefined`。
  - 触发面：`KnowledgeTreeNode.vue` 的**递归自引用组件**（`import` 自身 + 模板递归），新增于 `a388e1c`。后端 `get_knowledge_tree` 返回的嵌套树与契约均正常，**非数据问题**。
- **实现（方案 B：去递归扁平化）**:
  - 新增纯函数 `flattenVisibleTree(nodes, collapsedMap)`：前序遍历输出「可见行 `{node, depth}`」，折叠节点自身保留、其子孙裁剪；含 `Array.isArray`/空节点守卫。
  - `KnowledgeTreeNode.vue` 去自引用、去递归模板、清理无用 handler 与样式，退化为「非递归行组件」；级联勾选仍走 `collectNodeAndDescendantIds` + `toggleKnowledgeSubtree`（行内 `node` 仍含 `children`）。
  - 页面 `knowledge-tree/index.vue` 改为对 `visibleRows` 单层 `v-for` + `:level="row.depth"` 缩进；`allFlatNodes`（全选/覆盖率）保持全量语义。
  - 同步单测：utils 新增 `flattenVisibleTree` 5 例；组件用例改为「折叠箭头/叶子占位 + 不递归渲染子节点」；页面新增「折叠隐藏子孙」与「折叠态全选仍全量」2 例。
- **规范沉淀**: `.trellis/spec/frontend/quality-guidelines.md` 新增《WeChat Mini-Program 禁止递归组件，深层树用扁平化渲染》——记录 `u-p`/`propsCaches` 陷阱、`flattenVisibleTree` 契约、错误矩阵与 Wrong/Correct。
- **验证成果**:
  - 前端 `pnpm run lint` / `type-check` / `test:unit`（54 files / 452 passed，较基线 444 新增 8 例）全绿。
  - `pnpm run build:mp-weixin` 通过；编译产物 `KnowledgeTreeNode.json` 的 `usingComponents` 不再含自引用键，组件 `.js` 不再含自引用加载器，页面 wxml 为单层 `wx:for`。
  - 提交：`5b68fea`(fix) + archive 提交；任务已归档 `archive/2026-09/09-27-fix-knowledge-tree-recursion`。
- **遗留/待确认**:
  - 未在真机/微信开发者工具实机验证（本环境无法自动化小程序运行时）；已通过单测 + 编译产物断言间接验证，建议用户重跑 `dev:mp-weixin` 后确认 AC1–AC4。
  - 佐证：同仓 `questions` 页已验证可用的 `QuestionCard` 正是「v-for + 组件对象 props」模式，说明 `u-p` 透传本身可用，本次崩溃与递归自引用强相关。
  - `Some selectors are not allowed in component wxss` 等告警与本崩溃无因果，未处理。





## Session 1: C1 后端课程文件夹实体、归档与资料归属（迁移 0005）
<!-- trellis-session: v=2 fp=3cce3187772f3798 -->

**Date**: 2026-09-28
**Task**: C1 后端课程文件夹实体、归档与资料归属（迁移 0005）
**Branch**: `master`

### Summary

新增 material_folders 实体（含 archived_at）与 materials.folder_id（可空=未分类）；提供 /folders CRUD、归档/恢复/7 天惰性清理、资料按课程过滤与 PATCH /materials/{id}/folder 移动。规划父任务 09-27-course-folder-practice-loop 并拆 C1-C4；C1 实现+复核通过（修复: switch/retry 响应 folder_id 字段漂移、purge_after 重复逻辑），后端 1276 passed / 覆盖率 91.83%，全工具链绿。规格沉淀归档过滤与惰性清理契约。

### Git Commits

| Hash | Message |
|------|---------|
| `e3b35ef` | feat(folder): 课程文件夹实体、归档与资料归属（迁移 0005） |

### Status

[OK] **Completed**


## Session 2: C2 后端文件夹范围出题与组卷（迁移 0006）
<!-- trellis-session: v=2 fp=d340c0b21f51f1a7 -->

**Date**: 2026-09-28
**Task**: C2 后端文件夹范围出题与组卷（迁移 0006）
**Branch**: `master`

### Summary

出题与组卷范围扩展到课程文件夹：QuestionGenerateRequest.folder_id 跨资料综合出题（按 (material,version) 分组、题量均分、单事务原子、归档过滤、跨课程归属校验）、GET /questions?folder_id= 过滤、Practice 支持 folder_id 且 material_id 放开为可空（迁移 0006）。修复跨任务集成缺口：last_practice_at 兼顾课程范围练习。C2 实现+复核零缺陷，后端 1313 passed / 覆盖率 91.88%，全工具链绿；规格沉淀课程范围契约。

### Git Commits

| Hash | Message |
|------|---------|
| `36c4093` | feat(question): 文件夹范围综合出题与题库过滤 |

### Status

[OK] **Completed**


## Session 3: C3 前端课程信息架构、未分类与归档
<!-- trellis-session: v=2 fp=26a226939ce39ef5 -->

**Date**: 2026-09-28
**Task**: C3 前端课程信息架构、未分类与归档
**Branch**: `master`

### Summary

控制台首屏改为课程列表入口并移除总学习分卡（MasteryDashboardBar），新增未分类与已归档入口；新增课程详情页与文件夹 CRUD/归档/恢复 UI（含 7 天反悔剩余时间纯函数）；资料上传归属课程、未分类资料移动到课程；新增 api/folder.ts、types/folder.ts、folderStore，MaterialUpload/QuickUploadBar 支持 folderId。复核修复：拆分 >300 行文件（api/material.ts → materialUpload.ts、list/index.vue 抽 composable）、补 navigateTo fail 兜底。前端 66 files / 603 tests，lint/type-check/test:unit/build:mp-weixin 全绿。

### Git Commits

| Hash | Message |
|------|---------|
| `f7f8185` | feat(course): 课程信息架构、未分类与归档（前端） |

### Status

[OK] **Completed**


## Session 4: C4 前端出题→答题闭环
<!-- trellis-session: v=2 fp=abf8054c2891e28e -->

**Date**: 2026-09-28
**Task**: C4 前端出题→答题闭环
**Branch**: `master`

### Summary

打通课程内出题→题目列表→开始答题→组卷→答题页闭环：课程详情「智能出题」（CourseGenerateDrawer，folder 范围 generateQuestions）；题目列表兼容 folder_id（与 material_id 并存零回归）+ 吸底「开始答题」→ createPractice({folder_id,...}) → initSession → 跳答题页（带 fail）；类型放开 material_id 可空 + folder_id。消除 createPractice 死代码。复核零缺陷，前端 67 files / 616 tests，四门禁全绿；规格沉淀闭环契约。真机 E2E（AC1-AC3）待人工确认。

### Git Commits

| Hash | Message |
|------|---------|
| `84cf0ed` | feat(course): 课程内出题→答题闭环（前端） |

### Status

[OK] **Completed**


## Session 5: 父任务集成验收：课程文件夹与出题-答题闭环重构（C1-C4 全部归档）
<!-- trellis-session: v=2 fp=9e5685ecd3d69de7 -->

**Date**: 2026-09-28
**Task**: 父任务集成验收：课程文件夹与出题-答题闭环重构（C1-C4 全部归档）
**Branch**: `master`

### Summary

四个子任务全部完成并归档：C1 后端课程文件夹实体/归档/资料归属（迁移 0005）、C2 后端文件夹范围出题与组卷（迁移 0006）、C3 前端课程 IA/未分类/归档、C4 前端出题→答题闭环（消除 createPractice 死代码）。父任务最终集成验收：后端 1313 passed/覆盖率 91.88%（ruff/format/mypy/lint-imports 全绿）、前端 67 files/616 tests + build:mp-weixin 成功。规格沉淀 backend 课程范围契约 + frontend 课程 IA 与出题答题闭环契约。AC1-AC3 真机/真实 LLM 端到端待人工确认。

### Git Commits

| Hash | Message |
|------|---------|
| `13f5860` | chore(task): 父任务课程文件夹重构集成验收完成 |

### Status

[OK] **Completed**


## Session 6: 全新前端架构与用户体验重构 (v2 原生三 Tab 闭环与 AI 助教/离线防丢)
<!-- trellis-session: v=2 fp=09-28-new-frontend-v2-architecture -->

**Date**: 2026-09-28
**Task**: 全新前端架构与用户体验重构
**Branch**: `master`

### Summary

根据用户旅程垂直切片 J1~J8，全新构建 Uni-App (Vue 3 + TS) 小程序端架构，打通全链路闭环并完成体验增强：
1. 建立学术科技蓝调设计系统 `theme.scss`，重构原生三 Tab 架构（学习工作台、学情与错题、我的与数据治理）。
2. J1~J3 闭环：构建多图网格画廊质检（支持最多 9 张图片、单页即时重拍替换）与出题核验清单（讲义原文出处引证展开、AI 质检建议、增删改题目与一键开练）。
3. J4 作答引擎与 UX 增强：实现毫秒级 Storage 秒存与 800ms 防抖同步的离线防丢引擎 `usePracticeSync`，支持滑屏手势切题、标记疑难、答题卡抽屉与未作答拦截。
4. J5~J6 报告与 UX 增强：三阶段动效过渡态、学情雷达与薄弱点一键强化练习；深度解析详情页支持讲义出处原文展开、采分点视觉对齐、AI 复核与自评打分双通道纠错，以及内置【追问 AI 助教】抽屉式对话。
5. J7 错题攻克：按题型、时间段、课程多维筛选，支持购物车多选勾选特定错题并一键组卷（全栈协同支持后端 `question_ids` 组卷）。
6. J8 数据治理：学习资产卡片、课程归档箱管理，以及双重二次确认的高危账号注销物理擦除。
7. 后端协同扩展：`POST /api/v1/practices` 扩展支持 `question_ids` 精准组卷，新增 `POST /api/v1/questions/{id}/ask-coach` AI 助教答疑接口。
8. 验证全绿：后端 Pytest 91 passed，前端 Vitest 76 files / 668 passed，Type-Check 与 Lint 零报错，单文件 <= 300 行与零 Emoji 规范严格执行。

### Git Commits

| Hash | Message |
|------|---------|
| (Pending Commit) | feat(v2): 全新前端架构重构与 J1-J8 体验闭环（含三 Tab 底座、AI 追问与离线防丢） |

### Status

[OK] **Completed**


## Session 7: 全新前端架构与用户体验重构
<!-- trellis-session: v=2 fp=10ff8404e0c19505 -->

**Date**: 2026-09-28
**Task**: 全新前端架构与用户体验重构
**Branch**: `master`

### Summary

推倒旧前端，全新构建原生三Tab规范底座（学习工作台、学情错题看板、我的与数据治理）。闭环J1-J8用户旅程：9图画廊OCR质检单页即时重拍替换、出题质检清单与讲义原文引证；J4作答引擎与毫秒级Storage离线防丢系统；J5/J6三阶段过渡动效、自评与AI复核双通道纠错，以及内置追问AI助教对话能力；J7错题多选购物车与后端question_ids精准组卷；J8学习资产总览与物理彻底抹除。全端668项测试通过，全栈门禁全绿。

### Git Commits

| Hash | Message |
|------|---------|
| `b12c20e` | feat(v2): 全新前端架构重构与 J1-J8 体验闭环（含三 Tab 底座、AI 追问与离线防丢） |

### Status

[OK] **Completed**
