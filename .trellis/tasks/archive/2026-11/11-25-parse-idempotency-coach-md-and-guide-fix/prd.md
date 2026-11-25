# PRD: 解析幂等加固、AI 助教 Markdown 渲染、已删资料学情过滤与考前精讲异步提速

## 背景与目标

基于 PR #14 真机实测反馈，解决 4 项直接影响核心学习闭环的稳定性与体验问题：

1. **资料解析全链路幂等性（防双击/重复排队）**
   - 现状问题：
     - 前端点击「开始解析 / 重新解析」缺少请求中防重锁与按钮禁用态；
     - 后端 `trigger_parse` 在版本状态为 `FAILED`（而前一次失败的 RQ 自动重试仍在 `scheduled_job_registry` 等待执行）时未清理旧重试任务、也缺少按 `version_id` 的派发防重锁与 Worker 执行锁，导致同一资料版本在队列中出现两次解析连续执行（实测日志 `22:53:57 -> 22:56:30` 紧接着 `22:56:30 -> 23:01:49`）。
   - 目标：前后端双重防重，确保同一 `version_id` 同一时刻至多存在一个待执行/执行中的解析任务；双击或并发触发返回幂等结果，不重复排队、不重复消耗 OCR/VLM/LLM 额度。

2. **AI 助教 Markdown 完整富文本渲染**
   - 现状问题：
     - `CoachMessageList.vue` 中引用的 `参考讲义` 片段 (`source.excerpt`) 使用纯 `<text>` 展示，DeepSeek-OCR 输出的 Markdown 标题/列表/加粗与 LaTeX 公式全部原样暴露；
     - `AiCoachDrawer.vue` 展开态「当前语境」使用纯 `<text>` 展示含公式/Markdown 的考点定义；
     - `richText.ts` Markdown 解析器不支持分隔线 (`---`/`***`/`___`)、H5/H6 标题 (`#####`)、内部含 `*`（如 `$x^*$` / `$w^*$`）的加粗 `**...**`、`+ ` 无序列表、嵌套列表缩进、删除线 `~~...~~` 与链接 `[text](url)`，导致 AI 助教回复中这些语法以纯文本原样显示。
   - 目标：AI 助教正文、启发延伸、参考讲义摘录、展开语境及常见 Markdown 语法全部正确渲染为结构化富文本，不泄露原始 Markdown 符号。

3. **已删除资料在学情 Tab 的可见性收敛（保留历史练习记录）**
   - 用户明确决策：**隐藏已删除资料（`Material.is_deleted == True`）的题库、错题与考点掌握度，仅保留「练习记录」历史快照**。
   - 现状问题：
     - `QuestionRepository` 仅在指定 `folder_id` / `unclassified` 时过滤 `Material.is_deleted.is_(False)`，默认「全部课程」下已删资料的题库批次/题目/分组统计仍会显示；
     - `DiagnosisRepository` 错题列表、错题计数、错题分组、未掌握错题集合、薄弱考点集合均未过滤 `Material.is_deleted.is_(False)`；
     - `CollectionRepository` 题单题目计数、题单题目列表与整单开练题集未过滤已删资料的题目。
   - 目标：在「全部课程」与分课程视图下，掌握度、错题本、题库（含题单）统一排除已删资料；同时**不破坏**历史练习记录 (`Practice`) 及其报告详情中对历史题目的读取。

4. **考点考前精讲详情页（含典型例题、对比与避坑）异步非阻塞生成与提速**
   - 现状问题：
     - 实测 `POST /api/v1/knowledge/{kp_id}/study-guide/generate` 在 HTTP 请求内同步调用思考模型，耗时 26~50 秒（临近微信小程序 60 秒硬超时上限）；
     - 同步阻塞期间用户切换「精讲笔记 / 典型例题 / 对比与避坑」看到的都是静态提示，离开页面即丢失 HTTP 响应，且连续点开多个考点会并发阻塞 API worker。
   - 目标：
     - 将单考点考前精讲生成改为高优先级 RQ 异步队列 (`zhilian_high`, `priority=1`) + 单飞防重锁，接口毫秒级返回 `202 {status: "generating"}`（已缓存直接返回 `200 ready`），彻底消除 60s HTTP 超时风险；
     - 精简 Prompt 字数预算与思考冗余，将单考点生成耗时从 35~50s 压降至约 15~25s；
     - 补齐失败态写入与透传 (`status: "failed", error_message`)，前端 2s 轻量轮询、显示实时已耗时与按当前 Tab 语义化提示，失败可一键重试。

## 验收标准 (Acceptance Criteria)

- [ ] **AC-1 (解析幂等)**：同一 `version_id` 连续双击或并发调用 `POST /api/v1/materials/{id}/parse`（无论 `force=false` 或 `force=true`），处于 `queued`/`started` 活跃态时绝不重复入队；从 `failed` 强制重解析时会先取消该 `version_id` 遗留的 RQ `scheduled`/`queued` 重试任务再入队唯一新任务；Worker 侧加按 `version_id` 分布式执行锁，重复任务直接幂等跳过；前端 `backgroundTaskStore.startMaterialParse` 合并在途请求，`MaterialCourseHeader` 按钮在启动中与解析中禁用防双击。
- [ ] **AC-2 (AI 助教 Markdown)**：`richText.ts` 正确解析 `#{1,6}` 标题、`---`/`***`/`___` 分隔线、含 `*`（如 `**支持向量 $x^*$**`）的加粗、`+ ` 无序列表、缩进子列表、`~~删除线~~`、`[文字](链接)`；`CoachMessageList.vue` 的 `source.excerpt` 与 `AiCoachDrawer.vue` 展开态 `contextText` 使用 `<RichContent>` 渲染；前端单元测试覆盖全部新语法与回归样例。
- [ ] **AC-3 (已删资料学情过滤)**：软删除资料后，在「全部课程」「指定课程」「未分类」下，掌握度概览、错题本（列表/总数/分组/未攻克集合）、题库（题目列表/总数/批次列表/批次总数/分组汇总）与题单（题目计数/题目列表/开练题集）均不再包含该资料内容；同时该用户的历史 `Practice` 练习列表与历史报告详情仍完整可读。
- [ ] **AC-4 (考前精讲异步提速)**：`POST /api/v1/knowledge/{kp_id}/study-guide/generate` 在生产 RQ 队列模式下，已缓存秒返 `200 ready`，未缓存单飞加锁并入队 `zhilian_high`（`priority=1`）秒返 `202 generating`；Worker 执行成功后落库永久缓存并释放锁，终态失败写入短 TTL 错误态使 `GET .../study-guide` 返回 `status="failed"` 与 `error_message`；前端 2s 轮询、展示实时已耗时与分 Tab 状态文案、离开再进入自动接续，无 60s 超时卡死。
- [ ] **AC-5 (工程质量门禁)**：`task verify-backend` 全绿，`miniprogram` `lint` + `type-check` + `test:unit` + `build:mp-weixin` 全绿，所有 `.vue` ≤ 300 行、零裸 Hex、零 Emoji、零 `span` 警告。
