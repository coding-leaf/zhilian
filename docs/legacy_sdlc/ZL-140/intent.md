# Intent: 资料异步解析闭环与PDF提取及知识树串联

- **任务编号**: ZL-140
- **提出人**: Dev
- **创建时间**: 2026-09-25 23:46
- **初始 Change Tier**: Tier 3
- **当前状态**: Accepted

---

## 1. 问题与现状背景 (Problem)
1. **任务入队无消费者消费**：用户在小程序前端上传 PDF（如 `Maven基础讲义.pdf`）后，`POST /api/v1/materials/upload` 虽然将任务成功投递至队列（`self.queue.enqueue("parse_material_pipeline")`），但在单体/本地服务中缺乏后台 Worker 线程消费该任务，导致资料解析状态永久卡在 `queued`、资料状态为 `pending`。前端轮询多次后超时退出。
2. **知识树生成链条脱节**：即使资料切片与向量化解析完成，流水线并未自动触发 `knowledge_service.extract_and_build_knowledge_tree`，导致前端轮询或查看 `GET /api/v1/materials/{id}/knowledge-tree` 时无法直接获得已抽取的知识点树。
3. **PDF 原生文本提取失效**：`extract_text_from_raw_content` 针对 PDF 仅做 `content.decode("utf-8", errors="ignore")`，实测提取出的是 `%PDF-1.5 ... 1 0 obj` 等二进制流与原始指令，而非正文文本，导致后续分块切片无法提取出有效知识内容。

## 2. 变更性质分类 (Change Archetype - 单选)
- [ ] 局部结构精简 (Local Cleanup - 仅限模块内部冗余消除，不改数据流向与全局装配)
- [ ] 单模块特性演进 (Single-Module Feature - 单一模块业务增量或修复)
- [x] 跨领域架构重构 (Cross-Domain Rewiring - 触及应用全局装配、生命周期或跨域流向，必须升 Tier 3)

## 3. 期望达成效果 (Proposed Outcome)
1. **异步闭环消费**：在 API 层基于 FastAPI `BackgroundTasks`（或后台 Worker 执行引擎）在资料上传成功响应后，立即在后台异步拉起解析流水线，资料状态从 `pending` 推进至 `ready`（或异常时 `failed`）。
2. **全流程自动串联**：在后台解析流水线中，切片分块与向量化完成后，自动串联调用知识点抽取与知识树生成逻辑，使前端在上传完成后即可直接在知识树视图获取结构化知识点。
3. **纯 Python 原生 PDF 解析**：引入 `pypdf`（无外部二进制系统依赖），在 `extract_text_from_raw_content` 中支持按页提取文本与段落合并，准确提取 PDF 文字内容。

## 4. 波及工程分面 (Affected Architectural Layers)
- [x] 核心领域与计算逻辑 (Domain & Core Business Logic)
- [x] 外部接口与协议入口 (Public Ingress & Controllers & Protocols)
- [ ] 数据持久化与状态存储 (Database & Storage & Schemas)
- [x] 全局装配与应用入口 (Bootstrap & Lifecycle & Service Wiring)

## 5. 边界与硬性约束 (Constraints & Boundaries)
* **硬性技术制约**:
  - 严格遵守 `AGENTS.md` 单向依赖约束，`tooling/check_layers.py` 必须 100% 通过；
  - 异步任务执行不能阻塞主 HTTP 请求线程；
  - 异步任务中的 DB 会话必须独立创建并在完成后关闭，严禁跨线程复用请求级 SQLAlchemy Session；
  - 外部依赖仅限纯 Python 库（如 `pypdf`），严禁引入需要宿主机编译的重型 C 依赖。
* **明确非目标 (Non-Goals / Out-of-Scope)**:
  - 不包含复杂分布式 Celery 基础设施搭建；
  - 不修改现有数据库表结构（已有表字段完全满足需求）；
  - 不包含前端小程序页面的 UI 重构，前端保持现有轮询与接口契约不变。
* **完成判定条件 (Definition of Done)**:
  - 单元测试与集成测试全绿；
  - 实测上传真实 PDF 文件后，后台异步流水线顺利完成，Postgres 中状态变为 `ready`，且知识树节点成功落库；
  - `check_sdlc_integrity.py` 门禁全绿。

## 6. 未决疑问与待探讨点 (Open Questions)
- 知识树生成过程需要调用 LLM，当大模型响应耗时较长（10s~30s）时，前端轮询的默认最大超时时间是否足够（前端目前配置有轮询重试），后端状态应如何精细化反映（如 `extracting_knowledge` 细粒度状态）。

---

## 7. 阶段准出签批 (Gate 1 Sign-off)
- [x] 场景与问题已客观复现并达成共识
- [x] 边界、非目标与约束清晰明确
- [x] 初始 Change Tier 评定合理
- **准出结论**: Accepted
- **签批人 / 日期**: User / 2026-09-25 23:50
