# 实施计划：题目响应补切片正文

验证命令（每步后按需执行）：

```bash
cd backend && uv run pytest tests/unit/schemas/test_question_schemas.py tests/unit/services/test_question_service.py -q
cd backend && uv run mypy app && uv run ruff format --check . && uv run ruff check . && uv run lint-imports
cd miniprogram && pnpm run test:unit && pnpm run type-check && pnpm run lint
task verify   # 收口
```

## 1. 后端：DTO 归位（无行为变化，可独立验证）

- [x] `app/schemas/material.py`：新增 `SourceSnippetDTO`（逐字搬运，含 `id/chapter_title/page_index/snippet_content` 与默认值）。
- [x] `app/schemas/practice.py`：删除原类定义，改从 `app.schemas.material` 导入并保持 `__all__`/再导出可用。
- [x] 更新导入方：`app/services/practice.py`、`tests/unit/schemas/test_practice_schemas.py`、`tests/unit/services/test_practice_service.py`。
- [x] 门禁点：`uv run pytest tests/unit -q` 全绿（纯移动，行为应零变化）；`uv run lint-imports` 5 契约保持。

## 2. 后端：装配实现单一化

- [x] 新增 `app/services/source_snippets.py`：`resolve_snippet_page_index(snippet)` + `build_source_snippet_map(material_repo, snippet_ids, user_id)`（从 `PracticeService` 迁移逻辑）。
- [x] `PracticeService`：`_build_source_snippet_map` 改为委托共享实现，删除 `_resolve_snippet_page_index`；保留其「从快照提取 id」的领域逻辑。
- [x] 门禁点：`uv run pytest tests/unit/services/test_practice_service.py -q` 全绿（断言 DTO 内容的既有用例是本步的回归网）。

## 3. 后端：题目侧装配

- [x] `QuestionService.__init__` 依赖：**无需改动** —— `self.material_repo` 早已在建构函数里建好，直接复用。
- [x] 新增 `QuestionService.attach_source_snippets(items, user_id)`：按 `source_snippet_id` 去重、批量装配、就地补全。
- [x] `QuestionDetailResponse` 增 `source_snippet` 可空字段。
- [x] 四处装配：`_build_generate_response`（传入 service + user_id，覆盖 qualified 与 pending）、`GET /questions/{id}`、`GET /questions`、`PUT/PATCH /questions/{id}`。
- [x] 门禁点：`uv run pytest tests/unit/api/test_question_router.py tests/unit/services/test_question_service.py -q`；既有 mock 用例中 `attach_source_snippets` 为 MagicMock 空操作，不应失败。

## 3b. 后端：修复实施中发现的关系同名缺陷（计划外，必要）

- [x] 装配用例当场暴露：`model_validate(question)` 已产出半空 `source_snippet`（正文空串），根因是 ORM 关系 `Question.source_snippet` 与响应字段同名，`from_attributes` 读到了实体。
- [x] 关系改名 `primary_source_snippet`（`app/models/question.py`），更新 `tests/unit/models/test_question.py` 的引用。
- [x] 加回归用例「裸映射不读 ORM 关系」：脱管后 `model_validate` 的 `material_snippets` 查询数必须为 0（否则列表页 N+1）。
- [x] 端到端补断言：`tests/integration/test_p0_full_chain_e2e.py` 覆盖 generate / detail / list / update 四条路径真实返回来源，且无来源项保持 `null`。

## 4. 后端：测试

- [x] 服务层新增用例（镜像 `test_practice_service.py` 的装配用例）：
  - 有切片 → `source_snippet` 字段完整（正文/章节/页码）；
  - 无 `source_snippet_id` → `None`（向后兼容）；
  - 切片不存在或属他人 → `None`（租户隔离，不泄漏）；
  - 一次装配的查询次数为常数（无 N+1）。
- [x] 契约/序列化用例（真实 `model_dump()` 样本）：`source_snippet` 存在性与字段名固化；无来源时字段为 `None` 而非缺省缺失。

## 5. 前端：契约断言翻转（不新增伪造 fixture）

- [x] `miniprogram/tests/fixtures/backendResponses.ts`：题目 fixture 的来源字段取自**后端真实序列化样本**（跑一次后端序列化取值，不得手写）。
- [x] `miniprogram/tests/backendContracts.spec.ts`：题目侧断言从「无 `source_snippet`、`source_quote` 为 `undefined`」改为「有来源时 `source_quote` 等于真实正文」；保留「无来源 → 空态」用例。
- [x] 门禁点：`pnpm run test:unit` 全绿。

## 6. 规范同步（Phase 3.3）

- [x] `quality-guidelines.md`：来源装配 Scenario 扩为「跨练习/题目两域」并指向新的唯一实现（`app/services/source_snippets.py`）。
- [x] `quality-guidelines.md`：`Contract Fixture Fidelity` Scenario 里以「题目侧无正文」为例的段落改用其它真实差异（题目无 `explanation`、快照有），Wrong/Correct 与断言方向一并翻转。
- [x] `quality-guidelines.md`：新增 Scenario「Response Field Names Must Not Collide with ORM Relationships」（含 Wrong/Correct 与裸映射零查询要求）。
- [x] `frontend/quality-guidelines.md`：`source_quote` 来源说明改为两侧都下发；顺手去掉会腐化的用例计数。
- [x] `guides/cross-layer-thinking-guide.md`：字段存在性清单项的例子换成仍然成立的差异。

## 回滚点

- 第 1、2 步为纯重构，失败可单独回退且不影响新功能。
- 第 3 步后若要回退功能：删掉四处 `attach_source_snippets` 调用即回到当前行为（字段保持可空）。
