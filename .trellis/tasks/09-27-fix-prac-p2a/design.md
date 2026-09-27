# 技术设计：PRAC 切片 P2-A 修复

## 1. 背景与根因分析

### BUG-PRAC-005: 交卷幂等回放响应标记缺失
- **根因**: `backend/app/services/practice.py:666-681` 中，在命中 `self.idempotency.get_result(clean_key, str(user_id))` 分支构造并返回 `PracticeSubmissionResult` 时，未设置 `is_idempotent_replay=True`；且 `PracticeSubmissionResult` 数据类（`:98-108`）中根本未声明该字段。导致 API 路由 `backend/app/api/v1/practices.py:418` 中的 `getattr(result, "is_idempotent_replay", False)` 恒返回默认值 `False`。
- **解决方案**:
  1. 在 `PracticeSubmissionResult` 数据类中新增 `is_idempotent_replay: bool = False`。
  2. 在 `PracticeService.submit_practice` 命中幂等回放分支时，显式传入 `is_idempotent_replay=True`。

### BUG-PRAC-006: PracticeStatus 缺少 paused / timeout 且状态机跃迁无法识别
- **根因**:
  - `backend/app/models/practice.py:37-50` 中 `PracticeStatus(enum.StrEnum)` 仅有 `NOT_STARTED`, `IN_PROGRESS`, `PARTIALLY_GRADED`, `COMPLETED`。
  - Service 层 `pause_practice`、`timeout_practice` 直接以硬编码字符串字面量 `"paused"`（`:530`）、`"timeout"`（`:600`）持久化状态。
  - `validate_practice_transition`（`models/practice.py:161-206`）遇到 `"paused"` 或 `"timeout"` 时落入 `Unknown practice status` 拒绝分支。
- **解决方案**:
  1. `PracticeStatus` 扩展：
     ```python
     PAUSED = "paused"
     TIMEOUT = "timeout"
     ```
  2. `validate_practice_transition` 纯函数增加处理：
     - 若 `current_status == PracticeStatus.PAUSED.value`：支持跃迁至 `IN_PROGRESS`；
     - 若 `current_status == PracticeStatus.TIMEOUT.value`：不可逆终态，禁止跃迁（类似于 COMPLETED）。
  3. Service 层硬编码字符串字面量替换为 `PracticeStatus.PAUSED.value` 与 `PracticeStatus.TIMEOUT.value`。

### BUG-PRAC-007: save_answer 仅拦截 COMPLETED 状态
- **根因**:
  - `backend/app/services/practice.py:474-478` 仅判断：
    ```python
    if practice.status == PracticeStatus.COMPLETED.value:
        raise PracticeStatusError("练习已完成，禁止修改作答")
    ```
  - 当状态为 `paused`、`timeout`、`partially_graded` 时，仍会落入更新答案逻辑。
- **解决方案**:
  - 允许修改作答的状态白名单仅为 `NOT_STARTED` 和 `IN_PROGRESS`。若当前状态处于 `PAUSED`（暂停中）、`TIMEOUT`（已超时）、`PARTIALLY_GRADED`（已提交判分中）或 `COMPLETED`（已完成），统一拦截并抛出 `PracticeStatusError`。

### BUG-PRAC-008: 交卷后 practiceStore.drafts 未清除导致首页残留
- **根因**:
  - `miniprogram/src/subpackages/practice/pages/session/index.vue:201-202`：
    交卷成功后调用了 `clearDraftFromStorage(targetPracticeId)` 和 `practiceStore.clearSession()`。
  - 但 `practiceStore.clearSession`（`stores/practiceStore.ts:155-160`）仅重置了 `sessionId`、`questions`、`currentIndex`、`isSubmitting`，**没有清理 `drafts.value`** 中的该练习条目。
  - 首页 `index.vue` 使用 `extractLatestDraftPractice(practiceStore.drafts, ...)` 提取未完成练习。由于 Pinia 实例常驻且 `loadDraftFromStorage` 使用 `{ ...drafts.value, ...saved }` 合并，已提交练习在 `drafts.value` 中始终残留，继续被误当做未完成练习展示。
- **解决方案**:
  - 在 `practiceStore.ts` 增加 `removeDraft(id: string)` 方法，并在 `clearSession(id?: string)` 中如果传入或当前有对应 id 则从 `drafts.value` 移除。
  - 会话交卷后，同步清理内存 store 中的该 draft 条目。

### BUG-PRAC-009: 本地 Storage practice_drafts 结构分裂与强转问题
- **根因**:
  - `miniprogram/src/types/storage.ts:21` 声明白名单为 `Record<string, AnswerDraft>`。
  - `subpackages/practice/utils/draft.ts` 实际写入的是完整结构 `PracticeDraftRecord`（含 `items`、`answers`、`submit_key` 等），为此使用了 `as unknown as Record<string, never>` 绕过类型系统。
  - `practiceStore.ts:142` 的 `syncDraftToStorage` 又写入简化版 `Record<string, AnswerDraft>`。
- **解决方案**:
  - 统一规范：Storage 中的 `practice_drafts` 结构权威类型为 `PracticeDraftRecord`。
  - 更新 `types/storage.ts` 中 `practice_drafts` 为 `Record<string, PracticeDraftRecord>`。
  - 扩展 `AnswerDraft` 或在 store 中使用兼容的 `PracticeDraftRecord` 结构；`draft.ts` 移除 `as unknown as Record<string, never>` 强转，由类型系统原生保证合法。

### BUG-PRAC-010: 前后端状态枚举与映射收敛
- **根因**:
  - 后端状态集为：`not_started`, `in_progress`, `paused`, `timeout`, `partially_graded`, `completed`。
  - 前端 `PracticeStatus` 联合类型为：`'idle' | 'in_progress' | 'paused' | 'submitted' | 'graded'`。
  - 前端适配器 `miniprogram/src/api/adapters/practice.ts:adaptStatus` 缺少对 `timeout` 的映射，走 `default` 分支错误映射为 `'in_progress'`。
- **解决方案**:
  - 更新 `adaptStatus`：
    - `not_started` -> `'idle'`
    - `in_progress` -> `'in_progress'`
    - `paused` -> `'paused'`
    - `completed` -> `'submitted'`（或前端根据判题进入对应终态）
    - `partially_graded` -> `'submitted'`
    - `timeout` -> `'submitted'`（超时已冻结归档，不再允许作答）

### BUG-PRAC-011: PracticeDetailResponse mode 恒为 sequential，completed_count 恒为 0
- **根因**:
  - `backend/app/models/practice.py:209-356` 中 `Practice` ORM 模型未定义 `mode` 列；创建练习 `CreatePracticeOptions` 虽接收 `mode`，但未存入 `Practice` 实例中。
  - `PracticeDetailResponse` 虽然声明了 `completed_count` 字段，但 ORM 无此列；`synchronize_detail_fields` 也未根据练习项计算已完成数量。
- **解决方案**:
  - `mode` 列：
    - 在 `Practice` 模型新增 `mode: Mapped[str] = mapped_column(String(32), nullable=False, default="sequential")`。
    - 在 `PracticeService.create_practice` 中将 `options.mode.value` 存入 `Practice` 模型实例。
  - `completed_count` 计算：
    - 在 `PracticeDetailResponse.synchronize_detail_fields` 中：若 `data` 中包含 `items` 且未显式提供非零 `completed_count`，通过 `sum(1 for it in items if getattr(it, "is_answered", False))` 自动准确计算已答题目数。

---

## 2. 详细接口与模型契约设计

### 2.1 后端契约变更

#### `backend/app/models/practice.py`
```python
class PracticeStatus(enum.StrEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    TIMEOUT = "timeout"
    PARTIALLY_GRADED = "partially_graded"
    COMPLETED = "completed"

class Practice(Base, TimestampMixin, TenantModelMixin):
    # 新增 mode 列
    mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="sequential",
        comment="组卷抽题模式 (PracticeAssemblyMode: sequential/random/weak_points)",
    )
```

#### `backend/app/services/practice.py`
```python
@dataclass(frozen=True)
class PracticeSubmissionResult:
    practice_id: uuid.UUID
    task_id: str
    status: str
    unanswered_count: int
    total_questions: int
    submitted_at: datetime
    answered_questions: int = 0
    uncompleted_count: int = 0
    is_idempotent_replay: bool = False  # 新增字段，默认 False
```

#### `backend/app/schemas/practice.py`
在 `PracticeDetailResponse.synchronize_detail_fields` 中补充：
```python
# 自动统计已完成作答数
if "completed_count" not in data or data.get("completed_count") == 0:
    items = data.get("items") or []
    computed_completed = 0
    for it in items:
        if isinstance(it, dict) and it.get("is_answered"):
            computed_completed += 1
        elif hasattr(it, "is_answered") and getattr(it, "is_answered"):
            computed_completed += 1
    data["completed_count"] = computed_completed
```

### 2.2 前端契约变更

#### `miniprogram/src/types/storage.ts`
```typescript
import type { PracticeDraftRecord } from '../subpackages/practice/types/draft';

export interface StorageDataMap {
  auth_tokens: TokenPairResponse;
  practice_drafts: Record<string, PracticeDraftRecord>;
  user_settings: UserSettings;
}
```

#### `miniprogram/src/stores/practiceStore.ts`
```typescript
function removeDraft(practiceId: string): void {
  if (drafts.value[practiceId]) {
    const next = { ...drafts.value };
    delete next[practiceId];
    drafts.value = next;
  }
}

function clearSession(id?: string): void {
  const targetId = id ?? sessionId.value;
  if (targetId) {
    removeDraft(targetId);
  }
  sessionId.value = null;
  questions.value = [];
  currentIndex.value = 0;
  isSubmitting.value = false;
}
```

#### `miniprogram/src/api/adapters/practice.ts`
```typescript
function adaptStatus(status?: string): PracticeStatus {
  switch (status) {
    case 'in_progress':
    case 'paused':
      return status;
    case 'completed':
    case 'partially_graded':
    case 'timeout':
      return 'submitted';
    case 'not_started':
      return 'idle';
    default:
      return 'in_progress';
  }
}
```

---

## 3. 兼容性与回滚策略

1. **向后兼容性**:
   - `PracticeSubmissionResult.is_idempotent_replay` 默认值为 `False`，不破坏既有调用方。
   - `Practice.mode` 在 ORM 层面具备默认值 `"sequential"`，既有旧练习数据不会报错。
   - `completed_count` 属于计算补充，若已有显式提供值则保留，历史消费方无破坏风险。
   - Storage 类型收敛后，`PracticeDraftRecord` 完全超集覆盖了 `AnswerDraft`（均含 `practice_id`, `answers`, `updated_at`），因此读取既有持久化草稿平滑兼容。

2. **回滚点**:
   - 后端若异常，可直接还原 `PracticeStatus`、`save_answer` 拦截与 `Practice` model 的 `mode` 字段；
   - 前端若异常，可复位 `practiceStore.ts` 与 `storage.ts` 类型定义。

---

## 4. 影响文件清单

### 后端
- `backend/app/models/practice.py`（枚举扩充、mode 字段增加、validate_practice_transition 扩充）
- `backend/app/services/practice.py`（回放标记、枚举使用规范化、save_answer 作答拦截收紧、mode 赋值）
- `backend/app/schemas/practice.py`（synchronize_detail_fields 计算 completed_count）
- `backend/tests/unit/models/test_practice.py`（状态机跃迁用例）
- `backend/tests/unit/services/test_practice_service.py`（回放标记、paused/timeout 作答拦截测试）
- `backend/tests/unit/api/test_practice_router.py`（路由层验证）

### 前端
- `miniprogram/src/types/storage.ts`（规范 StorageDataMap）
- `miniprogram/src/stores/practiceStore.ts`（清除内存草稿、规范 draft 类型）
- `miniprogram/src/subpackages/practice/utils/draft.ts`（移除类型强转、确保类型完全对齐）
- `miniprogram/src/subpackages/practice/pages/session/index.vue`（交卷成功传参清除）
- `miniprogram/src/api/adapters/practice.ts`（补充 timeout 映射）
- `miniprogram/tests/unit/practice/draftUtils.spec.ts`（草稿读写用例）
- `miniprogram/tests/unit/stores/practice.spec.ts`（store 清理用例）
- `miniprogram/tests/unit/api/practiceAdapter.spec.ts`（状态适配器用例）
