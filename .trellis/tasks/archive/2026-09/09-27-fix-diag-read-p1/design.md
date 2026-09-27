# 技术设计：DIAG 读侧 P1 修复

## 1. 根因

### DIAG-001 / DIAG-002（报告契约）
- 后端 `DiagnosisReportResponse`（`schemas/diagnosis.py:172-211`）只提供 `weak_knowledge_points`、`score_rate`、`mastery_before/after`；**无** `weak_points`、`overall_score`、`mastery_rate`。
- 前端 `DiagnosisReport`（`types/report.ts:36-52`）必填 `overall_score`、`mastery_rate`，并以 `weak_points` 消费（`reportStore.ts:59-60`、`detail/index.vue:31-32,147`、`WeakKnowledgeCard`）。
- `utils/request.ts` 原样透传，无重命名层 → 字段恒 `undefined`，综合得分恒 0、薄弱卡片空、`masteryTier` 恒 unlearned。

### DIAG-007（掌握度全景）
- 前端 `fetchMasteryOverview()` 无参（`api/diagnosis.ts:41-48`；`pages/index/index.vue:107`）。
- 后端路由 `material_id` 可选（`api/v1/diagnosis.py:208`），透传 service；`get_user_mastery_overview` 形参类型为 `uuid.UUID`（`services/diagnosis.py:906`），`list_by_material_id(None)` 生成 `material_id IS NULL`（`repositories/knowledge.py:162-170`）。`KnowledgePoint.material_id` 为 NOT NULL → 恒空 → 全景恒 0。

### DIAG-008（退步符号）
- 后端 `check_regression`：`score_delta = round(previous_score - current_score, 4)`，`is_regressed = score_delta >= threshold`（`core/algorithms/diagnosis.py:196-197`；docstring `:133-134`）。
- 前端 `formatScoreDelta`：`isRegressed = delta <= -0.05`，正数显示 `+N%`（`subpackages/report/utils/reportFormat.ts:257-269`）。
- 语义相反 → 真退步显示为提升、且不显示“退步”徽章。

## 2. 契约设计

### 2.1 前端诊断报告适配层（新增 `src/api/adapters/diagnosis.ts`）
```ts
interface RawDiagnosisReport extends Partial<DiagnosisReport> {
  weak_knowledge_points?: WeakPoint[];
  score_rate?: number;
  mastery_after?: number | null;
}
export function adaptDiagnosisReport(raw: RawDiagnosisReport | null | undefined): DiagnosisReport;
```
规则（幂等，后端已给优先）：
- `weak_points = raw.weak_points ?? raw.weak_knowledge_points ?? []`
- `overall_score = raw.overall_score ?? Math.round((raw.score_rate ?? 0) * 100)`
- `mastery_rate = raw.mastery_rate ?? Math.round((raw.mastery_after ?? raw.score_rate ?? 0) * 100)`
- 其余字段（`id`/`practice_id`/`mastery_before`/`mastery_after`/`summary`/`created_at`/计数类）原样透传，缺省给稳定默认（0 / null / []）。

接入点：`api/diagnosis.ts::fetchDiagnosisReport` 改为 `request<RawDiagnosisReport>` 后 `adaptDiagnosisReport(res.data)` 包装（保留 `ApiResponse` 结构与其他字段）。其余报告接口（列表/按 ID）如被消费亦一并接入；至少覆盖 `fetchDiagnosisReport`。

### 2.2 掌握度全景缺省资料（后端）
- `DiagnosisService.get_user_mastery_overview(user_id, material_id: uuid.UUID | None = None, ...)`。
- 分支：
  - `material_id is not None` → 现有 `knowledge_repo.list_by_material_id` + `diagnosis_repo.list_mastery_records_by_material`（零回归）。
  - `material_id is None` → `knowledge_repo.list_all_by_user_id(user_id)`（新增，无 limit）+ `diagnosis_repo.list_mastery_records_by_user(user_id)`（已存在）。
- `KnowledgeRepository` 新增 `list_all_by_user_id(user_id) -> list[KnowledgePoint]`（`where user_id`，按 level/created 排序，无分页上限）。
- `_log_metric(target_id=...)`：`None` 时传 `"all"`（`target_id: uuid.UUID | str`）。
- 路由移除 `material_id=material_id,  # type: ignore[arg-type]`（签名已允许 None）。
- DTO `UserMasteryOverviewDTO.material_id` 允许 `None`（与响应 schema 一致）。

### 2.3 退步符号统一（后端算法）
- `check_regression`（及别名 `check_knowledge_regression`）：
  - `score_delta = round(current_score - previous_score, 4)`
  - `is_regressed = score_delta <= -threshold`
  - docstring：`score_delta: 分数变化值 (current_score - previous_score)，降幅为负`。
- `WeakKnowledgeItem.score_delta` docstring 同步为“当前 - 上次；负数=退步”。
- 保持退步判定集合不变（`previous-current >= threshold` ≡ `current-previous <= -threshold`）；仅返回值的符号翻转。
- 排序保持“最弱优先 + 降幅最大优先”：原 `(current_score, -score_delta)` 语义在符号翻转后需相应调整（按 `current_score` 升序、`score_delta` 升序），确保最负（降幅最大）在前。
- 前端 `formatScoreDelta` **不改**（已是负数=退步）。

## 3. 数据流

```
GET /api/v1/practices/{id}/diagnosis
  DiagnosisReportResponse{weak_knowledge_points, score_rate, mastery_after, ...}
  -> adaptDiagnosisReport
       weak_points / overall_score / mastery_rate
  -> reportStore.setReport -> WeakKnowledgeCard / DiagnosisSummaryCard / masteryTier

GET /api/v1/mastery/overview (no material_id)
  service material_id=None -> list_all_by_user_id + list_mastery_records_by_user -> 真实档位计数

诊断算法 check_regression
  score_delta = current - previous (负数=退步) -> WeakKnowledgeItemDTO.score_delta
  -> formatScoreDelta(negative).isRegressed = true -> “退步”徽章
```

## 4. 兼容性与回滚
- 适配层幂等：已含前端字段的夹具/响应不被改动。
- `material_id=None` 为新增分支，带参路径零回归。
- 退步符号翻转会使算法单测的期望值翻转（测试同步更新）；退步**集合**不变，业务判定等价。
- 回滚：移除适配层接入；`get_user_mastery_overview` 分支复位；`check_regression` 符号复位。

## 5. 影响文件
后端：
- `app/services/diagnosis.py`（mastery overview 分支）
- `app/repositories/knowledge.py`（新增 list_all_by_user_id）
- `app/core/algorithms/diagnosis.py`（score_delta 符号 + 排序）
- `app/api/v1/diagnosis.py`（移除 type ignore）
- 测试：`tests/unit/services/test_diagnosis_service.py`、`tests/unit/core/algorithms/test_diagnosis.py`、`tests/unit/api/test_diagnosis_router.py`（如涉及）、`tests/unit/repositories/test_knowledge_repo.py`（如涉及）

前端：
- `miniprogram/src/api/adapters/diagnosis.ts`（新增）
- `miniprogram/src/api/diagnosis.ts`（接入适配）
- `miniprogram/src/types/report.ts`（如需 Raw 类型）
- 测试：`miniprogram/tests/unit/api/diagnosisAdapter.spec.ts`（新增）、`diagnosis.spec.ts`（接入后）
