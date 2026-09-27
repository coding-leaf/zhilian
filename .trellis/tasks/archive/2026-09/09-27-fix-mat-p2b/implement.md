# 执行计划：MAT 切片 P2-B（012-018）修复

## 前置条件

- 任务：`09-27-fix-mat-p2b`（归属父任务：`09-27-fullstack-bug-audit-and-fix`）。
- 需求与验收标准见 `prd.md`，技术方案详见 `design.md`。

---

## 执行清单（有序敏捷交付）

### Step 1 — 失败回归与红用例编写 (Red Phase)
- [x] 1.1 **前端**: 在 `miniprogram/tests/unit/components/MaterialUpload.spec.ts` 中新增/补充测试用例：
  - 断言媒体选取在 `size` 缺失时调用 `uni.getFileInfo`；当文件过大或无法读取时阻止进入上传准备状态（针对 BUG-MAT-012）。
  - 断言非小程序环境下发起上传时，入参载荷包含 `source_type`（针对 BUG-MAT-014）。
- [x] 1.2 **后端 (知识点服务)**: 在 `backend/tests/unit/services/test_knowledge_service.py` 中新增红测试用例：
  - 构造 `ExtractedKnowledgeItem` 仅 1 项且包含重复 `source_snippet_indices=[0, 0]`，断言保存时不抛出数据库唯一键冲突（针对 BUG-MAT-015）。
  - 构造包含相同 `temp_id`（如两个 `"kp_dup"`）的候选列表，断言层级构建与保存成功生成两个不同的实体 UUID（针对 BUG-MAT-016）。
- [x] 1.3 **后端 (资料与路由服务)**:
  - 在 `backend/tests/unit/schemas/test_material_schemas.py` 中增加 `MaterialListItem` 包含 `key_points_count` 与 `page_count` 的序列化测试（针对 BUG-MAT-013）。
  - 在 `backend/tests/unit/services/test_material_service.py` 中针对 `reshoot_page` 新增测试：断言重拍完成后存储适配器的 `delete_object` 被调用且传入被替换的旧 key（针对 BUG-MAT-017）。
  - 在 `backend/tests/unit/api/test_material_router.py` 中新增测试：模拟超大文件上传或超长 Content-Length，断言流式中断并返回体积过大错误，且内存不缓冲完整内容（针对 BUG-MAT-018）。
- [x] 1.4 运行上述测试，确认新增测试如期处于失败状态（红）。

---

### Step 2 — 逐 Bug 修复实现 (Green Phase)

#### 2.1 BUG-MAT-012 实现 (前端文件大小安全兜底)
- [x] 改造 `MaterialUpload.vue:handleChooseMedia`：
  - 若 `files?.[0]?.size` 有效则直接使用；若缺失，调用 `uni.getFileInfo` 异步获取。
  - 获取失败或体积依然为 0/缺失时，使用 `uni.showToast` 提示并中断，严禁以 `1024` 兜底。

#### 2.2 BUG-MAT-014 实现 (保持非小程序上传渠道)
- [x] 修改 `miniprogram/src/api/material.ts:uploadMaterial`：
  - 非小程序分支的 POST 载荷补充 `source_type: sourceType`，与原生小程序分支对齐。

#### 2.3 BUG-MAT-013 实现 (考点与页数契约对齐)
- [x] 后端 DTO 修改：
  - `backend/app/schemas/material.py`：在 `MaterialListItem` 与 `MaterialDetailResponse` 中添加 `key_points_count: int | None = None`、`page_count: int | None = None`。
- [x] 后端 Service / Repo 注入：
  - `backend/app/repositories/material.py` 或 `MaterialService.get_materials_list`：关联查询最新激活版本的考点数与 OCR 页数并装配给 DTO。
- [x] 前端类型更新：
  - `miniprogram/src/types/material.ts`：在 `MaterialItem` 接口中增加可选属性 `key_points_count?: number` 与 `page_count?: number`。

#### 2.4 BUG-MAT-015 实现 (关联关系去重健壮性)
- [x] 修改 `backend/app/services/knowledge.py`：
  - 在 `deduplicate_candidate_points` 中，即使 `n <= 1` 也先遍历 items 对其 `source_snippet_indices` 执行 `sorted(set(...))`。
  - 在构建 `relations_to_save` 时使用 `seen_relations: set[tuple[uuid.UUID, uuid.UUID]]` 消除重复关联记录。

#### 2.5 BUG-MAT-016 实现 (防 LLM 重复 temp_id 坍缩)
- [x] 修改 `backend/app/services/knowledge.py`：
  - 在 `_build_knowledge_hierarchy` 中预先扫描 items 的 `temp_id`。如果检测到重复出现，动态重命名为 `{temp_id}_dup_{index}` 并同步维护映射关系，保证进入实体循环时每个 item 均拥有独一无二的映射与 UUID。

#### 2.6 BUG-MAT-017 实现 (OCR 重拍旧对象存储清理)
- [x] 修改 `backend/app/services/material.py` 中的 `reshoot_page`：
  - 在写入新图片与更新数据库后，记录被替换的原 `old_image_storage_key = page.image_storage_key`。
  - 调用 `self.storage.delete_object(self.bucket, old_image_storage_key)` 完成旧对象安全物理清除。

#### 2.7 BUG-MAT-018 实现 (上传流式大小拦截与请求前门禁)
- [x] 修改 `backend/app/api/v1/materials.py:upload_material`：
  - 解析 `request.headers.get("content-length")`，若大于全局单文件上限（如 20MB）则直接抛出 HTTP 413 异常。
  - 引入安全流式读取辅助函数：循环按 64KB 分块读取 `await file.read(65536)` 并累计大小，一旦超过对应格式上限立即中止并抛出 `MaterialInvalidError`，禁止全量无节制读入内存。

---

### Step 3 — 全门禁验证与回归质量门禁

- [x] 3.1 **后端全套质量检查**:
  - `uv run ruff format --check .`
  - `uv run ruff check .`
  - `uv run mypy app`
  - `uv run lint-imports`
  - `uv run pytest tests`
- [x] 3.2 **前端全套质量检查**:
  - `pnpm run lint`
  - `pnpm run type-check`
  - `pnpm run test:unit`
- [x] 3.3 确认所有 7 条 Bug 修复已完整生效，且无任何既有功能受损。

---

## 验证命令

```bash
# 后端检查 (workdir=backend)
uv run ruff format --check . && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run pytest tests

# 前端检查 (workdir=miniprogram)
pnpm run lint && pnpm run type-check && pnpm run test:unit
```

---

## 评审门禁与回滚点

- **评审门禁**:
  - Gate 1: 失败用例成功编写并变红，修复后全绿。
  - Gate 2: 后端静态检查、类型检查、架构建模、全量单元测试 100% 通过。
  - Gate 3: 前端代码规范、TS 类型编译、全量 Vitest 测试 100% 通过。
- **回滚点**:
  - 本次修复均不修改数据库 schema 表结构（无迁移脚本），所有逻辑加固与参数补充均向后兼容，出现异常可单文件 revert 代码回退。

---

## 执行结果（实现 Agent 回填）

### 逐 Bug 状态

| ID | 状态 | 关键改动 |
|---|---|---|
| BUG-MAT-012 | 已修复 | `MaterialUpload.vue:handleChooseMedia` + 新增 `resolveMediaSize`：size 缺失时经 `uni.getFileInfo` 补全，取不到则提示并阻断，杜绝 `1024` 兜底 |
| BUG-MAT-013 | 已修复 | `schemas/material.py` DTO 新增可选 `key_points_count/page_count`；`repositories/material.py` 新增分组计数 + `selectinload(...ocr_pages)`；`services/material.py` 装配；`api/v1/materials.py` 透传；`types/material.ts` 补类型 |
| BUG-MAT-014 | 已修复 | `api/material.ts:uploadMaterial` 非小程序分支 `data` 追加 `source_type` |
| BUG-MAT-015 | 已修复 | `services/knowledge.py:deduplicate_candidate_points` n<=1 去重 source indices；关联构建 `seen_relations` 集合判重 |
| BUG-MAT-016 | 已修复 | 新增纯函数 `normalize_extracted_temp_ids`，`build_knowledge_hierarchy` 与抽取服务落库前规整重复 temp_id |
| BUG-MAT-017 | 已修复 | `retry_ocr_pages` 记录被替换旧 key，提交后 `_purge_storage_objects` 幂等清理（含熔断分支）；`hard_delete_material` 复用同一 helper |
| BUG-MAT-018 | 已修复 | `api/v1/materials.py` 新增 `_read_upload_content_guarded`：读取前校验 Content-Length、64KB 分块累计，超限抛 HTTP 413 |

### 门禁结果

- 后端：`ruff format --check .` / `ruff check .` / `mypy app` / `lint-imports` 全绿；`pytest tests` = **1182 passed**。
- 前端：`pnpm run lint` / `pnpm run type-check` 全绿；`pnpm run test:unit` = **518 passed (58 files)**。

### 与 design.md 的偏差

1. 设计文档写 `_build_knowledge_hierarchy`，实际函数名为模块级 `build_knowledge_hierarchy`（在真实函数与抽取服务落库前共同规整 temp_id）。
2. BUG-MAT-013：`MaterialVersion` 与 `KnowledgePoint` 无 ORM 关系，故新增仓储分组计数查询（单次 `GROUP BY`），OCR 页数用 `selectinload` 预加载，均保持常数级查询。
3. BUG-MAT-017：清理动作放在事务 `commit()` 之后执行（非写库后立即），避免回滚时删掉仍被数据库引用的旧对象；熔断分支同样在 commit 后清理。
4. BUG-MAT-018：使用本地常量 `413` 替代已废弃的 `starlette.status.HTTP_413_REQUEST_ENTITY_TOO_LARGE`。
5. 同步更新 `tests/unit/api/material.spec.ts` 既有上传 payload 断言，纳入新增 `source_type`（契约对齐，非削弱）。
