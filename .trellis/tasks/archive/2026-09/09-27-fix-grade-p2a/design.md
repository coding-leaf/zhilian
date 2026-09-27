# 技术设计方案 (Design)：GRADE 切片 P2-A 修复

## 1. 缺陷根因分析 (file:line)

### 1.1 BUG-GRADE-003: 要点命中与遗漏关键词契约断裂
- **位置**: 
  - 后端：`backend/app/models/practice.py:533-544`，`backend/app/schemas/practice.py:87-187`
  - 前端：`miniprogram/src/subpackages/report/components/GradingResultList.vue:60-75, 166-170`，`miniprogram/src/types/report.ts:97-112`
- **根因**:
  - 后端判题时将 `hit_keywords` 和 `missing_keywords` 保存在 `GradingRecord` 实体中（`models/practice.py:533-544`）。
  - `PracticeItemDetailResponse` 及其嵌套的 `question_snapshot`（`QuestionSnapshotDTO`）未声明这两个字段，也未在序列化时由关联记录填充；
  - 前端 `GradingResultList.vue` 的模板及 `hasKeywords` 函数却强依赖 `item.question_snapshot?.hit_keywords` 与 `item.question_snapshot?.missing_keywords`，导致计算结果恒为 false，UI 永远不展示要点胶囊。

### 1.2 BUG-GRADE-004: 原文溯源抽屉切片对象缺失
- **位置**:
  - 后端：`backend/app/services/practice.py:310`，`backend/app/schemas/practice.py:113-116`
  - 前端：`miniprogram/src/subpackages/report/components/GradingResultList.vue:80, 172-176`，`pages/detail/index.vue:207-214`，`types/report.ts:76-82, 107`
- **根因**:
  - 出题与组卷时，题目快照中仅持久化了 `"source_snippet_id": str(q.source_snippet_id)`，未组装切片正文详情对象；
  - 前端 `GradingResultList.vue:172-176` 的 `hasSnippet` 看到 `source_snippet_id` 存在即展示“查看原文依据”按钮；
  - 用户点击后，`detail/index.vue:208` 执行 `activeSnippet.value = item.question_snapshot?.source_snippet || null`，由于后端从未返回 `source_snippet` 对象，导致 `activeSnippet` 为 `null`，抽屉内显示“暂无原文切片内容”。

### 1.3 BUG-GRADE-005: 报告详情页 items 死代码与容错缺失
- **位置**:
  - 后端：`backend/app/schemas/diagnosis.py:172-213`
  - 前端：`miniprogram/src/subpackages/report/pages/detail/index.vue:173, 182-186`
- **根因**:
  - 详情页优先判定 `repData.items`（:182），然而 `DiagnosisReportResponse` 在架构设计上是宏观学情评估，根本不包含逐题作答项（不含 `items` 字段）；
  - 真正的数据来源完全依赖并行发起的 `fetchPracticeSession(pid)`。在 `fetchPracticeSession` 发生网络异常时（:163 代码用 `.catch(() => null)` 静默吞掉），导致列表为空，前端没有任何明确的降级提示。

### 1.4 BUG-GRADE-006: 报告页初始化 onLoad + onMounted 重复加载
- **位置**:
  - 前端：`miniprogram/src/subpackages/report/pages/detail/index.vue:270-286`
- **根因**:
  - uni-app 页面生命周期中，`onLoad` 先于 `onMounted` 执行。`onLoad` 解析路由参数 `practice_id` 并立即调用 `loadReportData(pid)`；
  - 随后 `onMounted` 钩子又通过 `props.practiceId || currentPracticeId.value` 获取到相同的 `pid`，再次发起 `loadReportData(pid)`；
  - 由于缺少首屏防重守卫与加载状态锁，同一页面在打开时发出两次完全一样的异步网络请求，造成资源浪费且存在时序竞态风险。

### 1.5 BUG-GRADE-007: 非 short_answer 主观题自评与重判入口缺失
- **位置**:
  - 后端：`backend/app/core/algorithms/grading.py:137-143`（`SUBJECTIVE_QUESTION_TYPES = {term_explanation, short_answer, case_analysis}`）
  - 前端：`miniprogram/src/subpackages/report/components/GradingResultList.vue:124-130, 178-185`
- **根因**:
  - 前端 `canSelfGrade` 仅写死 `item.question_snapshot?.question_type === 'short_answer'`；
  - 前端 `questionTypeMap` 字典未配置 `term_explanation` 与 `case_analysis`；
  - 导致名词解释与案例分析题在报告中题型显示为“试题”，且无法进行自评或重判。

### 1.6 BUG-GRADE-008: 未作答主观题展示申请重判导致 403 异常
- **位置**:
  - 后端：`backend/app/services/grading.py:779-783`
  - 前端：`miniprogram/src/subpackages/report/components/GradingResultList.vue:93-95, 178-185`
- **根因**:
  - 后端在重判服务 `regrade_attempt` 中有严格防线：`if not item.is_answered or not item.user_answer: raise GradingNotAllowedError("未作答题目不允许重判")`；
  - 前端在模板中：只要 `canSelfGrade(item)` 为真即同时渲染“手动自评”与“申请重判”；
  - `canSelfGrade` 没有对 `is_answered` / `user_answer` 做判定，导致未作答的主观题（得分 0.0）暴露了重判按钮，用户点击提交后必然收到 403 报错。

---

## 2. 契约设计与跨层对齐

### 2.1 后端 DTO 增强（`backend/app/schemas/practice.py`）
保持完全向下兼容，均作为附加可选字段：
```python
class SourceSnippetDTO(BaseModel):
    """题目来源切片摘要数据传输对象。"""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID | str | None = Field(default=None, description="切片主键")
    chapter_title: str = Field(default="", description="所属章节标题")
    page_index: int = Field(default=1, ge=1, description="所在页码")
    snippet_content: str = Field(default="", description="切片纯文本内容")

class QuestionSnapshotDTO(BaseModel):
    ...
    source_snippet_id: uuid.UUID | None = Field(default=None)
    source_snippet_ids: list[Any] = Field(default_factory=list)
    source_snippet: SourceSnippetDTO | dict[str, Any] | None = Field(
        default=None, description="来源切片追溯详情对象"
    )
    hit_keywords: list[str] = Field(default_factory=list, description="命中要点列表")
    missing_keywords: list[str] = Field(default_factory=list, description="遗漏要点列表")

class PracticeItemDetailResponse(BaseModel):
    ...
    hit_keywords: list[str] = Field(default_factory=list, description="命中要点列表")
    missing_keywords: list[str] = Field(default_factory=list, description="遗漏要点列表")
    source_snippet: SourceSnippetDTO | dict[str, Any] | None = Field(
        default=None, description="来源切片追溯详情对象"
    )
```

在 `PracticeItemDetailResponse.synchronize_item_fields` 中：
- 若输入数据包含 `grading_records` 实体关系或已提取的最新生效记录，安全同步 `hit_keywords` 与 `missing_keywords`；
- 同时双向同步 `item` 与 `question_snapshot` 上的关键词与切片字段。

### 2.2 前端类型定义对齐（`miniprogram/src/types/report.ts`）
```typescript
export interface OriginalSnippet {
  id?: string;
  snippet_content?: string;
  chapter_title?: string;
  page_index?: number;
  keywords?: string[];
}

export interface AttemptGradingItem {
  ...
  hit_keywords?: string[];
  missing_keywords?: string[];
  source_snippet?: OriginalSnippet | null;
  question_snapshot: {
    ...
    source_snippet?: OriginalSnippet | null;
    source_snippet_id?: string | null;
    hit_keywords?: string[];
    missing_keywords?: string[];
    [key: string]: unknown;
  };
  ...
}
```

---

## 3. 详细实现方案

### 3.1 关键词与切片呈现优化（GRADE-003, GRADE-004）
1. **后端数据装配**：
   - 在 `PracticeItemDetailResponse` 的验证器及练习获取逻辑中，检查 `AttemptItem` 的生效 `GradingRecord`，提取 `hit_keywords` 与 `missing_keywords` 放入 DTO。
   - 若 `question_snapshot` 中带有 `source_snippet_id` 且快照未内联 `source_snippet`，且如果可从上下文或已有关系安全回填，则构造 `SourceSnippetDTO`；若在静态组卷快照中已存在，则正常透传。
2. **前端兼容读取**：
   - `GradingResultList.vue` 中：
     - `getHitKeywords(item)`：读取 `item.hit_keywords || item.question_snapshot?.hit_keywords || []`。
     - `getMissingKeywords(item)`：读取 `item.missing_keywords || item.question_snapshot?.missing_keywords || []`。
     - `hasKeywords(item)`：两者长度之和 > 0。
     - `getSnippet(item)`：读取 `item.source_snippet || item.question_snapshot?.source_snippet`。
     - 只要存在 `source_snippet` 或 `source_snippet_id`，均视为 `hasSnippet`。
   - `detail/index.vue` 中：
     - `handleViewSnippet` 提取 `getSnippet(item)`，即使 `source_snippet` 缺少部分字段也能安全展示（默认降级文本）。

### 3.2 报告数据加载与容错（GRADE-005）
1. 移除 `repData.items` 分支，统一由 `practiceRes` 提供逐题作答项。
2. 在 `loadReportData` 中：
   - 若 `reportRes.code !== 0`，报错并阻断；
   - 若 `practiceRes` 为空或失败，记录提示“作答详情加载失败，请重试”或触发友好错误态，并允许重试。

### 3.3 首屏请求去重（GRADE-006）
1. 参照 `BUG-MAT-011` 首屏去重模式，在 `detail/index.vue` 维护：
   - `let isInitialLoading = false;`
   - `let lastLoadedPracticeId = '';`
2. `loadReportData(pid)` 入口增加守卫：
   - 若 `isInitialLoading && lastLoadedPracticeId === pid`，直接返回，避免并发重复请求；
   - 在进入时置 `isInitialLoading = true; lastLoadedPracticeId = pid;`，并在 `finally` 中复位 `isInitialLoading = false;`。
3. `onLoad` 获取到 `pid` 时调用 `loadReportData(pid)`；`onMounted` 若检测到 `currentPracticeId.value` 已与 `lastLoadedPracticeId` 相同且已有数据/正在加载，则跳过首屏触发。

### 3.4 主观题类型支持与未作答重判保护（GRADE-007, GRADE-008）
1. `GradingResultList.vue` 定义主观题集合：
   ```typescript
   const SUBJECTIVE_TYPES = new Set(['short_answer', 'term_explanation', 'case_analysis']);
   ```
2. 扩充题型映射：
   ```typescript
   const questionTypeMap: Record<string, string> = {
     single_choice: '单选题',
     multiple_choice: '多选题',
     true_false: '判断题',
     fill_in_blank: '填空题',
     short_answer: '简答题',
     term_explanation: '名词解释',
     case_analysis: '案例分析',
   };
   ```
3. 拆分“自评”与“重判”的权限判断：
   ```typescript
   function isSubjectiveType(item: AttemptGradingItem): boolean {
     const qType = item.question_snapshot?.question_type;
     return Boolean(qType && SUBJECTIVE_TYPES.has(qType));
   }

   function canSelfGrade(item: AttemptGradingItem): boolean {
     const isSubjective = isSubjectiveType(item);
     const isPending =
       item.grading_status === 'pending_regrade' ||
       item.status === 'pending_regrade' ||
       item.score === null;
     return isSubjective || isPending;
   }

   function canRegrade(item: AttemptGradingItem): boolean {
     // 必须符合自评条件，且必须已作答 (有作答内容且 is_answered 为 true)
     if (!canSelfGrade(item)) return false;
     const hasAnswer = item.user_answer !== null && item.user_answer !== undefined && item.user_answer !== '';
     return Boolean(item.is_answered && hasAnswer);
   }
   ```
4. 模板中“申请重判”按钮由 `v-if="canSelfGrade(item)"` 改为 `v-if="canRegrade(item)"`。

---

## 4. 兼容性与回滚策略

- **向后兼容**：
  - 新增字段全部带默认值，不破坏已有 API 契约和数据库表结构（仅通过 DTO/快照透传）。
  - 前端对 `hit_keywords`、`source_snippet` 做多级取值降级（顶层与 `question_snapshot` 兼容），适应不同版本历史数据。
- **回滚方案**：
  - 代码变更均聚焦在应用层 DTO 与前端 Vue 组件，回滚只需 git revert 相关 commit，无任何数据迁移与外部不可逆操作。

---

## 5. 影响文件清单

### 后端
- `backend/app/schemas/practice.py`（增强 `QuestionSnapshotDTO`、`PracticeItemDetailResponse`，定义 `SourceSnippetDTO`）

### 前端
- `miniprogram/src/types/report.ts`（更新 `AttemptGradingItem` 及其快照类型）
- `miniprogram/src/subpackages/report/components/GradingResultList.vue`（题型映射、自评与重判条件解耦、关键词与切片读取适配）
- `miniprogram/src/subpackages/report/pages/detail/index.vue`（移除 items 死分支、生命周期请求防重与切片取值优化）

### 测试
- `backend/tests/unit/schemas/test_practice_schemas.py`
- `miniprogram/tests/unit/report/gradingResults.spec.ts`
- `miniprogram/tests/unit/report/reportDetailPage.spec.ts`
