# 技术设计：DIAG 切片 P2-B（016-022）修复

## 1. 背景与根因分析

### BUG-DIAG-016: setReport 陈旧 weakPoints 不清
- **位置**：`miniprogram/src/stores/reportStore.ts:57-62`
- **根因**：
  ```ts
  function setReport(report: DiagnosisReport | null): void {
    currentReport.value = report;
    if (report?.weak_points) {
      weakPoints.value = [...report.weak_points];
    }
  }
  ```
  当传入新的报告但该报告无薄弱知识点（`weak_points` 为空数组或 undefined），或者传入 null 时，缺少 `else` 重置分支，导致上一份报告残留的 `weakPoints` 无法被清除，跨报告浏览时污染页面呈现。
- **方案**：
  重构为：
  ```ts
  weakPoints.value = report?.weak_points ? [...report.weak_points] : [];
  ```

### BUG-DIAG-017: 草稿缺失 title / total_count / material_id
- **位置**：
  - `miniprogram/src/types/practice.ts:122-126` (`AnswerDraft` 接口)
  - `miniprogram/src/stores/practiceStore.ts:82-88, 126-135` (`initSession` 与 `updateDraft`)
  - `miniprogram/src/utils/recentLearning.ts:75-92` (`extractLatestDraftPractice`)
- **根因**：
  `AnswerDraft` 类型仅定义了 `practice_id`、`answers`、`updated_at`。`practiceStore.initSession` 初始化草稿时未存入题目总数、标题或关联资料 ID。而工作台 `recentLearning.ts` 在渲染草稿卡片时，强行尝试从 `rawAny.total_count`、`rawAny.totalCount`、`rawAny.title` 读取，读不到只能回退为 `Math.max(10, answeredCount)` 及“专项练习”，信息失真。
- **方案**：
  1. `AnswerDraft` 增加可选属性：`total_count?: number`、`title?: string`、`material_id?: string`。
  2. `practiceStore.initSession` 增加可选参数 `meta?: { title?: string; material_id?: string }`（保持向后兼容）；在创建初始草稿时记录 `total_count: questionList.length` 及 meta 中的标题与资料 ID。
  3. 兼容既有调用，保证 `initSession(id, questions)` 正常工作。

### BUG-DIAG-018: 继续练习幂等键未生效（Header 名与后端端点不匹配）
- **位置**：
  - `miniprogram/src/api/diagnosis.ts:169-172`
  - `backend/app/api/v1/practices.py:54-58`
  - `backend/app/schemas/practice.py:21-63`
- **根因**：
  1. 前端 `api/diagnosis.ts` 携带的是 `X-Idempotency-Key`，而项目中（如交卷 `practices.py:352` 及资料上传 `materials.py:118`）全局标准均为 `Idempotency-Key`。
  2. 后端 `POST /api/v1/practices`（`create_practice`）根本未声明接收 `Idempotency-Key` 请求头，`PracticeCreateRequest` 也没有该字段；因此前端发来的幂等键在创建练习时被完全忽略，快速点击时会重复建卷。
- **方案**：
  1. 前端 `continuePractice` 改为发送标准请求头 `headers['Idempotency-Key'] = payload.idempotency_key`。
  2. 后端 `backend/app/schemas/practice.py::PracticeCreateRequest` 增加可选字段 `idempotency_key: str | None = Field(default=None, max_length=128)`。
  3. 后端 `backend/app/api/v1/practices.py::create_practice` 添加请求头依赖：
     `idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None`。
  4. 将请求头中的 `idempotency_key`（或 body 中的）传入 `CreatePracticeOptions`，在服务层若存在有效幂等适配器或已存在该练习防重逻辑（结合既有 `find_active_by_source_report`），防止重复创建。

### BUG-DIAG-019: 报告生成幂等为先查后插，无并发冲突捕获
- **位置**：`backend/app/services/diagnosis.py:464-479, 750-752`
- **根因**：
  `generate_diagnosis_report` 生成报告时采用：
  1. 先查 `get_diagnosis_report_by_practice_id`；
  2. 没查到则执行计算并 `create_diagnosis_report` + `commit()`。
  数据库中对 `diagnosis_reports.practice_id` 有唯一索引约束（`models/practice.py:757-759`）。当两个并发请求几乎同时通过“先查”分支时，后 commit 的请求将直接抛出 SQLAlchemy `IntegrityError`，未捕获导致抛出未处理异常并返回 HTTP 500。
- **方案**：
  在 `services/diagnosis.py` 的 `generate_diagnosis_report` 提交事务处使用 try-except 捕获 `IntegrityError`：
  ```python
  from sqlalchemy.exc import IntegrityError

  try:
      created_report = self.diagnosis_repo.create_diagnosis_report(report, user_id=user_id)
      self.session.commit()
      return created_report
  except IntegrityError:
      self.session.rollback()
      existing_report = self.diagnosis_repo.get_diagnosis_report_by_practice_id(
          practice_id=practice_id,
          user_id=user_id,
      )
      if existing_report is not None:
          # 幂等返回已有报告
          return existing_report
      raise
  ```

### BUG-DIAG-020: 掌握度全景中薄弱点未排序
- **位置**：`backend/app/services/diagnosis.py:970, 977, 985, 996-1004`
- **根因**：
  `get_user_mastery_overview` 遍历知识点汇总薄弱条目 `weak_points_summary.append(summary_dto)`，完全依赖数据库查询返回的默认顺序（知识点创建顺序或层级顺序），未进行掌握度排序。而算法层 `core/algorithms/diagnosis.py:586` 明确规定薄弱知识点应按最薄弱优先（`mastery_score` 升序）展示。
- **方案**：
  在组装返回 `UserMasteryOverviewDTO` 之前，对 `weak_points_summary` 进行升序排序：
  ```python
  weak_points_summary.sort(key=lambda x: (x.mastery_score, x.knowledge_point_id))
  ```

### BUG-DIAG-021: 潜伏类型契约对齐（weak_points 与 KnowledgeMasterySummary）
- **位置**：
  - `backend/app/schemas/diagnosis.py:282-352` (`UserMasteryOverviewResponse`)
  - `miniprogram/src/types/report.ts:115-131` (`UserMasteryOverview`, `KnowledgeMasterySummary`)
- **根因**：
  1. 后端掌握度全景下发字段为 `weak_knowledge_points`，前端 `UserMasteryOverview` 定义期望 `weak_points?: WeakPoint[]`。
  2. 单知识点掌握度汇总在前端定义为 `KnowledgeMasterySummary`（`current_score`, `tier`, `sample_count`），后端 DTO 命名为 `KnowledgeMasterySummaryResponse`（`mastery_score`, `level`, `practice_count`）。
- **方案**：
  1. 后端 `UserMasteryOverviewResponse`：增加可选别名字段 `weak_points: list[KnowledgeMasterySummaryResponse] = Field(default_factory=list)`，并在序列化/验证器中将 `weak_knowledge_points` 同步赋值给 `weak_points`，保持完全对齐。
  2. 前端 `miniprogram/src/types/report.ts`：丰富 `KnowledgeMasterySummary` 声明，增加兼容字段定义：
     ```ts
     export interface KnowledgeMasterySummary {
       knowledge_point_id: string;
       knowledge_name?: string;
       mastery_score?: number;
       current_score: number;
       level?: string;
       tier: MasteryTier;
       practice_count?: number;
       sample_count: number;
       correct_count?: number;
       last_practiced_at?: string;
     }
     ```

### BUG-DIAG-022: 报告详情页缺失空态分支
- **位置**：`miniprogram/src/subpackages/report/pages/detail/index.vue:1-42`
- **根因**：
  模板仅包含三个状态分支：
  1. `v-if="loading"`（骨架屏）
  2. `v-else-if="error"`（异常状态）
  3. `v-else-if="currentReport"`（报告内容）
  当页面未接收到有效 `practice_id`（例如错误路由跳转），或接口返回成功但数据为空时，`loading=false`、`error=''` 且 `currentReport=null`。此时三个分支均不命中，页面直接空白无内容，也没有返回按钮。
- **方案**：
  在模板中补充 `v-else` 空态分支：
  ```html
  <view v-else class="empty-state">
    <text class="empty-text">暂无诊断报告数据</text>
    <view class="back-home-btn" @tap="handleBackHome">
      <text>返回学习中心</text>
    </view>
  </view>
  ```
  在脚本中补充 `handleBackHome` 导航方法，在 `detail.scss` 中补充空态样式，与项目中其他空态保持统一视觉标准。

---

## 2. 影响文件清单

### 后端 (Backend)
1. `backend/app/schemas/practice.py`：`PracticeCreateRequest` 增加 `idempotency_key` 字段。
2. `backend/app/schemas/diagnosis.py`：`UserMasteryOverviewResponse` 增加并同步 `weak_points` 字段。
3. `backend/app/api/v1/practices.py`：`create_practice` 接入 `Idempotency-Key` 请求头。
4. `backend/app/services/diagnosis.py`：
   - `generate_diagnosis_report` 增加并发唯一约束冲突捕获与回滚回查；
   - `get_user_mastery_overview` 对 `weak_points_summary` 升序排序。

### 前端 (Miniprogram)
1. `miniprogram/src/stores/reportStore.ts`：`setReport` 增加清空兜底，避免陈旧 `weakPoints` 残留。
2. `miniprogram/src/types/practice.ts`：`AnswerDraft` 增加 `total_count`、`title`、`material_id` 属性。
3. `miniprogram/src/types/report.ts`：`KnowledgeMasterySummary` 兼容字段补齐。
4. `miniprogram/src/stores/practiceStore.ts`：`initSession` 在创建草稿时保存 `total_count`、`title`、`material_id`。
5. `miniprogram/src/api/diagnosis.ts`：`continuePractice` 请求头改为 `Idempotency-Key`。
6. `miniprogram/src/subpackages/report/pages/detail/index.vue`：模板增加 `v-else` 空态，补充 `handleBackHome`。
7. `miniprogram/src/subpackages/report/pages/detail/detail.scss`：增加 `.empty-state` 样式。

---

## 3. 兼容性与回滚策略

1. **附加可选原则**：
   - 后端 DTO 的新增字段（`weak_points`、`idempotency_key`）及请求头均赋予默认值 `default=None` 或 `default_factory=list`，完全兼容旧客户端与存量单元测试。
   - 前端类型的字段增加全部为可选（`?:`），不破坏现有调用方。
2. **回滚方案**：
   - 若出现异常，直接回滚涉及的 11 个文件，各修改均为局部防守型强化，不存在数据表结构变动（migration-free）。
