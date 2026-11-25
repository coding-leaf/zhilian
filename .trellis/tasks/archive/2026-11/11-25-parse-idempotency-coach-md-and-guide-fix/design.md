# Design: 解析幂等、助教 Markdown、已删资料过滤与考前精讲异步化

## 1. 解析全链路幂等性架构

### 1.1 队列契约扩展 (`protocol.py` / `rq_adapter.py` / `memory.py`)
- 在 `QueueProtocol` 中保持现有 `has_active_job(task_name, match_payload)`，并新增两个可选能力方法（在 `RQQueueAdapter` 与 `MemoryQueueAdapter` 同步实现）：
  1. `has_live_job(task_name: str, match_payload: dict[str, str]) -> bool | None`：仅检查 `queued` 与 `started`（不含 `scheduled` 退避重试），用于区分「正在跑/马上跑」与「失败后等待退避重试」。
  2. `cancel_matching_jobs(task_name: str, match_payload: dict[str, str]) -> int`：遍历 `HIGH_QUEUE` 与 `DEFAULT_QUEUE` 的 `queued`、`scheduled`、`deferred` 注册表，取消匹配 `task_name` + `match_payload` 的非执行中任务并返回取消数量（不强杀 `started`）。
  3. 属性 `supports_async_worker: bool`：`RQQueueAdapter` 返回 `True`，`MemoryQueueAdapter` 返回 `False`（供考前精讲区分生产异步入队与单测同步模式）。

### 1.2 `MaterialService` 三层防重
1. **HTTP 派发短锁**：`trigger_parse` 进入状态判定与 CAS 跃迁前，尝试获取 Redis 派发短锁 `zhilian:material:parse:dispatch:{version_id}`（TTL 10s，无 Redis 时降级仅靠 DB CAS）；同一毫秒并发双击若抢锁失败直接返回当前 `target_version`。
2. **状态跃迁与退避重试清理**：
   - `target_version.parse_status in ACTIVE_PARSE_STATUSES`：
     - `force=False` -> 幂等返回；
     - `force=True` -> 仅当 `age >= STALE_PARSE_TIMEOUT` 或 `has_active_job is False`（且 `QUEUED` 满足 `ORPHAN_QUEUED_GRACE_PERIOD`）才允许恢复，否则幂等返回不入队。
   - 非活跃态（`FAILED` / `RETAKE_REQUIRED` / `PENDING` / `READY` + `force=True`）：
     - 若 `has_live_job("parse_material_pipeline", {"version_id": str(version_id)})` 为 `True` 且未超时，幂等返回不重复入队；
     - 原子 CAS 跃迁至 `QUEUED` 并提交后，先调用 `cancel_matching_jobs("parse_material_pipeline", {"version_id": str(version_id)})` 清理遗留的 RQ `scheduled` 退避重试，再入队唯一新任务。
3. **Worker 执行分布式锁**：
   - `parse_material_pipeline` 在异步路径（`sync=False` 或独立 Worker 调用）执行前获取 Redis 执行锁 `zhilian:material:parse:exec:{version_id}`（TTL 1800s，带唯一 token，`finally` 中安全释放）；若抢锁失败说明另一 Worker 正在解析同一版本，记录 warning 并幂等返回当前版本实体。

### 1.3 前端双层防重
- `stores/backgroundTask.ts`：维护 `inFlightParseRequests = new Map<string, Promise<{ message: string }>>()`，按 `materialId` 合并并发 `startMaterialParse` 调用（`finally` 清理）。
- `useCourseDetail.ts` + `MaterialCourseHeader.vue` + `course/index.vue`：新增 `isStartingParse` 状态，启动中与解析中禁用「开始解析」「重新解析」按钮并阻止 `confirmAndReparse` 重复弹窗。

## 2. AI 助教 Markdown 渲染增强

### 2.1 `richText.ts` & `richTextCore.ts`
- **标题**：支持 `#{1,6}`（H5/H6 复用紧凑字号样式）。
- **水平分隔线**：识别 `/^([-*_])(?:\s*\1){2,}$/` 独立行，输出 `<div class="rt-hr" style="...">`（`height:1px;background:rgb(214,211,209);margin:14rpx 0;`），同时加入 `isBlockStarter`。
- **行内加粗 `**...**` 修复**：改用安全配对扫描器 `findClosingDoubleAsterisk(rest)`（跳过行内公式 `$...$` / `\(...\)` 与行内代码 `` `...` `` 内部，允许普通单个 `*` 如 `$x^*$` 出现在加粗区间内），彻底解决 `**支持向量 $x^*$**` 退化成纯文本的问题。
- **列表增强**：支持 `+ ` 无序列表标记；按前导缩进空格数计算层级（每 2 空格缩进 1 级，上限 3 级，动态附加 `padding-left`）。
- **行内删除线与链接**：支持 `~~text~~`（`<span style="text-decoration:line-through;...">`）和 `[label](https?://...)`（渲染为蓝色加粗文本标签，避免小程序 `<rich-text>` 不可跳转 `<a>` 暴露原始括号 URL）。

### 2.2 `CoachMessageList.vue` & `AiCoachDrawer.vue`
- `CoachMessageList.vue`：
  - 将 `<text class="source-excerpt">{{ source.excerpt }}</text>` 改为 `<RichContent :content="source.excerpt" compact muted />`；
  - `defineOptions` 补齐 `styleIsolation: 'apply-shared'`。
- `AiCoachDrawer.vue`：
  - `contextExpanded` 为真时使用 `<RichContent :content="contextText" compact muted />` 渲染；折叠单行预览使用轻量去 Markdown 标记文本，兼顾整洁与可读性。

## 3. 已删除资料学情过滤（保留 `Practice` 历史）

- `DiagnosisRepository`：
  - `_apply_wrong_record_filters`：无条件 `join(KnowledgePoint)` + `join(Material)` 并施加 `KnowledgePoint.user_id == user_id`、`Material.user_id == user_id`、`Material.is_deleted.is_(False)`；再按需叠加 `material_id` / `folder_id` / `unclassified` 过滤。
  - `list_wrong_record_groups`、`list_unmastered_wrong_question_ids`、`list_weak_knowledge_point_ids`：统一追加 `Material.is_deleted.is_(False)`。
- `QuestionRepository`：
  - 新增统一辅助方法 `_apply_active_material_filter(stmt, user_id, folder_id=None, unclassified=False)`，始终 `join(Material)` + `Material.is_deleted.is_(False)`；当 `folder_id` 指定时额外 `join(MaterialFolder)` 并过滤 `archived_at.is_(None)`。
  - 应用于 `list_questions`、`count_questions`、`list_question_batches`、`count_question_batches`、`list_batch_sources`（内连接或过滤 `Material.is_deleted.is_(False)`）、`list_grouped_question_counts`。
  - **显式保留**：`get_question_by_id`、`list_questions_by_ids` 与 `PracticeRepository` 保持不排除已删资料，确保历史练习记录与成绩单报告完整可读。
- `CollectionRepository`：
  - `count_active_questions_by_collection_ids`、`list_collection_questions`、`list_active_question_ids`、`list_valid_user_question_ids` 统一 `join(Material)` 并施加 `Material.user_id == user_id`、`Material.is_deleted.is_(False)`。

## 4. 考前精讲异步非阻塞生成与提速

### 4.1 后端异步调度与状态契约
- `REGISTERED_TASK_NAMES` & `worker.py`：新增 `"generate_study_guide"` 任务，使用 **`priority=1` (`HIGH_QUEUE` / `zhilian_high`)** 抢占普通解析与整章预热队列。
- Redis 状态键（复用 `resolve_study_guide_redis_client`）：
  - 锁：`zhilian:study_guide:lock:{kp_id}`（TTL 180s，值 `lock_token`）
  - 错误态：`zhilian:study_guide:error:{kp_id}`（TTL 300s，存储用户可读错误摘要；开始新一轮生成或生成成功时清除）
- `StudyGuideResponse` (`backend/app/schemas/knowledge.py`)：
  - `status: Literal["ready", "generating", "empty", "failed"]`
  - `error_message: str | None = None`
- `GET /api/v1/knowledge/{kp_id}/study-guide`：
  1. DB 有永久缓存 -> `200 ready`
  2. Redis 锁存在 -> `200 generating`
  3. Redis 错误态存在 -> `200 failed` + `error_message`
  4. 否则 -> `200 empty`
- `POST /api/v1/knowledge/{kp_id}/study-guide/generate`：
  1. 若 `not force` 且 DB 已有缓存 -> 立即 `200 ready`
  2. 若 `queue` 存在且 `getattr(queue, "supports_async_worker", False)` 为 `True`（生产 RQ 环境）：
     - 若 Redis 锁已存在 -> 直接返回 `202 generating`（单飞幂等，不重复入队）
     - 获取 Redis 锁 (`lock_token`)、清除旧错误态，入队 `generate_study_guide`（`priority=1`，payload 带 `kp_id`, `user_id`, `force`, `lock_token`）；若入队失败立即释放锁并抛错
     - 立即返回 `202 generating`（<30ms，彻底告别 60s HTTP 超时）
  3. 否则（`queue is None` 或 `MemoryQueueAdapter` 单测模式）维持原单飞同步执行路径，保持向后兼容。
- Worker `_generate_study_guide`：
  - 使用 payload 中 `lock_token`（若缺失则自抢锁），执行 `_generate_with_lock_owned`，成功后清除错误态；异常时记录安全错误摘要到 `zhilian:study_guide:error:{kp_id}` 并在 `finally` 释放锁；同时在 `handle_job_terminal_failure` 中补齐终态兜底。
- Prompt 提速（`_study_guide.py`）：
  - 将总字数预算调整为 `800~1,500 汉字`，典型例题聚焦 1 道高含金量例题（3~5 步解答），易混对比 1~2 组，避坑 2~3 条，明确要求推理精炼不赘述。

### 4.2 前端异步轮询与分 Tab 反馈
- `miniprogram/src/types/knowledge.ts` & `api/adapters/knowledge.ts`：支持 `status: 'failed'` 与 `error_message`。
- `miniprogram/src/subpackages/material/pages/knowledge/index.vue`（≤ 300 行）：
  - 轮询间隔收敛至 2,000ms，最大 45 次（90s），无任何长连接 HTTP 超时风险；
  - 增加每秒跳动的 `elapsedSec` 计时器（完成/失败/卸载时清理）；
  - 按 `activeTab`（`note` / `examples` / `compare`）动态展示生成中文案（如「正在后台生成典型例题与分步解答（已耗时 12 秒）...」），并明确提示离开页面或先看「教材原文」不中断后台生成；
  - 收到 `status === 'failed'` 立即停止轮询并展示后端 `error_message` 与「重新生成」按钮。
