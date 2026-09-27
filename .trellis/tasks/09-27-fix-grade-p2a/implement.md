# 实施计划与执行清单 (Implement)：GRADE 切片 P2-A 修复

## 1. 实施流程概览

```
[Phase 1] 编写红灯失败测试 (TDD Red)
    ↓
[Phase 2] 后端契约增强 (GRADE-003, GRADE-004)
    ↓
[Phase 3] 前端组件与页面修复 (GRADE-003 ~ GRADE-008)
    ↓
[Phase 4] 测试验证转绿 (TDD Green)
    ↓
[Phase 5] 全量质量门禁验证 (Quality Gate)
```

---

## 2. 逐步任务拆解 (Checklist)

### Step 1: 编写失败回归测试用例 (红灯基线)
- [x] 1.1 **前端单元测试新增/更新** (`miniprogram/tests/unit/report/gradingResults.spec.ts`)：
  - 测试未作答题目 (`is_answered: false`) 隐藏“申请重判”按钮；
  - 测试已作答题目展示“申请重判”；
  - 测试主观题包含 `term_explanation` 和 `case_analysis`，题型标签分别显示“名词解释”与“案例分析”，并展示“手动自评”入口；
  - 测试在顶层或快照中存在 `hit_keywords` / `missing_keywords` 时，正常渲染关键词胶囊；
  - 验证运行测试产生失败（红灯）。
- [x] 1.2 **前端报告页防重测试** (`miniprogram/tests/unit/report/reportDetailPage.spec.ts`)：
  - 测试页面在同一 practiceId 初始化时，网络请求只触发 1 次；
  - 新增 practice 失败时的 items 错误提示 + 重试用例；顶层 `source_snippet` 溯源用例；
  - 验证运行测试产生失败（红灯）。
- [x] 1.3 **后端 DTO 契约测试** (`backend/tests/unit/schemas/test_practice_schemas.py`)：
  - 测试 `PracticeItemDetailResponse` 接受 `hit_keywords`, `missing_keywords`, `source_snippet` 并正确同步；
  - 新增 `SourceSnippetDTO` 往返与生效判题记录合并用例。

### Step 2: 后端契约与 DTO 增强 (GRADE-003, GRADE-004)
- [x] 2.1 修改 `backend/app/schemas/practice.py`：
  - 新增 `SourceSnippetDTO` 定义；
  - 在 `QuestionSnapshotDTO` 中添加 `hit_keywords`, `missing_keywords`, `source_snippet` 字段；
  - 在 `PracticeItemDetailResponse` 中添加 `hit_keywords`, `missing_keywords`, `source_snippet` 字段，并在 `synchronize_item_fields` 提取与同步（仅消费已预加载的 `grading_records`，避免 N+1）；
  - 运行后端 schema 测试，确保通过。
- [x] 2.2 追加后端装配支撑：
  - `backend/app/repositories/practice.py`：`get_practice_by_id(make include_items=True)` 预加载 `AttemptItem.grading_records`；
  - `backend/app/repositories/material.py`：新增 `list_snippets_by_ids`（租户隔离批量切片查询）；
  - `backend/app/services/practice.py`：`get_practice` 返回 `PracticeDetailResponse`，按 `source_snippet_id` 批量装配 `source_snippet`。

### Step 3: 前端类型与组件修复 (GRADE-003, GRADE-004, GRADE-007, GRADE-008)
- [x] 3.1 修改 `miniprogram/src/types/report.ts`：
  - 在 `AttemptGradingItem` 顶层及快照对象中增加 `hit_keywords?: string[]`、`missing_keywords?: string[]`、`source_snippet?: OriginalSnippet | null`。
- [x] 3.2 修改 `miniprogram/src/subpackages/report/components/GradingResultList.vue`：
  - 补充 `questionTypeMap`（`term_explanation`, `case_analysis`）；
  - 扩展 `canSelfGrade` 支持三类主观题型；
  - 新增 `canRegrade`，校验 `item.is_answered` 及答案非空，模板中申请重判改用 `v-if="canRegrade(item)"`；
  - 适配 `hit_keywords` 与 `source_snippet` 的多级安全访问。
- [x] 3.3 同步 `miniprogram/src/types/practice.ts` 原始契约字段（`RawPracticeItem`/`RawPracticeQuestionSnapshot`/`RawSourceSnippet`）。

### Step 4: 前端详情页加载与防重优化 (GRADE-005, GRADE-006)
- [x] 4.1 修改 `miniprogram/src/subpackages/report/pages/detail/index.vue`：
  - 移除 `repData.items` 死代码，统一以 `practiceRes.data.items` 为数据源；
  - 增加对 `practiceRes` 加载异常时的错误处理提示（`itemsError` + 重试）；
  - 增加请求防重机制（`isInitialLoading` 守卫与已加载 ID 校验），解决 `onLoad` 与 `onMounted` 重复触发问题；
  - 原文切片提取适配 `item.source_snippet || item.question_snapshot?.source_snippet`。

### Step 5: 单元测试全部转绿 (绿灯基线)
- [x] 5.1 运行前端 Vitest 单测并确保全部绿灯通过：
  ```bash
  cd miniprogram && pnpm test:unit   # 59 files / 541 tests passed
  ```
- [x] 5.2 运行后端 Pytest 单测并确保全部绿灯通过：
  ```bash
  cd backend && pytest tests         # 1201 passed
  ```

### Step 6: 全量质量门禁验证
- [x] 6.1 后端代码规范与类型检查：
  ```bash
  cd backend && ruff format --check . && ruff check . && mypy app && lint-imports
  ```
- [x] 6.2 前端代码规范与类型检查：
  ```bash
  cd miniprogram && pnpm lint && pnpm type-check
  ```

---

## 3. 验证命令集

| 验证项 | 执行环境 | 命令 | 期望结果 |
|---|---|---|---|
| 前端单测 | miniprogram 目录 | `pnpm test:unit` | 全部 pass，新增用例覆盖 6 项缺陷 |
| 前端类型检查 | miniprogram 目录 | `pnpm type-check` | 0 errors |
| 前端 Lint | miniprogram 目录 | `pnpm lint` | 0 errors / 0 warnings |
| 后端 Schema 单测 | backend 虚拟环境 | `pytest tests/unit/schemas/test_practice_schemas.py` | 全部 pass |
| 后端代码格式与检查 | backend 虚拟环境 | `ruff check app` | All checks passed |
| 后端类型检查 | backend 虚拟环境 | `mypy app` | Success: no issues found |

---

## 4. 评审门禁与回滚点

- **评审门禁**：
  1. 所有新增字段均为可选带默认值，不破坏已有历史数据解析。
  2. 未作答主观题确保 100% 隐藏重判入口，不可触发 403 异常。
  3. 首屏网络请求必须从 2 次降为 1 次。
  4. 前后端无任何类型擦除与 `any` 引入。
- **回滚点**：
  - 本次变更无外部数据迁移依赖，若上线出现异常，直接执行 `git revert` 即可无损回退。

---

## 5. 实施结果 (Execution Result)

- **BUG-GRADE-003**: 修复。后端 DTO 透传生效判题记录要点，前端顶层 + `question_snapshot` 二级兜底渲染。
- **BUG-GRADE-004**: 修复。`get_practice` 按 `source_snippet_id` 批量装配 `SourceSnippetDTO`；前端顶层 + 嵌套兜底读取，抽屉展示章节/页码/正文。
- **BUG-GRADE-005**: 修复。移除 `repData.items` 死分支；practice 失败时展示“作答明细加载失败，请重试”并提供重试。
- **BUG-GRADE-006**: 修复。`isInitialLoading` 并发锁 + `lastLoadedPracticeId` 守卫，首屏仅 1 次请求。
- **BUG-GRADE-007**: 修复。题型映射补齐 `term_explanation`/`case_analysis`，主观题集合与后端对齐。
- **BUG-GRADE-008**: 修复。新增 `canRegrade`，未作答主观题隐藏“申请重判”，杜绝 403。

### 门禁结果

- 后端：`ruff format --check .` ✅ / `ruff check .` ✅ / `mypy app` ✅ / `lint-imports` ✅ (5 kept) / `pytest tests` ✅ (1201 passed)
- 前端：`pnpm run lint` ✅ / `pnpm run type-check` ✅ / `pnpm run test:unit` ✅ (59 files, 541 tests passed)

### 兼容性

- 新增字段全部为附加可选（默认 `None` / `[]`），未改动历史响应契约与 P1 的 `grading_status` 三态、`RegradeResponse` 同步语义。
