# Quality Guidelines

> **事实源**：`backend/app/services/`、`backend/app/api/v1/`、`backend/app/repositories/`、`backend/app/models/`、`backend/app/core/`、`backend/app/integrations/`、`backend/app/cli/`、`backend/tests/`、`backend/migrations/`、`backend/pyproject.toml`、`Taskfile.yml`
> **最后核对**：2026-09-29 @ c6e1003
> **核对方式**：`rg -n "^### Scenario:|^#### 代码锚点" .trellis/spec/backend/quality-guidelines.md`，再按各 scenario 锚点 `rg` 复核

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
- Service: `MaterialService.retry_material_pipeline(*, material_id: uuid.UUID, user_id: uuid.UUID) -> tuple[Material, MaterialVersion]`（关键字参数、返回资料与版本二元组）

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
# 正确做法：以条件更新原子地把 failed 跃迁为 queued，并清空错误信息与失败阶段
# （reset_errors 内部置 None）。派发必须是原子的，见下方 not_started Scenario。
if not self.repo.try_transition_version_status(
    version.id, material_id,
    from_status=ParseStatus.FAILED.value,
    to_status=ParseStatus.QUEUED.value,
    reset_errors=True,
):
    raise MaterialInvalidError("解析重试已在处理中，请勿重复提交")
self.repo.update_material_status(
    material_id=material_id, user_id=user_id,
    status=MaterialStatus.PENDING.value, current_version_id=version.id,
)
self.session.commit()
self._enqueue_parse(material_id, version.id, user_id)   # 失败 → 回写 FAILED 且可见
```

#### 代码锚点
- `backend/app/api/v1/materials.py::retry_material_pipeline`
- `backend/app/services/material.py::MaterialService.retry_material_pipeline`
- `backend/app/repositories/material.py::MaterialRepository.update_version_status`

---

### Scenario: Dual-Mode Auth & Deterministic Development OpenID

#### 1. Scope / Trigger
- 小程序登录鉴权支持本地开发联调与线上真实环境无缝切换，避免生成临时假账号分裂数据。

#### 2. Contracts
- 若传入固定 `dev_code`，强制解析为确定性 OpenID `wx_dev_deterministic_user`。
- 若传入 `dev_` 或 `mock_` 前缀，强制解析为 `wx_dev_{code}`。
- 前端在授权失败时，严禁向本地 Store 写入任意未验证或伪造的 Token（如 `mock_access_token_*`），避免 401 拦截器死锁。

#### 代码锚点
- `backend/app/services/auth.py::AuthService._resolve_wechat_openid`

---

### Scenario: LangGraph Schema-as-Tool Calling Pipeline

#### 1. Scope / Trigger
- LLM 结构化抽取（知识考点抽取、题目生成等）强制采用原生 OpenAPI Function Calling 模式。

#### 2. Contracts
- 模型选项通过 `LLMOptions(tools=[...], tool_choice={"type": "function", ...})` 透传。
- 状态图节点 `validate_output_node` 优先从 `raw_response.tool_calls` 提取入参反序列化，仅在未命中工具调用时才作为纯文本降级处理。

#### 代码锚点
- `backend/app/integrations/llm/agent_graph.py::pydantic_to_tool_schema`
- `backend/app/integrations/llm/agent_graph.py::call_model_node`
- `backend/app/integrations/llm/agent_graph.py::validate_output_node`
- `backend/app/integrations/llm/agent_graph.py::run_structured_agent_workflow`

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

#### 代码锚点
- `backend/app/cli/main.py::main`
- `backend/app/cli/errors.py::CliError`
- `backend/app/cli/commands/doctor.py::handle`
- `backend/app/cli/smoke.py::register`
- `backend/app/cli/context.py::CliContext.assert_real_providers`
- `backend/app/cli/report.py::redact_url`

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

#### 代码锚点
- `backend/app/integrations/search/protocol.py::SearchSnippetCandidate`
- `backend/app/services/question.py::QuestionService._retrieve_and_gate_snippets`
- `backend/app/core/algorithms/search.py::compute_bm25_score`
- `backend/app/integrations/search/pgvector.py`（`final_score` 由 RRF 融合产生）

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

#### 代码锚点
- `backend/app/integrations/llm/agent_graph.py::pydantic_to_tool_schema`（仅强制调用，未输出 `strict`）
- `backend/app/integrations/llm/protocol.py::LLMOptions.tool_choice`
- `backend/app/core/errors.py::LLMResponseFormatError`

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

#### 代码锚点
- `backend/app/services/question.py::distribute_count`
- `backend/app/services/question.py::MultiKnowledgePointGenerationResult`
- `backend/app/services/question.py::QuestionService.generate_questions_for_knowledge_points`
- `backend/app/api/v1/questions.py`（多考点请求分支）

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

#### 代码锚点
- `backend/app/core/security.py::get_secret_key`
- `backend/app/core/config.py::AppSettings.secret_key`
- `backend/app/core/config.py::DEVELOPMENT_SECRET_KEY`
- `backend/app/core/config.py::validate_secret_key`

---

### Scenario: Backend↔Frontend Response Field-Name Contract Pinning

#### 1. Scope / Trigger
- 任何新增/变更的 API 响应模型，其字段会被前端 `src/api/*`、`src/types/*`、store 或组件直接消费时。

#### 2. Contracts
- 响应字段名是**跨层契约**，后端 schema 字段名即为契约真名；前端类型与绑定必须逐字段对齐，**不得**在两侧各用一套命名。
- 需要别名/兼容时，必须在**同一处**显式声明（后端 `alias`/`serialization_alias`，或前端统一归一化层），并在响应模型上以注释标注。
- 已知高风险命名族（历史缺陷；2026-09-28 裁决 corrected：后端现已在 schema 层双向同步别名）：
  - 题目选项：后端 `{key, content}` vs 前端 `{key, text}` → 客观题选项渲染为空。
  - 练习详情/创建题目列表：后端 `items[]`（元素 `question_snapshot`）vs 前端 `questions` → 会话题目恒空。
  - 诊断薄弱知识点：后端 `weak_knowledge_points` 现已同时下发别名 `weak_points`（`KnowledgeMasterySummaryResponse` 双向同步），前端优先读 `weak_points`；仍禁止两侧各造一套命名。

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

#### 代码锚点
- `backend/app/schemas/practice.py::QuestionSnapshotDTO.options`
- `backend/app/schemas/practice.py::PracticeDetailResponse.items`
- `backend/app/schemas/diagnosis.py::KnowledgeMasterySummaryResponse`（`weak_points` ↔ `weak_knowledge_points` 双向同步）
- `miniprogram/src/api/adapters/diagnosis.ts::adaptDiagnosisReport`

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

#### 代码锚点
- `backend/app/services/material.py::build_material_storage_key`
- `backend/app/services/material.py::MaterialService.hard_delete_material`
- `backend/app/repositories/material.py::MaterialRepository.find_version_by_hash`

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

#### 代码锚点
- `backend/app/services/material.py::MaterialService.reshoot_material_page`
- `backend/app/services/material.py::MaterialService.list_ocr_pages`
- `backend/app/services/material.py::MaterialService._resolve_status_filter`
- `backend/app/models/material.py::MaterialStatus.RETAKE_REQUIRED`
- `backend/app/api/v1/materials.py`（`/{material_id}/ocr-pages`、`/{material_id}/reshoot`）

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

#### 代码锚点
- `backend/app/schemas/practice.py::PracticeItemDetailResponse.grading_status`
- `backend/app/services/grading.py::GradingService.regrade_attempt`
- `backend/app/services/grading.py::GradingService._build_pending_regrade_record`
- `backend/app/core/algorithms/grading.py::SCORE_ROUNDING_UNIT`

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

#### 代码锚点
- `backend/app/services/diagnosis.py::DiagnosisService.get_user_mastery_overview`
- `backend/app/core/algorithms/diagnosis.py::check_regression`
- `backend/app/repositories/knowledge.py::KnowledgeRepository.list_all_by_user_id`
- `miniprogram/src/api/adapters/diagnosis.ts::adaptDiagnosisReport`

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



#### 代码锚点
- `backend/app/repositories/diagnosis.py::DiagnosisRepository.count_wrong_records`
- `backend/app/services/diagnosis.py::DiagnosisService.list_wrong_records`
- `backend/app/api/v1/diagnosis.py::mark_wrong_record_mastered`
- `backend/app/schemas/diagnosis.py::WrongRecordItemResponse`
- `backend/app/schemas/practice.py::PracticeCreateRequest.material_id`

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

#### 代码锚点
- `backend/app/api/v1/users.py::update_current_user_profile`
- `backend/app/api/v1/users.py::delete_current_user_account`
- `backend/app/services/auth.py::AuthService.update_user_profile`
- `backend/app/api/v1/auth.py`（`run_in_threadpool` 包裹同步登录）
- `backend/app/schemas/user.py::UpdateUserProfileRequest`

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

#### 代码锚点
- `backend/app/services/knowledge.py::normalize_extracted_temp_ids`
- `backend/app/api/v1/materials.py::_read_upload_content_guarded`
- `backend/app/api/v1/materials.py::_UPLOAD_CHUNK_BYTES`
- `backend/app/services/material.py::MaterialService._purge_storage_objects`

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

#### 代码锚点
- `backend/app/schemas/question.py::QuestionGenerateRequest.question_types`
- `backend/app/api/v1/questions.py::_resolve_delete_reason`
- `backend/app/core/algorithms/question_quality.py::check_answer_conflict`
- `backend/app/services/question.py::GenerateQuestionsOptions.__post_init__`

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

#### 代码锚点
- `backend/app/models/practice.py::PracticeStatus`
- `backend/app/models/practice.py::validate_practice_transition`
- `backend/app/services/practice.py::PracticeService.save_answer`
- `backend/app/services/practice.py::PracticeSubmissionResult.is_idempotent_replay`
- `backend/app/schemas/practice.py::PracticeDetailResponse.completed_count`

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

#### 代码锚点
- `backend/app/services/practice.py::PracticeService.submit_practice`
- `backend/app/services/practice.py::_serialize_user_answer`
- `backend/app/schemas/practice.py::_normalize_persisted_user_answer`
- `backend/app/schemas/practice.py::PracticeDetailResponse.time_elapsed_seconds`

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

#### 代码锚点
- `backend/app/schemas/practice.py::PracticeItemDetailResponse`（顶层要点与 `question_snapshot` 双同步）
- `backend/app/schemas/practice.py::_pick_final_grading_record`
- `backend/app/services/practice.py::PracticeService._attach_source_snippets`
- `backend/app/repositories/material.py::MaterialRepository.list_snippets_by_ids`
- `backend/app/schemas/practice.py::SourceSnippetDTO`

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

#### 代码锚点
- `backend/app/core/algorithms/grading.py::round_half_up`
- `backend/app/core/algorithms/grading.py::SCORE_ROUNDING_UNIT`
- `backend/app/services/grading.py::GradingService._grade_attempt_item`
- `backend/app/services/grading.py::SelfEvaluateDTO.is_correct`

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

#### 代码锚点
- `backend/app/schemas/diagnosis.py::UserMasteryOverviewResponse`
- `backend/app/repositories/diagnosis.py::DiagnosisRepository.list_wrong_records`
- `backend/app/repositories/diagnosis.py::DiagnosisRepository.count_wrong_records`
- `backend/app/schemas/diagnosis.py::DeleteWrongRecordResponse.removed`

### Scenario: Report Generation Race, Create-Practice Idempotency & Mastery Ordering

#### 1. Scope / Trigger
- 报告生成并发唯一键冲突、`POST /practices` 幂等创建、掌握度全景薄弱点排序。

#### 2. Contracts
- 报告生成先查后插若并发撞 `practice_id` 唯一约束，必须捕获 `IntegrityError`、`rollback()` 后回查并返回既有报告；非冲突异常不得吞掉。
- `POST /practices` 幂等：头名与前端逐字一致（`Idempotency-Key`）；命中已完成快照则回放（不取锁），并发同 key 拒绝（409），无 key 走旧链路；**锁必须在任何失败路径释放**，快照写入失败须降级告警（不得 commit 后 500 或泄漏锁）。
- `get_user_mastery_overview` 的薄弱点按 `(mastery_score, knowledge_point_id)` 升序稳定排序（最弱在前）。

#### 3. Tests Required
- 并发 `IntegrityError` → rollback + 回查返回既有报告；同 key 并发 409；快照写失败仍成功且锁释放可重试；无 key 零回归；薄弱点严格升序（含并列稳定）。

#### 代码锚点
- `backend/app/services/diagnosis.py::DiagnosisService`（报告生成 `IntegrityError` 回滚回查）
- `backend/app/api/v1/practices.py::create_practice`（`Idempotency-Key` 头名）
- `backend/app/services/practice.py::PracticeService.create_practice`
- `backend/app/services/diagnosis.py::DiagnosisService.get_user_mastery_overview`（薄弱点稳定升序）

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
- **归档同名可复用**：`name_exists` 与唯一约束均排除归档行（部分唯一索引 `uq_material_folders_user_name_active`，`archived_at IS NULL`）；归档课程不占用名称，可新建同名活跃课程。恢复（restore）时若已有同名活跃课程，返回 `FolderNameConflictError`（409），不得违反唯一约束。
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

#### 代码锚点
- `backend/app/models/material.py::MaterialFolder`
- `backend/app/services/folder.py::FolderService.purge_folder`
- `backend/app/services/folder.py::FolderService._purge_expired`
- `backend/app/repositories/folder.py::FolderRepository.list_expired`
- `backend/app/services/folder.py::ARCHIVE_RETENTION`

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
- **批次落库**：`questions.batch_id`（可空、索引）持久化本次生成批次号；单考点 / 多考点 / 课程范围三链路的题目必须共享**同一** `batch_id`——由最外层编排生成并逐层透传（`generate_questions(..., batch_id=)`），禁止各层各自 `uuid4` 新建。`QuestionQualityCheck.batch_id` 与题目行一致。`GET /questions` 支持 `batch_id` 过滤，历史无 `batch_id` 行为视为不过滤且不报错。

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

#### 代码锚点
- `backend/app/services/question.py::QuestionService.generate_questions_for_folder`
- `backend/app/repositories/question.py::QuestionRepository.list_material_ids_for_folder`
- `backend/app/repositories/question.py::QuestionRepository.list_knowledge_points_for_folder`
- `backend/app/repositories/folder.py::FolderRepository.last_practice_at_by_folder_ids`
- `backend/app/models/question.py::Question.batch_id`

---

### Scenario: Upload-Only Persistence & User-Triggered Material Parsing (`not_started`)

#### 1. Scope / Trigger
- 资料上传后的解析调度语义：上传只落库，解析必须由用户显式启动（`POST /materials/{id}/parse`）；失败后走 `POST /materials/{id}/retry`。

#### 2. Signatures
- `ParseStatus`（版本级）新增 `NOT_STARTED = "not_started"`，完整取值：`not_started | queued | parsing_doc | ocr_processing | extracting_knowledge | auditing_knowledge | embedding_generation | ready | failed`。
- 资料主状态 `MaterialStatus`：`pending | parsing | ready | failed | retake_required`。
- `POST /api/v1/materials/{id}/parse` -> 首次启动解析；`POST /api/v1/materials/{id}/retry` -> 失败重试（既有语义，仍重置为 `QUEUED`）。

#### 3. Contracts
- **上传零调度**：`POST /materials/upload` 只持久化资料与版本，**不得**入队解析，**也不得**注册 `BackgroundTasks`；新版本初始 `parse_status = NOT_STARTED`。历史上这段逻辑同时存在于 service 入队与路由后台任务两处，改动时必须两条都关闭。
- **派发必须原子**：解析入口（`/parse` 与 `/retry`）都是「用户命令 → 置 `QUEUED` → 入队」，状态跃迁必须走数据库条件更新 `MaterialRepository.try_transition_version_status(version_id, material_id, *, from_status, to_status, reset_errors=False) -> bool`。**禁止先读后写**：两个并发请求会凭同一次陈旧读各自入队一次，同一版本被两个 worker 同时解析——`parse_material_pipeline` 只在 `READY` 时早退，非 READY 的并发任务会各自跑完整 OCR/LLM 并重复写切片。CAS 未命中说明该版本已被其他请求推进，本次直接返回、**不**重复派发。
- **在途状态直接返回**：`trigger_parse` 命中 `queued/parsing_doc/ocr_processing/extracting_knowledge/auditing_knowledge/embedding_generation/ready` 时按既有语义直接返回，不重复调度。
- **`retry` 语义**：仅 `failed` 可重试；重置为 `QUEUED` 并清空 `error_message`/`failed_stage`（`reset_errors=True`）。CAS 未命中 → `MaterialInvalidError`（并发重试已被处理）。
- **入队失败可见**：`_enqueue_parse` 抛错必须回写版本 `FAILED` + `failed_stage="queue_dispatch"` + 提示文案，并把资料置 `FAILED`，不得静默停在 `queued`。
- **旧数据兼容**：已存在 `queued` 记录维持原语义，不批量取消、不改写。
- **前端状态映射**必须覆盖全部主状态与细化 `parse_status`，`ready` 才允许进入知识树与组卷；`not_started` 显示「待解析」并提供「开始解析」入口（不得显示为「排队中」）。

#### 4. Validation & Error Matrix
- 上传成功 → 版本 `not_started`、资料 `pending`、**队列为空**。
- `parse` 命中 `not_started`/`failed` → `queued` + 入队一次。
- `parse` 命中 `parsing`/`ready` → 拒绝（不重复调度）。
- 入队失败 → 版本回写 `failed`（而非停留 `queued`）。
- 越权/不存在 → 404。

#### 5. Wrong vs Correct
##### Wrong
```python
# 错误1：上传即入队（用户未点「开始解析」就消耗 OCR/LLM）
self.queue.enqueue(task_name="parse_material_pipeline", payload={...}, user_id=str(user_id))

# 错误2：只关掉 service 入队，路由仍挂 BackgroundTasks → 仍会自动解析
background_tasks.add_task(run_parse, material_id)

# 错误3：新版本写成 queued 却没入队 → 永久「排队中」且无消费者
version = MaterialVersion(..., parse_status=ParseStatus.QUEUED.value)
```
##### Correct
```python
# 正确：上传只落库；解析由用户命令触发，派发经条件更新且入队失败可见
version = MaterialVersion(..., parse_status=ParseStatus.NOT_STARTED.value)
# POST /{id}/parse：
if not self.repo.try_transition_version_status(
    target_version.id, material_id,
    from_status=target_version.parse_status,       # 陈旧读无法通过：DB 行已变 → 未命中
    to_status=ParseStatus.QUEUED.value, reset_errors=True,
):
    return target_version                                # 已被其他请求推进，不重复派发
self._enqueue_parse(material_id, target_version.id, user_id)   # 失败 → 回写 FAILED
```

#### 6. Tests Required
- 上传后 `parse_status == not_started` 且**队列无任务**（断言 `len(queue._queue) == 0`）。
- `parse` 后恰好入队一次；重复 `parse` 被拒（在途状态直接返回）。
- **并发竞态**：本会话持有陈旧 `not_started` 实体、DB 行已被推进到 `queued` 时，`trigger_parse` 必须**不**再入队（守 CAS 回归）；`retry` 同理由 CAS 拒绝。
- 入队抛错 → 版本 `failed` + `failed_stage="queue_dispatch"`（可重试），不留 `queued`。
- 旧 `queued` 数据仍可被 worker 消费（零回归）。
- 前端：`not_started` → 「待解析」+ 「开始解析」可达；状态筛选含 `retake_required`。

#### 代码锚点
- `backend/app/models/material.py::ParseStatus.NOT_STARTED`
- `backend/app/repositories/material.py::MaterialRepository.try_transition_version_status`
- `backend/app/services/material.py::MaterialService.create_material`（不再入队）
- `backend/app/services/material.py::MaterialService.trigger_parse`（CAS 派发）
- `backend/app/services/material.py::MaterialService.retry_material_pipeline`（CAS 重试）
- `backend/app/services/material.py::MaterialService._enqueue_parse`（失败回写）
- `backend/app/api/v1/materials.py`（`/upload` 无后台任务、`/{id}/parse`、`/{id}/retry`）
- `miniprogram/src/utils/materialState.ts`

---

### Scenario: Out-of-Process Queue Execution (RQ) & Terminal-Failure Writeback

#### 1. Scope / Trigger
- 解析与判题任务的真实执行：任务是进程外消费者执行的，业务记录是用户可见状态的事实源。

#### 2. Signatures
- `QueueProtocol.enqueue(task_name, payload, user_id, *, task_id=None, delay_seconds=0, priority=0) -> str`。
- 受控任务白名单 `REGISTERED_TASK_NAMES = frozenset({"parse_material_pipeline", "grading_jobs"})`。
- 入口固定为 `app.worker.execute_registered_task(task_name, payload, user_id)`；终态失败回调固定为 `app.worker.handle_job_terminal_failure`。
- 队列名：默认 `zhilian`，`priority > 0` 走 `zhilian_high`。
- 重试：`Retry(max=3, interval=[10, 30, 90])`（`min(10 * 3**i, 300)`）；`job_timeout=1800`s；`failure_ttl=7d`；`result_ttl=1d`；回调超时 60s。
- 环境变量：`ZHILIAN_QUEUE__PROVIDER=redis`（见 `Taskfile.yml::worker`）；worker 启动 `cd backend && uv run python -m app.worker`。

#### 3. Contracts
- **只投递受控任务名**：`enqueue` 校验 `task_name in REGISTERED_TASK_NAMES` 与 `payload["user_id"] == user_id`，否则 `QueueError`；**禁止**反序列化任意客户端函数。RQ 侧只传固定入口模块路径 + 轻量标识（UUID），不携带原文或用户作答。
- **无消费者即无执行**：内存适配器只服务单元测试与显式同步场景（`process_next` 仅在测试调用）；生产必须部署独立 worker，否则任务永久待处理。
- **终态失败才回写**：`on_failure` 在**每次**失败都会触发（含仍将重试的中间失败），回写前必须用 `job.should_retry` 判定；`should_retry=True` 只记 warning。回写自身异常必须被吞掉（不得让回调异常污染 RQ）。
- **幂等**：任务键绑定资料版本或练习；重复领取（重投/重试）不得重复解析、重复计分或产生重复生效判题记录。
- **可定位**：`python -m app.cli queue stalled [--older-than-minutes N] [--limit N]` **只读**列出长期停留的 `practices.status='submitted'` 与解析中间态版本，并给出恢复入口；无滞留退出码 0、检出退出码 2、DB 不可达退出码 4。禁止在该命令中写任何业务状态。

#### 4. Validation & Error Matrix
- 未注册任务名 / 载荷用户与 `user_id` 不一致 → `QueueError`（拒绝入队）。
- `delay_seconds < 0` 或 `priority < 0` → `QueueError`。
- 中间失败（`should_retry=True`）→ 仅 warning，**不**改业务状态。
- 重试耗尽 / 判定为终态 → 记 error 并回写业务状态（见下一 Scenario）。
- 解析任务：service 自身已回写 `FAILED`，回调不再重复回写（避免双重语义）。

#### 5. Wrong vs Correct
##### Wrong
```python
# 错误1：存在入队代码但没有任何消费者 → 任务永久待处理且无提示
queue.enqueue("parse_material_pipeline", {...})   # 生产无 worker 运行

# 错误2：把 on_failure 当"最终失败"用，中间失败也回写 → 把仍在重试的记录标成终态
def handle_job_terminal_failure(job, *args): 
    mark_failed(job)                              # 未判 should_retry

# 错误3：让客户端传函数名/序列化函数对象
queue.enqueue(payload["callable"], {...})
```
##### Correct
```python
# 正确：受控白名单 + 终态判定 + 回写异常吞掉
if task_name not in REGISTERED_TASK_NAMES:
    raise QueueError(f"未注册的后台任务: {task_name}")
if getattr(job, "should_retry", False):
    logger.warning("后台任务失败，RQ 将按退避策略重试"); return
try:
    handler(container, payload, user_id)          # 固定模块路径解析得到
except Exception:
    logger.exception("终态失败回写自身异常")        # 不污染 RQ
```

#### 6. Tests Required
- `enqueue` 断言 `on_failure.name == "app.worker.handle_job_terminal_failure"`（受控路径）。
- 未注册任务名 / 用户不匹配被拒。
- `should_retry=True`、解析任务、未知任务 → **不**回写。
- 回写自身抛错不外溢。
- CLI：空库退出 0；超阈值记录被检出并给 `action`（退出 2）；阈值内不误报；**断言业务状态未被改写**。
- 真实 Redis 跨进程消费需人工验证（本环境无 Redis，纯替身单测不能替代）。

#### 代码锚点
- `backend/app/integrations/queue/protocol.py::REGISTERED_TASK_NAMES`
- `backend/app/integrations/queue/rq_adapter.py`（`TASK_ENTRY`/`TERMINAL_FAILURE_CALLBACK`/`Retry`/`Callback`）
- `backend/app/worker.py::REGISTERED_TASKS`、`execute_registered_task`、`handle_job_terminal_failure`
- `backend/app/cli/commands/queue.py`、`backend/Dockerfile.worker`、`deploy/docker-compose.yml`

---

### Scenario: Grading Completion Gate, Recovery State & Atomic Retry Dispatch

#### 1. Scope / Trigger
- 交卷 → 异步判题 → 报告生成的时序；判题任务终态失败后的可恢复状态；用户主动重试判题。

#### 2. Signatures
- `POST /api/v1/practices/{id}/regrade` -> `PracticeStatusResponse`（**练习级**判题重试；与**题目级** AI 复查 `POST /api/v1/grading/regrade` 不同语义、不同路由）。
- `PracticeService.mark_grading_failed(user_id, practice_id, *, reason="", request_id="") -> Practice | None`。
- `PracticeService.retry_grading(user_id, practice_id, request_id="") -> tuple[str, Practice]`。
- `PracticeRepository.try_transition_status(practice_id, user_id, *, from_status, to_status) -> bool`。
- 前端：`needsGradingRetry(session)`（仅 `partially_graded` 为真）、`apiRetryPracticeGrading`。

#### 3. Contracts
- **`completed_at` 是全判完的唯一标记**：`GradingService` 仅在全部作答项判完（`all_graded`）时写 `COMPLETED` + `completed_at`；存在待重判则 `partially_graded` 且 `completed_at = None`。
- **诊断门禁双条件**：`DiagnosisService` 只接受 `status == completed` **且** `completed_at is not None`，否则 40016。任何回写/重试路径都**不得**写 `completed_at`，否则绕过门禁产出早产报告。
- **`partially_graded` 有两个成因**：主观题 LLM 超时降级为待重判；判题任务终态失败被回写。两者共享同一恢复入口 `POST /{id}/regrade`，因此 UI 文案必须对两种成因都成立（「仍有 N 题未判定」），不得表述为「部分判完」。
- **失败回写单调**：`mark_grading_failed` 仅当 `status == submitted` 时置 `partially_graded`；`completed`/`partially_graded`/`timeout` 一律跳过，绝不回退已生效判分；重复回调天然幂等。
- **重试派发必须原子**：状态跃迁走数据库条件更新（compare-and-swap），**不得**「先读状态再写状态」——两个并发请求会同时通过状态校验并重复入队，同一批待判项被判两遍、产生重复 `is_final` 记录。仅当 CAS 成功才入队；入队失败必须 `rollback()` 退回 `partially_graded`，恢复入口不被堵死。
- **判题幂等**：`GradingService.grade_practice` 对已有 `SUCCESS` 且非用户自评的生效记录跳过；重复整卷判题不得重复计分、不得产生重复生效记录。
- **结果页不显示假零分**：未判/待重判项显示「判题中」/「待重判」，不得显示 0 分或答错。

#### 4. Validation & Error Matrix
- `status == timeout` → 40011（超时冻结，不可重试）。
- `completed_at is not None` 或 `status == completed` → 40011（已全判完）。
- `status` 既非 `partially_graded` 也非上述 → 40011（判题尚未结束）。`submitted` 视为判题进行中，**不**开放重试，避免并发双判。
- CAS 未命中（并发已被其他请求推进）→ 40011，且**不得**入队。
- 入队失败 → 回滚为 `partially_graded`，可再次重试。
- 练习不存在 / 越权 → 404。

#### 5. Wrong vs Correct
##### Wrong
```python
# 错误1：先读后写，两个并发重试都通过校验并各自入队（同一批待判项判两遍）
practice = repo.get_practice_by_id(practice_id, user_id)
if practice.status != PracticeStatus.PARTIALLY_GRADED.value:
    raise PracticeStatusError(...)
repo.update_practice_status(practice_id, user_id, PracticeStatus.SUBMITTED.value)
queue.enqueue(task_name="grading_jobs", payload={...}, user_id=str(user_id))

# 错误2：失败回写顺手写完成时间 → 绕过诊断门禁产出早产报告
practice.completed_at = datetime.now(UTC)
```
##### Correct
```python
# 正确：状态跃迁由数据库判定，只有改到该行的调用才入队
transitioned = repo.try_transition_status(
    practice_id, user_id,
    from_status=PracticeStatus.PARTIALLY_GRADED.value,
    to_status=PracticeStatus.SUBMITTED.value,
)
if not transitioned:
    raise PracticeStatusError("判题任务已在重试中，请勿重复提交")
try:
    task_id = queue.enqueue(task_name="grading_jobs", payload={...}, user_id=str(user_id), priority=1)
    session.commit()
except Exception:
    session.rollback()      # 退回 partially_graded，恢复入口保持可用
    raise
# completed_at 只由 GradingService 在 all_graded 时写入
```

#### 6. Tests Required
- 重试耗尽回写 → `partially_graded` 且 `completed_at is None`；重复回调幂等；`completed` 不被降级；未交卷练习不受影响。
- 重试派发一次；第二次触发被拒且队列长度不变；**并发竞态**：本会话持有陈旧 `partially_graded` 实体、DB 行已被推进到 `submitted` 时，重试必须被拒且**不入队**（守 CAS 回归）。
- 入队失败回滚为 `partially_graded` 且仍可再试。
- 重试后真正跑完全卷才写 `completed_at`；重复整卷判题不重复计分、生效记录数 == 作答项数。
- 诊断门禁：`partially_graded` → 40016（守门禁不被绕过）。
- 前端：`needsGradingRetry` 仅对 `partially_graded` 为真；未判项 `score`/`isCorrect` 为 `null` 而非 0。

#### 代码锚点
- `backend/app/services/grading.py::GradingService.grade_practice`（`all_graded` 才写 `completed_at`）
- `backend/app/services/diagnosis.py::DiagnosisService`（`status == COMPLETED and completed_at is not None` 门禁）
- `backend/app/services/practice.py::PracticeService.mark_grading_failed`
- `backend/app/services/practice.py::PracticeService.retry_grading`
- `backend/app/repositories/practice.py::PracticeRepository.try_transition_status`
- `backend/app/api/v1/practices.py`（`/{id}/regrade`）
- `miniprogram/src/api/adapters/practice.ts::needsGradingRetry`

---

### Scenario: Source-Snippet Enrichment Across Practice and Question Domains

#### 1. Scope / Trigger
- 结果页原文依据（练习作答项）与核对页来源框（题目）都需逐题切片正文；同一实体的创建/查询/列表/更新路径响应必须形状一致。

#### 2. Signatures
- `app/services/source_snippets.py::build_source_snippet_map(material_repo, snippet_ids, user_id)`（**跨域唯一装配实现**：投影构造 + 页码回退规则只在此处）。
- `PracticeService._build_source_snippet_map(items, user_id)`（练习侧只负责「从快照提取切片主键」，随后委托上者）、`_attach_source_snippets(detail, user_id)`（详情路径）、`_attach_source_snippets_to_items(practice, user_id)`（创建路径）。
- `QuestionService.attach_source_snippets(items, user_id)`（题目侧批量为 `QuestionDetailResponse` 就地补全 `source_snippet`）。
- `MaterialRepository.list_snippets_by_ids(snippet_ids, user_id)`（批量 + 租户过滤）。

#### 3. Contracts
- 原文装配**只有一个实现**（`build_source_snippet_map`）：题目/练习两域、创建/查询/列表/更新各路径全部复用；任一侧不得另写投影或页码回退逻辑。
- 装配必须批量按 `source_snippet_id` 关联（单查询、按 `user_id` 过滤），禁 N+1、禁跨用户泄漏；切片缺失时投影为 `None`，前端渲染空态。
- 装配点覆盖：题目 `POST /questions/generate`（qualified + pending）、`GET /questions/{id}`、`GET /questions`、`PUT /questions/{id}`；练习创建与详情。题目列表同样装配（该端点本就返回题干/答案/解析全量字段，一条切片正文属同量级），代价是每响应一次批量查询。
- 两侧共用**同一个 DTO 类**：`app/schemas/material.py::SourceSnippetDTO`（切片属资料域）。禁止同形异构副本，否则前后端与两个业务域会出现多份会漂移的来源模型。
- 回填快照时**必须拷贝 dict**（`snapshot = dict(snapshot)`）再写入，禁止原地修改 ORM 的 JSON 列对象——否则瞬时装配数据会随会话提交被持久化进快照。
- 创建路径**不得**改写已落库的快照 JSON，也不得因此改变 service 的返回类型（既有调用方依赖 `Practice` ORM）。

#### 4. Tests Required
- 练习：创建练习的响应中作答项带完整 `source_snippet`（`snippet_content`/`chapter_title`/`page_index`），与查询详情路径一致。
- 练习：快照副本内同样可读到 `source_snippet`；**断言落库的 JSON 未被瞬时装配污染**。
- 题目：出题/详情/列表/更新四条路径的响应都带 `source_snippet`，形状为 `{id, chapter_title, page_index, snippet_content}`；无 `source_snippet_id` 的历史题目为 `null` 且键存在。
- 题目：切片属他人时装配结果为 `None`（租户隔离，不泄漏他人正文）。
- 题目：**裸 `model_validate(question)` 不得读取 ORM 关系**（`material_snippets` 查询数为 `0`），见下一条 Scenario。
- 两侧：切片缺失 → `None` 空态；批量查询次数常数级（题目数增加不增加切片查询）。

#### 代码锚点
- `backend/app/services/source_snippets.py::build_source_snippet_map`
- `backend/app/services/question.py::QuestionService.attach_source_snippets`
- `backend/app/services/practice.py::PracticeService._attach_source_snippets_to_items`
- `backend/app/schemas/material.py::SourceSnippetDTO`（两侧共用）
- `backend/app/schemas/practice.py::PracticeItemDetailResponse`（before-validator 回填快照副本）
- `backend/app/repositories/material.py::MaterialRepository.list_snippets_by_ids`

---

### Scenario: Response Field Names Must Not Collide with ORM Relationships

#### 1. Scope / Trigger
- `QuestionDetailResponse` 新增 `source_snippet` 字段（`SourceSnippetDTO` 投影）时，与 ORM 关系 `Question.source_snippet`（指向 `MaterialSnippet` 实体）**同名**。凡 `from_attributes=True` 的响应模型新增字段，都要先查模型侧是否有同名属性/关系。

#### 2. Contracts
- `from_attributes` 的字段名会直接 `getattr` 到 ORM 实体的同名属性，**关系也算**。同名时映射读到的是实体本身，后果是双重的：
  - **投影错误且静默**：实体没有 `snippet_content` 属性（真名 `content`），字段落空串；`page_index` 落默认值 1；
  - **每题一次惰性加载**：一页 20 条即多 20 次 `material_snippets` 查询（N+1），且服务层装配形同虚设。
- 处置：ORM 关系改名（`Question.primary_source_snippet`），把线格式名称留给响应投影；投影只能由服务层批量装配提供。
- 判别：`rg -n "source_snippet" backend/app/models/question.py` —— 模型侧不得再出现与响应字段同名的关系。

#### 3. Tests Required
- **裸映射零查询**：`expunge_all()` 后 `model_validate(question)` 期间 `material_snippets` 查询数必须为 `0`，且 `source_snippet is None`（守关系改名不被回退）。
- 装配后的内容与批量查询次数（常数级）另有用例。

#### 4. Wrong vs Correct
##### Wrong
```python
# 模型侧：关系与线格式字段同名
source_snippet: Mapped["MaterialSnippet | None"] = relationship("MaterialSnippet", foreign_keys=[source_snippet_id])
# 响应侧
source_snippet: SourceSnippetDTO | None = Field(default=None)
# → from_attributes 直接读关系实体：内容空串 + 每题一次惰性加载
```
##### Correct
```python
# 模型侧：关系改名，避开线格式字段名
primary_source_snippet: Mapped["MaterialSnippet | None"] = relationship("MaterialSnippet", foreign_keys=[source_snippet_id])
# 响应侧：线格式名保持不变，投影由 QuestionService.attach_source_snippets 批量装配
source_snippet: SourceSnippetDTO | None = Field(default=None)
```

#### 代码锚点
- `backend/app/models/question.py::Question.primary_source_snippet`
- `backend/app/schemas/question.py::QuestionDetailResponse`
- `backend/app/services/question.py::QuestionService.attach_source_snippets`
- `backend/tests/unit/services/test_question_service.py::TestQuestionSourceSnippetAssembly.test_response_mapping_does_not_read_orm_relationship`

---

### Scenario: Contract Fixture Fidelity (Never Assert Fields the Server Does Not Send)

#### 1. Scope / Trigger
- 任何用「真实后端序列化样本」固定跨层字段的前后端契约测试与 fixture。

#### 2. Contracts
- fixture 的字段名与**字段存在性**都必须逐字取自后端响应模型的真实序列化结果；**手工补一个服务端不返回的字段，会让断言在生产永不成立却测试恒绿**。
- 字段存在性判定要以响应模型为准：模型没有该字段时，前端读取恒为 `undefined`，绑定静默渲染为空——测试若自造字段则该缺陷永远发现不了。
- 同一实体的不同响应模型可能字段不同（例如**题目**：`QuestionDetailResponse` 只有 `analysis`，**没有** `explanation`；而练习快照 `QuestionSnapshotDTO` 同时有 `analysis` 与 `explanation`。前端 adapter 的 `explanation ?? analysis` 只在快照侧回退命中）。fixture 必须按**具体端点**取材，不得跨端点搬运字段。

#### 3. Wrong vs Correct
##### Wrong
```typescript
// 错误：给题目 fixture 手工补一个 QuestionDetailResponse 从不返回的字段
const generatedQuestionFixture = () => ({ ..., explanation: '服务端不返回该字段' })
expect(adaptQuestion(raw).explanation).toBe('服务端不返回该字段')   // 生产恒为 undefined → 假通过
```
##### Correct
```typescript
// 正确：按具体端点的响应模型取材，字段存在性一并断言
// 题目侧来源正文真的会下发（QuestionService.attach_source_snippets）
expect(adaptQuestion(realQuestionFixture).source_quote).toBe('慢启动阶段拥塞窗口指数增长，直到达到慢启动阈值。')
// 无来源时后端返回 null，前端渲染空态
expect(adaptQuestion({ ...realQuestionFixture, source_snippet: null }).source_quote).toBeUndefined()
// 仅在快照侧存在的字段不得搬到题目侧
expect('explanation' in realQuestionFixture).toBe(false)
expect(buildAttemptResults(adaptPractice(realItemFixture))[0].sourceQuote).toBe('...')
```

#### 4. Tests Required
- 题目侧：按真实响应断言 `source_quote` 命中 `source_snippet.snippet_content`；无来源（`source_snippet: null`）时断言 `undefined`（守空态）。**禁止**靠手工补字段让断言通过。
- 练习侧：用真实练习 fixture 断言 `source_quote` 正确映射。
- fixture 新增/修订后，必须能回答「这个字段由哪个响应模型的哪个字段产生」。后端样本以 `model_dump(mode="json")` 的真实输出为准（见 `backend/tests/unit/schemas/test_question_schemas.py` 的字段名固定用例）。

#### 代码锚点
- `miniprogram/tests/fixtures/backendResponses.ts`
- `miniprogram/tests/backendContracts.spec.ts`
- `backend/app/schemas/question.py::QuestionDetailResponse`（含 `source_snippet`；无 `explanation`）
- `backend/app/schemas/material.py::SourceSnippetDTO`、`backend/app/schemas/practice.py::QuestionSnapshotDTO`（含 `explanation`）

---

### Scenario: Managed Avatar Upload & Presigned URL Contract

#### 1. Scope / Trigger
- 用户头像由前端直接选图上传，由应用托管对象存储；不再要求用户手填图片 URL。

#### 2. Signatures
- `POST /api/v1/users/me/avatar`（multipart 图片）-> `UserProfileResponse`。
- `AuthService.upload_user_avatar(user_id, data: bytes) -> UserProfileResponse`。
- 对象键：`users/{user_id}/avatars/{uuid4().hex}{suffix}`；持久字段 `User.avatar_object_key`。

#### 3. Contracts
- **校验真实内容而非声明**：先判体积（> 5 MiB → 413），再按**魔数**识别 PNG/JPEG/GIF/WebP（不认可 → 400）；禁止只信 `Content-Type`/文件名后缀。
- **先写对象、后更新数据库**：对象写入成功后才更新 `avatar_object_key`；`avatar_url` 落库为空串，展示 URL 由响应**按需重新签发**（预签名有效期 3600s），**禁止**把会过期的签名 URL 当作长期数据库值。
- **失败保留旧值**：DB 更新失败 → `rollback()` 并删除刚写入的新对象；旧对象只在**新对象与数据库更新均成功后**才清理，清理失败仅告警不阻断。
- **兼容旧数据**：历史 `avatar_url` 直链仍可读；迁移后的托管头像以对象键优先。

#### 4. Validation & Error Matrix
- `len(data) > 5 MiB` → `StorageError(413)`。
- 魔数不识别 → `StorageError(400)`。
- 未配置对象存储 → `StorageError`。
- 用户不存在/已注销/已停用 → `AuthenticationError`。
- DB 更新失败 → 回滚 + 删除新对象，旧头像保持可用。

#### 5. Wrong vs Correct
##### Wrong
```python
# 错误1：只信声明类型；把预签名 URL 直接落库（过期后头像全裂）
if content_type not in ALLOWED: raise ...
user.avatar_url = generate_presigned_download_url(bucket, key, expires_in=3600)
# 错误2：先删旧对象再更新数据库，中途失败 → 用户既无新头像也无旧头像
storage.delete_object(bucket, old_key); repo.update_profile(user_id, avatar_object_key=new_key)
```
##### Correct
```python
# 正确：魔数校验 → 写新对象 → 更新对象键（url 留空）→ 成功后清理旧对象
detected = _detect_image_type(data)                 # 魔数
stored_key = storage.put_object(bucket, new_key, data, content_type=content_type)
updated = repo.update_profile(user_id, avatar_url="", avatar_object_key=stored_key)
session.commit()
profile = UserProfileResponse.model_validate(updated).model_copy(
    update={"avatar_url": generate_presigned_download_url(bucket, stored_key, expires_in=3600)})
if old_key: storage.delete_object(bucket, old_key)  # 仅在成功后
```

#### 6. Tests Required
- 超限（413）、非法内容（400，含"声明为图片但内容非图片"）、未配置存储。
- 上传成功：DB 存对象键且 `avatar_url` 不含签名查询串；响应 URL 可用。
- DB 更新失败 → 新对象被清理、旧头像仍可用。
- 迁移 0009 `upgrade → downgrade → upgrade` SQLite 对称；旧 `avatar_url` 数据仍可读。

#### 代码锚点
- `backend/app/api/v1/users.py`（`/me/avatar`）
- `backend/app/services/auth.py::AuthService.upload_user_avatar`、`_detect_image_type`、`_AVATAR_MAX_BYTES`
- `backend/app/models/user.py::User.avatar_object_key`
- `backend/migrations/versions/0009_avatar_object_key.py`

---

### Scenario: Grounded Course Coach with Bounded Citation Repair

#### 1. Scope / Trigger
- 课程/资料/知识点级 AI 助教答疑：回答必须基于当前用户有权访问的切片，并给出可核对的来源；无证据或服务失败时必须明确告知。

#### 2. Signatures
- `POST /api/v1/coach/ask`（`folder_id` / `material_id` / `knowledge_point_id` + 提问）-> `reply` + `suggestions` + 来源切片。
- 题目级助教维持 `POST /api/v1/questions/{id}/ask-coach`（返回 `reply`/`suggestions`）。
- 图：`build_coach_graph(search, llm)`，`StateGraph` 节点 授权范围解析 → 检索合并排序 → 证据是否足够 → 结构化回答 → 引用校验 → 至多一次修复或拒答。

#### 3. Contracts
- **授权是确定性代码，不交给模型**：服务层枚举当前用户有权访问的资料/版本并限定检索范围；LLM 不决定自己能读哪些资料。
- **引用只能来自本次授权检索返回的切片**：校验答案中的 `citation_ids` 与原始检索结果逐一核对；不通过时至多修复一次，仍失败则**拒答**，不得编造引用或改用固定模板冒充 AI 答疑。
- **无证据 → 明确空态**：检索为空或证据不足时返回明确不可用语义，不产出看似有理的答复。
- **有界**：图只在单次请求内运行，不持久化原文/对话 checkpoint；LangGraph 的状态持久化**不**替代队列 worker。
- **越权**：请求范围不归属当前用户 → 404，不得回落到"全库检索"。

#### 4. Validation & Error Matrix
- 检索为空 → `no_evidence` 状态 → 明确空态答复。
- 引用含授权范围外的切片 ID → 校验失败 → 一次修复；二次仍失败 → 拒答。
- LLM 调用失败 → 明确失败提示（不退化为模板文案）。
- 范围越权 / 不存在 → 404。

#### 5. Wrong vs Correct
##### Wrong
```python
# 错误1：没有 question_id 时拼接固定文案冒充答疑
reply = f"关于「{question}」，建议先复习相关章节。"   # 不检索、不推理
# 错误2：让模型自己决定检索哪些资料，或信任模型给出的引用 ID
citations = draft.citation_ids                        # 未与检索结果核对
```
##### Correct
```python
# 正确：授权范围由服务层枚举；引用与本次检索结果核对；失败至多修复一次后拒答
allowed_material_ids = self._authorized_material_ids(user_id, scope)   # 确定性
candidates = search.search(query, user_id=user_id, material_ids=allowed_material_ids, ...)
if not candidates:
    return CoachAnswer(status="no_evidence", reply="暂无可用资料依据", suggestions=[...])
draft = validate(draft)          # citation_ids ⊆ {c.id for c in candidates}
if not ok and state["retry_count"] == 0:
    draft = repair(...)          # 至多一次
if not ok:
    return CoachAnswer(status="refused", ...)
```

#### 6. Tests Required
- 无证据 → 明确空态，不产出答复。
- 越权切片**不得**进入证据集合；请求越权范围 → 404。
- 坏引用 → 触发修复且 `call_count == 2`；二次坏引用 → 拒答。
- LLM 失败 → 明确失败语义，不回落模板文案。
- 题目级助教读 `reply`/`suggestions`（前端不得读 `coach_reply` 等自造字段）。

#### 代码锚点
- `backend/app/integrations/llm/coach_graph.py::build_coach_graph`
- `backend/app/services/question.py::QuestionService.ask_scoped_coach`
- `backend/app/api/v1/questions.py`（`/coach/ask`、`/{id}/ask-coach`）
- `backend/app/integrations/search/protocol.py`（按用户/资料限定检索）
- `backend/tests/unit/integrations/llm/test_coach_graph.py`

---

### Scenario: 迁移-模型一致性闸门（Migration ↔ Model Drift Gate）

#### 1. Scope / Trigger
- 任何改动 `backend/app/models/**`（新增表、新增/改名/删除列）或新增、修改 `backend/migrations/versions/**` 的工作。
- 任何「环境跑起来报 `psycopg.errors.UndefinedColumn` / `no such column`」的排查。
- 触发判据：模型与迁移是两份必须手工保持一致的事实源，而二者的一致性**没有任何编译期或启动期检查**。

#### 2. Contracts
- 迁移链产物与 `Base.metadata` 的**表名集合**、每张表的**列名集合**必须完全一致。由 `backend/tests/unit/models/test_migration_model_consistency.py` 断言，随 `task verify-backend` 自动执行。
- 断言粒度刻意**不含类型、索引、约束**：pgvector 列在 SQLite 降级为 `JSON`、UUID 等类型存在方言差异，比较类型必然产生噪音；而表/列集合已精确覆盖目标故障类别。
- 该测试必须**完全离线**，不得经由 `migrations/env.py`：`env.py::_get_target_db_url()` 优先读 `get_settings()`（`@lru_cache`，取 `.env` 中的真实库 URL），而 `tests/conftest.py` 的网络守卫只拦非环回地址、**放行 `127.0.0.1`** —— 因此在测试里调用 `alembic.command.upgrade` 会真的连上并改动开发库，且不会被守卫拦下。
- 迁移链必须收敛到**单一 head**：多 head / 断链意味着部分迁移永不生效，是同一类漂移的另一种成因。

#### 3. Wrong vs Correct
##### Wrong
```python
# 错误1：改了模型，却没写迁移（或写了没执行）—— 跑测试全绿也照不出来
class User(Base):
    avatar_object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
# 没有对应迁移，本地库仍是旧 schema；只有真实库上的查询会 500
```
```python
# 错误2：以为 conftest 的网络守卫会挡住真库访问，于是在测试里直接跑 alembic
from alembic import command
command.upgrade(Config("alembic.ini"), "head")
# env.py 优先用 get_settings() 的 .env 真库 URL；127.0.0.1 被守卫放行 → 真实改动开发库
```
##### Correct
```bash
# 正确：模型变更、迁移文件、应用到库 —— 三件事一起做完
# 1) 写迁移（必须含可执行 downgrade，见 database-guidelines 的对称性约定）
#    backend/migrations/versions/0010_<slug>.py
# 2) 应用到本地库
uv run alembic upgrade head
# 3) 自查：库内版本应与代码 head 一致
uv run alembic current   # 应等于 uv run alembic heads
```
```python
# 正确：测试在进程内回放迁移链，不经 env.py、不碰真库
with _migrated_connection() as connection:                   # 内存 SQLite
    drift = _schema_drift(_production_model_schema(), _migrated_schema(inspect(connection)))
assert drift == [], "ORM 模型与 Alembic 迁移链不一致：\n" + "\n".join(drift)
```
```python
# 正确：模型侧必须按映射类的 __module__ 过滤，不能直接读全局 Base.metadata
# —— 测试模块会把替身模型挂到同一个 Base 上（见下方 Tests Required）
if mapper.class_.__module__.startswith("app.models."):
    schema[table.name] = {column.name for column in table.columns}
```

#### 4. Tests Required
`backend/tests/unit/models/test_migration_model_consistency.py`（5 个用例）：

- `test_migrated_schema_matches_production_models`：主闸门 —— 干净状态下漂移列表为空（零误报）。
- `test_migration_chain_has_single_head`：迁移链收敛到单一 head。只断言收敛性、不写死 revision，避免每加一个迁移就要改测试。
- `test_schema_drift_detects_injected_model_column_and_table`：**反向验证** —— 注入「模型有列、迁移无列」与「模型有表、迁移无表」两种漂移必须被检出。缺这条，`_schema_drift` 退化成永真的同义反复比较也无人察觉；**一个不会失败的闸门等于没有闸门**。
- `test_schema_drift_is_clean_for_identical_schemas`：与上条配对，证明 `_schema_drift` 是「比较」而非恒定返回内容。
- `test_production_model_schema_excludes_test_only_models`：模型侧过滤必须「既不漏也不多」。漏 = 静默丢表（比多更危险），多 = 把非生产表当模型。

**跨测试污染（本闸门最易踩的坑）**：`Base` 是全局共享的，`tests/unit/models/test_user.py::TenantDummyItem` 会把自己的 `test_tenant_items` 表注册到同一个 `Base` 上。因此「模型侧」必须按映射类的 `__module__` 过滤出 `app.models.*`，直接读 `Base.metadata` 会在全量套件里把测试替身误判为漂移 —— 单文件运行通过、全量运行失败。反向地，也不要为了造场景去 `import` 其它测试模块：全量运行时它已被 pytest 按顶层名导入，按点分路径再导入会二次执行并触发 `Table ... is already defined`。

手工复核（改动模型字段时执行一次）：临时给模型加一列 → 主闸门必须失败 → `git checkout --` 撤销探针。两种漂移形态均已按此方式实测失败。

#### 代码锚点
- `backend/tests/unit/models/test_migration_model_consistency.py`
- `backend/migrations/env.py::_get_target_db_url`（为什么测试必须绕开 `env.py`）
- `backend/tests/conftest.py::block_external_network`（守卫放行 `127.0.0.1`，挡不住真库）
- `backend/tests/unit/models/test_avatar_object_key_migration.py`（单条迁移的 upgrade/downgrade 对称性测试：**不覆盖**全链一致性）
- `backend/tests/integration/test_p0_full_chain_e2e.py::db_session`（`Base.metadata.create_all()` 建表：**同样不覆盖**漂移）
