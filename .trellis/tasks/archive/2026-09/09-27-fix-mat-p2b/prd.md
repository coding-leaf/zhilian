# 需求规格：修复 MAT 切片 P2-B（012-018）

## Goal

修复资料（MAT）切片 P2-B 批次共 7 条后端与边界类缺陷（BUG-MAT-012 至 BUG-MAT-018），清除大文件伪装穿透、前后端字段契约死锁、跨平台渠道字段丢失、知识点关联唯一键冲突、大模型 temp_id 坍缩、重拍旧图孤儿对象泄漏、以及大文件流先全量读入内存再校验导致的内存 DoS 风险。

## 需求来源

审计归档 `09-27-read-only-bug-audit` 的 `research/slice-MAT.md`：

| ID | 级别 | 层 | 现象与根因一句话 |
|---|---|---|---|
| BUG-MAT-012 | P2 | frontend | `MaterialUpload.vue` 在媒体选取 size 缺失时硬编码兜底 `1024`，导致超大图片绕过前端文件大小门禁校验 |
| BUG-MAT-013 | P2 | cross-layer | 前端组件读取 `key_points_count`/`page_count`，而后端 DTO 未包含该统计字段，导致列表与卡片考点/页数恒显示兜底文案 |
| BUG-MAT-014 | P2 | cross-layer | `material.ts` 在非小程序（H5/测试）环境 `uploadMaterial` 遗漏传递 `source_type`，导致渠道固定退化为后端默认值 `"local"` |
| BUG-MAT-015 | P2 | backend | `knowledge.py` 候选知识点 `n<=1` 时直接返回原列表未做 snippet index 去重，包含重复 index 时触发 `uq_knowledge_point_snippets_kp_snippet` 唯一约束异常导致整批抽取失败 |
| BUG-MAT-016 | P2 | backend | `knowledge.py` 在大模型输出重复 `temp_id` 时字典推导式键覆盖，导致相同 UUID 冲突或父子树关系丢失 |
| BUG-MAT-017 | P2 | backend | 资料物理硬删除仅清理 `ocr_pages` 当前记录引用的 key，重拍产生的历史临时图片对象 key 遗漏清理，导致对象存储永久残留孤儿文件 |
| BUG-MAT-018 | P2 | backend | 资料上传接口 `api/v1/materials.py` 先全量 `await file.read()` 缓冲进内存再做大小校验，存在大文件内存放大与 DoS 风险 |

## Requirements

### 功能要求

1. **BUG-MAT-012 (前端文件大小安全兜底)**
   - 在 `MaterialUpload.vue` 的 `handleChooseMedia` 中，若 `res.tempFiles` 未提供 `size`，不得使用 `1024` 虚假兜底放行。
   - 当 `size` 为空/0 或无法获取时，尝试通过 `uni.getFileInfo` 异步获取真实文件大小；若仍无法判定，则判定校验失败或给出阻断提示，禁止静默绕过 `validateMaterialFile` 的 `MAX_FILE_SIZE`（20MB）门禁。

2. **BUG-MAT-013 (跨层资料考点与页数契约对齐)**
   - 后端 `MaterialListItem` 与 `MaterialDetailResponse` DTO 增加可选字段：
     - `key_points_count: int | None = Field(default=None, description="考点总数统计")`
     - `page_count: int | None = Field(default=None, description="资料识别总页数")`
   - 后端路由/查询层在组装 `MaterialListItem` 时，从已有版本关联中正确注入统计值（例如 `len(ver.knowledge_points)` 与 `len(ver.ocr_pages)`，若未就绪则为 `0` 或 `None`）。
   - 前端 `MaterialItem` 接口增加可选属性 `key_points_count?: number`、`page_count?: number`，确保卡片展示真实考点数与页数。

3. **BUG-MAT-014 (跨平台上传保持渠道来源)**
   - 前端 `material.ts` 的 `uploadMaterial` 方法在 `!isRealMiniProgramUpload()` 分支（H5/测试）中，将入参中的 `source_type` 随 FormData 或请求体正确发送至后端（`data: { file, title, source_type }`），保持与真实小程序行为一致。

4. **BUG-MAT-015 (知识点与切片关联去重健壮性)**
   - 在 `KnowledgeService.extract_knowledge_points` 及 `deduplicate_candidate_points` 中：
     - 即使候选知识点数量 `n <= 1`，也要对单个 `ExtractedKnowledgeItem.source_snippet_indices` 执行 `sorted(set(...))` 归一化去重。
     - 在构建 `relations_to_save` 时增加集合判重机制 `(kp_uuid, snippet_id)`，确保落库 `KnowledgePointSnippet` 绝不触发 `UniqueConstraint("knowledge_point_id", "snippet_id")`。

5. **BUG-MAT-016 (防御 LLM 输出重复 temp_id)**
   - 在 `_build_knowledge_hierarchy` 构建层级结构前，增加对 `items` 中 `temp_id` 的唯一性检查与消重/重命名规整机制。
   - 若出现重复 `temp_id`，对后续重复项追加后缀（例如 `{temp_id}_{idx}`）并修正子节点的 `parent_temp_id` 指向，或者跳过完全重复节点，确保每个待建实体获得独立 UUID，杜绝主键碰撞。

6. **BUG-MAT-017 (OCR 重拍旧对象存储清理)**
   - 在 `MaterialService.reshoot_page` 执行单页重拍时，在更新数据库前先获取被替换的旧图片 `page.image_storage_key`，并在新图片成功写入后清理旧对象；或者在重拍与硬删除流程中确保历史重拍生成的临时 key（符合规范命名）均能被定位并彻底删除，杜绝孤儿文件泄漏。

7. **BUG-MAT-018 (文件上传读取前门禁与流式体积防御)**
   - 上传接口 `upload_material` 在调用 `file.read()` 之前，先检查请求头 `Content-Length`，若声明体积超过系统全局最大允许上限（20MB + 少量容差），立即中断并抛出 HTTP 413 / `MaterialInvalidError`。
   - 读取过程中采用定长分块流式读取（Chunked Stream Read），一旦累计读取字节数超过目标最大上限，立刻终止读取并抛出异常，防止恶意绕过 `Content-Length` 消耗服务器内存。

### 约束

- 契约规范：后端所有新增字段必须为**附加可选**（`Field(default=None)`），兼容旧客户端。
- 架构分层：严格遵守分层边界，API 路由层只做协议处理与请求守卫，复杂逻辑下沉至 `Service` 与 `Repository`。
- 类型安全：禁止在 TypeScript 中使用 `any`；Python 严格通过 `mypy --strict` 检查。
- 对象存储安全：遵循 `StorageProtocol` 契约，使用 `delete_object` 进行幂等清理。

### 不在范围内

- 前端真机环境特定差异与 Sass 警告（属于 SR / ENV）。
- 资料主观题判题流水线优化（属于 GRADE 切片）。

## Acceptance Criteria

- [ ] **BUG-MAT-012**: 单元测试验证 `MaterialUpload.vue` 处理缺失 size 的媒体文件时调用 `uni.getFileInfo`，若体积超限（>20MB）则拦截上传并提示错误。
- [ ] **BUG-MAT-013**: 后端 `GET /api/v1/materials` 列表与详情接口返回数据包含 `key_points_count` 与 `page_count`；前端展示组件正常渲染考点数与页数，不再显示兜底文案。
- [ ] **BUG-MAT-014**: 前端 `material.ts` 在非小程序环境发送上传请求时，载荷中包含指定的 `source_type`（如 `"wechat"`），后端成功接收并持久化。
- [ ] **BUG-MAT-015**: 单元测试模拟 LLM 输出单一候选知识点但包含重复 `source_snippet_indices=[1, 1]`，抽取流程正常完成，不发生数据库唯一键冲突。
- [ ] **BUG-MAT-016**: 单元测试模拟 LLM 输出具有重复 `temp_id`（如两个 `"kp_1"`）的列表，解析过程平滑处理，成功落库且无 UUID 重复冲突。
- [ ] **BUG-MAT-017**: 单元测试验证在连续重拍某页后执行硬删除，或者在重拍过程中，旧图片 key 得到调用 `delete_object` 清理，对象存储中无历史孤儿对象遗留。
- [ ] **BUG-MAT-018**: 单元测试模拟上传超大文件（超过 20MB），验证在读取超过阈值时被立刻拦截并返回体积超限错误，避免内存无节制缓冲。
- [ ] 质量门禁全绿：后端 `ruff check`, `mypy`, `pytest` 全部通过；前端 `eslint`, `type-check`, `vitest` 全部通过。

## Notes

- 本批次 7 条 bug 经过当前代码 HEAD 检验，均真实存在且具备明确的复现逻辑，无失效或误报项。
- 父任务：`09-27-fullstack-bug-audit-and-fix`。
