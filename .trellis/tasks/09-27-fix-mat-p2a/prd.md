# 修复 MAT 切片 P2-A（005-011）：大小格式契约、返回类型、知识树重置、半选与分页

## Goal

清零上游审计中 MAT 切片的前端与跨端契约类 P2 缺陷批次 BUG-MAT-005 … BUG-MAT-011，修复文件校验体积不一致、重拍响应类型漂移、知识树切资料残留、知识树父子半选与向上联动缺失、资料列表分页重复追加以及首屏重复请求等问题。对于产品设计收窄类问题（BUG-MAT-006）明确界定并在契约与文档中闭环。

## 需求来源

上游审计 `09-27-read-only-bug-audit`（已归档）`research/slice-MAT.md`（lines 78-182）：

| ID | 级别 | 层 | 审计描述与现象 | 状态评估 |
|---|---|---|---|---|
| BUG-MAT-005 | P2 | cross-layer | 前端统一 20MB 上限，后端按格式区分（png/jpg 10MB，txt/md 5MB），大图在前端放行后被后端 40001 拒绝 | 有效，需修复 |
| BUG-MAT-006 | P2 | cross-layer | 后端支持 pptx/txt/md，前端白名单仅列 pdf/docx/png/jpg/jpeg，契约/功能范围不一致 | 误报/设计意图，需规范记录 |
| BUG-MAT-007 | P2 | cross-layer | `retakeMaterialPage` 返回类型 `RetakePageResponse`（page_no/status）与后端实际响应 `MaterialReshootResponse`（page_index/is_qualified）字段完全不符 | 有效，需修复 |
| BUG-MAT-008 | P2 | frontend | 知识点树页面复用全局 store 但不重置 `selectedKnowledgeIds` / `knowledgeTreeCollapsedMap`，切换资料后旧选中项与折叠态残留 | 有效，需修复 |
| BUG-MAT-009 | P2 | frontend | 勾选级联只做向下全选，无向上回传父节点与半选态（父节点选中后取消部分子节点，父节点仍显示已选） | 有效，需修复 |
| BUG-MAT-010 | P2 | frontend | 触底分页直接追加 `[...listData, ...items]`，无按 id 去重，偏移漂移时列表产生重复项与 key 告警 | 有效，需修复 |
| BUG-MAT-011 | P2 | frontend | 列表页 `onMounted` 与 `onShow` 均调用 `loadData(true)`，首屏存在重复请求，页面切换隐式重置分页 | 有效，需修复 |

## Requirements

### 功能要求

1. **BUG-MAT-005（文件大小校验双端对齐）**：
   - 前端 `miniprogram/src/utils/file.ts` 引入与后端 `backend/app/services/material.py:MAX_FILE_SIZES` 一致的体积上限配置映射表：
     - pdf / docx: 20MB (`20 * 1024 * 1024`)
     - png / jpg / jpeg: 10MB (`10 * 1024 * 1024`)
     - txt / md: 5MB (`5 * 1024 * 1024`)
   - `validateMaterialFile(name, size)` 根据文件后缀动态匹配上限；若后缀未知则回退至 20MB 兜底。
   - 报错信息精确提示格式与对应上限（例如：“图片体积过大，请上传小于 10MB 的文件”或按统一标准提示）。

2. **BUG-MAT-006（允许格式收窄与契约对齐）**：
   - 经实测与业务架构审计，微信小程序端支持的上传格式由产品设计定义为 `pdf, docx, png, jpg, jpeg`（由于移动端选文交互及预览能力限制，未开放 pptx/txt/md）。
   - 保留小程序端白名单，在 `miniprogram/src/utils/file.ts` 注释明确与后端 `MaterialDocType` 的子集关系。
   - 记录为**已失效/非缺陷（设计收窄）**，代码保持受控收窄，补全单元测试断言。

3. **BUG-MAT-007（单页重拍响应类型契约统一）**：
   - 废除并安全废弃 `RetakePageResponse`，统一 `retakeMaterialPage` 返回类型为 `MaterialReshootResponse`（`page_index`, `is_qualified`, `reshoot_count`, `parse_status`, `unqualified_reason`）。
   - 保持向后兼容性：在 `MaterialReshootResponse` 或别名声明中标记字段映射关系，`miniprogram/src/api/material.ts` 的泛型由 `RetakePageResponse` 切换为 `MaterialReshootResponse`。
   - 更新消费端与测试夹具中 mock 数据的字段断言（`page_index` 替代 `page_no` 等）。

4. **BUG-MAT-008（知识树切资料状态重置）**：
   - 在 `miniprogram/src/stores/materialStore.ts` 暴露细粒度清空方法 `clearKnowledgeState()`（重置 `currentKnowledgeTree`, `selectedKnowledgeIds`, `knowledgeTreeCollapsedMap`）。
   - 在 `subpackages/material/pages/knowledge-tree/index.vue` 进入新资料时（`initData` 与 `loadKnowledgeTree` 开始前），先重置上一份资料残留的勾选与折叠状态，确保已选考点与覆盖率不被污染。

5. **BUG-MAT-009（知识树父子级联与半选/全选推导）**：
   - 在 `subpackages/material/utils/tree.ts` 引入基于当前树结构和 `selectedKnowledgeIds` 的节点选中状态计算函数 `getNodeCheckState(node, selectedIdSet)`，返回 `'checked' | 'indeterminate' | 'unchecked'`。
   - 级联反向联动：当子节点勾选改变时，父节点复选框能正确渲染半选（indeterminate，如横杠图标/样式）或全选（checked）。
   - 用户点击半选/未选父节点时，全选所有子孙；点击全选父节点时，取消全选所有子孙。
   - `KnowledgeTreeNode.vue` 界面增加半选样式，支持中立横杠状态展示。

6. **BUG-MAT-010（列表触底分页去重）**：
   - 在 `subpackages/material/pages/list/index.vue` 的 `loadData(false)` 追加逻辑中，参考 `questions/index.vue:105-106` 模式，使用 `existingIds = new Set(listData.value.map(item => item.id))` 对新页数据进行 ID 去重过滤后追加。
   - 杜绝因并发现象或数据插入/删除漂移导致的重复 key 渲染警告与列表数据重复。

7. **BUG-MAT-011（列表首屏生命周期去重）**：
   - 重构 `subpackages/material/pages/list/index.vue` 中 `onMounted` 与 `onShow` 的加载逻辑。
   - 设立 `hasFirstLoaded` 标记或首屏加载锁：`onMounted` 负责首屏数据初始化；`onShow` 仅在非首次进入（如从详情页/上传成功返回）且页面非加载中时按需刷新，避免首屏时 `onMounted` 与 `onShow` 近乎同时触发导致的重复请求与分页覆盖。

### 约束
- 契约权威：后端 `backend/app/schemas/material.py`（`MaterialReshootResponse`）与 `backend/app/services/material.py:MAX_FILE_SIZES`。
- 新增字段一律附加可选，默认值保持旧行为。
- 无 `any`；守分层与前端 ESLint / TypeScript 类型检查；测试夹具字段名逐字取自后端。
- 不弱化既有测试；前后端门禁全绿。

### 不在范围内
- MAT 其余 P2（`BUG-MAT-012…017`）由后续批次 P2-B 覆盖。
- 后端 OCR 质检算法与大模型知识抽取核心链路改造。

## Acceptance Criteria

- [ ] **MAT-005**：`validateMaterialFile('photo.jpg', 15 * 1024 * 1024)` 返回 `valid: false` 并提示图片过大；`validateMaterialFile('doc.pdf', 15 * 1024 * 1024)` 返回 `valid: true`。
- [ ] **MAT-006**：记录为“已确认设计收窄”，前端支持格式维持受控范围，补全测试明确预期。
- [ ] **MAT-007**：`retakeMaterialPage` 返回类型变更为 `Promise<ApiResponse<MaterialReshootResponse>>`，相关单元测试与组件不再引用过期的 `RetakePageResponse`。
- [ ] **MAT-008**：切换资料 ID 时，知识点树页面清空上一份资料的 `selectedKnowledgeIds` 和 `knowledgeTreeCollapsedMap`，计数与覆盖率重新计算归零。
- [ ] **MAT-009**：父节点在其部分子节点被勾选时，渲染 `indeterminate`（半选）视觉状态；点击半选节点可将其及所有子节点全选；取消所有子节点时父节点自动变更为未选。
- [ ] **MAT-010**：触底分页追加时遇到相同 ID 的项自动去重，不出现重复 key 告警。
- [ ] **MAT-011**：页面初始化首次载入时只向后端发出 1 次列表查询请求，从下级页面返回时能正常同步最新数据。
- [ ] 前端测试门禁通过：`pnpm run lint`、`pnpm run type-check`、`pnpm run test:unit` 无报错。

## Notes

- 上游参考：`archive/2026-09/09-27-read-only-bug-audit/research/slice-MAT.md`。
- BUG-MAT-006 确认为小程序端有意收窄支持格式（移动端针对性限制），代码层面明确规范化即可，不强制放开未适配格式。
