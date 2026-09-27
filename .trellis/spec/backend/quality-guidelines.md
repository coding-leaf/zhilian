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