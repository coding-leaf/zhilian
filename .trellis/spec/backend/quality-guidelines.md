# Quality Guidelines

> Code quality standards and verification baseline for backend development.

---

## Overview

Backend quality standards are enforced via automated CI gates, linting rules, type checking, architectural boundary checks, and automated tests.
All backend commands must be run within the `backend/` directory using `uv run`.

### Quality Gate Commands

```bash
cd backend
uv run ruff format --check .    # Code formatting check
uv run ruff check .             # Ruff linter (PEP 8, security, complexity, async)
uv run mypy app                 # Strict type checking on application code
uv run lint-imports             # Architecture dependency boundary verification
uv run pytest tests             # Full unit & integration test suite
```

---

## Forbidden Patterns

- **Architectural Boundary Violations (Enforced by import-linter)**:
  - Repositories (`app.repositories`) MUST NOT import `fastapi`, `app.integrations`, `app.services`, or `app.api`.
  - Core algorithms (`app.core.algorithms`) MUST remain pure functions and MUST NOT import `fastapi`, `sqlalchemy`, `httpx`, `redis`, `boto3`, or upper application layers.
  - Integrations (`app.integrations`) MUST NOT import services (`app.services`) or routes (`app.api`).
  - Core base (`app.core`) MUST NOT import upper application layers (`app.api`, `app.services`, `app.repositories`, `app.integrations`).
- **Unsafe Code & Secrets**:
  - Never hardcode API keys, secrets, or sensitive tokens (flagged by Ruff `S` rules).
  - Never use raw SQL string concatenation; always use parameterized SQLAlchemy queries or ORM expressions.
- **Untyped Public APIs**:
  - Missing type annotations on function parameters or return values in `app/` are forbidden (enforced by Mypy).

---

## Required Patterns

- **Dependency Injection**: Services and repositories should receive their dependencies via constructor injection (AppContainer / ProviderRegistry).
- **Explicit Type Hints**: All functions, methods, and dataclasses/pydantic models must have full type annotations (`def func(param: Type) -> ReturnType:`).
- **Layered Clean Architecture**:
  - `app.api`: Route handling, request validation, HTTP status codes, dependency wiring.
  - `app.services`: Business logic, domain rules, transactions.
  - `app.repositories`: Data access, ORM queries, persistence abstraction.
  - `app.models`: Declarative SQLAlchemy models and Alembic migrations.
  - `app.integrations`: Third-party providers (LLM, OCR, Storage) implementing domain protocols.
  - `app.core`: Configuration, exceptions, pure algorithms, utilities.

---

## Testing Requirements

- **Test Framework**: Pytest with `pytest-asyncio` for async tests.
- **Test Locations**: All tests live under `backend/tests/` (`unit/`, `integration/`, etc.).
- **Coverage & Pass Rate**: 100% test pass rate required. No regressions allowed.
- **Isolation**: Unit tests must use mock adapters, in-memory SQLite, or fake providers to avoid relying on external live services.

---

## Architectural Contracts & Cross-Layer Patterns

### Scenario: Material Parsing Retry & Idempotent Re-queueing

#### 1. Scope / Trigger
- 学习资料解析中断或失败后，前端发起单资料就地重试，或重复上传同哈希失败文件。

#### 2. Signatures
- API: `POST /api/v1/materials/{id}/retry` -> `MaterialDetailResponse` (HTTP 200)
- Service: `MaterialService.retry_material_pipeline(material_id: uuid.UUID, user_id: uuid.UUID) -> MaterialVersion`

#### 3. Contracts
- 校验租户归属（必须匹配 `user_id`，杜绝越权）。
- 将最新版本 `parse_status` 重置为 `QUEUED`，同时必须显式将 `error_message` 和 `failed_stage` 清空为 `None`。
- 将资料主实体 `status` 重置为 `PENDING`。
- 异步重新提交后台解析任务。

#### 4. Wrong vs Correct
##### Wrong
```python
# 错误做法：仅重置 parse_status，遗留历史 error_message 和 failed_stage，导致前端误判仍处于失败
version.parse_status = ParseStatus.QUEUED.value
material.status = MaterialStatus.PENDING.value
```
##### Correct
```python
# 正确做法：彻底清理错误信息与失败阶段，重置为排队解析
version.parse_status = ParseStatus.QUEUED.value
version.error_message = None
version.failed_stage = None
material.status = MaterialStatus.PENDING.value
```

---

### Scenario: Dual-Mode Auth & Deterministic Development OpenID

#### 1. Scope / Trigger
- 小程序登录鉴权支持本地开发联调与线上真实环境无缝切换，避免生成临时假账号分裂数据。

#### 2. Contracts
- 若传入固定 `dev_code`，强制解析为确定性 OpenID `wx_dev_deterministic_user`。
- 若传入 `dev_` 或 `mock_` 前缀，强制解析为 `wx_dev_{code}`。
- 前端在授权失败时，严禁向本地 Store 写入任意未验证或伪造的 Token（如 `mock_access_token_*`），避免 401 拦截器死锁。

---

### Scenario: LangGraph Schema-as-Tool Calling Pipeline

#### 1. Scope / Trigger
- LLM 结构化抽取（知识考点抽取、题目生成等）强制采用原生 OpenAPI Function Calling 模式。

#### 2. Contracts
- 模型选项通过 `LLMOptions(tools=[...], tool_choice={"type": "function", ...})` 透传。
- 状态图节点 `validate_output_node` 优先从 `raw_response.tool_calls` 提取入参反序列化，仅在未命中工具调用时才作为纯文本降级处理。

---

### Scenario: Headless CLI Closed-Loop Verification (`python -m app.cli`)

#### 1. Scope / Trigger
- 需要以脚本方式驱动真实业务链路（鉴权→上传→解析→知识树→出题→练习→判分→报告）做端到端闭环验证时。

#### 2. Signatures
```bash
python -m app.cli doctor [--require-real] [--json]
python -m app.cli db upgrade | db reset --yes
python -m app.cli auth login --code <code>
python -m app.cli material upload --file <path> [--user-id|--code]
python -m app.cli material parse --material-id <uuid>
python -m app.cli question generate --material-id <uuid> [--knowledge-point-id <uuid>]
python -m app.cli smoke [--file <path>] [--image <path>] [--json]
```

#### 3. Contracts
- **强制真实链路**：`smoke` / `doctor --require-real` 在检测到 `llm/embedding/search=fake`、`storage=memory`、`db=sqlite` 或密钥缺失时，**必须在任何业务动作前中止**，输出结构化缺口清单（环境变量键 + 期望形态），不得静默回落到 fake。
- **退出码契约**：`0` 成功；`1` 运行时错误；`2` 断言失败（含 `failed_stage`/原始 `error`）；`3` 配置缺失/非真实 Provider；`4` 基础设施不可达。
- **脱敏**：任何输出不得包含密钥/token/DB 密码明文；DB URL 脱敏为 `***@host/db`；token 仅输出 `has_*_token` 布尔。
- **装配原则**：必须经 `AppContainer` 工厂装配服务与 `container.get_session()` 管理会话；解析必须走 `parse_material_pipeline`，禁止绕过业务逻辑。

#### 4. Tests Required
- 离线单测（SQLite + fake Provider，`--allow-fake`，零联网）：断言退出码契约与「配置缺口时不执行任何业务」。
- 至少一次真实运行的 `smoke` 退出码 0 作为交付证据。

---

### Scenario: Retrieval Score Semantics (RRF vs Cosine) at Relevance Gates

#### 1. Scope / Trigger
- 任何用「检索结果分数」做相关性/相似度阈值的业务门禁（出题、RAG 选片、报告定位等）。

#### 2. Contracts
- `SearchSnippetCandidate` 同时携带三种分：`vector_score`（余弦相似度，0–1）、`bm25_score`（词法分，无界）、`final_score`（**RRF 融合排名分**，量级约 `1/(rrf_k+rank) ≈ 0.016`）。
- **相似度阈值判定必须用 `vector_score`**；`final_score` 仅用于**排序/召回融合**，严禁用于阈值比较。

#### 3. Wrong vs Correct
##### Wrong
```python
# 错误：拿 RRF 融合分去比余弦阈值，真实命中也必被拒（0.016 < 0.35）
SnippetCandidate(score=item.final_score)   # 门禁 if max_score < 0.35: raise
```
##### Correct
```python
# 正确：阈值语义是「相似度」，取余弦分
SnippetCandidate(score=item.vector_score)  # 0–1，可与 0.35 比较
```

#### 4. Tests Required
- 单测必须预置**贴近真实的分数**（`vector_score` 高、`final_score` 低），否则 mock 的假高分（`final_score=0.91`）会掩盖真实缺陷。
- 断言：高 `vector_score` + 低 `final_score` 的候选能通过门禁（守回归）。

---

### Scenario: LLM Structured Output Adherence (Model Selection & Strict-Mode Gap)

#### 1. Scope / Trigger
- 所有经 `run_structured_agent_workflow`（LangGraph Schema-as-Tool）的结构化 LLM 调用：出题、知识树抽取、判分、诊断等。

#### 2. Contracts
- 该路径由 `agent_graph.pydantic_to_tool_schema` 自动生成 function schema，并用 `tool_choice={"type":"function",...}` **强制调用该函数**；但**未开启 `strict`**，因此只是“强制调用”，**不约束参数内容**，模型仍可产出违反 schema 的 arguments。
- **弱模型会系统性违反 schema**：实测 `gemini-3.5-flash-lite`（经中转）对出题稳定返回 `options: [true, false]`（应为 `[{"key":"A","content":"..."}]`），3/3 复现，导致 `questions` 阶段恒失败（`LLMResponseFormatError`）。
- 因此：真实链路验证与生产**优先选强模型**（实测 `gemini-3.8-flash-high` 一次通过，11/11 阶段全绿）。
- 若必须使用弱模型，需要实现 **OpenAI Structured Outputs 严格模式**（见下），且需确认上游/中转支持。

#### 3. Wrong vs Correct
##### Wrong
```python
# 弱模型 + 无 strict：prompt 写了格式也拦不住
LLMOptions(temperature=0.3)   # tool schema 无 strict=true → 模型输出 options:[true,false]
```
##### Correct
```python
# 方案 A（首选，零代码）：配置强模型
# backend/.env: ZHILIAN_LLM__MODEL=gemini-3.8-flash-high
# 方案 B（弱模型兜底，需代码）：严格函数调用
#   tool 定义加 "strict": true，并对 model_json_schema() 递归补
#   additionalProperties:false + 全字段 required；
#   或用 response_format={"type":"json_schema","json_schema":{"strict":true,...}}
```

#### 4. Diagnosis Recipe
- 失败归因入口：`python -m app.cli smoke --json` → 读 `failed_stage` + `error` 精确定位环节。
- 区分「模型能力」与「代码缺陷」：若 prompt/schema 明确正确而模型仍违约 → 模型不遵从（换模型/开 strict）；若 prompt/schema 有误 → 改代码。
- 中转站可用模型查询：`GET {ZHILIAN_LLM__BASE_URL}/models`（Bearer 鉴权，勿回显密钥）。

---

### Scenario: Multi-Knowledge-Point Question Generation

#### 1. Scope / Trigger
- 一次请求需覆盖多个知识点出题（前端知识树多选考点后生成）。

#### 2. Signatures
- `POST /api/v1/questions/generate`；请求新增**可选** `knowledge_point_ids: list[UUID]`（保留 `knowledge_point_id`）；响应新增**可选** `knowledge_point_ids: list[UUID]`。
- Service: `QuestionService.generate_questions_for_knowledge_points(user_id, material_id, version_id, knowledge_point_ids, options) -> MultiKnowledgePointGenerationResult`
- 纯函数: `distribute_count(total: int, n: int) -> list[int]`

#### 3. Contracts
- **向后兼容**：仅传 `knowledge_point_id` 时走原单考点链路，行为与响应结构完全不变；新增字段一律为**附加可选**。
- **优先级**：`knowledge_point_ids` 非空优先；否则用 `knowledge_point_id`；两者皆空 → 校验失败（422）。
- **题量分配**：均分 + 余数前置（前 `rem` 个各 `base+1`）；**每考点至少 1 题**；`total < n` 时实际总数 = n。非法入参（`total<=0` 或 `n<=0`）抛 `ValueError`。
- **聚合**：`qualified_questions`/`pending_questions`/`quality_checks` 按调用顺序拼接；计数求和；`knowledge_point_id`（旧字段）= 首个考点；`knowledge_point_ids`（新字段）= 全量去重保序。
- **fail-fast + 单事务原子**：任一考点异常（`KnowledgeNotFoundError`/`MissingSourceSnippetError`）立即抛出，不静默跳过、不做部分成功降级；且**跨考点必须全有或全无**——多考点编排在**同一个外层事务**内提交，任一考点失败则整批回滚，不得遗留部分已入库题目。
- **提交边界**：`generate_questions(*, ..., defer_commit: bool = False)`——单考点默认 `False`（内部自行 `commit()`，零回归）；多考点编排传 `defer_commit=True` 并**仅由外层**在全部成功时 `commit()` 一次，失败时 `rollback()`。
- **仓储假设**：`batch_create_questions` / `batch_create_quality_checks` 必须仅 `add`+`flush()`，**禁止**内部独立 `commit()`，否则外层单事务不成立。
- **纯函数无 IO**：`distribute_count` 不得引入仓储/网络依赖（守 import-linter）。

#### 4. Wrong vs Correct
##### Wrong
```python
# 错误1：把简单整除当分配，total<n 时某些考点 0 题；或静默跳过失败考点
per = total // n
for kp in kps:
    try:
        generate(kp, per)   # 0 题；且吞错继续
    except Exception:
        pass

# 错误2：逐考点各自 commit —— 第 N 个失败时前 N-1 个已入库（非原子，遗留部分题目）
for kp, cnt in zip(kps, counts):
    generate_questions(..., knowledge_point_id=kp, options=...)  # 内部 commit()
```
##### Correct
```python
# 正确：均分+余数前置+每考点>=1；多考点单事务原子（外层唯一提交/回滚）
counts = distribute_count(total, n)     # (2,3) -> [1,1,1]
try:
    for kp, cnt in zip(kps, counts):
        result = self.generate_questions(..., knowledge_point_id=kp, options=per_kp_opts,
                                         defer_commit=True)   # 不在内层提交
        aggregate(result)
    self.session.commit()               # 全部成功：单次提交
except Exception:
    self.session.rollback()             # 任一失败：整批回滚，零遗留
    raise
```

#### 5. Tests Required
- `distribute_count` 边界：`(6,3)=[2,2,2]`、`(7,3)=[3,2,2]`、`(2,3)=[1,1,1]`、`(1,1)=[1]`、非法入参抛错。
- 编排：调用次数=去重考点数；各考点题量；聚合计数；题目 `knowledge_point_id` 覆盖集合；fail-fast（失败后不再调用后续考点）。
- **原子性（真实 SQLite）**：某考点抛 `MissingSourceSnippetError` → 落库计数为 **0**；全成功 → **单次** `commit()` 且全部落库。
- **单考点零回归**：`generate_questions` 默认 `defer_commit=False` 行为不变（内部自行提交）。
- API：多考点请求返回 `knowledge_point_ids` 与聚合题目；**旧单考点请求零回归**。

---

### Scenario: Secret Resolution Must Go Through Strongly-Typed Settings

#### 1. Scope / Trigger
- 任何读取密钥/凭证的代码路径（JWT 签名与验签、第三方 provider 密钥、DB 口令等）。

#### 2. Signatures
- Settings 模型：`Settings.secret_key: SecretStr`，环境变量名由 `model_config = SettingsConfigDict(env_prefix="ZHILIAN_")` 派生，即 **`ZHILIAN_SECRET_KEY`**。
- 读取入口：`get_settings().secret_key.get_secret_value()`。

#### 3. Contracts
- **唯一真相源**：密钥必须经 `get_settings()` 读取，**禁止**裸 `os.getenv("SECRET_KEY", ...)` 直接取密钥——`env_prefix="ZHILIAN_"` 会使规范注入的 `ZHILIAN_SECRET_KEY` 落在 Settings 上，裸 `SECRET_KEY` 恒为未设置并静默回退默认值。
- 开发默认密钥仅允许在**非生产**环境生效；生产检测到仍为默认密钥时须 fail-fast（启动期抛错）。

#### 4. Validation & Error Matrix
- 未配置密钥 + 非生产 → 使用开发默认密钥（记录警告）。
- 未配置密钥 + 生产 → 启动失败（fail-fast）。
- 已配置 `ZHILIAN_SECRET_KEY` → 必须与 `settings.secret_key` 一致。

#### 5. Wrong vs Correct
##### Wrong
```python
# 错误：绕过 Settings，忽略 ZHILIAN_ 前缀，生产注入被无视并回退硬编码默认密钥
DEFAULT_SECRET_KEY = "zhilian-insecure-development-...-2026"
def get_secret_key() -> str:
    return os.getenv("SECRET_KEY", DEFAULT_SECRET_KEY)
```
##### Correct
```python
# 正确：统一经强类型 Settings 读取（保留显式入参用于测试注入）
def get_secret_key(*, secret_key: str | None = None) -> str:
    if secret_key is not None:
        return secret_key
    return get_settings().secret_key.get_secret_value()
```

#### 6. Tests Required
- 只设置 `ZHILIAN_SECRET_KEY`、清空 `SECRET_KEY` 时，`get_secret_key()` **等于** `get_settings().secret_key`（守本缺陷回归）。
- 生产 + 默认密钥 → 启动期 fail-fast 断言。
- 显式 `secret_key` 入参优先级高于 Settings。

---

### Scenario: Backend↔Frontend Response Field-Name Contract Pinning

#### 1. Scope / Trigger
- 任何新增/变更的 API 响应模型，其字段会被前端 `src/api/*`、`src/types/*`、store 或组件直接消费时。

#### 2. Contracts
- 响应字段名是**跨层契约**，后端 schema 字段名即为契约真名；前端类型与绑定必须逐字段对齐，**不得**在两侧各用一套命名。
- 需要别名/兼容时，必须在**同一处**显式声明（后端 `alias`/`serialization_alias`，或前端统一归一化层），并在响应模型上以注释标注。
- 已知高风险命名族（历史缺陷）：
  - 题目选项：后端 `{key, content}` vs 前端 `{key, text}` → 客观题选项渲染为空。
  - 练习详情/创建题目列表：后端 `items[]`（元素 `question_snapshot`）vs 前端 `questions` → 会话题目恒空。
  - 诊断薄弱知识点：后端 `weak_knowledge_points` vs 前端 `weak_points` → 卡片不渲染。

#### 3. Validation & Error Matrix
- 前端读取到未定义字段 → `undefined`，绑定静默渲染为空（不报错、不抛异常）——**最隐蔽**，测试夹具若两侧各用一套命名亦无法发现。

#### 4. Tests Required
- 前端 api/类型层测试的夹具字段名必须**逐字取自真实后端响应模型**，禁止自造字段名。
- 交叉契约测试：以真实后端响应模型（或其 `model_json_schema()`）为准，断言前端类型/归一化输出的字段存在且非 `undefined`。
- `pytest` 与 `vitest` 夹具字段名须同源（如从共享 schema/常量派生），防止双侧夹具各自漂移而同时“通过”。

#### 5. Wrong vs Correct
##### Wrong
```typescript
// 错误：前端自造 questions/text，与后端 items/content 脱节，测试也自造同名夹具 → 双侧假绿
practiceStore.initSession(id, res.data.questions);      // 后端是 items
<text>{{ option.text }}</text>                          // 后端是 option.content
```
##### Correct
```typescript
// 正确：字段名以后端响应模型为准；需要适配则集中在一处归一化
const items = res.data.items.map(adaptItem);            // items -> 内部模型
<text>{{ option.content }}</text>                       // 与后端 content 对齐（或归一为 text 后统一消费）
```

---

### Scenario: Content-Hash Dedup Must Not Share Physical Storage Objects

#### 1. Scope / Trigger
- 任何按内容哈希做上传「秒传」/去重的资料路径（`MaterialService.create_material`）与硬删除清理（`hard_delete_material`）。

#### 2. Contracts
- **哈希只用于逻辑去重，不作为跨资料共享物理对象键**：命中同用户同哈希的历史版本时，新资料仍必须 `put_object` 到**本资料自有** `storage_key`（`build_material_storage_key(user_id, material.id, ...)`），不得复用 `existing_ver.storage_key`。
- 理由：`hard_delete_material` 按本资料 versions 收集 `storage_key` 并无条件 `delete_object`；若键被跨资料共享，删除源资料会连带使引用方指向已删对象，后续 `storage.get_object` 抛 `StorageNotFoundError`。
- 现有实现命中后**仍入队完整解析**，故复用的唯一收益是省一次 `put_object`；以少量存储换数据完整性是正确的取舍。

#### 3. Validation & Error Matrix
- 同哈希两份资料：两者 `storage_key` 必须不同。
- 硬删源资料后：引用方对象仍存在且可解析。

#### 4. Wrong vs Correct
##### Wrong
```python
# 错误：跨资料复用物理键，源资料硬删后引用方指向已删对象
existing_ver = self.repo.find_version_by_hash(user_id, content_hash)
storage_key = existing_ver.storage_key if existing_ver else build_key(...)   # 共享！
```
##### Correct
```python
# 正确：始终写本资料自有键；content_hash 仅落库表达逻辑去重
storage_key = build_material_storage_key(user_id, material.id, 1, content_hash, fmt)
self.storage.put_object(self.bucket, storage_key, file_content, content_type)
```

#### 5. Tests Required
- 断言同哈希两资料 `storage_key` 不同。
- 断言硬删源资料后，另一资料对象仍可取用。

---

### Scenario: OCR Retake State Machine & Knowledge-Tree Rebuild

#### 1. Scope / Trigger
- 图片资料 OCR 质检未达标后的「待重拍 → 逐页重拍 → 达标」闭环，及重拍完成后的知识树重建。

#### 2. Signatures
```python
# MaterialStatus 新增
class MaterialStatus(enum.StrEnum):
    ...
    RETAKE_REQUIRED = "retake_required"

# GET /api/v1/materials/{material_id}/ocr-pages?only_unqualified=false
# -> MaterialOCRPagesResponse{ material_id, version_id, items[ page_number, is_qualified, reshoot_count, unqualified_reason ] }
# POST /api/v1/materials/{material_id}/reshoot   (multipart: page_index=Form, file=File, version_id=Form 可选)
```

#### 3. Contracts
- **门禁失败语义**：OCR 质检不达标时，版本 `parse_status=FAILED` 且 `failed_stage='ocr_quality_gate'`，**资料主状态置 `RETAKE_REQUIRED`**（可恢复，非终态 FAILED）。
- **状态筛选**：`_resolve_status_filter('retake_required')` 返回 `[retake_required]`（禁止返回 `[]` 造成「筛选恒空」）；列表/详情/`statusTag` 大小写归一一致。
- **重拍解析版本**：`reshoot_material_page` 在 `material.current_version_id` 为空（门禁失败时常见）必须回退 `get_latest_version`，否则重拍主路径直接失败。
- **重拍达标后续（关键）**：全页达标重建 slices 时，必须**同步重建知识树**——`update_version_status(EXTRACTING_KNOWLEDGE)` → `knowledge_service.extract_and_build_knowledge_tree(...)`（内部含 `delete_knowledge_points_by_version`）→ 置 READY。置 READY 时须 `reset_errors=True` 清除 `failed_stage`/`error_message`，避免 READY 与失败阶段并存的矛盾终态。
- **重拍未达标**：资料维持/置 `RETAKE_REQUIRED`；`reshoot_count >= 3` 仍未达标 → 熔断置 `FAILED`（终态）。
- **前端**：待重拍页列表必须由 `/ocr-pages` 接口填充（禁止硬编码假页面）；轮询期间状态转入 `retake_required` 时须拉取真实不合格页。

#### 4. Wrong vs Correct
##### Wrong
```python
# 错误1：门禁失败置终态 FAILED，重拍入口不可达
self.repo.update_material_status(material_id, user_id, MaterialStatus.FAILED.value)

# 错误2：重拍达标只重建 slices，不重建知识树 → READY 资料知识树空/陈旧
self.repo.delete_snippets_by_version(version_id, user_id)
self.repo.create_snippets(new_snippets)
self.repo.update_version_status(version_id, user_id, ParseStatus.READY.value)

# 错误3：重拍只看 current_version_id，门禁失败时其为 None → 重拍必然报错
version = self.repo.get_version_by_id(material.current_version_id, user_id)
```
##### Correct
```python
# 正确1：门禁失败置可恢复的 RETAKE_REQUIRED
self.repo.update_material_status(material_id, user_id, MaterialStatus.RETAKE_REQUIRED.value)

# 正确2：达标重建 slices 后串联知识树重建再置 READY
self.repo.delete_snippets_by_version(version_id, user_id)
self.repo.create_snippets(new_snippets)
if self.knowledge_service is not None:
    self.repo.update_version_status(version_id, user_id, ParseStatus.EXTRACTING_KNOWLEDGE.value)
    self.knowledge_service.extract_and_build_knowledge_tree(
        material_id=material_id, version_id=version_id, user_id=user_id,
    )
self.repo.update_version_status(version_id, user_id, ParseStatus.READY.value, reset_errors=True)

# 正确3：无激活版本时回退最新版本
version = self.repo.get_version_by_id(material.current_version_id, user_id) or \
    self.repo.get_latest_version(material_id, user_id)
```

#### 5. Tests Required
- 门禁失败 → 资料状态 `retake_required`；`retake_required` 筛选返回真实条目。
- `/ocr-pages` 返回不合格页；仅校验租户归属。
- 重拍达标 → 调用知识树重建入口 + 知识点非空 + `failed_stage`/`error_message` 清空。
- 无 `current_version_id` 时重拍回退最新版本成功。
- 前端详情由接口（非硬编码）填充待重拍列表；轮询转入 `retake_required` 拉取页面。

---

### Scenario: Practice Item Grading Status & Degraded-Score Semantics

#### 1. Scope / Trigger
- 练习/报告逐题判级展示，以及判题失败降级（待重判）、同步重判回填。

#### 2. Signatures
- `PracticeItemDetailResponse.grading_status: str | None`（附加可选）∈ `unanswered | pending_regrade | graded`；`PracticeItemDetailResponse.status` 为**遗留字段**。
- `RegradeResponse.status: str = "success"`，新增 `score: float | None`、`is_final: bool = True`；`GradingService.regrade_attempt` **同步**返回生效记录。

#### 3. Contracts
- **`status` 不可作为判题状态来源**：`AttemptItem` 无 `status` 列，`PracticeItemDetailResponse.status` 对真实 ORM 恒为默认 `"unanswered"`（before-validator 触不到该键）。判题状态必须由显式 `grading_status` 表达。
- **`grading_status` 三态派生**（由 `is_answered`/`score`）：`is_answered is False` → `unanswered`；否则 `score is None` → `pending_regrade`；否则 `graded`。上游若显式提供则尊重（不覆盖）。
- **降级不变量**：待重判必须 `AttemptItem.score = None`（未定分），**禁止**写 `0.0`——否则与“真实 0 分（判错）”不可区分。汇总口径 `sum(it.score or 0.0)` 已容忍 `None`；`GradingRecord.score` 可保持 `0.0`。
- **前端判定优先级**：`grading_status` 显式存在时**优先**（pending/unanswered 直接命中；`graded` 走 score 阈值），**不得**再回落到遗留 `status`；仅当 `grading_status` 缺失（旧数据）时回退 `status`。
- **重批为同步**：成功即 `status="success"` 且回传新 `score`；前端据此就地更新分数并判级，**禁止**成功路径硬编码 `pending_regrade`。

#### 4. Validation & Error Matrix
- 已答 + `score=None` → `pending_regrade`（显示“待重新判题/待判定”）。
- 未作答（`is_answered=False`）→ `unanswered`。
- 已判分（`score` 有值，含 `0.0`）→ `graded`（再按 `score >= max*0.6` 判对/判错）。
- `grading_status='graded'` + 遗留 `status='unanswered'` → 必须按 score 渲染，**不得**显示“未作答”。

#### 5. Wrong vs Correct
##### Wrong
```python
# 错误1：降级 pending 仍写 0.0，与真实 0 分（判错）混淆
item.score = 0.0            # status=pending_regrade

# 错误2：前端把遗留 status 当判题状态
if item.status === 'unanswered': return UNANSWERED   # 真实 ORM 恒为 unanswered → 全部误判未作答
```
##### Correct
```python
# 正确1：待重判 = 未定分
item.score = None           # grading_status 派生为 pending_regrade
```
```typescript
// 正确2：显式 grading_status 优先，仅缺失时回退遗留 status
const gs = item.grading_status;
if (gs === 'pending_regrade') return PENDING;
if (gs === 'unanswered') return UNANSWERED;
if (gs == null) { /* legacy fallback on item.status */ }
if (item.score == null) return PENDING;
return item.score >= max * 0.6 ? CORRECT : WRONG;
```

#### 6. Tests Required
- 服务：LLM 超时降级 → `AttemptItem.score is None` 且 `GradingRecord.status == pending_regrade`。
- Schema：`grading_status` 三态（unanswered / pending_regrade / graded）与显式覆盖不重算。
- 路由：重批成功返回 `status="success"` 与新 `score`。
- 前端：`grading_status` 优先级、`graded` 覆盖遗留 `status='unanswered'`、重批成功就地更新分数文本。
- 夹具字段名逐字取自后端；双侧夹具同源，禁各自漂移。

---

### Scenario: Diagnosis Report Adaptation, Mastery Aggregation & Regression Sign

#### 1. Scope / Trigger
- 学情诊断报告展示、掌握度宏观全景、薄弱/退步知识点预警。

#### 2. Signatures
- 前端适配：`adaptDiagnosisReport(raw) -> DiagnosisReport`（`src/api/adapters/diagnosis.ts`，唯一归一化边界）。
- 后端：`DiagnosisService.get_user_mastery_overview(user_id, material_id: uuid.UUID | None = None, ...)`。
- 纯函数：`check_regression(current_score, previous_score, threshold) -> (is_regressed, score_delta)`。

#### 3. Contracts
- **报告字段归一（前端适配层）**：后端响应为 `weak_knowledge_points`、`score_rate`(0–1)、`mastery_before/after`(0–1)；前端内部契约为 `weak_points`、`overall_score`(0–100)、`mastery_rate`(0–100)。归一集中一处，幂等且**后端已给值优先**：`weak_points ?? weak_knowledge_points`、`overall_score ?? round(score_rate*100)`、`mastery_rate ?? round((mastery_after ?? score_rate)*100)`。消费点（store/组件）禁止各自映射。
- **掌握度全景缺省资料**：`material_id is None` 时必须聚合该用户**全部**知识点（`list_all_by_user_id` + `list_mastery_records_by_user`），**禁止**落成 `material_id IS NULL`（`KnowledgePoint.material_id` 为 NOT NULL → 恒空）。带 `material_id` 路径零回归；租户隔离必须保留。
- **退步符号唯一约定**：`score_delta = current_score - previous_score`（**负数 = 退步**），`is_regressed = score_delta <= -threshold`；与 `RegressedKnowledgeItemDTO`（负数=退步）及前端 `formatScoreDelta`（负数=退步）一致。排序保持“最弱优先 + 降幅最大优先”。

#### 4. Validation & Error Matrix
- 后端已提供 `weak_points`/`overall_score`/`mastery_rate` → 适配层不得覆盖（幂等）。
- `material_id=None` → 跨资料聚合；`material_id=UUID` → 单资料（零回归）。
- 退步集合不变：`prev-cur >= thr` ≡ `cur-prev <= -thr`；仅返回值符号翻转。

#### 5. Wrong vs Correct
##### Wrong
```python
# 错误：material_id 为 None 仍按 material_id == None 过滤（NOT NULL 列 → 恒空）
knowledge_points = repo.list_by_material_id(material_id=None, user_id=user_id)
# 错误：退步为正（与前端的负数约定相反）
score_delta = round(previous_score - current_score, 4)
```
##### Correct
```python
# 正确：缺省资料聚合全部；符号统一 current - previous
points = repo.list_all_by_user_id(user_id) if material_id is None \
    else repo.list_by_material_id(material_id, user_id)
score_delta = round(current_score - previous_score, 4)
is_regressed = score_delta <= -threshold
```

#### 6. Tests Required
- 适配层：后端形态夹具（`weak_knowledge_points`/`score_rate`/`mastery_after`，无前端字段）→ `weak_points` 非空、`overall_score`/`mastery_rate` 非零；已含前端字段时幂等。
- 服务：`material_id=None` 聚合全部知识点且租户隔离（真实 SQLite）；带 `material_id` 零回归。
- 算法：退步 `score_delta` 为负且 `is_regressed` 为真；提升为正且为假；排序最弱/降幅最大在前。
- 前端 `formatScoreDelta` 保持负数=退步，退步徽章渲染正确。

---

### Scenario: Wrong-Book Pagination, Mastery Toggle & Continue-Practice Contract

#### 1. Scope / Trigger
- 错题本列表分页、攻克状态切换、错题作答回显，以及“一键巩固错题”继续练习。

#### 2. Signatures
- `GET /api/v1/wrong-records` → `WrongRecordListResponse.total`（**真实总数**）。
- `DiagnosisRepository.count_wrong_records(user_id, is_mastered=None, knowledge_point_id=None) -> int`；`DiagnosisService.list_wrong_records(...) -> tuple[list[WrongRecord], int]`。
- `POST /api/v1/wrong-records/{id}/master`，可选体 `{"is_mastered": bool}`（缺省 True）。
- `WrongRecordItemResponse.user_answer: str | None`（映射实体 `last_wrong_answer`）。
- `POST /api/v1/practices`：`source_type` ∈ `{normal, weakness, wrong_record}`；`material_id` 可选。

#### 3. Contracts
- **分页 total 必须为全量计数**：列表接口 `total` 不得为 `len(items)`（当前页条数），否则前端 `hasMore = loaded < total` 在满页时恒 false、后续页永不可达。计数须与列表**同一过滤条件**（`user_id` 租户隔离 + `is_mastered` + `knowledge_point_id`）。
- **攻克可切换**：`master` 端点接受可选 `is_mastered`；缺省 `True`（向后兼容，无 body 仍置已攻克）；`False` 时 `is_mastered=False` 且 `mastered_at=None`。
- **作答回显**：错题 DTO 必须下发 `user_answer`（源实体 `last_wrong_answer`），覆盖 `from_attributes` ORM 解析路径。
- **继续练习来源与资料**：`source_type='wrong_record'` 合法；`material_id` 可选，缺省时由命中题目（`Question.material_id` NOT NULL）解析，**禁止**向 NOT NULL 列写 NULL；`knowledge_point_ids` 至少 1（前端无可用知识点时禁用入口）。

#### 4. Validation & Error Matrix
- `total` = 真实全量；满页时 `hasMore` 为真。
- `{is_mastered:false}` → false/None；无 body → true/时间戳。
- `last_wrong_answer=None` → `user_answer=None`（正确“未作答”），不得伪造。
- `source_type='wrong_record'` + `material_id=None` + `knowledge_point_ids≥1` → 201 创建成功。

#### 5. Wrong vs Correct
##### Wrong
```python
# 错误1：total 用当前页条数，满页时前端判定无更多
total_count = len(items)
# 错误2：master 端点无请求体，恒置已攻克（取消攻克无效）
record.is_mastered = True
# 错误3：继续练习要求 material_id 必填 + 合法 source_type 未含 wrong_record
material_id: uuid.UUID = Field(...)   # 错题本页常缺 → 422
```
##### Correct
```python
# 正确：真实计数（同过滤条件）；可选攻克；可选 material 由题目解析
total = repo.count_wrong_records(user_id, is_mastered=..., knowledge_point_id=...)
record.is_mastered = is_mastered
record.mastered_at = now if is_mastered else None
resolved_material_id = options.material_id or scattered_questions[0].material_id
```

#### 6. Tests Required
- 列表：真实 total > 页大小；租户隔离；满页 `hasMore` 为真、可翻页。
- 攻克：无 body → true；`{is_mastered:false}` → false 且 `mastered_at=None`；`true` → true 且时间戳。
- DTO：ORM/dict 两路径 `last_wrong_answer → user_answer`；`None` 保持 `None`。
- 继续练习：`wrong_record` + 无 `material_id` 创建成功（201）；旧 `normal`/`weakness` 零回归。



### Scenario: User Profile Update Endpoint & Auth Service Result Propagation

#### 1. Scope / Trigger
- 画像更新端点、吊销/注销端点返回值语义、微信登录同步 IO、依赖 fallback 会话托管。

#### 2. Signatures
- `PUT /api/v1/users/me` -> `UserProfileResponse`；`UpdateUserProfileRequest{nickname?, avatar_url?}`（`extra="forbid"`）。
- `AuthService.update_user_profile(user_id, *, nickname=None, avatar_url=None) -> UserProfileResponse`；用户不存在抛 `AuthenticationError`。

#### 3. Contracts
- 前端声明的画像更新契约必须在后端落地，禁止契约悬空（接入即 405）。
- `revoke`/`delete` 端点必须透传 service 布尔结果到 `UserActionResponse.success`，失败不得报告成功。
- async 路由中调用同步阻塞的第三方 HTTP（`httpx.get`）必须经 `run_in_threadpool` offload，禁止阻塞事件循环。
- DI fallback 若用 `session_factory()` 新建 Session，必须以 `with container.get_session()`/生成器依赖托管关闭，禁止裸建不关闭造成连接泄漏。

#### 4. Tests Required
- PUT 合法/部分更新 200、用户不存在 401、非法字段 422；service 返回 False 时响应 `success=false`；fallback 路径 session 关闭断言。

### Scenario: Knowledge Extraction Robustness, Upload Size Guard & Object Cleanup

#### 1. Scope / Trigger
- LLM 知识点抽取落库、资料上传体积门禁、OCR 重拍/硬删除的对象存储清理、资料 DTO 统计字段装配。

#### 2. Contracts
- 候选知识点索引必须在 `n<=1` 与 `n>1` 两条路径**都**去重（`sorted(set(...))`）；落库 `KnowledgePointSnippet` 关联前再以 `(kp_id, snippet_id)` 集合判重，绝不触发 `uq_knowledge_point_snippets_kp_snippet`。
- LLM 输出 `temp_id` 必须做唯一性规整：重命名后的新 id 不得占用其他节点已存在的 `temp_id`（含 `__dup_{n}` 形态），并同步修正子节点 `parent_temp_id`，保证每个实体独立 UUID。
- 上传端点必须**先**校验 `Content-Length`（缺失则跳过，畸形按 -1），随后按 64KB 分块累加读取，累计超上限立即中断并抛 `MaterialInvalidError(status_code=413, error_code=40001)`；禁止先全量 `file.read()` 再校验。
- 重拍替换的旧对象 key 必须在**成功 commit 之后**清理；硬删除复用同一清理助手；被其他页/版本引用的 key 不得删除；单 key 清理失败仅告警不阻断。
- DTO 新增统计字段一律附加可选 `int | None = Field(default=None, ge=0)`（未就绪 0/None），装配查询数须为常数级（禁止 N+1）。

#### 3. Tests Required
- 单候选重复 snippet index 不崩；重复 temp_id（含与既有 `__dup_1` 冲突）父子关系保持正确；声明超限与谎报 Content-Length 均返回 413 且不进入 `import_material_file`；重拍后旧 key 被删、commit 失败不删；列表统计装配查询数常数级。

### Scenario: Question Generation Bounds, Delete Reason & Answer-Conflict Domains

#### 1. Scope / Trigger
- 出题数量校验、题目删除原因传递、客观题答案冲突判定。

#### 2. Contracts
- 出题数量硬上限以后端为准（1–20）；前端输入框/校验必须与之逐字对齐，禁止前端放行 >20 的请求。
- 删除原因参数位置统一为 **Query**（前端拼接 `?reason=`，不发送 body）；后端以 Query 为准并对旧客户端保留 JSON body 兜底。
- `check_answer_conflict` 仅在**同一答案域**内比对：`true_false` 与选择题之间答案域不兼容，跨域即使题干相似度超阈值也不判冲突；同域答案相反/不同仍须判冲突。
- `question_types` 必须非空（`min_length=1`）且每项为合法 `QuestionType`，请求 schema 与 `GenerateQuestionsOptions.__post_init__` 双向校验。

#### 3. Tests Required
- >20 被前端拦截且后端 422；空/非法题型在 schema 与服务层均抛错；query 与 body-only 两种删除原因均落审计；跨题型不误判、同域相反答案仍判冲突。

### Scenario: Practice State Machine, Idempotent Replay & Detail Field Semantics

#### 1. Scope / Trigger
- 练习状态持久化与跃迁、交卷幂等回放标记、作答保存状态白名单、详情 `mode`/`completed_count`。

#### 2. Signatures
- `PracticeStatus`（StrEnum）必须包含 `not_started/in_progress/paused/timeout/partially_graded/completed`；service 禁止以字面量持久化状态。
- `PracticeSubmissionResult.is_idempotent_replay: bool = False`；命中幂等缓存回放分支时置 `True`，正常提交保持 `False`。
- `PracticeService.save_answer` 仅允许 `NOT_STARTED`（自跃迁为 `IN_PROGRESS`）与 `IN_PROGRESS`，其余一律 `PracticeStatusError`（40011/HTTP 400）。
- `PracticeDetailResponse.completed_count` 由 `items[].is_answered` 派生；`mode` 落库于 `Practice.mode`，旧行/None 回退 `"sequential"`。

#### 3. Contracts
- 新增状态值必须同时纳入 `validate_practice_transition`：`PAUSED` 可恢复至 `IN_PROGRESS`；`TIMEOUT` 为不可逆终态。
- 新增列须有对称的 Alembic 迁移（`batch_alter_table` 保证 SQLite 可用），`down_revision` 挂在真实 head 上。
- 详情派生字段不得覆盖调用方显式提供的非零值。

#### 4. Tests Required
- 首次提交 `is_idempotent_replay=False`、二次回放 `True`；`PAUSED/TIMEOUT/PARTIALLY_GRADED` 真实 service 拒绝作答且 `NOT_STARTED` 首次保存仍可；`PAUSED→IN_PROGRESS` 有效、`TIMEOUT` 不可逆；`mode="random"` 详情回读且 `completed_count` = 已答数；迁移 upgrade/downgrade 对称可执行。

### Scenario: Submit Snapshot Fault-Tolerance, Elapsed Aggregation & Answer Serialization

#### 1. Scope / Trigger
- 交卷幂等快照写入失败、练习详情耗时、多选作答序列化。

#### 2. Contracts
- `set_result`（幂等快照）失败不得让已提交的交卷返回 5xx：捕获降级记录告警，并释放幂等锁，使同 key 重试可回放。
- 若幂等缓存未命中但练习已是 COMPLETED 且 `submit_idempotency_key == 请求 key`，必须从 DB 重建回放结果，禁止返回 40011；不同 key 仍拒绝。
- `PracticeDetailResponse.time_elapsed_seconds` 附加可选（默认 0），由 items 的 `duration_seconds` 聚合；历史无耗时为 0。
- `save_answer` 对 list/dict 作答以 `json.dumps(..., ensure_ascii=False)` 落库；DTO 输出时把历史 Python repr（`"['A', 'B']"`）容错归一为 JSON，标量不得被改写。

#### 3. Tests Required
- `set_result` 抛错时交卷成功且同 key 可回放、不同 key 40011；耗时聚合（含 0）；多选落库可 `json.loads`、历史 repr 归一；标量不变。

### Scenario: Grading Keyword/Snippet Enrichment & Effective-Record Selection

#### 1. Scope / Trigger
- 练习/报告逐题接口需下发判题命中要点与原文切片；判题记录多版本时的生效选择。

#### 2. Signatures
- `PracticeItemDetailResponse` / `QuestionSnapshotDTO` 附加可选 `hit_keywords: list[str]`、`missing_keywords: list[str]`、`source_snippet: SourceSnippetDTO | None`。
- `SourceSnippetDTO{id, chapter_title, page_index, snippet_content}`。
- `MaterialRepository.list_snippets_by_ids(ids, user_id)`（批量+租户过滤）。

#### 3. Contracts
- 要点字段须在顶层与 `question_snapshot` 双同步，前端二者任一可读；来源为**该作答项唯一生效**（`is_final=True`）的 `GradingRecord`，禁止泄漏被取代记录。
- 原文切片按 `source_snippet_id` 批量关联（单查询、按 `user_id` 过滤，禁 N+1、禁跨用户泄漏）；缺失时 DTO 为 `None`，前端渲染空态。
- 装配判题记录须 `selectinload` 预加载（固定查询数）；`get_practice` 返回 `PracticeDetailResponse` 时保持既有调用方兼容。

#### 4. Tests Required
- 顶层/嵌套两来源均渲染要点；生效记录覆盖旧记录且不泄漏旧关键词；切片缺失空态；预加载查询数常数级。

### Scenario: Deterministic Half-Up Score Rounding & Grade-Record Transaction Safety

#### 1. Scope / Trigger
- 主观题得分舍入、LLM 判分/重批粒度、自评正误契约、判题记录失效/生效顺序。

#### 2. Contracts
- 得分舍入必须为**确定性 half-up**（`Decimal` + `ROUND_HALF_UP`，粒度默认 0.5），禁止使用 Python 原生 `round`（银行家舍入）；`.25`/`.75` 边界必须稳定向上。
- LLM 首次判分与重批：先 clamp 到 `[0, max_score]`，再 `round_half_up(..., SCORE_ROUNDING_UNIT)`；全链路分值必须为 0.5 整数倍。
- `SelfEvaluateDTO.is_correct` 附加可选；显式值时优先采纳，`None` 才回退 `score > 0`。
- `_grade_attempt_item` 必须在算法**成功产出结果后**才失效旧记录并写入新生效记录；算法异常须捕获并降级 `pending_regrade`，保证任一时刻恰有一条 `is_final` 记录、不整卷崩溃。

#### 3. Tests Required
- `round_half_up(9.25,0.5)==9.5`、`(7.25)==7.5`（对比 `round(9.25/0.5)*0.5==9.0`）；LLM 7.3→7.5、8.24→8.0；`is_correct` 显式覆盖与默认回退；算法异常时单 final + 原记录保留 + 不崩整卷。

### Scenario: Diagnosis Mastery Counts, Filter Pushdown & Delete Contract

#### 1. Scope / Trigger
- 掌握度概览计数、错题本多维过滤（error_type/question_type/material_id）、删除错题响应字段。

#### 2. Contracts
- `UserMasteryOverviewResponse` 的 `mastered_count`/`learning_count` 必须与 `proficient_count`/`basic_count` 同步（before/after 校验器均须覆盖 dict 与 ORM/DTO），且**不得用 0 覆盖真实计数**。
- 错题过滤必须**下推 SQL**（`error_type` 等值、`question_snapshot["question_type"].as_string()`、`material_id` 经 `KnowledgePoint` JOIN 且租户过滤）；`list` 与 `count` 必须共享同一 WHERE，`total` 反映过滤后真实总数；未知枚举值返回空而非静默全量。
- 禁止内存 `limit=1000` 截断；分页与计数必须在 DB 层完成。
- `DeleteWrongRecordResponse` 必须包含 `removed`（附加可选，默认 True）并在所有删除路径下发。

#### 3. Tests Required
- DTO 计数同步（dict/ORM）；error_type 简写归一与非法值空结果；question_type/material_id 过滤与 count 一致；>1000 行无截断且 total 精确；删除响应含 `removed`。

### Scenario: Report Generation Race, Create-Practice Idempotency & Mastery Ordering

#### 1. Scope / Trigger
- 报告生成并发唯一键冲突、`POST /practices` 幂等创建、掌握度全景薄弱点排序。

#### 2. Contracts
- 报告生成先查后插若并发撞 `practice_id` 唯一约束，必须捕获 `IntegrityError`、`rollback()` 后回查并返回既有报告；非冲突异常不得吞掉。
- `POST /practices` 幂等：头名与前端逐字一致（`Idempotency-Key`）；命中已完成快照则回放（不取锁），并发同 key 拒绝（409），无 key 走旧链路；**锁必须在任何失败路径释放**，快照写入失败须降级告警（不得 commit 后 500 或泄漏锁）。
- `get_user_mastery_overview` 的薄弱点按 `(mastery_score, knowledge_point_id)` 升序稳定排序（最弱在前）。

#### 3. Tests Required
- 并发 `IntegrityError` → rollback + 回查返回既有报告；同 key 并发 409；快照写失败仍成功且锁释放可重试；无 key 零回归；薄弱点严格升序（含并列稳定）。

---

### Scenario: Course Folder Archive, Lazy Purge & Material Attribution

#### 1. Scope / Trigger
- 单层「课程文件夹」实体（`material_folders`）、资料归属（`materials.folder_id`）、归档 / 恢复 / 逾期惰性清理，以及按课程过滤与资料移动。

#### 2. Signatures
- 表 `material_folders`；`materials.folder_id`（可空 FK → `material_folders.id` ON DELETE SET NULL）。
- API：`POST/GET/GET{id}/PATCH/DELETE /folders`、`POST /folders/{id}/restore`、`DELETE /folders/{id}/purge`；`POST /materials/upload` 可选 `folder_id`；`GET /materials?folder_id=<uuid|__none__>`；`PATCH /materials/{id}/folder` body `{folder_id: UUID|null}`。

#### 3. Contracts
- **归档即软删除**：`DELETE /folders/{id}` 只写 `archived_at=now`，不回退资料、不物理删除；`purge_after = archived_at + 7d`。列表默认 `archived_at IS NULL` 隐藏归档课程，`include_archived=true` 才返回。
- **资料随课程隐藏（查询层口径）**：`materials.folder_id` 指向归档课程的资料在列表/详情默认隐藏；未分类（`folder_id IS NULL`）不受影响。过滤条件为 `folder_id IS NULL OR MaterialFolder.archived_at IS NULL`。
- **惰性清理副作用**：`list_folders` / `get_folder` 入口先把 `archived_at < now - 7d` 的课程物理级联清理（复用 `MaterialService.hard_delete_material` 逐个硬删其下资料，再删课程行），**必须显式 commit**；单课程清理失败仅 `rollback()` 并告警，不得阻断本次只读查询返回。无需常驻调度器。
- **ON DELETE SET NULL vs purge**：归档不触发 FK 级联；只有显式 `purge` / 惰性清理才逐个硬删资料（FK 的 SET NULL 只兜底课程行被删而资料保留的场景）。
- **多租户隔离**：所有仓储方法强制 `user_id` 过滤；越权访问课程返回 `FolderNotFoundError`（404）。同用户重名 `FolderNameConflictError`（409）。
- **移动校验**：目标课程须归属当前用户且未归档，否则 404；`folder_id=null` 移回未分类。
- **聚合计数 N+1 防护**：列表聚合计数必须走批量分组查询（`_by_folder_ids`），禁止逐课程循环查询。

#### 4. Wrong vs Correct
##### Wrong
```python
# 错误：查询层不过滤归档课程，且惰性清理在只读 GET 里不提交事务
stmt = select(Material).where(Material.user_id == user_id)   # 归档课程的资料仍可见
expired = repo.list_expired(user_id, before=...)
for f in expired:
    self.purge_folder(user_id, f.id)   # purge 未 commit → 只读会话回滚，清理丢失
```
##### Correct
```python
# 正确：可见性过滤 + 清理入口显式提交且失败降级不阻断
stmt = stmt.outerjoin(MaterialFolder, Material.folder_id == MaterialFolder.id).where(
    or_(Material.folder_id.is_(None), MaterialFolder.archived_at.is_(None))
)
for f in self.repo.list_expired(user_id, before=datetime.now(UTC) - timedelta(days=7)):
    try:
        self.purge_folder(user_id, f.id)   # 内部 list/hard_delete/commit
    except Exception:
        self.session.rollback()            # 降级为本次不清理，查询照常返回
```

#### 5. Tests Required
- 模型/迁移：`(user_id, name)` 唯一约束；`Material.folder_id` FK `SET NULL`；迁移 0005 `upgrade → downgrade → upgrade` 对称。
- 仓储：CRUD、归档默认隐藏、`list_expired` 阈值、批量计数、跨租户隔离。
- 服务：重名 409、越权 404、归档/恢复、`purge_after=+7d`、**`archived_at=now-8d` 时任意列表查询物理删除课程及其资料**、聚合计数、移动（未分类↔课程、目标归档/他人 404）。
- API：课程各端点状态码与响应契约；上传带/不带 `folder_id`；列表 `__none__` 与非法 `folder_id` 400；`PATCH /materials/{id}/folder`。

---

### Scenario: Course Folder Scope Generation & Practice Assembly

#### 1. Scope / Trigger
- 将「出题」与「组卷」范围从单份资料扩展到课程文件夹：`POST /questions/generate` 携带 `folder_id`、`GET /questions?folder_id=`、`POST /practices` 携带 `folder_id`。

#### 2. Signatures
- Schema：`QuestionGenerateRequest.folder_id`（可选，与 `material_id` 至少一个）；`QuestionGenerateResponse` 的 `material_id/version_id/knowledge_point_id` 均可空；`PracticeCreateRequest.folder_id`（可选，`knowledge_point_ids` 允许为空）。
- Service：`QuestionService.generate_questions_for_folder(*, user_id, folder_id, knowledge_point_ids=None, options=None) -> MultiKnowledgePointGenerationResult`；`PracticeService.create_practice(user_id, CreatePracticeOptions(..., folder_id=None))`。
- Repository：`QuestionRepository.list_questions(..., folder_id=...)`、`list_knowledge_points_for_folder(user_id, folder_id)`、`list_material_ids_for_folder(user_id, folder_id, *, ready_only=False)`。

#### 3. Contracts
- **归档一致性**：folder 范围出题 / 组卷 / 题目列表一律排除归档课程资料（`MaterialFolder.archived_at IS NOT NULL`）；未分类资料（`folder_id IS NULL`）不参与任何 folder 范围；单资料路径不受归档过滤影响（零回归）。
- **范围解析**：显式 `knowledge_point_ids` 必须逐个校验其 `material_id` 属于该文件夹未归档资料，否则 `KnowledgeNotFoundError`；缺省取文件夹全部 ready 未软删除资料的考点，为空则明确 4xx（不静默成功）。
- **跨资料单事务原子**：按 `(material_id, version_id)` 保序分组；题量先按组 `distribute_count`，再在组内按考点 `distribute_count`（均分 + 余数前置 + 每组至少 1）；逐组调用既有链路且传 `defer_commit=True`，**仅由外层在全部成功时 `commit()` 一次**，任一失败 `rollback()` + re-raise，零遗留部分题目。
- **`defer_commit` 契约**：`generate_questions_for_knowledge_points(..., defer_commit=False)` 默认仍自提交（单资料/单批零回归）；`True` 时仅 `flush`，不 `commit`/`rollback`，交由外层。
- **folder 组卷落库**：提供 `folder_id` 时 `material_id` 可为空且落库为空；`folder_id` 落库；`knowledge_point_ids` 存展开后的实际考点集；题量不足仍抛 `PracticeEmptyQuestionsError`（40012）。
- **课程聚合计数口径**：`FolderRepository.last_practice_at_by_folder_ids` 必须同时覆盖「资料范围练习」（`Practice.material_id` 经 `Material.folder_id` 归属）与「课程范围练习」（`Practice.folder_id` 直接指向课程、`material_id` 为空），取两者最大 `created_at`；仅按 `material_id` join 会漏算课程范围练习（`material_id IS NULL`）。

#### 4. Wrong vs Correct
##### Wrong
```python
# 错误1：folder 出题逐组各自提交，第 N 组失败时前 N-1 组已入库（非原子）
for group in groups:
    generate(...)  # 内部 commit()

# 错误2：显式考点不校验归属，可跨课程越界出题
kp = knowledge_repo.get_by_id(kp_id, user_id)
generate(kp)  # kp.material_id 可能不在目标文件夹

# 错误3：folder 组卷回填 material_id，破坏课程范围语义
if resolved_material_id is None:
    resolved_material_id = scattered_questions[0].material_id  # folder 范围必须保持 None
```
##### Correct
```python
# 正确：跨组单事务原子 + 归属校验 + 归档过滤 + folder 范围 material_id 保持空
allowed = set(question_repo.list_material_ids_for_folder(user_id, folder_id))
for kp_id in explicit_ids:
    kp = knowledge_repo.get_by_id(kp_id, user_id)
    if kp is None or kp.material_id not in allowed:
        raise KnowledgeNotFoundError(...)
for key, cnt in zip(group_keys, distribute_count(total, len(group_keys)), strict=True):
    generate_questions_for_knowledge_points(..., options=per_group_opts, defer_commit=True)
self.session.commit()        # 全部成功：唯一一次提交
# 任一失败：except → self.session.rollback(); raise
```

#### 5. Tests Required
- 分组与题量：`(4,2)` 组分配 + 组内分配；显式跨资料考点聚合、`knowledge_point_id`/`knowledge_point_ids` 契约。
- **原子性（真实 SQLite）**：某组抛 `MissingSourceSnippetError` → 落库计数为 0；全成功 → 单次 `commit()` 且全部落库。
- 缺省范围：仅纳入 ready 资料考点；无 ready 资料 / 无考点 → 4xx；归档课程 → `FolderNotFoundError`；跨租户越权 → 404；显式考点越界 → `KnowledgeNotFoundError`。
- 组卷：folder 范围 `material_id` 为空、`folder_id` 落库、缺省考点展开、题量不足 40012；单资料路径零回归。
- 仓储：`folder_id` 过滤与 `material_id` 组合、归档排除、`list_knowledge_points_for_folder`/`list_material_ids_for_folder`。
- 迁移 0006：`material_id` 改可空 + `folder_id` + 索引，`upgrade → downgrade → upgrade` SQLite 对称。