# Spec: 资料异步解析闭环与PDF提取及知识树串联 - 技术契约

- **关联 Intent**: ZL-140
- **主导设计人**: Dev
- **当前状态**: In-Review
- **任务分级**: Tier 3 (Cross-Domain Rewiring)

---

## 1. 架构流向与设计方案

本任务旨在消除学习资料上传后因缺乏后台消费者导致的任务永久挂起问题，打通从“文件上传”到“PDF原生文本提取”、“向量切片落库”以及“自动知识树生成”的端到端异步解析闭环。

### 1.1 端到端架构调用链与数据流

```mermaid
flowchart TD
    Client([小程序前端 / 客户端]) -->|1. POST /upload 二进制流| API[FastAPI: upload_material]
    
    subgraph SynchronousScope [同步请求生命周期 (HTTP Request Scope)]
        API -->|2. import_material_file| MS_Sync[MaterialService: 请求级会话]
        MS_Sync -->|3. 存储原文件 & SHA256查重| MinIO[(MinIO 存储)]
        MS_Sync -->|4. 创建 Material pending & Version queued| DB_Sync[(PostgreSQL 写入)]
        API -->|5. 注册后台任务| BG[FastAPI BackgroundTasks]
        API -->|6. 返回 201 Created| Client
    end

    subgraph AsynchronousScope [后台异步流水线生命周期 (Background Task Scope)]
        BG -->|7. 异步拉起独立上下文| Runner[run_parse_material_background]
        Runner -->|8. 从 AppContainer 获取全新独立 Session| NewSession[(独立 DB 会话)]
        
        Runner -->|9. 解析文档 parsing_doc| PDF[pypdf 提取正文文本]
        PDF -->|10. 文本清洗 & 持久化 raw_text.txt| MinIO
        
        Runner -->|11. 状态推进: extracting_knowledge| Chunk[split_material_into_snippets]
        Chunk -->|12. 状态推进: embedding_generation| Embed[EmbeddingService: embed_documents]
        Embed -->|13. 批量写入 MaterialSnippet| NewSession
        
        Runner -->|14. 自动串联知识抽取| KS[KnowledgeService: extract_and_build_knowledge_tree]
        KS -->|15. LLM 抽取、质检、去重与建树| LLM[(LLM 适配器)]
        KS -->|16. 写入 KnowledgePoint 节点与关联| NewSession
        
        Runner -->|17. 终态准出: ready| DB_Commit[更新 Version ready & Material ready]
        DB_Commit -->|18. 事务安全提交 commit| NewSession
    end

    subgraph ErrorHandling [异常拦截与事务屏障]
        Runner -.->|任何阶段未捕获异常| Rollback[session.rollback & 状态标记]
        Rollback -.->|记录 failed_stage & error_message| DB_Fail[更新 Version failed & Material failed]
    end
```

### 1.2 核心架构原则与关键机制

1. **请求级 Session 隔离红线 (Request Session Isolation)**:
   - FastAPI 请求生命周期中的 SQLAlchemy Session 随 HTTP 请求结束自动触发 `session.close()`；
   - 后台任务函数必须且仅能通过 `AppContainer.get_session()` 上下文管理器获取独立的事务会话，严禁将请求级 Session 或绑定了请求级 Session 的服务实例隐式传递至后台任务；
   - 在后台任务内部，分别通过 `container.create_material_service(session)` 与 `container.create_knowledge_service(session)` 装配服务，确保生命周期独立受控。

2. **双表联动细粒度状态机 (State Machine Alignment)**:
   - **主表 Material.status**: `pending` -> `parsing` -> `ready` (异常时推进至 `failed`)；
   - **版本表 MaterialVersion.parse_status**: 
     - 初始状态: `queued`
     - 阶段 1 (文档解析): `parsing_doc` (图片格式为 `ocr_processing`)
     - 阶段 2 (切片阶段): `extracting_knowledge`
     - 阶段 3 (向量计算): `embedding_generation`
     - 阶段 4 (知识树构建): 保持 `extracting_knowledge` / `auditing_knowledge`
     - 终态: `ready` (成功) / `failed` (失败)
   - **两表原子性保证**: 任何中间环节抛出异常，必须显式同时更新 `MaterialVersion` 为 `failed` (附带 `failed_stage` 与脱敏 `error_message`) 及 `Material` 为 `failed`，杜绝状态撕裂。

3. **知识点自动抽取建树串联 (Knowledge Tree Automatic Chaining)**:
   - 资料切片分块与向量落库是知识树生成的物理前置依赖；
   - 后台流水线在完成切片持久化后，直接编排调用 `KnowledgeService.extract_and_build_knowledge_tree`；
   - 依赖其内部基于版本覆盖清理的幂等机制 (`delete_knowledge_points_by_version`)，保证重复重试不会产生重复知识节点。

---

## 2. API 与数据契约设计

### 2.1 资料上传创建接口 (POST /api/v1/materials/upload)

* **接口路由**: `POST /api/v1/materials/upload`
* **协议与 Content-Type**: `multipart/form-data`
* **请求头**:
  - `Authorization`: `Bearer <token>` (必须，租户认证)
  - `Idempotency-Key`: `string` (可选，防重防抖 UUID)
* **入参 Form 字段**:
  - `file`: `UploadFile` (二进制流，必选，支持 pdf, docx, pptx, md, txt, png, jpg)
  - `title`: `string | null` (可选，展示标题，默认取文件名)
  - `source_type`: `string` (可选，默认 `"local"`)
* **出参 Schema (MaterialUploadResponse - 保持既有契约完全兼容)**:
  ```json
  {
    "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "version_id": "8bb983dc-68d2-430c-b26a-93a52542a123",
    "title": "Maven基础讲义",
    "file_format": "pdf",
    "file_size": 245890,
    "source_type": "local",
    "status": "pending",
    "created_at": "2026-09-25T14:30:00Z"
  }
  ```
* **状态码**:
  - `201 Created`: 接收成功并完成初始落库，已入队后台流水线；
  - `400 Bad Request`: 格式不支持、文件为空或魔数校验失败；
  - `401 Unauthorized`: 未登录或令牌失效；
  - `422 Unprocessable Entity`: 参数校验不合法。

### 2.2 资料详情与轮询查询接口 (GET /api/v1/materials/{id})

* **接口路由**: `GET /api/v1/materials/{material_id}`
* **出参 Schema (MaterialDetailResponse)**:
  ```json
  {
    "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "title": "Maven基础讲义",
    "file_format": "pdf",
    "file_size": 245890,
    "source_type": "local",
    "status": "parsing",
    "current_version": {
      "id": "8bb983dc-68d2-430c-b26a-93a52542a123",
      "version_number": 1,
      "parse_status": "embedding_generation",
      "failed_stage": null,
      "error_message": null,
      "is_active": true,
      "created_at": "2026-09-25T14:30:00Z"
    },
    "versions_count": 1,
    "created_at": "2026-09-25T14:30:00Z"
  }
  ```
* **异常与错误码定义**:
  - `10001`: 参数格式或校验错误；
  - `20001` / `20002`: 未授权或跨租户水平越权；
  - `40001`: 资料内容校验不合法（如未切分出有效文本、PDF 损坏等）；
  - `40003`: 资料或版本不存在；
  - `50001`: 后台流水线处理或数据持久化异常。

---

## 3. 可测性设计 (Design for Testability)

### 3.1 独立纯函数计算核

1. **PDF 与原生文本提取纯函数 (extract_text_from_raw_content)**:
   - **函数签名**: `extract_text_from_raw_content(content: bytes, file_format: str) -> list[str]`
   - **设计职责**:
     - 基于纯 Python 库 `pypdf.PdfReader` 挂载 `io.BytesIO(content)` 流；
     - 逐页抽取文本，统一做换行规范化、去重、页眉页脚去噪与空白段落剔除；
     - 兜底防护：对全空白、纯图片扫描版（有效字符数 < 10）抛出明确的 `MaterialInvalidError`，支持无外部环境下的 100% 确定性白盒测试；
     - McCabe 复杂度控制: 严格限制 V(G) <= 10。

### 3.2 外部依赖与 Mock / 替身策略

1. **FastAPI BackgroundTasks 隔离测试**:
   - 在单元测试中使用 `BackgroundTasks` 实例并显式执行其注册任务（同步调用后台任务函数），验证端到端流水线推进逻辑；
2. **数据库会话测试替身**:
   - 使用内存 SQLite 或测试容器独立的 `sessionmaker` 提供全新的 Session，验证后台独立会话关闭与事务隔离机制；
3. **外部适配器 Stub/Fake 隔离 (零外部网络访问红线)**:
   - `EmbeddingProtocol`: 使用 `FakeEmbeddingAdapter`（固定生成 1024 维全 0.1 向量），杜绝真实网络访问；
   - `LLMProtocol`: 使用 `FakeLLMAdapter`（返回规范化的知识点 JSON 结构，包含知识点名称、层级与置信度）；
   - `StorageProtocol`: 使用 `FakeStorageAdapter`（在内存 dict 中完成对象的 put/get，验证 `raw_text.txt` 落地与读取）；
   - `OCRProtocol`: 对图片格式使用 Fake OCR 返回预设识别文字。

---

## 4. 替代方案与权衡考量 (Alternatives Considered & Trade-offs)

### 4.1 评估过的替代方案

1. **方案 A (采纳方案): FastAPI 原生 BackgroundTasks + 容器 Session 独立生命周期**
   - **架构做法**: 在 HTTP 请求线程中完成基础落库并返回，将异步流水线委托给 FastAPI `BackgroundTasks`，在后台函数中从 `AppContainer` 申请全新独立 Session 串联执行。
2. **方案 B: 引入 Celery / Redis Queue (RQ) 分布式 Worker 进程**
   - **架构做法**: 上传接口将任务投入 Redis，独立启动 Celery Worker 监听消费。
3. **方案 C: 同步阻塞处理 (直接在 HTTP 上传接口内同步执行全流程)**
   - **架构做法**: 用户请求在等待 PDF 解析、向量化及 LLM 知识树构建全部完成后再返回 HTTP 响应。

### 4.2 未采纳原因与权衡分析

* **为什么不选方案 B (Celery/RQ)**:
  - 违背 KISS 原则：当前系统部署阶段为单服务/小程序配套后端，引入 Celery 需额外维护 Worker 守护进程、Result Backend 与复杂的任务重试路由，增加了极大的运维与调试成本；
  - 当前 BackgroundTasks 配合数据库版本状态持久化，在单进程故障恢复上完全可通过启动补偿任务解决，满足当下需求。
* **为什么不选方案 C (同步阻塞)**:
  - 破坏性体验与网络超时：LLM 抽取多轮质检与向量计算通常耗时 5~30 秒，极大超过微信小程序 HTTP 请求的建议响应窗口，极易造成客户端超时重试风暴；
  - 资源耗尽风险：长耗时同步阻塞会快速耗尽 Uvicorn Worker 线程连接池。

---

## 5. 动态风险核验与回滚预案 (Risk & Rollback Verification)

### 5.1 7 大风险维度核验清单

| 维度 | 影响度 | 现实核验与防御策略 |
| :--- | :--- | :--- |
| **1. Affected Files** | 中 (5~6 个文件) | 涉及 pyproject.toml, material.py, materials.py, container.py 及单测文件；各模块职责单一，修改范围边界明确。 |
| **2. Public API** | 低 (完全向前兼容) | POST /upload 请求体与出参完全兼容；GET /materials/{id} 原生支持状态反映，无需改动现有接口定义。 |
| **3. Data Schema** | 零 (无表结构变更) | 原模型中已具备 parse_status, failed_stage, error_message 字段，无需任何数据库 DDL 迁移。 |
| **4. Auth & Security**| 低 (多租户硬隔离) | 后台异步流水线强制要求透传并使用 user_id 过滤，仓储层所有 SQL 严格携带租户条件；结构化日志脱敏输出。 |
| **5. Dependencies** | 低 (纯 Python 依赖) | 引入 pypdf>=4.0.0，纯 Python 实现，无 C 动态库编译依赖，不影响跨平台与打包体积。 |
| **6. Rollback** | 极低 (无状态回滚) | 无 Schema 变更；若出现严重问题，撤销代码并重新部署即可，原有上传与存储文件保持幂等可追溯。 |
| **7. Blast Radius** | 中 (限后台流水线) | 异常由独立 try-except 屏障全面兜底，后台任务异常不会导致主 Web 服务进程崩溃，主请求始终安全。 |

### 5.2 关键关注点标注 (Flagged Concerns)

1. **请求 Session 提前关闭引发后台任务崩溃 (Session Lifetime Conflict)**:
   - 关注点: 若后台任务直接捕获了请求中的 `material_service`，当请求结束 session 释放后，后台读取或写入 DB 时将抛出 `InvalidRequestError: This session is closed`。
   - 强制策略: 后台任务入口必须强制接收 `AppContainer`，并显式使用 `with container.get_session() as session:` 开启全新会话。
2. **PDF 扫描件或乱码导致分块失败 (Silent Extraction Failure)**:
   - 关注点: 纯图片扫描版 PDF 提取出来的文本为全空白，若直接进入切片阶段会报“未切分出有效知识切片”而使状态变为 failed。
   - 防御对策: 提取阶段做字符长度阈值校验（`valid_char_count < 10`），明确在 `failed_stage="parsing_doc"` 中提示“PDF文件无有效文字内容，扫描件请上传图片格式”。
3. **LLM 知识树构建耗时与小程序轮询窗口协调 (Polling Timeout)**:
   - 关注点: 较长资料抽取可能超过 20 秒，前端若固定轮询 10 次（每次 1 秒）可能提前超时。
   - 防护机制: 后台状态细粒度拆分，前端轮询可根据状态是否持续推进（如从 `parsing_doc` 到 `embedding_generation` 再到 `extracting_knowledge`）动态延长等待窗口。

### 5.3 回滚与故障应急策略

1. **代码级快速回滚**: 若新版本出现非预期异常，直接 git revert 并重新构建部署镜像，由于没有任何 DB 表结构迁移，回滚后立即可用；
2. **故障数据补偿处置**: 若由于代码缺陷产生了一批状态处于 failed 的历史版本，租户可通过现有的重新上传接口直接重新发起，或由运维脚本根据 failed_stage 触发单版本重跑。

---

## 6. 阶段准出签批 (Gate 2 Sign-off)

- [x] 架构流向与 API 契约已冻结
- [x] 替代方案已完成推演与权衡
- [x] 7 维风险已核验且具备明确回滚预案
- **审查结论**: Accepted
- **签批人 / 日期**: User / 2026-09-25 23:55
