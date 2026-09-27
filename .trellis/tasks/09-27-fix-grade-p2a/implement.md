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
- [ ] 1.1 **前端单元测试新增/更新** (`miniprogram/tests/unit/report/gradingResults.spec.ts`)：
  - 测试未作答题目 (`is_answered: false`) 隐藏“申请重判”按钮；
  - 测试已作答题目展示“申请重判”；
  - 测试主观题包含 `term_explanation` 和 `case_analysis`，题型标签分别显示“名词解释”与“案例分析”，并展示“手动自评”入口；
  - 测试在顶层或快照中存在 `hit_keywords` / `missing_keywords` 时，正常渲染关键词胶囊；
  - 验证运行测试产生失败（红灯）。
- [ ] 1.2 **前端报告页防重测试** (`miniprogram/tests/unit/report/reportDetailPage.spec.ts`)：
  - 测试页面在同一 practiceId 初始化时，网络请求只触发 1 次；
  - 验证运行测试产生失败（红灯）。
- [ ] 1.3 **后端 DTO 契约测试** (`backend/tests/unit/schemas/test_practice_schemas.py`)：
  - 测试 `PracticeItemDetailResponse` 接受 `hit_keywords`, `missing_keywords`, `source_snippet` 并正确同步。

### Step 2: 后端契约与 DTO 增强 (GRADE-003, GRADE-004)
- [ ] 2.1 修改 `backend/app/schemas/practice.py`：
  - 新增 `SourceSnippetDTO` 定义；
  - 在 `QuestionSnapshotDTO` 中添加 `hit_keywords`, `missing_keywords`, `source_snippet` 字段；
  - 在 `PracticeItemDetailResponse` 中添加 `hit_keywords`, `missing_keywords`, `source_snippet` 字段，并在 `synchronize_item_fields` 提取与同步；
  - 运行后端 schema 测试，确保通过。

### Step 3: 前端类型与组件修复 (GRADE-003, GRADE-004, GRADE-007, GRADE-008)
- [ ] 3.1 修改 `miniprogram/src/types/report.ts`：
  - 在 `AttemptGradingItem` 顶层及快照对象中增加 `hit_keywords?: string[]`、`missing_keywords?: string[]`、`source_snippet?: OriginalSnippet | null`。
- [ ] 3.2 修改 `miniprogram/src/subpackages/report/components/GradingResultList.vue`：
  - 补充 `questionTypeMap`（`term_explanation`, `case_analysis`）；
  - 扩展 `canSelfGrade` 支持三类主观题型；
  - 新增 `canRegrade`，校验 `item.is_answered` 及答案非空，模板中申请重判改用 `v-if="canRegrade(item)"`；
  - 适配 `hit_keywords` 与 `source_snippet` 的多级安全访问。

### Step 4: 前端详情页加载与防重优化 (GRADE-005, GRADE-006)
- [ ] 4.1 修改 `miniprogram/src/subpackages/report/pages/detail/index.vue`：
  - 移除 `repData.items` 死代码，统一以 `practiceRes.data.items` 为数据源；
  - 增加对 `practiceRes` 加载异常时的错误处理提示；
  - 增加请求防重机制（`isInitialLoading` 守卫与已加载 ID 校验），解决 `onLoad` 与 `onMounted` 重复触发问题；
  - 原文切片提取适配 `item.source_snippet || item.question_snapshot?.source_snippet`。

### Step 5: 单元测试全部转绿 (绿灯基线)
- [ ] 5.1 运行前端 Vitest 单测并确保全部绿灯通过：
  ```bash
  cd miniprogram && pnpm test:unit
  ```
- [ ] 5.2 运行后端 Pytest 单测并确保全部绿灯通过：
  ```bash
  cd backend && pytest tests/unit/schemas/test_practice_schemas.py
  ```

### Step 6: 全量质量门禁验证
- [ ] 6.1 后端代码规范与类型检查：
  ```bash
  cd backend && ruff format --check . && ruff check . && mypy app
  ```
- [ ] 6.2 前端代码规范与类型检查：
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
