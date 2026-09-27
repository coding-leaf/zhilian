# 修复设计：MAT 切片 P1

## 1. 边界与原则

- 契约权威：后端状态枚举与响应模型；字段/状态值前后端逐字对齐。
- 四项互为因果（002/003/004 构成重拍闭环），需一并修；001 独立（数据完整性）。
- 新增状态成员为附加项，DB 列存字符串，无需迁移。

## 2. 真实契约（已核实）

### 秒传（MAT-001）
- `services/material.py:453-469`：命中 `find_version_by_hash`（跨资料，按 user+hash，`repositories/material.py:360-383`）且命中版本 READY/FAILED 时，`storage_key = existing_ver.storage_key`，跳过 `put_object`。存储键 `build_material_storage_key(user_id, material.id, 1, hash, fmt)` 内嵌**源资料 id**。
- `hard_delete_material`（`:1440-1463`）收集本资料各版本 `storage_key` 后无条件 `delete_object` → 共享对象被删。

### 重拍传输（MAT-002）
- 后端 `materials.py:421-433`：`page_index: Form(ge=1)` + `file: UploadFile=File(...)`（multipart）。
- 前端 `api/material.ts:196-212` `retakeMaterialPage` 用 `request({data:{page_index,file}})`（JSON）；同文件 `reshootMaterialPage`（`:242-267`）已有 `isRealMiniProgramUpload()` → `uploadFile` 分支。`RetakeDrawer.vue:131` 调 `retakeMaterialPage`。

### 重拍达标后续（MAT-003）
- `retry_ocr_pages` 全达标分支（`services/material.py:913-961`）：`delete_snippets_by_version` → `create_snippets` → 置版本 READY + 资料 READY；**未**触碰知识树。
- 正常流水线阶段 D（`:709-719`）在切片后调用 `knowledge_service.extract_and_build_knowledge_tree`；`knowledge_service.extract_and_build_knowledge_tree`（`services/knowledge.py:349`）内部已含 `delete_knowledge_points_by_version`（`:511`）。

### 待重拍状态（MAT-004）
- `MaterialStatus`（`models/material.py:31-38`）仅 pending/parsing/ready/failed。
- OCR 门禁失败（`services/material.py:640-653`）置版本 FAILED + 资料 FAILED 并 return。
- `_resolve_status_filter('retake_required')` 返回 `[]`（`:1013-1014`）。
- `api/v1/materials.py:208` 已把 `retake_required` 列为合法筛选值；`materials.py` 无 OCR 页查询路由。
- `repositories/material.py:621` `get_ocr_pages(version_id, user_id)` 已存在。
- 前端 `detail/index.vue:200-211` 在 `statusUpper==='RETAKE_REQUIRED'` 时**硬编码**一条假页面；`:165-167` 状态判断用大写 `RETAKE_REQUIRED`；列表页 `list/index.vue:73` 筛选 `retake_required`。

## 3. 方案设计

### 3.1 MAT-001（backend）
- `create_material`：删除「命中即复用 `existing_ver.storage_key`」分支，**始终** `put_object` 到本资料自有 key（`build_material_storage_key(user_id, material.id, ...)`）。
- `find_version_by_hash` 方法保留（可能被其它路径/测试引用），但 `create_material` 不再用它做物理键复用（保留记录了内容的去重语义由 `content_hash` 行数据表达）。
- 语义说明：现有实现命中后**仍会入队完整解析**（`:482-492`），故复用的唯一收益是省一次 `put_object`；为数据完整性放弃该微优化。
- **不做** purge 引用计数（更复杂且仍共享物理对象），采用「不共享」从根消除问题。

### 3.2 MAT-002（frontend）
- `retakeMaterialPage` 增加真机分支，复用 `reshootMaterialPage` 逻辑（单一真源）：
  - `isRealMiniProgramUpload() && typeof file === 'string'` → `uploadFile({ url, filePath: file, name: 'file', formData: { page_index: pageNo }, headers })`。
  - 否则保留 `request` 分支（测试/开发）。
- 或让 `RetakeDrawer` 改调 `reshootMaterialPage`；设计采用「修 `retakeMaterialPage`」以保持调用点与既有测试合约。

### 3.3 MAT-003（backend）
- `retry_ocr_pages` 全达标分支，在 `create_snippets` 之后、置 READY 之前：
  ```python
  if self.knowledge_service is not None:
      self.repo.update_version_status(version_id, user_id, ParseStatus.EXTRACTING_KNOWLEDGE.value)
      self.knowledge_service.extract_and_build_knowledge_tree(
          material_id=material_id, version_id=version_id, user_id=user_id,
      )
  ```
  （`extract_and_build_knowledge_tree` 内部已 `delete_knowledge_points_by_version`，与阶段 D 一致。）
- 保持四处一致：阶段 D、重拍达标、`_retry`/`regenerate`（如适用）均走同一知识树重建入口。

### 3.4 MAT-004（cross-layer）
1. 枚举：`MaterialStatus` 增 `RETAKE_REQUIRED = "retake_required"`。
2. 流水线（`:640-653`）OCR 门禁失败：资料状态置 `RETAKE_REQUIRED`（版本仍 FAILED，`failed_stage='ocr_quality_gate'`）。
3. `_resolve_status_filter('retake_required')` → `[MaterialStatus.RETAKE_REQUIRED.value]`；`_calculate_progress_percentage` 对 `RETAKE_REQUIRED` 返回 `0`。
4. 新响应模型 + 路由：
   - `MaterialOCRPageItem`：`page_number:int`、`is_qualified:bool`、`reshoot_count:int`、`unqualified_reason:str|None`。
   - `MaterialOCRPagesResponse`：`material_id:UUID`、`version_id:UUID|None`、`items:list[MaterialOCRPageItem]`。
   - `GET /api/v1/materials/{material_id}/ocr-pages?only_unqualified=false`（默认全量）→ 解析当前激活/最新版本的 `get_ocr_pages`。
   - Service：`list_ocr_pages(*, material_id, user_id, only_unqualified=False) -> tuple[version_id|None, list[MaterialOCRPage]]`（复用 `_resolve_version`/`get_latest_version` 语义）。
5. 重拍闭环：`reshoot_material_page` 后若仍有不合格页 → 资料维持/置 `RETAKE_REQUIRED`；全部达标 → `READY`（现有 `:956-961` 保持，补不合格分支状态）。
6. 前端：
   - `api/material.ts` 增 `fetchMaterialOCRPages(materialId, onlyUnqualified?)`。
   - `detail/index.vue`：状态判断对齐小写（`String(status).toLowerCase() === 'retake_required'` 或统一 `resolveMaterialStatusTag`）；删除硬编码假页面，改为调用新接口把后端页映射为 `PageOCRStatus`（`page_no`←`page_number`，`issue_description`←`unqualified_reason`，`retake_count`←`reshoot_count`）。
   - 列表页「待重拍」筛选在新状态产出后自然返回真实条目（无需改前端筛选值）。

## 4. 影响面与兼容

| 文件 | 变更 |
|---|---|
| `backend/app/services/material.py` | 秒传不再复用键；重拍达标建知识树；OCR 门禁置 RETAKE_REQUIRED；重拍后状态；`_resolve_status_filter` 修复；新增 `list_ocr_pages` |
| `backend/app/models/material.py` | 新增 `MaterialStatus.RETAKE_REQUIRED` |
| `backend/app/api/v1/materials.py` | 新增 `/ocr-pages` 路由 |
| `backend/app/schemas/material.py` | 新增 OCR 页响应模型 |
| `backend/app/repositories/material.py` | 复用既有 `get_ocr_pages`（如缺 latest 版本解析则补） |
| `miniprogram/src/api/material.ts` | `retakeMaterialPage` 真机 multipart；新增 `fetchMaterialOCRPages` |
| `miniprogram/src/pages/.../detail/index.vue` | 移除假页面，改用接口；状态对齐 |
| 测试 | 后端 material/knowledge/api 相关；前端 material api + detail 页 |

- 兼容：新增状态为附加；新路由为附加；`retakeMaterialPage` 非真机行为不变。
- 风险：OCR 门禁失败由 FAILED 改 RETAKE_REQUIRED，可能影响依赖 FAILED 的既有断言/前端 `isFailed`（需同步评估 `statusTag` 与筛选）。

## 5. 验证 & 回归

先红后绿断言：
1. 同哈希两资料 `storage_key` 不同；硬删源后另一资料对象仍可取。
2. 真机 `retakeMaterialPage` 走 `uploadFile` 且 `formData.page_index` 正确。
3. `retry_ocr_pages` 全达标调用知识树重建（spy）且树非空。
4. OCR 门禁失败资料状态 `retake_required`；筛选返回条目；`/ocr-pages` 返回不合格页；前端详情由接口填充。

门禁：后端五项 + 前端三项全绿。

## 6. 回滚点

- 秒传改动为删除复用分支，可回退（但会复现数据完整性问题）。
- 状态新增与路由为附加，回退即移除前端消费。
- 若既有测试强依赖 OCR 失败=FOUND FAILED，先评估再改断言语义（保持用例意图而非削弱）。
