# 非功能性发现普查：重复造轮子 / 死代码 / 坏味道 / 规范违背

- **Query**: 全仓（`backend/app/**`、`backend/app/cli/**`、`miniprogram/src/**`，排除 node_modules）只读非功能性发现普查
- **Scope**: mixed（内部静态审阅 + 仓库检索）
- **Date**: 2026-09-27
- **工具说明**: 本机未安装 `rg`（`Get-Command rg` 无结果）。改用 **`git grep`**（全库、含 tests、可重跑）与 `grep` 工具执行核验。下文所有「搜索命令」均为可复现的 `git grep` 命令。

---

## 0. 核验纪律与已知反例处理

- **死代码**：报出前均在**全库（含 `miniprogram/tests/**`、后端 `tests/**`）**搜索该符号；下列"真死代码"为 0 引用，"仅测试引用"单独标注，不与真死代码混计。
- **重复实现**：均给出两处及以上 `file:line` 与能力重合点。
- **已知反例复核**：
  - `miniprogram/src/stores/{material,practice,report,user}.ts` 确为 re-export shim（内容 `export * from './xxxStore'`）。**但经全库检索确认 0 引用**（生产与测试均直接 import `*Store`），故按任务规则（"除非能证明 shim 无引用"）由"重复实现"改判为 **死代码**，见 `SMELL-FE-STORE-001`。
  - `miniprogram/src/pages/login/index.vue` 为跳转壳，由 `pages.json` 路由注册，非死代码，未列入。
  - 后端分层 / import-linter 契约全绿，未将合规分层计为坏味道。

---

## 1. 重复实现（同一能力两份及以上独立实现）

### SMELL-BE-SERVICE-001 — `validate_user_status` 两处逐字重复

- **类别**: 重复实现
- **位置**: `backend/app/services/auth.py:36-63`；`backend/app/api/deps/auth.py:91-118`
- **证据**:
  ```bash
  git grep -n "validate_user_status" -- backend
  ```
  两处函数体（None 校验 / is_active / is_deleted / verify_token_version）**逐字相同**，仅所在模块不同；`api/deps/auth.py:188,196` 与 `services/auth.py:250` 各自调用本模块副本。
- **影响**: 鉴权规则出现双份单一真相源，未来改一处会漏另一处，导致登录/接口鉴权行为分叉（安全相关）。
- **建议方向**: 保留 `services/auth.py` 一份为权威实现，`api/deps/auth.py` 改为 import 复用（或抽出 `core/security` 纯函数）。
- **预计风险**: 低（纯函数，无 IO；改动面小，测试已覆盖两处）。

### SMELL-BE-INTEG-001 — `_mask_redis_url` 两处逐字重复

- **类别**: 重复实现
- **位置**: `backend/app/integrations/idempotency/redis.py:22-33`；`backend/app/integrations/queue/redis.py:32-44`
- **证据**:
  ```bash
  git grep -n "_mask_redis_url" -- backend/app
  ```
  两处正则 `re.sub(r":([^:@]+)@", r":***@", url)` 与默认值 `redis://localhost:6379/0` 完全一致。
- **影响**: 脱敏规则双份；若某处修复脱敏漏洞（如多段凭据），另一处会泄漏 Redis 明文。
- **建议方向**: 抽取到 `integrations` 公共小工具或 `core` 脱敏工具模块。
- **预计风险**: 低。

### SMELL-BE-INTEG-002 — 存储参数校验两处逐字重复

- **类别**: 重复实现
- **位置**: `backend/app/integrations/storage/memory.py:54-84`（`_validate_bucket_and_key`、`_validate_expires_in`）；`backend/app/integrations/storage/s3.py:100-130`（同名两函数）
- **证据**:
  ```bash
  git grep -n "_validate_bucket_and_key\|_validate_expires_in" -- backend/app
  ```
  memory 与 s3 适配器各自静态复刻同一套校验与错误文案。
- **影响**: 存储适配器契约校验漂移；新增适配器需再抄一遍。
- **建议方向**: 上提到 `storage/protocol.py` 的共享校验函数或基类 mixin。
- **预计风险**: 低。

### SMELL-FE-API-001 — `fetchMaterialDetail` 与 `fetchMaterialStatus` 两份完全相同实现

- **类别**: 重复实现
- **位置**: `miniprogram/src/api/material.ts:51-56`；`miniprogram/src/api/material.ts:64-69`
- **证据**:
  ```bash
  git grep -n "fetchMaterialStatus\|fetchMaterialDetail" -- miniprogram
  ```
  两函数 URL（`/api/v1/materials/${id}`）、method（GET）、返回类型（`ApiResponse<MaterialItem>`）完全相同，但被不同调用方使用（详情页 vs 轮询/列表）。
- **影响**: 同一后端端点在前端有两个语义别名，契约演进时容易只改一个；读者误以为存在"状态专用端点"。
- **建议方向**: 保留一个（如 `fetchMaterialDetail`），另一处改 import 别名或在调用点统一。
- **预计风险**: 低（需同步更新单测引用）。

### SMELL-FE-API-002 — `markWrongRecordMastered` 是 `toggleWrongRecordResolved` 的功能子集

- **类别**: 重复实现
- **位置**: `miniprogram/src/api/diagnosis.ts:72-83`；`miniprogram/src/api/diagnosis.ts:92-105`
- **证据**:
  ```bash
  git grep -n "markWrongRecordMastered\|toggleWrongRecordResolved" -- miniprogram
  ```
  两者命中同一端点 `POST /api/v1/wrong-records/${id}/master`，返回类型相同；`toggleWrongRecordResolved(id)` 不传 `is_mastered` 时即为后端取反，与 `markWrongRecordMastered(id)`（无 body）等价。
- **影响**: 生产仅使用 `toggleWrongRecordResolved`（`wrong-book/index.vue:236`），`markWrongRecordMastered` 为冗余复制语义。
- **建议方向**: 保留语义更完整的 toggle，删除 mark（或让 mark 调 toggle）。
- **预计风险**: 低。

---

## 2. 近似重复（可抽象）

### SMELL-FE-UTIL-001 — `generateIdempotencyKey` 三份实现（算法不一致）

- **类别**: 近似重复(可抽象)
- **位置**: `miniprogram/src/utils/file.ts:15-31`；`miniprogram/src/subpackages/practice/utils/draft.ts:221-230`；`miniprogram/src/subpackages/report/utils/wrongBookFormat.ts:189-195`
- **证据**:
  ```bash
  git grep -n "generateIdempotencyKey" -- miniprogram
  ```
  - `utils/file.ts`：base62 16 字符（`crypto.getRandomValues` + 回退 `Math.random`）；
  - `practice/utils/draft.ts`：UUIDv4，优先 `crypto.randomUUID()`；
  - `report/utils/wrongBookFormat.ts`：UUIDv4，纯 `Math.random`，**无 `crypto.randomUUID` 分支**。
- **影响**: 同一"防重放幂等键"能力三种强度/格式；后端若对键格式或熵有约束，仅靠 `Math.random` 的版本存在碰撞风险；修复一处不传播。
- **建议方向**: 统一为单一工具（建议 `utils/file.ts` 的 UUIDv4 强实现），其余 import 复用。
- **预计风险**: 中（调用点涉及上传/交卷/继续练习三处，需回归幂等测试）。

### SMELL-FE-UTIL-002 — 相对时间格式化两份实现

- **类别**: 近似重复(可抽象)
- **位置**: `miniprogram/src/utils/recentLearning.ts:22-39`（`formatRelativeTime`）；`miniprogram/src/subpackages/report/utils/wrongBookFormat.ts:111-143`（`formatRelativeErrorTime`）
- **证据**:
  ```bash
  git grep -n "formatRelativeTime\|formatRelativeErrorTime" -- miniprogram
  ```
  均为"毫秒差 → 刚刚/N分钟前/N小时前/N天前 → 日期"逻辑，仅阈值（7 天 vs 30 天）与最后日期格式（`MM-DD` vs `YYYY-MM-DD`）不同。
- **影响**: 两套相对时间口径，用户在不同页面看到不一致措辞；边界（未来时间、NaN）处理各写一遍。
- **建议方向**: 抽出一个带 `options`（阈值/日期格式）的共享 `formatRelativeTime`。
- **预计风险**: 低。

### SMELL-FE-UTIL-003 — 资料状态文案 switch 重复两份

- **类别**: 近似重复(可抽象)
- **位置**: `miniprogram/src/utils/copywriting.ts:86-104`（`formatMaterialStatus`）；`miniprogram/src/utils/copywriting.ts:112-130`（`resolveMaterialStatusTag`）
- **证据**: 同一文件内对 `PENDING/PARSING/RETAKE_REQUIRED/READY|COMPLETED/FAILED` 各写一遍 switch，文本逐字相同，仅后者附加 `type`。
- **影响**: 新增状态需同步改两处；文案与徽章样式易漂移。
- **建议方向**: 单一状态→元数据表，`formatMaterialStatus` 取 `.text`，`resolveMaterialStatusTag` 返回整表。
- **预计风险**: 低。

### SMELL-FE-COMP-001 — `question_type` → 中文标签映射在 5 处各写一份（且键漂移）

- **类别**: 近似重复(可抽象) + 契约漂移
- **位置**:
  - `miniprogram/src/subpackages/material/components/QuestionCard.vue:83-92`
  - `miniprogram/src/subpackages/practice/components/QuestionRenderer.vue:113-122`
  - `miniprogram/src/subpackages/report/components/GradingResultList.vue:124-135`
  - `miniprogram/src/subpackages/report/components/WrongRecordCard.vue:161-177`
  - `miniprogram/src/subpackages/report/components/WrongRecordFilterBar.vue:121-128`
  - 权威定义：`miniprogram/src/subpackages/material/utils/questionGeneration.ts:16-21`（`QUESTION_TYPE_OPTIONS`）+ `miniprogram/src/types/question.ts:7`（`fill_in_blank`）
- **证据**:
  ```bash
  git grep -n "单选题\|QUESTION_TYPE_OPTIONS\|fill_in" -- miniprogram/src
  ```
  映射重复 5 份；且 `WrongRecordCard.vue:169-170` 使用 `fill_in_the_blank`/`fill_blank`，`WrongRecordFilterBar.vue:126` 使用 `fill_in_the_blank`，与权威类型 `fill_in_blank` **不一致**（该分支对权威值失配，会落入 default）。
- **影响**: 同一题型在不同页面显示措辞不一（"简答题" vs "主观简答题"）；键不一致导致填空题标签在错题本侧回退为"试题"。
- **建议方向**: 在 `utils` 暴露唯一 `formatQuestionType()` / 复用 `QUESTION_TYPE_OPTIONS`，删除各组件内联 map。
- **预计风险**: 中（涉及 5 个组件与快照字段，需回归渲染单测）。

### SMELL-FE-UTIL-004 — GET 空参数清洗逻辑重复

- **类别**: 近似重复(可抽象)
- **位置**: `miniprogram/src/utils/request.ts:226-239`；`miniprogram/src/api/material.ts:30-37`
- **证据**: `request` 层已对 GET 的 `undefined/null/''` 做清洗；`fetchMaterialList` 又对 `params` 做了一遍同样的清洗。
- **影响**: 重复契约逻辑，两处规则可能分叉（如某处日后加入 `all` 占位符清洗）。
- **建议方向**: 仅保留 `request` 层清洗，API 层直接透传 `params`。
- **预计风险**: 低。

### SMELL-FE-API-003 — 上传/重拍 API 的对象式包装与主函数重叠

- **类别**: 近似重复(可抽象)
- **位置**: `miniprogram/src/api/material.ts:155-185`（`uploadMaterial`）与 `:220-234`（`uploadMaterialFile`）；`:196-212`（`retakeMaterialPage`）与 `:242-278`（`reshootMaterialPage`）
- **证据**: `uploadMaterialFile` 仅转发 `uploadMaterial`；`retakeMaterialPage`/`reshootMaterialPage` 命中同一 `/reshoot` 端点、同一 `Idempotency-Key` 头与分支逻辑，仅参数形态不同。
- **影响**: 两套调用签名并存（位置参数 vs 对象），维护需双改；重拍请求体字段（`page_index`/`pageIndex`）易不一致。
- **建议方向**: 保留一种调用约定（对象式更适合小程序），删除别名层。
- **预计风险**: 中（生产调用点在 `MaterialUpload.vue`/`RetakeDrawer.vue`）。

### SMELL-BE-ALGO-001 — `calculate_cosine_similarity` 两份实现且裁剪区间不同

- **类别**: 近似重复(可抽象)
- **位置**: `backend/app/core/algorithms/grading.py:453-482`；`backend/app/core/algorithms/question_quality.py:229-253`
- **证据**:
  ```bash
  git grep -n "calculate_cosine_similarity" -- backend
  ```
  两函数同名同签名，但 `grading` 版裁剪到 `[0.0,1.0]` 且 `len==0` 提前返回；`question_quality` 版裁剪到 `[-1.0,1.0]`、`zip(..., strict=False)`。各自在文件内被调用（`grading.py:778`；`question_quality.py:375,574`）。
- **影响**: 同一数学能力两种语义；反向向量在一处得 0、另一处得 -1，阈值门禁行为不一致（且与 `quality-guidelines.md` 的"门禁用 `vector_score`"契约相关）。
- **建议方向**: 抽为 `core/algorithms` 单一实现，用参数/文档明确裁剪区间。
- **预计风险**: 中（会影响相似度阈值判定，改动需重跑对应用例）。

### SMELL-BE-SERVICE-002 — `_log_metric` 三处近重复结构化日志

- **类别**: 近似重复(可抽象)
- **位置**: `backend/app/services/diagnosis.py:207-235`；`backend/app/services/grading.py:159-186`；`backend/app/services/practice.py:138-165`
- **证据**:
  ```bash
  git grep -n "_log_metric" -- backend/app
  ```
  三处均拼装同一套 8 要素 payload（`timestamp/level/logger_name/request_id/user_ref/target_id/duration_ms/error_code/action`），差异仅 `logger_name` 来源（`__name__` vs `logger.name`）、是否暴露 `level` 入参、空 request_id 兜底。
- **影响**: 结构化日志字段契约三份；排序/字段名漂移会影响日志采集（且有脱敏红线，应单点维护）。
- **建议方向**: 抽到 `core`（或 logging util）统一函数，服务传入 action/context。
- **预计风险**: 低（不改业务语义，仅日志）。

### SMELL-BE-INTEG-003 — OpenAI 兼容 HTTP 重试逻辑两份

- **类别**: 近似重复(可抽象)
- **位置**: `backend/app/integrations/embedding/openai.py:77-158`；`backend/app/integrations/llm/openai.py:81-179`
- **证据**:
  ```bash
  git grep -n "_get_client\|_send_request_with_retries" -- backend/app
  ```
  两处 `_get_client` + `_send_request_with_retries` 结构一致：指数退避 `retry_delay_base * 2**attempt`、401/403 直抛、429/5xx 重试、JSON 反序列化异常转译；仅错误类（`EmbeddingError` vs `LLMError`）与 URL 不同。
- **影响**: 重试/超时/异常分类契约双份，易出现一个 provider 修复另一个不复用（历史上 `llm/openai.py` 已额外加 `TypeError` 兼容分支，embedding 侧没有）。
- **建议方向**: 抽出共享 HTTP 重试基类/函数，通过泛型错误工厂注入。
- **预计风险**: 中（网络行为，需两组 provider 单测回归）。

### SMELL-BE-INTEG-004 — `_execute_with_retry` 在 OCR/队列三处结构性重复

- **类别**: 近似重复(可抽象)
- **位置**: `backend/app/integrations/ocr/baidu.py:183`；`backend/app/integrations/ocr/tencent.py:167`；`backend/app/integrations/queue/redis.py:92`
- **证据**:
  ```bash
  git grep -n "_execute_with_retry" -- backend/app
  ```
  三处均为"指数退避 + 异常分类 + 认证错误直抛"的重试循环，实现细节不同（同步 HTTP / SDK / Redis 操作、错误码分类各异）。
- **影响**: 退避参数与重试语义分散，调优需三处同步。
- **建议方向**: 评估抽取通用退避执行器（保留各自异常转译回调）——注意存在实质差异，抽象需谨慎。
- **预计风险**: 中高（OCR/队列为关键路径；若抽象不当会放大影响）。

### SMELL-BE-SCHEMA-001 — DTO 字段别名同步逻辑在多个类中复制

- **类别**: 近似重复(可抽象)
- **位置**: `backend/app/schemas/diagnosis.py:53-66` 与 `:69-79`、`:104-120` 与 `:123-133`、`:309-320` 与 `:337-...`（`_sync_fields` / `_sync_after` / `_sync_pagination` 成对出现）
- **证据**: 多个 DTO 各自复制 `knowledge_point_id`↔`knowledge_id`、`knowledge_name`↔`knowledge_title` 的双向同步 `model_validator`。
- **影响**: 兼容字段映射逻辑多份，新增 DTO 需再抄；某字段语义变更会部分失同步。
- **建议方向**: 抽公共 `Annotated`/mixin/validator 复用。
- **预计风险**: 低（Pydantic before/after 校验，需注意继承顺序）。

### SMELL-BE-INTEG-005 — 内存 Fake 适配器 `_check_hooks` 重复

- **类别**: 近似重复(可抽象)
- **位置**: `backend/app/integrations/idempotency/memory.py:57-64`；`backend/app/integrations/queue/memory.py:42-55`；`backend/app/integrations/storage/memory.py:39-52`
- **证据**:
  ```bash
  git grep -n -A6 "def _check_hooks" -- backend/app/integrations
  ```
  三处均实现"故障注入（+ 延迟）触发"，仅字段名（`method_name`/`operation`）不同。
- **影响**: 测试基建重复；故障注入契约分散。
- **建议方向**: 抽 `_FaultInjectingMixin` 供三个 Fake 复用。
- **预计风险**: 低（仅测试替身）。

### SMELL-CROSS-001 — 掌握度分档阈值前后端各写一份且不一致

- **类别**: 近似重复(可抽象) / 规范违背（跨层契约）
- **位置**:
  - 后端：`backend/app/core/algorithms/mastery.py:27-37,318-352`（WEAK < 0.40、DEVELOPING < 0.70、MASTERED ≥ 0.70，共 3 档）
  - 前端：`miniprogram/src/subpackages/report/utils/reportFormat.ts:49-102`（mastered ≥ 0.85、proficient ≥ 0.70、weak ≥ 0.40、unlearned < 0.40，共 4 档）
- **证据**:
  ```bash
  git grep -n "0.85\|0.70\|0.40" -- backend/app/core/algorithms/mastery.py miniprogram/src/subpackages/report/utils/reportFormat.ts
  ```
- **影响**: 同一"掌握度分档"业务规则两处定义且阈值不同（前端多出 0.85"精通"档）；后端 `MASTERED`(≥0.70) 与前端 `proficient`(≥0.70) 语义错位，报告展示与后端聚合结论可能不一致。
- **建议方向**: 由后端在响应中返回 tier 元数据（或前端从后端契约常量生成），前端不再自定义阈值。
- **预计风险**: 中（影响报告/看板展示口径，需跨层核对）。

---

## 3. 死代码（未被引用导出）

> 判定口径：全库（`miniprogram/src` + `miniprogram/tests`）搜索 `git grep`。

### SMELL-FE-STORE-001 — 4 个 store re-export shim 全库 0 引用

- **类别**: 死代码(未被引用导出)
- **位置**: `miniprogram/src/stores/material.ts:1-2`、`practice.ts:1-2`、`report.ts:1-2`、`user.ts:1-2`
- **证据**:
  ```bash
  git grep -n "stores/material\|stores/practice\|stores/report\|stores/user" -- miniprogram
  ```
  结果全部指向 `*Store`（如 `@/stores/materialStore`、`./stores/userStore`），**无任何代码 import 无 `Store` 后缀的 shim**；`stores/index.ts` 也只从 `*Store` 再导出。即 4 个 shim 文件 0 引用。
- **影响**: 死文件干扰目录理解；与 `design.md §7` 记录的"已排除伪发现"前提（re-export shim）不同——实测无引用，应视为死代码而非有效兼容层。
- **建议方向**: 确认无外部/小程序端动态引用后删除；若需保留兼容期，至少在 `stores/index.ts` 中使用它们以证明存活。
- **预计风险**: 低（删除前再确认 uni-app 构建无路径约定依赖）。

### SMELL-FE-UTIL-005 — `subpackages/material/utils/file.ts` shim 全库 0 引用

- **类别**: 死代码(未被引用导出)
- **位置**: `miniprogram/src/subpackages/material/utils/file.ts:5`
- **证据**:
  ```bash
  git grep -n "material/utils/file" -- miniprogram      # 0 命中
  git grep -n "utils/file" -- miniprogram               # 仅 @/utils/file 与自身
  ```
  `MaterialUpload.vue:56,64`、`RetakeDrawer.vue:58` 均直接 import `@/utils/file`；subpackage 内相对 import 只到 `../utils/tree`、`../utils/questionGeneration`，无人走该 shim。
- **影响**: 死转发层。对比：同目录 `material/utils/copywriting.ts` shim **被使用**（`MaterialCard.vue:43`、`detail/index.vue:120`），故仅 file shim 死。
- **建议方向**: 删除。
- **预计风险**: 低。

### SMELL-FE-STORE-002 — `materialStore` 未被引用 action

- **类别**: 死代码(未被引用导出)
- **位置**: `miniprogram/src/stores/materialStore.ts:84-86`（`setCurrentMaterialId`）、`:143-145`（`resetMaterialState`）
- **证据**:
  ```bash
  git grep -n "setCurrentMaterialId\|resetMaterialState" -- miniprogram
  ```
  仅命中定义行与 store 内部 `return` 注册行，无任何调用方（含测试）。
- **影响**: 死 action；`setCurrentMaterialId` 与 `setActiveMaterial` 重复、`resetMaterialState` 与 `reset` 重复。
- **建议方向**: 删除或合并到已有 action。
- **预计风险**: 低。

### SMELL-FE-STORE-003 — `userStore` 未被引用 getter

- **类别**: 死代码(未被引用导出)
- **位置**: `miniprogram/src/stores/userStore.ts:21`（`isLoggedIn`）、`:24`（`hasValidToken`）
- **证据**:
  ```bash
  git grep -n "isLoggedIn\|hasValidToken" -- miniprogram
  ```
  仅命中定义 + return 注册，无调用方；二者均 `= isAuthenticated` 的别名。
- **影响**: 死别名 getter。
- **建议方向**: 删除。
- **预计风险**: 低。

### SMELL-FE-UTIL-006 — `clearWhitelistStorage` 未被引用

- **类别**: 死代码(未被引用导出)
- **位置**: `miniprogram/src/utils/storage.ts:121`
- **证据**:
  ```bash
  git grep -n "clearWhitelistStorage" -- miniprogram
  ```
  仅定义 + `storage` 对象注册处命中，无外部调用。
- **影响**: 冗余别名（`clear` 已在 `storage` 对象内暴露）。
- **建议方向**: 删除。
- **预计风险**: 低。

### SMELL-FE-API-004 — 仅被单测引用、生产 0 调用的 API 导出（测试专用导出群）

- **类别**: 死代码(未被引用导出) — **仅测试引用**，单列
- **位置**:
  - `miniprogram/src/api/auth.ts:35-42`（`refreshToken`，生产刷新由 `utils/request.ts:104` 自实现）、`:49-54`（`revokeTokens`）
  - `miniprogram/src/api/user.ts:34-42`（`updateUserProfile`）、`:49-54`（`deleteAccount`）
  - `miniprogram/src/api/practice.ts:18-26`（`createPractice`，生产走 `diagnosis.continuePractice`）
  - `miniprogram/src/api/diagnosis.ts:72-83`（`markWrongRecordMastered`）
  - `miniprogram/src/api/material.ts:242-278`（`reshootMaterialPage`）
  - `miniprogram/src/api/question.ts:111-118`（`fetchQuestionAudit`，生产用别名 `fetchQuestionAuditLogs`）
- **证据**:
  ```bash
  git grep -n "refreshToken\|revokeTokens\|updateUserProfile\|deleteAccount\|createPractice\|markWrongRecordMastered\|reshootMaterialPage\|fetchQuestionAudit" -- miniprogram/src
  # 上述符号在 src 仅有定义/别名行，无生产调用；tests 有引用（如 api/auth.spec.ts、api/user.spec.ts、api/practice.spec.ts）
  ```
- **影响**: 存在一套"只有测试在喂"的 API，给覆盖率造成有生产使用的假象；真正未被产品路径使用。
- **建议方向**: 若暂不接入产品，标注 `@internal/testonly` 或移入测试夹具；若属未来能力，补生产调用或在 `api/index.ts` 注明。
- **预计风险**: 低。

### SMELL-FE-COMP-002 — `reportFormat` 两别名仅测试引用

- **类别**: 死代码(未被引用导出) — **仅测试引用**，单列
- **位置**: `miniprogram/src/subpackages/report/utils/reportFormat.ts:40`（`formatDuration`）、`:248`（`highlightSnippetKeywords`）
- **证据**:
  ```bash
  git grep -n "formatDuration\b\|highlightSnippetKeywords" -- miniprogram
  ```
  生产仅用原名 `formatReportDuration` / `splitSnippetHighlights`；别名只在 `tests/unit/report/reportFormat.spec.ts` 被断言。
- **影响**: 别名层无生产消费者。
- **建议方向**: 删除别名或改测试直接用原名。
- **预计风险**: 低。

> **后端死代码：零发现（已确认）**。对 `backend/app` 所有非下划线顶层 `def/class` 做了"跨文件引用计数"，疑似未用项逐一用 `git grep` 复核后，均为：① 被同文件内部调用（如 `material_chunking.py:77,111,181`、`question.py:386/410/462/528`、`knowledge.py:83/109/184`）；② FastAPI 装饰器注册的路由处理器（如 `materials.py:109`、`diagnosis.py:205`）；③ CLI 子命令处理器（`cli/commands/*.py:handle_*`）；④ 测试专用 helper（如 `grading.py:485`、`diagnosis.py:127/148`）。无确认的死函数。

---

## 4. 规范违背

### SMELL-FE-COMP-003 — `question_type` 字面量漂移违背统一契约

- **类别**: 规范违背
- **位置**: 权威 `miniprogram/src/types/question.ts:7`（`fill_in_blank`）；违规处 `WrongRecordCard.vue:169-170`（`fill_in_the_blank`/`fill_blank`）、`WrongRecordFilterBar.vue:126`（`fill_in_the_blank`）
- **证据**: 见 `SMELL-FE-COMP-001` 的命令与结果；权威联合类型不含 `fill_in_the_blank`。
- **影响**: 错题本侧填空题型标签走 `default` 回退（显示"试题"），筛选值传后端也可能不匹配。属前后端/组件契约不一致。
- **建议方向**: 统一使用 `fill_in_blank`，并复用共享 `formatQuestionType`。
- **预计风险**: 低-中（影响错题本展示/筛选）。

### SMELL-FE-STORE-004 — `userStore` 文件头契约与实现不符（文档漂移）

- **类别**: 规范违背
- **位置**: `miniprogram/src/stores/userStore.ts:3-5`（注释："Enforces pure state mutation **without direct network API calls**"）；实现 `:11`（`import { fetchUserProfile }`）、`:60-91`（`hydrateProfile` 直接发起网络请求）
- **证据**:
  ```bash
  git grep -n "without direct network API calls\|fetchUserProfile" -- miniprogram/src/stores
  ```
- **影响**: 文件声明的架构约束与实现矛盾，误导后续维护者（也说明该注释未被质量门禁约束）。
- **建议方向**: 按实际（`quality-guidelines.md` 的"鉴权静默水合"场景本就允许 `hydrateProfile` 拉取）更新注释，或把请求下沉。
- **预计风险**: 低（纯注释/契约澄清）。

---

## 5. 冗余抽象层

### SMELL-FE-STORE-005 — store 内薄别名 action/getter 层

- **类别**: 冗余抽象层
- **位置**: `miniprogram/src/stores/materialStore.ts:23-25,55-57,84-86,143-145`；`miniprogram/src/stores/userStore.ts:21,24,45-47`
- **证据**:
  - `setMaterialsList`→`setMaterials`（前者生产在用，`pages/index/index.vue:116`；为纯转发）；
  - `currentMaterialId`→`activeMaterialId`、`activeVersion`→`activeVersionId`（仅测试引用）；
  - `setUserProfile`→`setProfile`（生产在用，`pages/auth/login.vue:73`；纯转发）。
- **影响**: 同一状态两个名字，读者难以判断权威名；测试与生产各用一套，进一步固化分裂。
- **建议方向**: 每个状态保留单一权威命名，删除转发别名。
- **预计风险**: 低-中（需同步改生产/测试调用点；`setMaterialsList` 已被 `quality-guidelines.md` 用作"错误覆盖示例"）。

### SMELL-FE-API-005 — API/工具 barrel 中的别名与聚合导出

- **类别**: 冗余抽象层
- **位置**: `miniprogram/src/api/question.ts:123`（`fetchQuestionAuditLogs = fetchQuestionAudit`）；`miniprogram/src/utils/storage.ts:121-129`（`clearWhitelistStorage` + `storage` 对象 + `default storage` 三重导出）
- **证据**:
  ```bash
  git grep -n "fetchQuestionAuditLogs" -- miniprogram        # 生产/测试用别名，原名反而测试专用
  git grep -n "clearWhitelistStorage\|export default storage" -- miniprogram/src/utils/storage.ts
  ```
- **影响**: 同一能力多个导出名；`storage` 同时有具名对象与 default，import 风格不统一。
- **建议方向**: 每个能力单一导出名。
- **预计风险**: 低。

### SMELL-FE-COMP-004 — `MaterialUpload.vue` 同时 re-export 与 import 同一模块

- **类别**: 冗余抽象层
- **位置**: `miniprogram/src/components/common/MaterialUpload.vue:56`（`export { generateIdempotencyKey, validateMaterialFile, type SelectedFileInfo } from '@/utils/file'`）与 `:64`（同模块 import）
- **证据**: 组件仅被默认导入使用（`QuickUploadBar.vue:35`、`list/index.vue:61`）；该具名 re-export 仅被 `tests/unit/components/MaterialUpload.spec.ts:4-7` 消费。
- **影响**: 组件文件承担了工具模块的转发职责，形成额外抽象层；源于测试从组件反向 import 工具。
- **建议方向**: 测试直接 import `@/utils/file`，删除组件 re-export。
- **预计风险**: 低。

---

## 6. 分类计数小结

| 类别 | 数量 | ID 列表 |
|---|---|---|
| 重复实现 | 5 | BE-SERVICE-001, BE-INTEG-001, BE-INTEG-002, FE-API-001, FE-API-002 |
| 近似重复(可抽象) | 13 | FE-UTIL-001~004, FE-COMP-001, FE-API-003, BE-ALGO-001, BE-SERVICE-002, BE-INTEG-003~005, BE-SCHEMA-001, CROSS-001 |
| 死代码(未被引用导出) | 8 | FE-STORE-001~003, FE-UTIL-005, FE-UTIL-006, FE-API-004, FE-COMP-002（其中 FE-API-004/FE-COMP-002 标"仅测试引用"） |
| 规范违背 | 2 | FE-COMP-003, FE-STORE-004 |
| 冗余抽象层 | 3 | FE-STORE-005, FE-API-005, FE-COMP-004 |
| **合计** | **31** | — |

**区域分布**：前端 21 条（FE-*）；后端 9 条（BE-*）；跨层 1 条（CROSS-001）。

**零发现说明**：
- **后端死代码：零发现**（所有疑似未用顶层函数经复核均为同文件内部调用 / 路由注册 / CLI 注册 / 测试 helper）。
- **重复实现（后端）：仅 `validate_user_status` 一处为逐字级重复**；其余后端发现均为"近似重复"。
- 未发现前端 `.vue` 文件超过 `docs/DESIGN.md:150` 的 300 行硬限（当前最大 291 行）；未发现 `console.*`、`TODO/FIXME`、生产代码 `any`（仅 `env.d.ts:13` 的 `declare const wx: any` 属类型声明）。

---

## 7. 最值得重构 3 条

1. **SMELL-FE-UTIL-001** — `generateIdempotencyKey` 三份实现（其中一份弱随机无 UUID 分支），幂等键是交卷/上传防重的安全底线。
2. **SMELL-BE-SERVICE-001** — `validate_user_status` 在服务层与 API 依赖层逐字重复，鉴权规则双份真相源。
3. **SMELL-FE-COMP-001** — `question_type` 标签映射复制 5 份且键漂移（`fill_in_the_blank` vs `fill_in_blank`），已造成错题本填空题回退显示。
