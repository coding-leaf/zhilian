# 修复 MAT 切片 P1：重拍链路与秒传数据完整性

## Goal

修复审计清单 MAT 切片 4 条 P1：秒传跨资料复用存储键导致源删后数据损坏、真机重拍走错传输协议、逐页重拍达标后未重建知识树、以及「待重拍」状态链路整体不可达。

## 需求来源

上游审计 `09-27-read-only-bug-audit`（已归档）`research/slice-MAT.md`：

| ID | 级别 | 层 | 一句话 |
|---|---|---|---|
| BUG-MAT-001 | P1 | backend | 秒传命中复用**他资料** `storage_key`，源资料硬删连带 purge → 当前资料指向已删对象 |
| BUG-MAT-002 | P1 | cross-layer | `retakeMaterialPage` 用 JSON `request`，后端要 multipart `File+Form` → 真机重拍必失败 |
| BUG-MAT-003 | P1 | backend | 逐页重拍全部达标后仅重建切片置 READY，未重建知识树/清理旧知识点 → 知识树空或陈旧 |
| BUG-MAT-004 | P1 | cross-layer | 后端从不产生 `retake_required` 状态、无不合格页查询接口 → 前端待重拍入口整条不可达 |

## Requirements

### 功能要求
1. **MAT-001**：`create_material` 不再复用其它资料的物理 `storage_key`；秒传命中时仍为新资料写入**自有对象副本**（内容哈希用于跳过重复解析/记录，不作为跨资料共享物理对象）。确保 `hard_delete_material` 只删除本资料独占对象。
2. **MAT-002**：`retakeMaterialPage` 在真机端必须走 `uploadFile`（multipart，`page_index` 作为 form 字段），与后端 `File+Form` 契约一致；非真机（测试/开发）保持现有 `request` 分支以不破坏既有单测。
3. **MAT-003**：`retry_ocr_pages` 全部达标分支在重建切片后，必须清理该版本旧知识点并重建知识树（复用阶段 D 的 `knowledge_service.extract_and_build_knowledge_tree`），再置 READY/激活。
4. **MAT-004**：后端产生可用的 `retake_required` 状态与「不合格页列表」查询接口，前端据此展示真实待重拍页面并驱动重拍：
   - 新增 `MaterialStatus.RETAKE_REQUIRED`；OCR 质检门禁失败时资料状态置 `RETAKE_REQUIRED`（版本 `parse_status=FAILED`，`failed_stage='ocr_quality_gate'`）。
   - `_resolve_status_filter('retake_required')` 返回 `[RETAKE_REQUIRED]`（不再恒空）。
   - 新增 `GET /api/v1/materials/{material_id}/ocr-pages`（可选 `only_unqualified`）返回页码、是否达标、重拍次数、原因。
   - 重拍后若仍有不合格页，资料维持 `RETAKE_REQUIRED`；全部达标转 `READY`。
   - 前端 `detail/index.vue` 移除硬编码假页面，改调真实接口；状态判断与后端小写枚举对齐。

### 约束
- 契约权威：后端响应模型与状态枚举为准；字段命名/状态值前后端对齐（见 `.trellis/spec/backend/quality-guidelines.md` 场景「Backend↔Frontend Response Field-Name Contract Pinning」）。
- 不混入其它切片修复；不弱化既有测试；无 `any`。
- 新增状态枚举成员为附加项（DB 列为字符串，无需迁移）。

### 不在范围内
- MAT 其余 P2（`BUG-MAT-005…018`）→ 后续 P2 批次。
- OCR 质检算法本身的阈值/策略。

## Acceptance Criteria

- [ ] **MAT-001**：回归——同哈希上传两份资料后，两者 `storage_key` **不同**；硬删源资料后，另一份资料的对象仍存在且 `parse_material_pipeline` 可取到内容。
- [ ] **MAT-002**：回归——真机分支下 `retakeMaterialPage` 调用 `uni.uploadFile`，`formData` 含 `page_index`（spy 断言），不再对真实端点发 JSON body。
- [ ] **MAT-003**：回归——`retry_ocr_pages` 全达标时调用 `delete_knowledge_points_by_version` 与 `extract_and_build_knowledge_tree`（spy），且知识树非空。
- [ ] **MAT-004**：回归——OCR 门禁失败→资料状态为 `retake_required`；状态筛选 `retake_required` 返回真实条目；新接口返回不合格页；前端详情页由接口（非硬编码）填充待重拍列表。
- [ ] 后端门禁全绿：`ruff format --check`、`ruff check`、`mypy app`、`lint-imports`、`pytest`。
- [ ] 前端门禁全绿：`pnpm run lint`、`type-check`、`test:unit`。
- [ ] 逐条关闭 `bug-ledger.md` BUG-MAT-001/002/003/004。

## Notes

- 父任务：`09-27-fullstack-bug-audit-and-fix`；依赖：无前置子任务。
- `BUG-MAT-002/004` 与 `BUG-MAT-003` 互为因果，须一并修复方能让重拍链路端到端可用。
- 完整证据见归档 `archive/2026-09/09-27-read-only-bug-audit/research/slice-MAT.md`。
