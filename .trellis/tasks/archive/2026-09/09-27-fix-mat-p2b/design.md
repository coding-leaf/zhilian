# 技术设计：MAT 切片 P2-B 修复

## 1. 背景与根因剖析

### BUG-MAT-012: 媒体选取 size 缺失虚假兜底
- **位置**: `miniprogram/src/components/common/MaterialUpload.vue:130-131`
- **根因**: `const size = files?.[0]?.size || 1024;` 在小程序真机环境（部分机型返回临时文件对象未带 size 字段）下，直接回退至 `1024`（1KB）。当用户选择实际数十兆的超大图片时，`validateMaterialFile(name, size)` 将判定体积合法，导致超大流量被发送至后端。
- **修复方案**: 当 `files?.[0]?.size` 缺失或为 0 时，调用 `uni.getFileInfo({ filePath })` 异步获取真实文件大小；若获取失败或体积依然未知，阻断并提示“无法获取文件大小，请重新选择”，坚决不以虚假数值绕过校验。

### BUG-MAT-013: 考点数与页数死字段导致前端恒展示兜底文案
- **位置**:
  - 前端: `MaterialCard.vue:100-104`, `RecentLearningSection.vue:154-165`（读取 `key_points_count ?? points_count` 与 `page_count ?? pages_count`）
  - 后端: `backend/app/schemas/material.py:89-109`（`MaterialListItem` 与 `MaterialDetailResponse` 缺失上述字段）
  - 路由: `backend/app/api/v1/materials.py:223-239`（响应未注入相关统计数据）
- **根因**: 前后端契约不一致。前端期待列表和卡片能展示考点和页数信息，但后端未在响应中计算与透传。
- **修复方案**:
  - 在 `MaterialListItem` 和 `MaterialDetailResponse` DTO 中新增附加可选字段：
    - `key_points_count: int | None = Field(default=None, description="考点总数")`
    - `page_count: int | None = Field(default=None, description="总页数")`
  - 在前端 `MaterialItem`（`types/material.ts`）补全对应字段类型定义。
  - 在后端 Repository / Service 查询时，通过子查询或关系加载获取当前激活版本的知识点数量及 OCR 页数，并在组装响应时安全填入。

### BUG-MAT-014: 非小程序环境 uploadMaterial 丢失 source_type
- **位置**: `miniprogram/src/api/material.ts:180-185`
- **根因**: 小程序分支在 `formData` 中带上了 `source_type`，而 H5/非小程序分支：
  `request<MaterialUploadResponse>({ url: '...', method: 'POST', data: { file, title }, headers })`
  遗漏了 `source_type` 字段，导致后端始终采用默认的 `"local"`，丢失了传入的真实来源渠道（例如 `"wechat"`）。
- **修复方案**: 在 `data` 载荷中追加 `source_type`（支持通过 FormData 或普通 payload 传输），确保各环境一致。

### BUG-MAT-015: 候选知识点 n<=1 时重复 snippet index 触发唯一约束崩溃
- **位置**: `backend/app/services/knowledge.py:124-126, 497-507`, `backend/app/models/knowledge.py:169-174`
- **根因**: `deduplicate_candidate_points` 在 `n <= 1` 时直接返回原列表 `list(items)`，跳过了 `all_indices = set(...)` 的去重操作。如果单项中的 `source_snippet_indices` 包含重复索引（例如大模型输出了 `[0, 0]`），随后在保存关联时会将两个相同 `(knowledge_point_id, snippet_id)` 提交至数据库，触发 `uq_knowledge_point_snippets_kp_snippet` 唯一约束违背错误，导致整批事务回滚。
- **修复方案**:
  - `deduplicate_candidate_points` 函数开头对每个 item 的 `source_snippet_indices` 执行 `list(dict.fromkeys(item.source_snippet_indices))`（或 `sorted(set(...))`）去重归一。
  - 在 `relations_to_save` 组装环节使用 `set[tuple[uuid.UUID, uuid.UUID]]` 判重，提供双重防御。

### BUG-MAT-016: 大模型输出重复 temp_id 导致字典坍缩与 UUID 碰撞
- **位置**: `backend/app/services/knowledge.py:208-209, 229-245`
- **根因**: `temp_to_uuid = {it.temp_id: uuid.uuid4() for it in items}`。若大模型异常生成了重复的 `temp_id`（例如两个 `"kp_1"`），字典推导式会后项覆盖前项，但循环遍历 `items` 时：
  两个不同的知识点实体将取到同一个 `uuid.UUID`，插入数据库时触发主键冲突崩溃。
- **修复方案**:
  - 在 `_build_knowledge_hierarchy` 中执行防坍缩预处理：检查 `temp_id` 唯一性；若遇到重复 `temp_id`，对重复项重新分配唯一标识符（如追加后缀或重新生成）并建立重命名映射表，保证每个知识点对象具备独立全局 UUID 且层级父子引用不受破坏。

### BUG-MAT-017: OCR 单页重拍旧图片对象存储泄漏
- **位置**: `backend/app/services/material.py:877-894, 1510-1520`
- **根因**: 每次单页重拍时，系统在 MinIO 中存入新键 `pages/page_{page_num}_reshoot_{next_reshoot_count}.png` 并覆盖了 `MaterialOCRPage.image_storage_key`。被替换掉的旧图片键既没有即时删除，在资料物理硬删除时也只能查到当前被引用的 key，导致历次重拍产生的旧图片在 MinIO 中永久变成孤儿对象。
- **修复方案**:
  - 方案选择：在 `reshoot_page` 流程中，在成功写入新对象并更新数据库记录后，即时对被替换的原 `old_storage_key` 调用 `self.storage.delete_object(self.bucket, old_storage_key)` 执行物理清理。此做法轻量、实时、无需侵入式改造表结构记录冗余历史键，且具备天然幂等性。

### BUG-MAT-018: 上传端点全量读取请求体导致内存放大与 DoS 风险
- **位置**: `backend/app/api/v1/materials.py:138`, `backend/app/services/material.py:427-431`
- **根因**: `content = await file.read()` 在路由入口处对整个上传文件进行了一次性全量异步读取，放入内存变量 `content` 后才传给 Service 进行大小判定。攻击者若并发上传数百兆文件，将瞬间撑爆服务容器内存。
- **修复方案**:
  - 在 `upload_material` 路由入口处首先校验 `Request` 头部的 `Content-Length`，若超出系统全局允许的最大单文件上限（当前上限为 20MB，可配置全局上限如 25MB），直接抛出 HTTP 413 Payload Too Large。
  - 读取时使用分块流式读取工具函数：按 64KB 循环读取 `await file.read(65536)`，累计字节数一旦超过目标格式允许上限（或系统全局最大 20MB），立刻终止循环并抛出 `MaterialInvalidError`，绝不将超限字节全部载入内存。

---

## 2. 影响文件与修改范围清单

### 前端 (miniprogram)
- `miniprogram/src/components/common/MaterialUpload.vue` (BUG-MAT-012)
- `miniprogram/src/types/material.ts` (BUG-MAT-013)
- `miniprogram/src/api/material.ts` (BUG-MAT-014)

### 后端 (backend)
- `backend/app/schemas/material.py` (BUG-MAT-013: 增加 `key_points_count`, `page_count`)
- `backend/app/repositories/material.py` (BUG-MAT-013: 列表查询注入考点/页数统计)
- `backend/app/api/v1/materials.py` (BUG-MAT-013, BUG-MAT-018: 响应模型适配、上传流式检查)
- `backend/app/services/knowledge.py` (BUG-MAT-015, BUG-MAT-016: snippet 去重、temp_id 重命名防坍缩)
- `backend/app/services/material.py` (BUG-MAT-017: 重拍后即时删除旧图片对象)

### 测试文件 (tests)
- `miniprogram/tests/unit/components/MaterialUpload.spec.ts` (BUG-MAT-012, 014 测试)
- `backend/tests/unit/schemas/test_material_schemas.py` (BUG-MAT-013 DTO 测试)
- `backend/tests/unit/api/test_material_router.py` (BUG-MAT-013, BUG-MAT-018 路由与超限测试)
- `backend/tests/unit/services/test_knowledge_service.py` (BUG-MAT-015, 016 去重与重复 ID 测试)
- `backend/tests/unit/services/test_material_service.py` (BUG-MAT-017 旧对象删除测试)

---

## 3. 兼容性与回滚策略

- **向后兼容**:
  - DTO 中所有新增的 `key_points_count`、`page_count` 均赋予 `default=None`，不破坏既有前端序列化。
  - `source_type` 字段增加传递，后端原有默认值 `"local"` 保持作为兜底。
- **回滚机制**:
  - 所有改动为逻辑加固与防御性校验，不涉及不可逆的数据库迁移脚本（Alembic Migration）。若遇异常，单点代码 revert 即可恢复原有逻辑。
