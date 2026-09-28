# 学习闭环修复：契约与状态研究

## 资料上传和解析

- `backend/app/models/material.py:34-56`：资料主状态为 `pending/parsing/ready/failed/retake_required`；版本解析状态含 `queued/parsing_doc/.../ready/failed`。
- `backend/app/services/material.py:470-503`：新版本初始写 `queued` 且 `create_material` 直接入队。
- `backend/app/api/v1/materials.py:236-253`：上传路由另加独立 Session 后台解析任务。用户已决定关闭上传自动解析，必须同时处理这两条调度；已排队的历史任务不在本次取消范围。
- `backend/app/services/material.py:1394-1465`：手动 `trigger_parse` 可使状态入队并调度；`POST /materials/{id}/retry` 是用户主动失败重试。新上传版本应有与“尚未启动”一致的解析状态，不得继续标记为 `queued` 而实际不入队。
- 前端以 `GET /materials/{id}` 主状态与细粒度 `parse_status` 显示进度；`ready` 后才请求知识树。上传入口、课程卡片、资料详情共用状态映射。

## 出题与练习

- `backend/app/schemas/question.py:18-85`：生成必须指定 `folder_id` 或 `material_id`，单次 `count` 在 1 到 20，返回题型为 `question_type`、选项为 `{key, content}`。前端的 `type`、字符串选项及 `source_quote` 不能直接读取原响应。
- 用户已确认所有已选知识点都须覆盖。预计题量至少为 `max(已选考点数, 用户指定题量)`；若超过单次 20 题限制，需要分批。合格题实际覆盖不足时明确提示，不得假称完成覆盖。
- 用户已确认核对页不展示答案/解析，支持剔除或重新生成不合适题；剔除后重新核对考点覆盖，不足则阻止进入测验。
- `backend/app/schemas/practice.py:423-459`：创建/查询练习返回 `items[].question_snapshot`，不是 `questions[]`；作答项带 `attempt_item_id/question_id/user_answer/score/grading_status`。统一 API adapter 映射题目预览、答题、结果页使用的投影。
- `backend/app/schemas/practice.py:640-668`：逐题保存传 `question_id/user_answer`；前端草稿异步写入需在提交前全部确认，并避免同题乱序。`POST /submit` 的 `Idempotency-Key` 应对同一提交重试保持稳定。

## 交卷与诊断

- `backend/app/core/config.py:158-183` 默认队列是 `memory` 且 `immediate_mode=False`。仓库里没有解析或判题任务的运行时消费者；`MemoryQueueAdapter.process_next` 只在测试中调用，`RedisQueueAdapter` 只实现入队、状态查询与取消。现有上传路由独立 BackgroundTasks 是解析可能运行的唯一显式 Web 调度路径；交卷只入队判题，可能永久待处理。修复设计必须增加真实执行器或明确改变调度方式，并验证重启/失败恢复。
- `backend/app/services/practice.py:1106-1130`：交卷先写 `completed`，再派发异步判题；此时 `completed` 不代表判完。
- `backend/app/services/grading.py:258-270`：全判完才写 `completed_at`；若有待重判项，改为 `partially_graded`。
- `backend/app/services/diagnosis.py:471-486`：目前只看 `status` 就允许生成正式诊断，存在交卷后抢先生成报告的竞态。需以后端真正终态信号约束诊断生成。
- `backend/app/schemas/diagnosis.py:172-210`：诊断只含学情汇总，无前端假定的 `details/score/accuracy/weaknesses`；逐题结果来自 `GET /practices/{id}`，错题知识点来自错题记录或明确的服务端关联。
- 用户已确认交卷后立刻进入结果页，区分已判/待判；正式诊断全判完后出现；可离开并从学情页重进。未判结果不得显示为零分/答错。

## 错题与 AI 助教

- `backend/app/schemas/diagnosis.py:393-416`：错题响应有考点 ID 和原题快照，但无课程/资料 ID；现有列表分页。用户已确认按课程归类，只有一个课程时直接巩固，多个课程时选择课程，未分类资料单独归类。需补可分页的分组/筛选契约，不能仅按第一页 50 条推断全部课程。
- `backend/app/services/practice.py:586-593`：仅凭跨资料 `question_ids` 组卷会将首题资料写成练习归属，不适合伪装为跨课程一卷。
- `backend/app/schemas/question.py:273-277`：题目助教返回 `reply/suggestions`；前端目前读取 `coach_reply`。
- 课程/知识点助教当前是固定文案。`SearchProtocol.search` 支持按用户、资料/版本限定检索（`backend/app/integrations/search/protocol.py`）；课程范围需要服务层枚举当前用户有权访问的资料，合并排序切片，再给 LLM 提供有限、可溯源的上下文。
- `backend/app/integrations/llm/agent_graph.py` 已用 LangGraph `StateGraph` 实现结构化输出的校验、一次修复及回退；`KnowledgeService`、`QuestionService` 直接调用，`GradingService` 与题目级助教经 `LLMAdapter.generate_structured` 间接复用。课程助教新增图只负责授权范围检索、证据门控、带引用生成和引用校验，不重复造通用结构化输出图。
- LangGraph 的 checkpoint 持久化是图状态持久化，并非 Redis 消费者；即使启用 checkpoint，仍需独立 worker 启动任务。课程助教本期不存原文、对话或模型上下文的持久 checkpoint，避免额外隐私与保留策略问题。

## 头像与验证边界

- 个人中心目前只有 URL 输入，后端仅存 `avatar_url`，没有头像上传接口；对象存储协议支持写入、删除、签名下载（`backend/app/integrations/storage/protocol.py`）。用户已确认直接选图上传并由应用托管。
- 头像对象键应持久保存；返回给小程序的展示 URL 可续期，不能把会过期的签名 URL 当作永久数据库值。上传失败保留旧头像，服务端限制大小和真实图片格式。
- 既有前端测试只有两条 store 状态测试，无法验证真实响应契约；使用后端响应模型序列化样本构建前端契约 fixture，并覆盖失败/异步/恢复路径。

## 独立 worker 选型

- 现有 `QueueProtocol` 是入队/查询/取消边界，Redis 实现仅维护自有 List/状态键，没有消费、确认或崩溃恢复；业务服务已有 `parse_material_pipeline` 和 `grade_practice_submission` 可作 worker 入口。
- 采用 RQ 作为 Redis 上的进程外执行器是当前推荐技术路线：保留业务侧 `QueueProtocol`，将生产 Redis 适配层接到 RQ job/registry，注册受控任务名到入口函数，不反序列化任意客户端函数。RQ 自带 worker、失败注册表及有限重试，Windows 开发机可用 `SpawnWorker`；现有内存适配器留给单元测试。
- 解析与判题任务必须幂等、可重试，状态以数据库领域记录为准，RQ 状态仅作运维诊断。失败和超过最大重试后需将业务记录标成可见失败/待重判，并保留手动重试入口；部署要启动 Redis 和 worker，测试要用实际执行器消费一次。
