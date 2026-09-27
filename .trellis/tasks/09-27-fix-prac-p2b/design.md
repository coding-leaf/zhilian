# 技术设计：PRAC 切片 P2-B 修复

## 1. 背景与根因分析

### BUG-PRAC-012：前端防抖同步在会话销毁时未 flush
- **位置**：`miniprogram/src/subpackages/practice/composables/usePracticeSession.ts:86-92, 147-153`
- **根因**：作答变更后设定 600ms 防抖定时器 `syncTimeout` 调用 `syncSingleDraft`。当用户在 600ms 内点击离开或返回（触发 `onUnload`/`onBeforeUnmount` 调用 `cleanupSession`）时，代码仅执行了 `clearTimeout(syncTimeout)`，直接丢弃了本次网络请求调度。虽然本地 storage 有草稿，但远端未即时收到最新输入，造成多端或再次进入时的作答延迟不一致。
- **方案**：在 `cleanupSession` 时，若 `syncTimeout` 存在，先清理定时器，同时主动触发 `void syncPendingDrafts()`（或立即单次 flush），使离开前的未同步作答立即通过 HTTP 发送至后端暂存。

### BUG-PRAC-013：交卷事务提交与幂等快照解耦导致的 400/5xx 缺陷
- **位置**：`backend/app/services/practice.py:724-771`
- **根因**：在 `submit_practice` 执行流程中，第 4 步 `update_practice_status(COMPLETED)` 与第 5 步 `self.session.commit()` 先行执行，之后才在第 6 步调用 `self.idempotency.set_result(clean_key, ...)`。若 Redis 写入超时或抛出网络异常，外部捕获到异常导致 API 返回 5xx；但此时数据库已处于 `COMPLETED` 状态，客户端若用相同的 `clean_key` 进行重试，第 1 步 `cached_result` 为空，进入主逻辑校验到 `practice.status == COMPLETED`，直接抛出 `PracticeStatusError("练习已完成，禁止重复提交", error_code=40011)`。
- **方案**：
  1. 隔离快照持久化异常：若 `session.commit()` 已成功，快照写入包裹在独立 try-except 块中并记录 warning 日志，不阻断本次成功返回。
  2. 增强 DB 级幂等兜底：在状态校验处，若 `practice.status == COMPLETED`，检查 `practice.submit_idempotency_key == clean_key`。若相同，说明是本次重试撞上已提交练习，不再抛出异常，而是从数据库练习实体及其题目统计安全重建 `PracticeSubmissionResult`，实现高可靠幂等回放。

### BUG-PRAC-014：前端题型渲染对主观题型未覆盖
- **位置**：`miniprogram/src/subpackages/practice/components/QuestionRenderer.vue:15-74` 与 `backend/app/core/algorithms/grading.py:114-123`
- **根因**：`QuestionRenderer.vue` 模版中仅针对 `single_choice`, `multiple_choice`, `true_false`, `fill_in_blank`, `short_answer` 提供了分支，未覆盖后端已支持的主观题型 `term_explanation`（名词解释）与 `case_analysis`（案例分析）。一旦组卷快照中下发这两种题型，页面无任何输入控件，用户无法输入作答。
- **方案**：
  1. 在 `QuestionRenderer.vue` 中为 `short_answer`、`term_explanation`、`case_analysis` 以及通用主观题 fallback 统一复用多行文本输入组件（textarea），并支持灵活的字数上限提示。
  2. 在 `questionTypeLabel` 计算属性中添加对应映射：`term_explanation: '名词解释'`, `case_analysis: '案例分析'`。

### BUG-PRAC-015：累计耗时未在后端聚合输出与前端耗时硬编码
- **位置**：`backend/app/schemas/practice.py:249-277`；`miniprogram/src/subpackages/practice/composables/usePracticeSession.ts:55, 82, 103`
- **根因**：
  1. 前端在 `loadPractice` 时读取 `res.data.time_elapsed_seconds`，但后端 `PracticeDetailResponse` 缺失该字段，导致每次重新进入练习耗时均归零。
  2. 前端在 `handleAnswerChange` 中向 `createOrUpdateDraft` 传入硬编码的常量 `1`（`duration: 1`），且暂存接口入参也硬编码 `time_spent_seconds: 1`，导致单题与整卷耗时与实际作答时间脱节。
- **方案**：
  1. **后端**：在 `PracticeDetailResponse` 中新增附加可选字段 `time_elapsed_seconds: int = 0`。在 `synchronize_detail_fields` 中若入参包含 `items`，可动态计算 `sum(item.duration_seconds for item in items if hasattr(item, "duration_seconds"))`。
  2. **前端**：在 `usePracticeSession.ts` 中维护每题进入的 `questionStartTime = Date.now()`；切换或输入作答时计算时间差 `Math.max(1, Math.round((Date.now() - questionStartTime) / 1000))`，传给草稿和暂存接口，并重置当前题起始时间。

### BUG-PRAC-016：多选题存储格式非 JSON 与历史数据兼容
- **位置**：`backend/app/services/practice.py:451-455`；`backend/app/models/practice.py:405-410`
- **根因**：前端在提交选项数组时（`val: string[]`），后端服务层执行 `str(user_answer)`，导致列表被转成了 Python 的 repr 字符串（如 `"['A', 'B']"`），违背了跨语言标准的 JSON 数组格式契约。
- **方案**：
  1. **服务层写入**：在 `save_answer` 中，当 `user_answer` 为列表时，通过 `json.dumps(sorted(user_answer), ensure_ascii=False)` 格式化为合法 JSON 字符串。
  2. **跨端读取与判题**：后端判题算法 `normalize_objective_token` 目前已使用正则提取字母，本就兼容 `"['A', 'B']"` 与 `json.dumps` 格式；在 DTO 层向前端序列化时保持字符串透传，同时前端适配层 `adaptPracticeResponse` 解析选项时同时支持标准 JSON 字符串与 Python repr 字符串（通过正则提取字符兼容）。

### BUG-PRAC-017：前端缺少 pause/resume API 与会话层状态封装
- **位置**：`miniprogram/src/api/practice.ts`；后端 `backend/app/api/v1/practices.py:252-341`
- **根因**：后端已实现 `POST /practices/{id}/pause` 与 `POST /practices/{id}/resume`，但前端完全缺失对应的网络函数定义与会话层控制方法。
- **方案**：
  1. `miniprogram/src/api/practice.ts` 补齐 `pausePractice(practiceId: string)` 与 `resumePractice(practiceId: string)`，调用对应端点，响应类型为 `PracticeStatusResponse`。
  2. 在 `usePracticeSession.ts` 中提供 `pauseSession` 与 `resumeSession`，在暂停时停止本地计时并调用后端接口，在恢复时启动计时并调用后端接口。

---

## 2. 契约设计与跨层一致性

### 2.1 后端 `PracticeDetailResponse` 扩展（`schemas/practice.py`）
```python
class PracticeDetailResponse(BaseModel):
    ...
    time_elapsed_seconds: int = Field(default=0, ge=0, description="练习累计已消耗秒数")
```
在 `synchronize_detail_fields` before validator 中：
- 若原始实体对象上有 `items` 且未提供 `time_elapsed_seconds`，汇总计算 `sum(getattr(it, "duration_seconds", 0) for it in items)` 填充。

### 2.2 前端 API 新增（`miniprogram/src/api/practice.ts`）
```typescript
export interface PracticeStatusChangeResult {
  practice_id: string;
  status: string;
  message: string;
}

export function pausePractice(practiceId: string): Promise<ApiResponse<PracticeStatusChangeResult>> {
  return request<PracticeStatusChangeResult>({
    url: `/api/v1/practices/${practiceId}/pause`,
    method: 'POST',
  });
}

export function resumePractice(practiceId: string): Promise<ApiResponse<PracticeStatusChangeResult>> {
  return request<PracticeStatusChangeResult>({
    url: `/api/v1/practices/${practiceId}/resume`,
    method: 'POST',
  });
}
```

---

## 3. 影响文件清单

### 后端
- `backend/app/schemas/practice.py`（增加 `time_elapsed_seconds` 字段与 validator 汇总计算）
- `backend/app/services/practice.py`（优化交卷幂等容错与重试回放；规范化多选 `json.dumps` 存储）
- `backend/tests/unit/services/test_practice_service.py`（添加幂等快照异常容错测试与 JSON 格式保存测试）
- `backend/tests/unit/schemas/test_practice_schemas.py`（添加 `time_elapsed_seconds` 字段验证）

### 前端
- `miniprogram/src/api/practice.ts`（增加 `pausePractice` / `resumePractice`）
- `miniprogram/src/api/adapters/practice.ts`（适配 `time_elapsed_seconds` 与多选答案解析）
- `miniprogram/src/types/practice.ts`（完善 `PracticeStatusChangeResult`）
- `miniprogram/src/subpackages/practice/composables/usePracticeSession.ts`（增加 flush、真实计时、暂停恢复）
- `miniprogram/src/subpackages/practice/components/QuestionRenderer.vue`（扩展名词解释、案例分析等主观题渲染）
- `miniprogram/tests/unit/components/QuestionRenderer.spec.ts`（题型渲染单测覆盖）
- `miniprogram/tests/unit/composables/usePracticeSession.spec.ts`（flush与计时逻辑单测覆盖）

---

## 4. 兼容性与回滚策略

- **数据库与模型**：无新增 DB 列，字段基于现有列与逻辑计算，无需 Alembic 迁移。
- **向后兼容**：
  - `time_elapsed_seconds` 为可选默认值 `0`，历史客户端不处理也不会报错。
  - `SaveAnswerDTO.user_answer` 历史存储的数据无需批量更新，判题算法对多选依然通过正则解析，平滑过渡。
- **回滚点**：各改动均为纯应用层逻辑，撤销对应 commit 即可快速回滚，不破坏任何已持久化数据。
