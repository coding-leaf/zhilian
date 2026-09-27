# 只读 Bug 审计 · 切片 MAT（素材 / 知识点树）

- **Query**: 前后端同片只读审计 MAT 切片
- **Scope**: mixed（backend + frontend + cross-layer）
- **Date**: 2026-09-27
- **依据**: `prd.md`、`design.md` §3 切片表 / §4 分级 / §5 证据标准 / §8 ledger schema
- **工具链基线**: 见 `research/toolchain-baseline.md`。后端 5 项、前端 3 项全绿（`1130 passed` / `452 passed`），因此本片缺陷均来自**静态审阅 + 跨层核对**，不含工具链直接暴露项。
- **证据强度图例**: `实测`（命令/接口实测） > `测试`（单测/组件测试可复现） > `推理`（静态推理链）。

> 范围声明：`subpackages/material/components/Question*`、`pages/questions`、`api/question` 属 QGEN 切片，本文件不重复记录；仅在 MAT 页面消费处交叉引用契约（`QuestionConfigDrawer` 由 `knowledge-tree` 页面挂载）。

---

## 一、功能性 Bug 清单

### BUG-MAT-001

| 字段 | 内容 |
|---|---|
| ID | BUG-MAT-001 |
| 级别 | P1 |
| 切片 | MAT |
| 层 | backend |
| 位置 | `backend/app/services/material.py:454-469`（复用哈希命中版本的 storage_key）；`backend/app/services/material.py:1440-1463`（硬删按本资料 versions 收集并 purge）；`backend/app/repositories/material.py:360-383`（`find_version_by_hash` 跨资料命中） |
| 现象 | 内容哈希秒传时，新建版本直接复用**另一份资料**的 `storage_key`；当那份源资料被硬删除时，共享对象被 purge，当前资料的版本指向已不存在的对象。 |
| 证据/复现 | 静态推理链：① A 上传文件 → `version_A.storage_key = users/A/materials/A/v1/<hash>...`；② B 上传**相同字节** → `find_version_by_hash` 跨资料命中 A 的 READY 版本，`storage_key = existing_ver.storage_key`，跳过 `put_object`（material.py:454-463）；③ `hard_delete_material(A)` 遍历 A 的 versions，将 `users/A/.../<hash>` 加入 `keys_to_purge` 并 `delete_object`（material.py:1447-1463）；④ B 的资料仍引用该 key，后续 `parse_material_pipeline` 的 `storage.get_object` 抛 `StorageNotFoundError` → B 解析失败。 |
| 影响 | 数据完整性 / 可解析性：秒传资料在源资料硬删后无法再解析，且用户无感知（列表仍显示 B）。 |
| 修复方向 | 秒传命中时不复用物理 key，改为按新 material_id 复制/重建对象路径；或 purge 前校验该 key 是否被其他 Material 的版本引用。 |
| 证据强度 | 推理 |

### BUG-MAT-002

| 字段 | 内容 |
|---|---|
| ID | BUG-MAT-002 |
| 级别 | P1 |
| 切片 | MAT |
| 层 | cross-layer |
| 位置 | 前端 `miniprogram/src/subpackages/material/components/RetakeDrawer.vue:131`；`miniprogram/src/api/material.ts:196-212`；后端 `backend/app/api/v1/materials.py:421-457` |
| 现象 | 重拍接口在真机走 `request`（JSON body）而非 `uploadFile`（multipart），后端却以 `File(...) + Form(...)` 解析，真机重拍请求必然 422/400。 |
| 证据/复现 | 静态推理链：`RetakeDrawer.handleRetake → submitRetake → retakeMaterialPage(...)`；`retakeMaterialPage` 使用 `request({url:'.../reshoot', method:'POST', data:{page_index, file}})`, 无 `uploadFile` 分支（material.ts:196-212）。对照同文件 `reshootMaterialPage` 别名在真机分支使用 `uploadFile`（material.ts:253-267），而 `uploadMaterial` 亦有 `isRealMiniProgramUpload()` 分支（material.ts:166-177）。后端签名为 `page_index: Annotated[int, Form(ge=1)]`、`file: Annotated[UploadFile, File()]`（materials.py:427-433）。 |
| 影响 | 核心功能中断：真机端「单页重新拍摄」100% 失败；单测仅 mock `request`，无法覆盖（`tests/unit/components/RetakeDrawer.spec.ts:148`）。 |
| 修复方向 | `retakeMaterialPage` 复用 `reshootMaterialPage` 的真机 `uploadFile` 分支，或让 RetakeDrawer 直接调用 `reshootMaterialPage` 别名。 |
| 证据强度 | 推理 |

### BUG-MAT-003

| 字段 | 内容 |
|---|---|
| ID | BUG-MAT-003 |
| 级别 | P1 |
| 切片 | MAT |
| 层 | backend |
| 位置 | `backend/app/services/material.py:913-964`（重拍全达标后重建 snippets 并置 READY；未调用 `knowledge_service.extract_and_build_knowledge_tree`，也未清理旧 knowledge_points） |
| 现象 | 图片资料经逐页重拍最终全部达标后，版本被置为 READY 且切片被重建，但知识树既未重建、旧知识点也未清除，导致 READY 资料知识树为空或指向已被删除切片。 |
| 证据/复现 | 静态推理链：`retry_ocr_pages` 在 `all_pages qualified` 分支执行 `delete_snippets_by_version` + `create_snippets` + `update_version_status(READY)`（material.py:927-961），全程未调用 `knowledge_service`。而正常流水线在建 slices 后于阶段 D 调用 `extract_and_build_knowledge_tree`（material.py:709-719）。旧 `KnowledgePoint`/`KnowledgePointSnippet` 未删除；`delete_snippets_by_version` 的 DB 级联会移除 `knowledge_point_snippets`，留下无来源的知识点。 |
| 影响 | 功能错误：重拍完成后 `/knowledge-tree` 返回空树或陈旧树，用户无法出题。 |
| 修复方向 | 重拍达标分支复用阶段 D 的 `extract_and_build_knowledge_tree`，并在重建前 `delete_knowledge_points_by_version`。 |
| 证据强度 | 推理 |

### BUG-MAT-004

| 字段 | 内容 |
|---|---|
| ID | BUG-MAT-004 |
| 级别 | P1 |
| 切片 | MAT |
| 层 | cross-layer |
| 位置 | 后端 `backend/app/models/material.py:31-38`（`MaterialStatus` 仅 pending/parsing/ready/failed）；`backend/app/services/material.py:1013-1015`（`retake_required` 返回 `[]`）；`backend/app/api/v1/materials.py:208-210`（将 `retake_required` 列为合法筛选值）；后端无 OCR 页查询路由（`backend/app/api/v1/materials.py` 全量路由）；前端 `miniprogram/src/types/material.ts:11`、`miniprogram/src/utils/copywriting.ts:120-121`、`miniprogram/src/subpackages/material/pages/list/index.vue:73`、`miniprogram/src/subpackages/material/pages/detail/index.vue:165-168,200-211` |
| 现象 | 前端存在 `retake_required` 状态、待重拍筛选 tab、重拍抽屉与横幅，但后端从不产生该状态，也没有返回不合格页列表的接口，重拍入口整条链路不可达。 |
| 证据/复现 | ① `MaterialStatus` 无 `retake_required`（models/material.py:31-38）；② `_resolve_status_filter('retake_required')` 返回 `[]` → `Material.status.in_([])` 恒空；③ 列表 tab「待重拍」筛选（list/index.vue:73）因此永远为空；④ 详情页 `isRetakeRequired` 依赖后端 `RETAKE_REQUIRED` 或 `unqualifiedPages`，而后者仅在后端状态为 `RETAKE_REQUIRED` 时被硬编码填入一条假数据（detail/index.vue:200-211）；⑤ grep `backend/app/api` 无 `ocr_pages`/`unqualified` 查询路由（仅 materials.py:471 响应字段）。 |
| 影响 | 功能性错误 + 数据不可达：OCR 质检失败资料的「重拍」能力在前后端契约上断裂，用户无法恢复解析。 |
| 修复方向 | 后端补充待重拍状态/不合格页列表接口并在状态机中产出；或前端明确降级并移除不可达入口。 |
| 证据强度 | 推理（后端无路由为 `实测` grep 确认） |

---

### BUG-MAT-005

| 字段 | 内容 |
|---|---|
| ID | BUG-MAT-005 |
| 级别 | P2 |
| 切片 | MAT |
| 层 | cross-layer |
| 位置 | 前端 `miniprogram/src/utils/file.ts:12-13`；后端 `backend/app/services/material.py:68-77` |
| 现象 | 前端统一按 20MB 上限校验所有格式，后端按格式区分：png/jpg/jpeg 10MB、txt/md 5MB。 |
| 证据/复现 | 前端 `MAX_FILE_SIZE = 20*1024*1024` 且不分格式（utils/file.ts:12-13）；后端 `MAX_FILE_SIZES` png/jpg/jpeg=10MB、txt/md=5MB（material.py:68-77）。一张 15MB JPG 通过前端校验后被后端 `MaterialInvalidError(40001)` 拒绝。 |
| 影响 | 用户体验错误：可选中文件上传后失败；错误被 MaterialUpload 泛化为「上传失败，请重试」（MaterialUpload.vue:162-165）。 |
| 修复方向 | 前端按格式维护与后端一致的 `MAX_FILE_SIZES`。 |
| 证据强度 | 推理 |

### BUG-MAT-006

| 字段 | 内容 |
|---|---|
| ID | BUG-MAT-006 |
| 级别 | P2 |
| 切片 | MAT |
| 层 | cross-layer |
| 位置 | 前端 `miniprogram/src/utils/file.ts:12`；`miniprogram/src/components/common/MaterialUpload.vue:106`；后端 `backend/app/services/material.py:58-77`；`backend/app/models/material.py:60-68` |
| 现象 | 后端支持 pptx/txt/md（魔数与大小表 + `MaterialDocType`），前端 `ALLOWED_EXTENSIONS` 与微信 `chooseMessageFile.extension` 仅列 pdf/docx/png/jpg/jpeg。 |
| 证据/复现 | 前端白名单 `['.pdf','.docx','.png','.jpg','.jpeg']`（file.ts:12、MaterialUpload.vue:106）；后端 `MAX_FILE_SIZES` 含 pptx/txt/md（material.py:68-77），`MaterialDocType` 含 PPTX/MARKDOWN/TXT（models/material.py:60-68）。 |
| 影响 | 契约不一致：后端可接受格式在前端被静默拒绝（若为产品有意收窄则属设计差异，需确认）。 |
| 修复方向 | 对齐双端允许格式集合，或在后端移除未开放格式。 |
| 证据强度 | 推理 |

### BUG-MAT-007

| 字段 | 内容 |
|---|---|
| ID | BUG-MAT-007 |
| 级别 | P2 |
| 切片 | MAT |
| 层 | cross-layer |
| 位置 | 前端 `miniprogram/src/types/material.ts:93-98`（`RetakePageResponse`）与 `:117-125`（`MaterialReshootResponse`）；`miniprogram/src/api/material.ts:201-211`；后端 `backend/app/schemas/material.py:164-175` |
| 现象 | `retakeMaterialPage` 声明的返回类型 `RetakePageResponse`（`page_no/status/message`）与后端实际响应 `MaterialReshootResponse`（`page_index/is_qualified/reshoot_count/parse_status/unqualified_reason`）字段完全不符。 |
| 证据/复现 | 后端响应模型见 schemas/material.py:164-175；前端 `retakeMaterialPage` 返回 `Promise<ApiResponse<RetakePageResponse>>`（api/material.ts:196-212），而 `RetakePageResponse` 字段为 `{material_id,page_no,status,message}`（types/material.ts:93-98）。当前 RetakeDrawer 只透传 `res.data`、未读字段，故未运行时崩，但类型契约错误。 |
| 影响 | 类型漏洞 / 契约不符；后续任何按 `page_no`/`status` 消费的代码将拿到 `undefined`。 |
| 修复方向 | 统一 `retakeMaterialPage` 返回类型为 `MaterialReshootResponse` 并删除 `RetakePageResponse`。 |
| 证据强度 | 推理 |

### BUG-MAT-008

| 字段 | 内容 |
|---|---|
| ID | BUG-MAT-008 |
| 级别 | P2 |
| 切片 | MAT |
| 层 | frontend |
| 位置 | `miniprogram/src/stores/materialStore.ts:88-90,134-141`；`miniprogram/src/subpackages/material/pages/knowledge-tree/index.vue:136-150,197-209` |
| 现象 | 知识点树页面复用全局 store 但不重置 `selectedKnowledgeIds` / `knowledgeTreeCollapsedMap`；切换资料后旧选中项与折叠态残留。 |
| 证据/复现 | `setKnowledgeTree` 只覆盖 `currentKnowledgeTree`（materialStore.ts:88-90）；`reset()` 才会清空选中/折叠，但 `knowledge-tree/index.vue` 的 `loadKnowledgeTree/initData` 未调用 `reset`/`clearKnowledgeSelection`（index.vue:136-150、197-209）。同 store 跨页面共享（`stores/index.ts` 单例）。 |
| 影响 | 状态未重置：覆盖率与「已选考点」计数包含上一份资料的 ID，出题参数污染。 |
| 修复方向 | 加载新资料知识树前重置选中与折叠态（或按 materialId 分区存储）。 |
| 证据强度 | 推理 |

### BUG-MAT-009

| 字段 | 内容 |
|---|---|
| ID | BUG-MAT-009 |
| 级别 | P2 |
| 切片 | MAT |
| 层 | frontend |
| 位置 | `miniprogram/src/subpackages/material/components/KnowledgeTreeNode.vue:77-93`；`miniprogram/src/stores/materialStore.ts:96-117`；`miniprogram/src/subpackages/material/utils/tree.ts:80-95` |
| 现象 | 勾选级联只做「向下全选/全不选」，不向上回传父节点，也无半选态：父节点已选中后取消部分子节点，父节点复选框仍显示已选。 |
| 证据/复现 | `isSelected` 仅判断自身 id（KnowledgeTreeNode.vue:77-79）；`handleToggleSelect` 用 `collectNodeAndDescendantIds` 对子树统一增删（:85-93 → tree.ts:80-95 → materialStore.ts:105-117），未触碰祖先；`selectedKnowledgeIds` 为扁平数组无父子推导（materialStore.ts:19）。 |
| 影响 | 状态不一致：父节点视觉选中但子树不全选；全选计数与语义不符。 |
| 修复方向 | 引入父子半选推导（由选中集合反推祖先 checked/indeterminate）。 |
| 证据强度 | 推理 |

### BUG-MAT-010

| 字段 | 内容 |
|---|---|
| ID | BUG-MAT-010 |
| 级别 | P2 |
| 切片 | MAT |
| 层 | frontend |
| 位置 | `miniprogram/src/subpackages/material/pages/list/index.vue:190-194,279-284` |
| 现象 | 触底分页直接追加，无按 id 去重；上传/删除导致偏移漂移时同一资料可重复出现。 |
| 证据/复现 | `loadData(false)` 执行 `listData.value = [...listData.value, ...items]`（index.vue:193）；`onReachBottom` 仅以 `listData.length < total` 判断（:279-284）。对比 `pages/questions/index.vue:105-106` 使用了 `existingIds` 去重，证明去重为可预期做法。 |
| 影响 | 列表重复项，`MaterialCard` 的 `:key="item.id"` 触发 Vue 重复 key 警告与渲染异常。 |
| 修复方向 | 追加时按 id 去重（同 questions 页模式）。 |
| 证据强度 | 推理 |

### BUG-MAT-011

| 字段 | 内容 |
|---|---|
| ID | BUG-MAT-011 |
| 级别 | P2 |
| 切片 | MAT |
| 层 | frontend |
| 位置 | `miniprogram/src/subpackages/material/pages/list/index.vue:286-306` |
| 现象 | 列表页 `onMounted` 与 `onShow` 均调用 `loadData(true)`，首屏存在重复请求；返回页面时 `onShow` 亦强制整表重载。 |
| 证据/复现 | `onShow(() => { isPageVisible=true; void loadData(true); })`（:286-289）与 `onMounted(() => { ... void loadData(true); })`（:303-306）并存。`loadData` 仅有 `loading` 守卫（:175-176），异步窗口内二次调用会被吞，但同步完成后仍可能重复请求/重置分页。 |
| 影响 | 冗余网络与状态抖动；分页被隐式重置。 |
| 修复方向 | 首屏仅由单一生命周期触发，`onShow` 仅在 return 场景刷新。 |
| 证据强度 | 推理 |

### BUG-MAT-012

| 字段 | 内容 |
|---|---|
| ID | BUG-MAT-012 |
| 级别 | P2 |
| 切片 | MAT |
| 层 | frontend |
| 位置 | `miniprogram/src/components/common/MaterialUpload.vue:122-143` |
| 现象 | 相册/拍照选取时若 `res.tempFiles` 未提供 size，则以常量 1024 兜底，导致超大图片绕过 `validateMaterialFile` 的体积校验。 |
| 证据/复现 | `const size = files?.[0]?.size || 1024;`（MaterialUpload.vue:131）后拼装 `SelectedFileInfo` 并走 `handleFilePicked → validateMaterialFile(name,size)`（:91-99）。真实大图 size 缺失时按 1KB 校验通过。 |
| 影响 | 边界值错误：超大文件上传到后端才被拒，浪费流量。 |
| 修复方向 | size 缺失时不放行，或调用 `uni.getFileInfo` 补全后再校验。 |
| 证据强度 | 推理 |

### BUG-MAT-013

| 字段 | 内容 |
|---|---|
| ID | BUG-MAT-013 |
| 级别 | P2 |
| 切片 | MAT |
| 层 | cross-layer |
| 位置 | 前端 `miniprogram/src/subpackages/material/components/MaterialCard.vue:100-104`；`miniprogram/src/components/home/RecentLearningSection.vue:154-165`；后端 `backend/app/schemas/material.py:89-108`（`MaterialListItem` 无对应字段）；`backend/app/api/v1/materials.py:221-241` |
| 现象 | 前端读取 `key_points_count`/`points_count`/`page_count`，后端列表与详情 DTO 从不返回这些字段，考点/页数展示恒为兜底文案。 |
| 证据/复现 | MaterialCard.vue:100-104 与 RecentLearningSection.vue:154-165 读取 `raw.key_points_count ?? raw.points_count`、`page_count ?? pages_count`；后端 `MaterialListItem`/`MaterialDetailResponse` 字段集不含这些键（schemas/material.py:66-108），`list_materials` 响应构造亦未注入（materials.py:221-241）。 |
| 影响 | 契约不一致：前端展示能力长期失效（「待提取考点」），易被误判为解析失败。 |
| 修复方向 | 后端补 `key_points_count` 等聚合字段，或前端移除死字段读取。 |
| 证据强度 | 推理 |

### BUG-MAT-014

| 字段 | 内容 |
|---|---|
| ID | BUG-MAT-014 |
| 级别 | P2 |
| 切片 | MAT |
| 层 | cross-layer |
| 位置 | 前端 `miniprogram/src/api/material.ts:179-184`；后端 `backend/app/api/v1/materials.py:109-118,114-115` |
| 现象 | 非小程序（H5/测试）`uploadMaterial` 分支只发送 `{ file, title }`，缺失后端 `Form(source_type)` 字段。 |
| 证据/复现 | `request({url:'/api/v1/materials/upload', method:'POST', data:{file,title}})`（material.ts:179-184）；后端 `source_type` 为 `Form` 且默认 `"local"`（materials.py:115）。因有默认值不报错，但调用方传入的 `wechat` 在非小程序分支丢失。 |
| 影响 | 契约不一致：H5/测试分支来源渠道恒为 local。 |
| 修复方向 | 非小程序分支同时提交 `source_type`。 |
| 证据强度 | 推理 |

### BUG-MAT-015

| 字段 | 内容 |
|---|---|
| ID | BUG-MAT-015 |
| 级别 | P2 |
| 切片 | MAT |
| 层 | backend |
| 位置 | `backend/app/services/knowledge.py:124-126`（`n<=1` 直接返回原列表，未去重 `source_snippet_indices`）；`backend/app/services/knowledge.py:495-507`（按每个 index 建关联）；`backend/app/models/knowledge.py:169-174`（`uq_knowledge_point_snippets_kp_snippet`） |
| 现象 | 当仅 1 个候选知识点且其 `source_snippet_indices` 含重复值时，去重函数短路返回，关联批量插入触发唯一约束冲突 → 事务回滚、抽取失败。 |
| 证据/复现 | `deduplicate_candidate_points` 在 `n<=1` 时 `return list(items)`，不做 set 归一（knowledge.py:124-126）；后续 `relations_to_save` 对每个 index 无去重 append（:497-507），命中 `UniqueConstraint(knowledge_point_id, snippet_id)`（models/knowledge.py:169-174）。`n>1` 路径因用 `set` 归一而不受影响（:146-149）。 |
| 影响 | 边界值错误：LLM 返回单候选且重复 index 时整批抽取失败（版本置 FAILED）。 |
| 修复方向 | 在 `n<=1` 早返回前对 `source_snippet_indices` 去重，或在建关联时按 set 去重。 |
| 证据强度 | 推理 |

### BUG-MAT-016

| 字段 | 内容 |
|---|---|
| ID | BUG-MAT-016 |
| 级别 | P2 |
| 切片 | MAT |
| 层 | backend |
| 位置 | `backend/app/services/knowledge.py:208-209`（`temp_parents` / `temp_to_uuid` 以 temp_id 为键）；`:229-245`（按 temp_id 取 UUID 建实体） |
| 现象 | 若 LLM 输出重复 `temp_id`，字典推导会坍缩：父映射被覆盖、多个 item 共享同一 UUID，导致知识点主键冲突或父子关系错位。 |
| 证据/复现 | `temp_parents = {it.temp_id: it.parent_temp_id for it in items}` 与 `temp_to_uuid = {it.temp_id: uuid.uuid4() for it in items}`（knowledge.py:208-209）；`ExtractedKnowledgeItem.temp_id` 仅 `str` 无唯一性约束（:57）。重复 temp_id 时循环创建两个相同 `id` 的 `KnowledgePoint`（:233-244）。 |
| 影响 | 边界值错误/崩溃：PK 冲突或静默丢失节点。 |
| 修复方向 | 构建前校验 temp_id 唯一性，重复时重新编号或丢弃。 |
| 证据强度 | 推理 |

### BUG-MAT-017

| 字段 | 内容 |
|---|---|
| ID | BUG-MAT-017 |
| 级别 | P2 |
| 切片 | MAT |
| 层 | backend |
| 位置 | `backend/app/services/material.py:1446-1463`；`backend/app/services/material.py:882-886`（每次重拍生成新 `page_{n}_reshoot_{k}.png` 并覆盖 `image_storage_key`） |
| 现象 | 硬删除只收集版本当前 `image_storage_key`，历次重拍产生的旧图片对象键已丢失，无法清理，形成对象存储永久泄漏。 |
| 证据/复现 | 硬删遍历 `ver.ocr_pages` 仅取 `page.image_storage_key`（material.py:1453-1455）；重拍每次写入新 key 并用 `update_ocr_page(image_storage_key=新key)` 覆盖（:882-898），旧 key 不再被任何记录引用。`raw_text.txt` 同理仅保留最新。 |
| 影响 | 存储泄漏 / 成本；长期累积无用对象。 |
| 修复方向 | 重拍时记录历史 key（或按前缀列举 `pages/` 目录批量清理）。 |
| 证据强度 | 推理 |

### BUG-MAT-018

| 字段 | 内容 |
|---|---|
| ID | BUG-MAT-018 |
| 级别 | P2 |
| 切片 | MAT |
| 层 | backend |
| 位置 | `backend/app/api/v1/materials.py:136-144`（先 `await file.read()` 全量读入再交给 service 做大小门禁）；`backend/app/services/material.py:414-431`（大小校验在读入之后） |
| 现象 | 上传端点在读取完整请求体后才执行大小校验，超大文件会被完整缓冲进进程内存，存在内存耗尽（DoS）风险。 |
| 证据/复现 | `content = await file.read()`（materials.py:136）先于 `import_material_file → create_material` 的 `len(file_content) > max_allowed_size` 判断（material.py:427-431）。未发现请求体大小中间件（grep 无相关限制）。 |
| 影响 | 安全/可靠性：恶意大文件可造成内存放大；NFR-22 仅约束切片数不约束上传。 |
| 修复方向 | 读取前校验 `Content-Length`/分块读取并在超限时中断。 |
| 证据强度 | 推理 |

---

## 二、疑似（SR，不计级）

| ID | 位置 | 现象 | 说明 |
|---|---|---|---|
| BUG-MAT-SR01 | `miniprogram/src/components/common/MaterialUpload.vue:101-120,122-143` | 微信 `wx.chooseMessageFile` / `uni.chooseImage` 在真机的 `tempFiles.size`、文件名后缀行为与开发者工具不一致，导致校验分支差异 | 真机专属，静态与组件测试无法确证；属 design.md §4 疑似项规则 |
| BUG-MAT-SR02 | `miniprogram/src/subpackages/material/components/KnowledgeTreeNode.vue:5-19,141-160` | 自定义复选框与折叠箭头的点击热区/层级缩进在真机渲染表现 | 依赖 wot-design-uni 组件渲染，`toolchain-baseline.md` 已记录测试环境 `wd-*` 未注册噪声 |

---

## 三、环境受限（ENV，不计级）

| ID | 位置 | 说明 |
|---|---|---|
| BUG-MAT-ENV01 | `toolchain-baseline.md` 已记录 | vitest(happy-dom) 中 `wd-icon/wd-loading/wd-tag`、`scroll-view` 未注册为测试环境噪声；Sass `legacy-js-api` 弃用属版本提示。均非产品 bug。 |

---

## 四、非功能性（不在本文件计级，转 `code-smells.md`）

仅记录线索，不计入本文件计数：

- `miniprogram/src/api/material.ts:64-69`：`fetchMaterialStatus` 与 `fetchMaterialDetail` 实现完全相同（重复工具）。
- `components/common/MaterialUpload.vue:55-57` 的 re-export 与 `subpackages/material/utils/file.ts` 的 `export * from '@/utils/file'` 转发（shim 模式，per design.md §7 已知非重复）。
- `backend/app/services/material.py` 中多处 `**kwargs` 兼容参数与 `_kw` 别名（`soft_delete_material` 1383-1403 等）。

---

## 五、跨层契约核对结论（MAT 片）

| 契约面 | 结论 | 关联条目 |
|---|---|---|
| 上传端点 `POST /materials/upload` 字段 | ⚠️ 不一致：`source_type`（非小程序分支缺失）；格式/大小门禁集合不一致 | BUG-MAT-005/006/014 |
| 重拍端点 `POST /materials/{id}/reshoot` | ❌ 不一致：前端 JSON vs 后端 multipart；响应 DTO 类型不符 | BUG-MAT-002/007 |
| 待重拍状态与页面查询 | ❌ 断裂：后端无 `retake_required` 状态、无 OCR 页查询接口 | BUG-MAT-004 |
| 资料列表/详情 DTO ↔ `MaterialItem` | ✅ 字段（`parse_status`/`progress_percentage`/`versions_count`/`current_version_id`）一致；⚠️ 前端额外读 `key_points_count` 等无后端来源 | BUG-MAT-013 |
| 知识树 DTO ↔ `KnowledgeTreeResponse` | ✅ 结构一致（`nodes` 递归 + `version_id`）；⚠️ 无版本归属校验（非漏洞，仅提示） | 无 |
| 状态枚举 ↔ 前端文案映射 | ⚠️ 前端含 `retake_required`/`COMPLETED` 分支，后端仅 4 态 | BUG-MAT-004 |
| 删除端点 | ✅ 软/硬路径与响应基本一致 | 无 |

---

## 六、计数小结

| 级别 | 数量 | 备注 |
|---|---|---|
| P0 | 0 | 本片未发现确定性核心中断/数据丢失的 P0 |
| P1 | 4 | BUG-MAT-001 ~ 004 |
| P2 | 14 | BUG-MAT-005 ~ 018 |
| 合计（功能性） | 18 | — |
| 疑似(SR) | 2 | 不计级 |
| 环境受限(ENV) | 1 | 不计级 |
| 非功能性(SMELL) | 3 | 不计入本文件计数，见 `code-smells.md` |

**按层分布**：backend 5（001/003/015/016/017/018 中 001、003、015、016、017、018 = 6，其中 018 backend）；cross-layer 6（002/004/005/006/007/013/014 = 7）；frontend 5（008/009/010/011/012）。合计 18。

> 精确计数（按“层”主属）：backend = 001,003,015,016,017,018 = 6；cross-layer = 002,004,005,006,007,013,014 = 7；frontend = 008,009,010,011,012 = 5。合计 18。

**证据强度分布**：推理 18；测试 0；实测 0（工具链基线全绿，无由门禁直接暴露的 MAT 项；BUG-MAT-004 的“后端无路由”辅以 grep 实测）。
