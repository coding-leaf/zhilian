# 技术设计：DIAG 错题本 P1 修复

## 1. 根因

### DIAG-003（分页总数失真）
- 服务 `list_wrong_records` 返回 `list[WrongRecord]`（`services/diagnosis.py:1087-1150`）；路由 `total_count = getattr(records,"total",None)` 对 list 恒 None → 回退 `len(items)`（`api/v1/diagnosis.py:323-325`）。
- 前端 `wrongHasMore = wrongRecords.length < total`（`reportStore.ts:86`）→ 满页时 false → `onReachBottom` 不再加载（`wrong-book/index.vue:266-269`）。

### DIAG-004（取消攻克无效）
- 前端 `toggleWrongRecordResolved(id,false)` 发 `{is_mastered:false}`（`api/diagnosis.ts:93-106`）；后端路由无请求体参数（`api/v1/diagnosis.py:343-346`），仓库恒置 True（`repositories/diagnosis.py:463-464`）。

### DIAG-005（作答未下发）
- 实体 `WrongRecord.last_wrong_answer` 存在（`models/practice.py:831-836`），但 `WrongRecordItemResponse` 无 `user_answer`（`schemas/diagnosis.py:360-380`）；前端 `WrongRecordCard.vue:149-151` 读 `record.user_answer` → 恒空。

### DIAG-006（一键巩固 422）
- 前端 `source_type='wrong_record'`（`wrong-book/index.vue:77`、`wrongBookFormat.ts:252`）；后端合法集合仅 `{normal, weakness}`（`schemas/practice.py:18`）→ 422。
- `material_id` 后端必填（`schemas/practice.py:30`），错题本页未传时为 `''` → 缺失；`knowledge_point_ids` `min_length=1`。

## 2. 契约设计

### 2.1 DIAG-003 真实总数
- 仓储新增 `count_wrong_records(user_id, is_mastered=None, knowledge_point_id=None) -> int`（与 `list_wrong_records` 同过滤条件，`select(func.count())`）。
- 服务 `list_wrong_records(...) -> tuple[list[WrongRecord], int]`：
  - `material_id` 分支：`filtered` 列表 → `(filtered[offset:offset+limit], len(filtered))`。
  - 其他：`(repo.list(...), repo.count(...))`。
- 路由：`result = service.list_wrong_records(...)`；若是 `WrongRecordListResponse` 直接返回；否则解包 `(records, total)`（兼容旧 list 返回：`total=len`）；`error_type` 事后过滤保持（其失真属 P2）。
- 更新受影响的测试（服务/路由 mock 改为 tuple）。

### 2.2 DIAG-004 可选攻克入参
- 新增 `MarkWrongRecordMasteredRequest(BaseModel): is_mastered: bool | None = None`（`schemas/diagnosis.py`）。
- 路由 `mark_wrong_record_mastered(id, request: MarkWrongRecordMasteredRequest | None = None, ...)`：
  `target = (request.is_mastered if request and request.is_mastered is not None else True)`；调用 `service.mark_wrong_record_mastered(..., is_mastered=target)`。
- 服务 `mark_wrong_record_mastered(..., is_mastered: bool = True)` → 透传 repo；message：`target ? "错题已成功标记为已攻克" : "已取消该错题的攻克状态"`。
- 仓库 `mark_wrong_record_mastered(..., is_mastered: bool = True)`：`record.is_mastered = is_mastered; record.mastered_at = datetime.now(UTC) if is_mastered else None`。
- 无 body 的既有调用（`markWrongRecordMastered`）行为不变（默认 True）。

### 2.3 DIAG-005 作答下发
- `WrongRecordItemResponse` 新增 `user_answer: str | None = None`。
- before-validator 需覆盖 ORM `from_attributes` 路径：非 dict 输入时按字段清单（含 `last_wrong_answer`）`getattr` 抽取为 dict，再 `user_answer = data.get("user_answer") ?? data.get("last_wrong_answer")`；dict 路径同样同步。
- 前端无需改动（已读 `record.user_answer`）。

### 2.4 DIAG-006 继续练习契约
- `VALID_PRACTICE_SOURCE_TYPES` 增加 `"wrong_record"`；`PracticeSourceType` 增加 `WRONG_RECORD = "wrong_record"`。
- `PracticeCreateRequest.material_id: uuid.UUID | None = None`；`CreatePracticeOptions.material_id: uuid.UUID | None = None`。
- `PracticeService.create_practice`：创建 `Practice` 前解析 `resolved_material_id = options.material_id or selected/scattered_questions[0].material_id`（题目实体带 `material_id`）；写入 `Practice.material_id=resolved_material_id`。题目数门禁保证 `>=1`。
- 路由 `create_practice` 透传 `material_id=request.material_id`（可 None）。
- 前端：`wrong-book/index.vue` 在 `targetKnowledgePointIds.length === 0` 时禁用 `ContinuePracticeBar`（disabled 组合）；`materialId` 为空时后端自行解析。
- 旧 `weakness`/`normal` 行为零回归。

## 3. 数据流

```
GET /wrong-records  -> service (items, real_total) -> WrongRecordListResponse.total
  -> reportStore.wrongHasMore = loaded < total -> onReachBottom 翻页

POST /wrong-records/{id}/master {is_mastered:false}
  -> service(is_mastered=False) -> repo(False, mastered_at=None) -> 响应 is_mastered=false

GET /wrong-records item.user_answer <- entity.last_wrong_answer -> WrongRecordCard

POST /practices {source_type:'wrong_record', knowledge_point_ids:[...], material_id?}
  -> resolve material from questions -> Practice -> 200
```

## 4. 兼容性与回滚
- `master` 无 body = 置 True（旧行为）；`material_id` 可选为附加；`source_type` 扩展为附加枚举。
- 服务返回 tuple 属内部契约变更，调用点仅路由与测试，测试同步更新。
- 回滚：`count_*` 移除、服务返回 list、`source_type`/可选 material 复位。

## 5. 影响文件
后端：
- `app/repositories/diagnosis.py`（count_wrong_records、master is_mastered）
- `app/services/diagnosis.py`（list_wrong_records tuple、mark 入参）
- `app/api/v1/diagnosis.py`（解包 total、master 请求体）
- `app/schemas/diagnosis.py`（user_answer、MarkWrongRecordMasteredRequest）
- `app/schemas/practice.py`（source_type 白名单、material_id 可选）
- `app/services/practice.py`（CreatePracticeOptions.material_id 可选 + 解析）
- `app/models/practice.py`（PracticeSourceType.WRONG_RECORD）
- `app/api/v1/practices.py`（透传可选 material_id）
- 测试：`tests/unit/repositories/test_diagnosis_repo.py`、`tests/unit/services/test_diagnosis_service.py`、`tests/unit/api/test_diagnosis_router.py`、`tests/unit/schemas/test_*diagnosis*`、practice 相关测试

前端：
- `miniprogram/src/subpackages/report/pages/wrong-book/index.vue`（禁用条件）
- `miniprogram/tests/unit/report/wrongBookPage.spec.ts`（如存在，补回归）
