# 执行计划：MAT 切片 P1 修复

## 前置

- 任务：`09-27-fix-mat-p1`（父：`09-27-fullstack-bug-audit-and-fix`）。
- 权威契约见 `design.md` §2；证据见归档 `archive/2026-09/09-27-read-only-bug-audit/research/slice-MAT.md`。

## 执行清单（有序）

### Step 1 — 失败回归（红）
- [ ] 1.1 后端 MAT-001：同哈希两资料 `storage_key` 断言不同 + 硬删源后另一资料对象仍可取（红：现相同且被删）。
- [ ] 1.2 前端 MAT-002：真机分支 `retakeMaterialPage` → `uploadFile`（spy `formData.page_index`）。
- [ ] 1.3 后端 MAT-003：`retry_ocr_pages` 全达标调用知识树重建（spy）。
- [ ] 1.4 后端/前端 MAT-004：OCR 门禁失败 → 资料 `retake_required`；筛选返回条目；`/ocr-pages` 返回不合格页；详情页由接口填充。
- [ ] 1.5 运行测试确认新增断言红。

### Step 2 — MAT-001 实现
- [ ] 2.1 `create_material` 删除复用 `existing_ver.storage_key`，始终写自有对象。
- [ ] 2.2 后端测试转绿。

### Step 3 — MAT-003 实现
- [ ] 3.1 `retry_ocr_pages` 全达标分支插入知识树重建（对齐阶段 D）。
- [ ] 3.2 后端测试转绿。

### Step 4 — MAT-004 实现（后端）
- [ ] 4.1 新增 `MaterialStatus.RETAKE_REQUIRED`；OCR 门禁失败置该状态。
- [ ] 4.2 修 `_resolve_status_filter`；补 `_calculate_progress_percentage`。
- [ ] 4.3 新增 `list_ocr_pages` service 方法 + `MaterialOCRPageItem/MaterialOCRPagesResponse` schema + `GET /materials/{id}/ocr-pages`。
- [ ] 4.4 `reshoot_material_page` 不合格分支状态补齐。
- [ ] 4.5 后端测试转绿。

### Step 5 — MAT-002 + MAT-004 实现（前端）
- [ ] 5.1 `api/material.ts`：`retakeMaterialPage` 真机 multipart；新增 `fetchMaterialOCRPages`。
- [ ] 5.2 `detail/index.vue`：移除硬编码假页面，改接口填充；状态判断对齐后端小写枚举。
- [ ] 5.3 前端测试转绿。

### Step 6 — 全门禁
- [ ] 6.1 后端：`uv run ruff format --check .` + `ruff check .` + `mypy app` + `lint-imports` + `pytest`。
- [ ] 6.2 前端：`pnpm run lint` + `pnpm run type-check` + `pnpm run test:unit`。
- [ ] 6.3 逐条关闭 BUG-MAT-001/002/003/004。

## 验证命令

```bash
# 后端（workdir=backend）
uv run ruff format --check . && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run pytest tests
# 前端（workdir=miniprogram）
pnpm run lint && pnpm run type-check && pnpm run test:unit
```

## 评审门禁

- Gate A：4 组回归断言先红后绿。
- Gate B：后端五项 + 前端三项全绿；派发 `trellis-check` 复核状态机、契约与规范。

## 回滚点

- 秒传改动可回退（会复现完整性问题）。
- 状态/路由为附加；OCR 失败语义由 FAILED→RETAKE_REQUIRED 的断言调整须保持用例意图。
