# Intent: 向量化与混合检索适配器 (pgvector/BM25)

- **任务编号**: ZL-116
- **提出人**: Dev
- **创建时间**: 2026-09-24 00:26
- **初始 Change Tier**: Tier 2
- **当前状态**: Accepted

---

## 1. 问题与现状背景 (Problem)
智练自主学习平台在学习资料导入与出题生成（FR-21 出题前置检索支持，NFR-01 检索响应时间 P95 < 200ms，NFR-26 外部能力解耦与 Fake 隔离测试）场景中，需要将学习材料的知识切片进行定长向量化并提供高精度的混合语义检索：
- **出题前置检索依赖缺失**：ZL-104 虽已交付 `MaterialSnippet` 数据模型及 pgvector 1024 维 HNSW 余弦近邻索引定义，但当前系统缺乏将文本转化为 1024 维定长浮点向量的统一抽象适配层，也缺少衔接数据库 pgvector 粗排与 BM25 精排的混合检索组件；
- **外部能力解耦与单测零网络红线**：根据《AGENTS.md》契约，业务层严禁直接硬编码第三方 AI 厂商 SDK，单元测试中严禁发起真实公网连接（`conftest.py` 严格网络阻断）。因此必须定义纯抽象契约 `EmbeddingProtocol` 并提供开箱即用、确定性生成、支持时延/故障注入的纯内存假适配器 `FakeEmbeddingAdapter`；
- **生产稳定性与退避重试**：公网 Embedding API（如通义千问 DashScope / OpenAI 兼容接口）存在偶发网络抖动与限流（429/5xx），需具备 20s 默认超时、最多 3 次指数退避重试机制，并将网络异常映射为 30xxx 统一业务异常体系（30007~30009）；
- **混合检索与多租户安全红线**：纯向量检索对专有名词、编号术语易产生语义漂移，纯关键词匹配无法捕获上下文语义，必须支持 pgvector 余弦近邻粗排（Top 20）+ 关键词/BM25 重排（Top 4）并融合打分（RRF / 加权）；同时检索全程必须严格强校验 `user_id`，杜绝跨租户越权查询与版本污染；
- **绝密脱敏红线**：生产适配器的 `__repr__` 必须对 `api_key` 实施严格掩码（`api_key='******'`），日志中严禁输出明文凭据或资料全文。

## 2. 变更性质分类 (Change Archetype - 单选)
- [ ] 局部结构精简 (Local Cleanup - 仅限模块内部冗余消除，不改数据流向与全局装配)
- [x] 单模块特性演进 (Single-Module Feature - 单一模块业务增量或修复)
- [ ] 跨领域架构重构 (Cross-Domain Rewiring - 触及应用全局装配、生命周期或跨域流向，必须升 Tier 3)

## 3. 期望达成效果 (Proposed Outcome)
1. **统一向量化协议抽象 (EmbeddingProtocol)**：
   - 位于 `backend/app/integrations/embedding/`；
   - 定义 `embed_query(text: str) -> list[float]` 与 `embed_documents(texts: list[str]) -> list[list[float]]`，固定返回 1024 维浮点向量。
2. **离线与单测假实现 (FakeEmbeddingAdapter)**：
   - 基于文本哈希生成确定性 1024 维单位向量；
   - 支持预置向量匹配（`set_canned_vector`）、延迟注入（`set_latency`）与故障注入（`set_fault_injection`）；
   - 内部基于 `threading.Lock` 保证并发线程安全，单测 0 网络套接字连接。
3. **生产向量化适配器 (OpenAICompatibleEmbeddingAdapter)**：
   - 兼容通义千问 DashScope 及 OpenAI `/v1/embeddings` 标准接口；
   - 默认 20s 超时控制，3 次指数退避重试；
   - 凭据脱敏保护（`__repr__` 格式化 `api_key='******'`）；
   - 底层异常映射为统一业务异常 `EmbeddingError`(30007)、`EmbeddingTimeoutError`(30008)、`EmbeddingAuthError`(30009)。
4. **纯函数算法核 (Search Pure Algorithms)**：
   - 位于 `backend/app/core/algorithms/search.py`，0 外部重型依赖；
   - 提供文本轻量分词 `tokenize_text`、Okapi BM25 评分 `compute_bm25_score`、倒数排名融合 `reciprocal_rank_fusion` (RRF)、加权融合 `weighted_score_fusion` 以及向量余弦相似度 `cosine_similarity`；
   - 算法白盒覆盖率 100%，无 ORM 或网络耦合。
5. **混合检索组件 (PgvectorHybridSearchAdapter)**：
   - 位于 `backend/app/integrations/search/`；
   - 定义统一抽象 `SearchProtocol` 与数据模型 `SearchResult`、`SearchSnippetCandidate`、`SearchOptions`；
   - 提供 `FakeSearchAdapter` 供上层单测开箱即用；
   - 生产检索实现 `PgvectorHybridSearchAdapter`：强制校验 `user_id`（防越权），基于 `MaterialSnippet` 的 1024 维向量执行余弦近邻粗排（Top 20），再使用 BM25 结合候选集进行关键词评分，通过 RRF/加权算法重排选出高质量 Top 4 切片；检索响应时间 P95 < 200ms。
6. **工厂函数与全局门禁**：
   - 分别提供 `create_embedding_adapter` 与 `create_search_adapter`；
   - `tooling/check_layers.py` 扫描 0 跨层违规（严禁反向导入 `app/services`）；
   - 全量单测毫秒级通过，分支覆盖率达标，bandit 0 安全隐患。

## 4. 波及工程分面 (Affected Architectural Layers)
- [x] 核心领域与计算逻辑 (Domain & Core Business Logic)
- [ ] 外部接口与协议入口 (Public Ingress & Controllers & Protocols)
- [ ] 数据持久化与状态存储 (Database & Storage & Schemas)
- [x] 外部能力适配与集成层 (External Integrations & Adapters)

## 5. 边界与硬性约束 (Constraints & Boundaries)
* **硬性技术制约**:
  - `app/integrations/` 严禁反向导入 `app/services`，纯算法核 `app/core/algorithms/` 严禁导入 ORM/网络/上层业务模块；
  - 缩写白名单严格限定为 8 个（`api`, `id`, `url`, `ocr`, `llm`, `db`, `config`, `env`）；
  - 向量维度严格固定为 1024 维（与 ZL-104 `MaterialSnippet.embedding` 字段一致）；
  - 检索逻辑必须强校验 `user_id`，防止越权；
  - 单元测试运行在网络绝对阻断环境下，0 真实 Socket 连接；
  - 凭据敏感信息（`api_key`）与文本原文严禁暴露在 `__repr__` 或日志中。
* **明确非目标 (Non-Goals / Out-of-Scope)**:
  - 不包含数据库 DDL 变更或数据迁移（表与索引已在 ZL-104 完成交付）；
  - 不包含上层出题大模型调用与 Prompt 编排（属于 ZL-120/121）；
  - 不包含资料导入切分异步流水线（属于 ZL-119）。
* **完成判定条件 (Definition of Done)**:
  - `EmbeddingProtocol` 与 `SearchProtocol` 抽象完备；
  - `FakeEmbeddingAdapter` 与 `FakeSearchAdapter` 满足并发安全与可控注入要求；
  - `OpenAICompatibleEmbeddingAdapter` 凭据脱敏、重试与异常转译通过测试；
  - 纯函数 BM25、RRF 与加权融合算法单元测试判定覆盖率 100%；
  - `PgvectorHybridSearchAdapter` 粗排 20 + 重排 4 流水线验证完整，强制 `user_id` 越权阻断；
  - 扩充 30007~30010 异常类，静态分层检查与代码质量门禁全部绿灯。

## 6. 未决疑问与待探讨点 (Open Questions)
- 单元测试环境下数据库为 SQLite（无原生 pgvector 扩展），`PgvectorHybridSearchAdapter` 在无法执行原生 `<=>` 运算符时，内部需平滑回退为纯函数 `cosine_similarity` 计算粗排，确保在 SQLite 内存库中单测可闭环运行。

---

## 7. 阶段准出签批 (Gate 1 Sign-off)
- [x] 场景与问题已客观复现并达成共识
- [x] 边界、非目标与约束清晰明确
- [x] 初始 Change Tier 评定合理
- **准出结论**: Accepted
- **签批人 / 日期**: Dev / 2026-09-24 00:26