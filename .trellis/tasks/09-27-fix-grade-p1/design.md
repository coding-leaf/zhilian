# 技术设计：GRADE 切片 P1 修复

## 1. 背景与根因

### GRADE-001 重批同步语义
- `GradingService.regrade_attempt`（`backend/app/services/grading.py:707-884`）在请求内**同步**调用 LLM，写入 `status=SUCCESS, is_final=True` 的新记录并 `item.score = final_score`，返回该 `GradingRecord`。
- 路由 `api/v1/grading.py:135-140` 把 `record.status` 原样返回（真实为 `"success"`），但 `RegradeResponse.status` 默认/文档写死 `pending_regrade`，且**不回传分数**。
- 前端 `RegradeModal.vue:136` 仅 emit `{attempt_item_id, reason}`；`detail/index.vue:243-247` 忽略响应，硬编码 `target.status='pending_regrade'` 且不更新分数。
- 结论：同步完成却按异步待判呈现，分数停留旧值。

### GRADE-002 待重判呈现
- 降级路径 `_build_pending_regrade_record`（`grading.py:500-527`）将 `item.score = 0.0`。
- `AttemptItem`（`models/practice.py:363-433`）**无 status 列**；`PracticeItemDetailResponse.status`（`schemas/practice.py:155`）对真实 ORM 恒为默认 `"unanswered"`（before-validator 仅在 `data["status"]=="unanswered"` 时翻为 `answered`，而 ORM 路径不会产生该键；详见 §2 实证）。
- 前端 `reportFormat.getGradingStatusInfo` 依赖 `item.status`/`item.score`，`score=0.0` 且非 null → 落到阈值分支显示“判错”。
- 结论：缺可判定的判题状态字段；pending 与“真实 0 分”无法区分。

## 2. 关键实证（objective evidence）

在 `backend/.venv` 实测：

```
PracticeItemDetailResponse.model_validate(<AttemptItem 实例: user_answer='hello', is_answered=True, score=None>)
# => status='unanswered', score=None
hasattr(<AttemptItem>, 'status') => False
```

即：练习项 DTO 的 `status` 字段对真实 ORM **恒为 `unanswered`**，不可作为判题状态来源。因此必须引入显式 `grading_status`。

## 3. 契约设计

### 3.1 后端 `RegradeResponse`（`schemas/grading.py`）
```
attempt_item_id: UUID
status: str = "success"      # 终态；成功即 success（同步语义）
message: str = ""            # 改为“重新判题已完成”
grading_record_id: UUID|None
score: float|None = None     # 新增：重判后新分数，供前端就地更新
is_final: bool = True        # 新增：重判记录是否生效终态
```

### 3.2 后端 `PracticeItemDetailResponse.grading_status`（`schemas/practice.py`）
- 新增字段 `grading_status: str | None = None`，描述 `unanswered | pending_regrade | graded`。
- 在既有 before-validator 计算（仅当未提供时）：
  - `is_answered is False` → `"unanswered"`
  - 否则 `score is None` → `"pending_regrade"`
  - 否则 → `"graded"`
- `field_names` 追加 `"grading_status"`（若上游/ORM 已显式提供则尊重）。
- 关键不变量：**降级 pending 必须 `item.score=None`**（§4），否则无法与真实 0 分区分。

### 3.3 前端判级（`subpackages/report/utils/reportFormat.ts`）
`getGradingStatusInfo({ grading_status?, status?, score?, max_score? })` 判定顺序：
1. `grading_status === 'pending_regrade'` → 待重新判题
2. `grading_status === 'unanswered'` → 未作答
3. `grading_status == null`（旧数据）时回退：`status==='pending_regrade'` / `status==='unanswered'`
4. `score == null` → 待重新判题
5. `score >= max*0.6` → 判对；否则判错

### 3.4 前端重判成功回填（`detail/index.vue`）
`onRegradeSuccess(payload)`：payload 携带 `status`、`score`。
- `status === 'success' && typeof score === 'number'` → `target.score = score; target.status = 'graded'`
- 否则 → `target.status = 'pending_regrade'`
- 仍触发一次报告刷新（既有行为保留）。

`RegradeModal.vue` 的 `success` 事件 payload 增加 `status`/`score`（取 `res.data`）。

## 4. 数据流与状态机

```
LLM 超时/失败
  _grade_with_llm except
    -> _build_pending_regrade_record
         item.score = None      (原 0.0)
         record.status = pending_regrade, record.score = 0.0 (记录保留 0.0)
  -> practice.status = partially_graded

GET /practices/{id}
  PracticeItemDetailResponse.model_validate(orm)
    grading_status = unanswered | pending_regrade | graded

前端 getGradingStatusInfo
  pending_regrade -> 待重新判题 / 待判定
```

重判（同步）:
```
POST /grading/regrade -> record(status=success, score=新分)
  RegradeResponse{status:'success', score:新分}
前端 onRegradeSuccess -> target.score=新分, target.status='graded'
```

## 5. 兼容性与回滚
- `grading_status` 与 `score`/`is_final` 均为**附加可选**，默认值不变；旧客户端忽略即可。
- `RegradeResponse.status` 默认由 `pending_regrade` 改为 `success`：属**修正**（真实服务本返回 success）；对 mock 断言有影响，测试同步更新。
- `AttemptItem.score` 由 `0.0` 改 `None`：`sum(it.score or 0.0)` 已兼容；pending 记录 `score` 仍为 `0.0`（不改）。
- 回滚点：还原 `_build_pending_regrade_record` 的 `item.score`；移除 DTO 新字段与前端适配分支；`RegradeResponse` 默认值复位。

## 6. 影响文件清单
后端：
- `backend/app/services/grading.py`（pending item.score=None）
- `backend/app/schemas/grading.py`（RegradeResponse）
- `backend/app/schemas/practice.py`（grading_status）
- `backend/app/api/v1/grading.py`（透传 status/score/message）
- 测试：`tests/unit/services/test_grading_service.py`、`tests/unit/schemas/test_practice_schemas.py`、`tests/unit/api/test_grading_router.py`、`tests/unit/api/test_practice_grading_flow.py`

前端：
- `miniprogram/src/types/report.ts`（AttemptGradingItem.grading_status）
- `miniprogram/src/types/practice.ts`（RawPracticeItem.grading_status）
- `miniprogram/src/subpackages/report/utils/reportFormat.ts`
- `miniprogram/src/subpackages/report/components/GradingResultList.vue`
- `miniprogram/src/subpackages/report/components/RegradeModal.vue`
- `miniprogram/src/subpackages/report/pages/detail/index.vue`
- `miniprogram/src/api/diagnosis.ts`（requestRegrade 响应类型）
- 测试：`tests/unit/report/reportFormat.spec.ts`、`gradingModals.spec.ts`、`reportDetailPage.spec.ts`、`tests/unit/api/diagnosis.spec.ts`
