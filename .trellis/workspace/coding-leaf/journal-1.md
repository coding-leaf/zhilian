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



