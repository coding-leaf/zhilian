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


