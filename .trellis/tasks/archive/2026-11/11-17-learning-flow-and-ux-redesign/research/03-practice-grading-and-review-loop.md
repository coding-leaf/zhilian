## Executive Summary

1. **「答题后学情界面啥都没有」的真实成因（实库 + 代码双实证）**：
   - **实库证明数据已入库**：最近测试用户（`a7be4fd8-...`，`贝叶斯分类器.pdf`）在 `11:47:01 UTC` 交卷练习 `c899f193-...`（6 题，总分 `0.0/6.0`），Worker `deploy-worker-1` 在 `0.338s` 内完成判题；`11:47:02 UTC` 前端触发了诊断接口，库内已真实存在 `diagnosis_reports`（1 条）、`wrong_records`（6 条）、`mastery_records`（5 条）及 `questions` 批次 `batch_b44cc12c2bdd`（9 题）。模拟调用 `/wrong-records`、`/practices`、`/questions/batches`、`/mastery` 均正常返回非空数据。
   - **前端核心断链（Tab 页无 `onShow` 刷新）**：`pages/review/index.vue:195`（及 `QuestionBankSection.vue:122`）仅在 `onMounted` 拉取数据，**未注册 `@dcloudio/uni-app` 的 `onShow`**（对比 `pages/profile/index.vue:78` 使用了 `onShow`）。小程序 TabBar 页首次切入后常驻内存，只要用户在答题前打开过「学情」Tab，之后交卷返回工作台再切回「学情」，不会发任何请求，三个区块永久停留在初次渲染的空态；加之 `loadWrongs`/`loadPractices` 静默吞错（`review/index.vue:180-192`），超时或失败时也直接显示「没有错题」。
   - **后端数据沉淀断链**：`GradingService.grade_practice`（`backend/app/services/grading.py:174-314`）判完只写 `GradingRecord` 与 `Practice.status`，**不会**写入 `WrongRecord` 或更新 `MasteryRecord`；两者仅在前端停留在报告页轮询到 `completed` 后主动调用 `POST /practices/{id}/diagnosis`（`diagnosis.py:372-587`）才顺带落库。若用户提前离开报告页、或主观题降级为 `partially_graded`，即使客观题已判错，错题本与掌握度仍全为 0。
   - **学情页产品能力缺失**：前端没有任何模块调用后端已实现的 `GET /mastery` 与 `GET /diagnosis/reports`（`miniprogram/src/api/modules/diagnosis.ts:1-10` 仅有 `apiTriggerDiagnosis`），「学情」页既无总览仪表盘，也无知识掌握度分布与薄弱点视图。
2. **「题目显示格式错乱」的实库与渲染根因**：
   - **PDF 公式乱码直出**：`MaterialSnippet`（`贝叶斯分类器.pdf` 切片 #3/#4/#7/#12/#13）含大量 `!"!#" AB&A& #$%&` 字体乱码；`QuestionPreviewCard.vue:23-26` 与 `AttemptResultCard.vue:37-40` 直接把 `source_quote` 裸文本拼在题目卡片下方；同时题干内联数学符号被拍平（如 `5f3e5686-...` 含 `P(x•j=vl|Y=ck)`、`P(Y=ck|X=xj)`），无公式/换行/富文本渲染。
   - **题型组件与样式/契约错位**：`QuestionPreviewCard.vue` 缺失 `.q-options` 样式且不展示答案/解析/评分细则；`session/index.vue:28` 绑定的 `currentQuestion.knowledge_point` 从未被 `QuestionSnapshotDTO`/`adaptQuestion` 填充而失效；单选无选项角标、多空填空仅给单行 `<input>`、题干与选项缺 `white-space: pre-wrap`；**跨端多选恢复 Bug**：后端 `PracticeItemDetailResponse` 把多选 `user_answer` 返回为 JSON 字符串 `'["C"]'`（`backend/app/schemas/practice.py:461-462`），前端 `adaptPractice` 未做 `JSON.parse`（`api/adapters/practice.ts:61-65`），导致续练时 `isMultipleSelected`（`Array.isArray`）恒为 `false`。
3. **重设计方向**：建立「交卷即刻客观秒判 + 后台主观精批 → 判题完成态自动同步错题与掌握度（不依赖报告页停留） → 分层学情中心（掌握度总览仪表盘 / 薄弱点热力 / 错题攻克 / 练习续练复盘 / 题库批次）」及统一富文本题目渲染器。

---

## 1. Live Read-Only PostgreSQL & Worker Verification

> 查询执行时间：2026-11-17 19:52–19:55 CST（UTC `11:52–11:55`），通过 `backend/.venv/Scripts/python.exe` 只读 `SELECT` `backend/.env` 所连 PostgreSQL，并检查 `deploy-worker-1` 容器日志（所有密钥/Token 均未读取或打印）。

### 1.1 全库行数基线

| 数据表 | 总行数 | 说明 |
| --- | ---: | --- |
| `materials` | 17 | 含最新上传 `贝叶斯分类器.pdf` |
| `knowledge_points` | 358 | 含 `贝叶斯分类器.pdf` 下 7 个考点（其中 `朴素贝叶斯分类器` 存在同名两条：`489eeaed-...`、`ede532fc-...`） |
| `questions` | 41 | 含最新批次 `batch_b44cc12c2bdd` 共 9 题 |
| `practices` | 3 | 含本次测试练习 `c899f193-...` + 历史 2 份（`9b6b2855-...` 用户） |
| `attempt_items` | 25 | 含本次 6 题快照与作答 |
| `grading_records` | 18 | 含本次 6 条 `offline / success / is_final=true` |
| `diagnosis_reports` | 2 | 含本次练习报告 `4af60282-...` |
| `wrong_records` | 14 | 含本次用户 6 条未掌握错题 |
| `mastery_records` | 17 | 含本次用户 5 条 `weak (score=0.0)` 记录 |

### 1.2 本次测试用户（`a7be4fd8-c18a-41b0-9bc0-f4afa2f07b7d`）实库时间线铁证

| 时间 (UTC) | 实体 / 事件 | 关键字段实值 |
| --- | --- | --- |
| `11:38:32` | `User` 创建 | `id=a7be4fd8-c18a-41b0-9bc0-f4afa2f07b7d`, `openid_prefix=wx_0c14s` |
| `11:39:00` | `Material` 上传并解析 | `id=7b2b2eec-42c6-49fa-aad3-fe3237aa8ba6`, `title="贝叶斯分类器.pdf"`, `folder_id=None`, `status="ready"` |
| `11:41:04` | `deploy-worker-1` 解析完成 | `parse_material_pipeline` Job OK（耗时 `1m40.52s`），生成 23 条 `material_snippets`、7 条 `knowledge_points` |
| `11:44:36`–`11:46:05` | `Question` 批次生成 | `batch_id="batch_b44cc12c2bdd"` 共 9 题：`6` 题 `available`、`3` 题 `pending_review` |
| `11:46:24` | `Practice` 创建 | `id=c899f193-8e12-4d5c-a272-c1fa7df3f99b`, `title="讲义专题测验"`, `folder_id=None`, `question_count=6` |
| `11:47:01.192` | 交卷 (`POST /practices/{id}/submit`) | 6 道 `attempt_items` 均 `is_answered=true`（单选 `"C"`、多选 `'["C"]'`、简答 `"werewolf"` / `"我去日期"`） |
| `11:47:01.571` | `deploy-worker-1` 判题完成 | `grading_jobs` Job OK（耗时 `0.337s`）；6 题全部命中 `OFFLINE_RULE` 判错（两道简答因与标准答案重合度 `<= 0.45` 直接走离线判错阈值），`status="completed"`, `total_score=0.0`, `max_score=6.0` |
| `11:47:02.693` | `DiagnosisReport` 生成 | `id=4af60282-...`, `score_rate=0.0`, `wrong_count=6`, `unanswered_count=0`, `weak_kps_len=5`；同时写入 6 条 `wrong_records`（`is_mastered=false`）与 5 条 `mastery_records`（`level="weak"`, `score=0.0`） |

### 1.3 模拟线上 API 路由序列化结果

在 `backend/.venv` 中直接调用 `app/api/v1/diagnosis.py::list_wrong_records`、`app/api/v1/practices.py::list_practices`、`app/api/v1/questions.py::list_question_batches` 及 `DiagnosisService.get_user_mastery_overview`（传入用户 `a7be4fd8-...`）：
- `GET /wrong-records` → `total=6, items=6, groups=[{'folder_id': None, 'material_id': '7b2b2eec-...', 'material_title': '贝叶斯分类器.pdf', 'count': 6}]`
- `GET /practices` → `total=1, items=[(c899f193-..., 'completed', '讲义专题测验')]`
- `GET /questions/batches` → `total=1, items=[{'batch_id': 'batch_b44cc12c2bdd', 'question_count': 9, 'available_count': 6, 'pending_review_count': 3}]`
- `GET /mastery` → `total_knowledge_points=7, unlearned_count=2, weak_count=5, basic_count=0, proficient_count=0`

**结论**：后端在本次用户完整走完 `detail` 页后**已把数据写入 PostgreSQL 且 API 序列化正常**；同时发现历史另一练习 `d1919c58-...`（`user_id=9b6b2855-...`）至今卡在 `status="submitted"`、`completed_at=None`、`grading_records=0`（见表 1.1 前期遗留）。

### 1.4 题目与切片实库样本（解释「题目显示格式错乱」）

1. **`material_snippets` 含严重 PDF 公式字体乱码**（被前端当作 `source_quote` 原样展示在题目卡片下方）：
   - `snippet #3`：`!"\n!"!#" !"\n!#"!#" =\n!"#!#!#\n$\n!\n"\n!\n! #AB#BAB !=\n=`
   - `snippet #4`：`AB&A&\nAB&A&\nB&\nAB&A&BA&\n!\n"#$"$...`
   - `snippet #13`：`!\n!\n"\n#$"...’"(#)* ===• !"#`
2. **`questions` 实库样本结构**：
   - 9 题的 `stem`、`options`（`[{"key": "A", "content": "..."}]`）、`answer`、`grading_rubric` 均为合法结构化 JSON/文本，**无 JSON 截断**；
   - 但 `5f3e5686-...`（`pending_review`）题干包含 PDF 复制残留符号 `P(x•j=vl|Y=ck)`；其余题干/答案包含未排版数学记号 `P(Y=ck|X=xj)`、`xij`、`P(football|sport)=(3+1)/(15+19)`；且 9 题 `source_snippet_id` 指向上述含乱码的切片。

---

## 2. Full Code Trace & Exact Root Causes (`file:line`)

### 2.1 痛点一：「随便答题后，学情界面啥都没有」

1. **P0 — TabBar 页面缺少 `onShow` 生命周期，切回「学情」永不刷新**：
   - `miniprogram/src/pages.json:41-44` 将 `pages/review/index` 注册为底部 Tab 页；小程序 Tab 页首次打开后长期驻留内存，切换 Tab 只触发 `onShow`，不会重新触发 `onMounted`。
   - `miniprogram/src/pages/review/index.vue:98-99,195-197` 仅导入并调用 `onMounted`（`Promise.all([loadWrongs(), loadPractices()])`）与 `onPullDownRefresh`，**完全未调用 `onShow`**（对比「我的」Tab `miniprogram/src/pages/profile/index.vue:59,78-83` 正确使用 `onShow`）。
   - 子组件 `miniprogram/src/pages/review/components/QuestionBankSection.vue:73,122-125` 同样只在 `onMounted(loadBatches)` 拉取一次，`defineExpose({ loadBatches })` 仅被父页面 `onPullDownRefresh` 调用（`review/index.vue:200`）。
   - 若用户在答题前曾点开「学情」（或未登录时点开），三个区块便永久锁定在空态（`我的题目` 显示空态卡、`我的练习` 因 `v-if="practices.length"` 整块隐藏、`错题巩固` 显示「没有待巩固错题」），直到手动下拉刷新。
2. **P0 — `loadWrongs` / `loadPractices` 静默吞错且无错误/重试态**：
   - `miniprogram/src/pages/review/index.vue:180-192` 的 `catch` 仅 `console.error`，未设置错误状态或重试按钮；当请求因未登录竞态或后端阻塞（15s 超时）失败时，页面直接以 `wrongRecords = []`、`practices = []` 渲染成「暂无错题」和空白练习列表。
3. **P0 — 错题本与掌握度更新强耦合于「用户停留在报告页触发 `POST /diagnosis`」**：
   - `backend/app/services/grading.py:174-314`（`grade_practice`）与 `backend/app/services/_grading_llm.py:186-204`（`refresh_practice_grading_state`）在判完整卷或自评/重判后，**只更新 `AttemptItem.score`、`GradingRecord`、`Practice.status`/`total_score`**，从未触发错题同步或掌握度重算。
   - 唯一调用 `calculate_and_update_mastery` 和 `sync_wrong_records_from_evaluations` 的入口是 `DiagnosisService.generate_diagnosis_report`（`backend/app/services/diagnosis.py:494-531`），而后端**不会在判题完成时自动调用它**（`miniprogram/src/stores/diagnosis.ts:35` 注释已明写）。
   - 该设计存在两大必现盲区：
     - 用户交卷跳到 `subpackages/report/pages/detail/index.vue` 后，若在轮询完成前点击「返回工作台」（`report/pages/detail/index.vue:121-126`）或直接切到「学情」，`POST /practices/{id}/diagnosis` 永不执行；
     - 只要卷面有 1 道主观题 LLM 超时降级为 `pending_regrade`（`Practice.status = partially_graded`），`generate_diagnosis_report` 即被 `PracticeNotGradedError (40016)` 阻断（`backend/app/services/diagnosis.py:432-447`），**导致整份试卷已判错的客观题也全部无法进入 `wrong_records` 和 `mastery_records`**。
4. **P1 — 「学情」页面缺失掌握度总览、薄弱点与报告入口**：
   - 后端已提供 `GET /mastery`（`backend/app/api/v1/diagnosis.py:187-215`，`UserMasteryOverviewResponse`）与 `GET /diagnosis/reports`（`diagnosis.py:106-152`），但前端 `miniprogram/src/api/modules/diagnosis.ts:1-10` 仅封装了 `apiTriggerDiagnosis`。
   - `pages/review/index.vue:7-22` 顶部概览卡只统计 `待攻克错题 / 已消灭错题 / 归属范围`，完全没有学习总览（累计练习/正确率/综合掌握度/四档分布/薄弱考点列表）；`PracticeEntryCard.vue:1-16` 甚至未展示得分与正确率（`PracticeSummaryResponse` 也缺 `score_rate` / `folder_name`）。

### 2.2 痛点二：「虽然后续生题成功，但是题目显示格式错乱」

1. **含乱码的 PDF 原文切片直接裸露在题目卡下方**：
   - `backend/app/services/question.py` + `_question_generation.py:120-160` 装配的 `source_snippet` 保留了 PDF 提取出的乱码字符（见 1.4 节）。
   - `QuestionPreviewCard.vue:23-26`（核对出题页）与 `AttemptResultCard.vue:37-40`（报告页）无任何清洗、折叠或异常字符过滤，直接在题目正文下方整段输出 `!"!#" AB&A& ...`。
2. **多题型与数学文本展示退化为未排版的纯文本**：
   - 题目 `stem`、`options`、`analysis` 在 `QuestionPreviewCard.vue:11-21`、`session/index.vue:34-91`、`AttemptResultCard.vue:8-25` 全部使用普通 `<text>`，缺少 `white-space: pre-wrap` / `word-break: break-word` 与公式/代码/列表/加粗富文本排版（如 `P(Y=ck|X=xj)`、`P(x•j=vl|Y=ck)` 挤成一团）。
   - `QuestionPreviewCard.vue` 的 `<style>` 中 **`.q-options` 未定义样式**，`.option-item`（line 63）无底色边框间距，选项键与文本靠 `optionDisplayText`（`api/adapters/question.ts:185-187`）拼成纯文本 `A. ...`，长选项折行后视觉混成一块；且预览卡不显示参考答案、解析与主观题评分细则，用户「核对生成题目」无从核对正误。
3. **作答页（`session/index.vue`）题型控件与考点标签缺陷**：
   - `session/index.vue:28-30` 渲染 `currentQuestion.knowledge_point`，但后端 `QuestionSnapshotDTO`（`backend/app/schemas/practice.py:188-248`）只存 `knowledge_point_id` 无名称，前端 `adaptQuestion`（`api/adapters/question.ts:41-72`）也未映射该字段，导致考点头标永久空白。
   - 单选题/判断题（`session/index.vue:36-48`）选项无字母圆圈/单选框，与多选题（`57-67`）视觉不统一；填空题（`72-80`）对多空题（后端 `_grade_fill_blank` 以 `;` / `；` / `&&` 分空，`backend/app/core/algorithms/grading.py:367-396`）仅提供单行 `<input>` 且无分隔提示；`session.scss:163-167` 的 `.opt-content` 缺失 `line-height`。
4. **跨层隐性 Bug：续练时多选题已保存答案丢失**：
   - `PracticeService.save_answer` 将多选数组用 `json.dumps` 存为字符串（`backend/app/services/practice.py:72-91`，实库 `ea1193f8-...` 值为 `'["C"]'`）。
   - `PracticeItemDetailResponse.synchronize_item_fields`（`backend/app/schemas/practice.py:461-462`）返回该字段仍为 **JSON 字符串**；前端 `adaptPractice`（`miniprogram/src/api/adapters/practice.ts:61-65`）直接原样塞入 `user_answers`；而 `session/index.vue:182-185` 的 `isMultipleSelected` 判断 `Array.isArray(current)`——当用户从「学情 → 我的练习 → 继续作答」进入（无本地 storage 草稿）时，已选的多选题选项全部不回显，点选还会覆盖旧答案。
5. **错题卡片错标「题型」为「考点」且信息残缺**：
   - `WrongRecordCard.vue:4-6,41-44` 将 `kp-tag` 绑定到 `questionTypeLabel(type)`，实际展示的是「单选题/简答题」而非知识点名称，且卡片无选项、用户错误作答、正确答案、错因与解析展开。

---

## 3. Redesign Blueprint: Post-Practice, Grading & Review Loop

目标闭环：**作答体验对齐富文本/分题型 → 交卷即刻同步判客观题 + 后台异步精批主观题 → 判题完成态自动沉淀错题与掌握度（解耦报告页停留） → 真正可复盘的「学情中心」**。

### 3.1 交卷、判题与自动学情沉淀架构（Backend）

1. **交卷响应「两阶段快慢分离」（`POST /practices/{id}/submit`）**：
   - **同步快路径（<100ms）**：交卷事务内**立即离线秒判所有客观题**（单选/多选/判断/填空，含未作答 0 分；纯内存正则计算零 I/O），同时**立即写入客观题错题与局部掌握度**，并返回已判客观题得分与 `grading_summary`（如「6 题中 4 道客观题已出分，2 道简答题 AI 精批中」）。
   - **异步慢路径（RQ Worker `grading_jobs`）**：仅对含主观题且未命中离线双阈值的题目派发后台任务；若全卷均为客观题，交卷请求直接进入 `completed` 终态，前端跳转结果页**零轮询直接出报告**。
2. **把错题与掌握度沉淀下沉为后端判题后置钩子（彻底解耦报告页）**：
   - 抽离 `DiagnosisService.sync_practice_learning_state(user_id, practice_id, *, partial_ok=True)`：
     - 对所有 `status == success` 的作答项（无论整卷是 `completed` 还是 `partially_graded`），幂等执行 `sync_wrong_records_from_evaluations`（答错记入/累加 `WrongRecord`，重做全对标 `is_mastered=True`）并重算涉及知识点的 `MasteryRecord`；
     - 在以下 4 个后端事务入口统一触发（而非仅靠前端调 `POST /practices/{id}/diagnosis`）：
       1. `PracticeService.submit_practice`（全客观题直接完成时）；
       2. `GradingService.grade_practice`（Worker 整卷判完，含 `partially_graded` 场景下已判题部分）；
       3. `GradingService.regrade_attempt`（单题重判生效时）；
       4. `GradingService.self_evaluate_attempt`（用户主观题自评覆盖后，需同步修正错题本与掌握度，当前缺失）。
   - `POST /practices/{id}/diagnosis` 收敛为「生成/取回全卷结构化诊断建议（`DiagnosisReport`）」，并在 Worker 判至 `completed` 时自动预生成，用户切去别处后再回看报告或学情页均立即可见。
3. **补充后端查询契约字段**：
   - `PracticeSummaryResponse`（`backend/app/schemas/practice.py:537`）补充 `folder_name`、`material_title`、`score_rate`、`graded_count`、`pending_regrade_count`；
   - `QuestionSnapshotDTO`（`backend/app/schemas/practice.py:188`）补充 `knowledge_point_name`（创建快照时由 `build_question_snapshot` 或列表投影填充），同时在 `PracticeItemDetailResponse` 对 `multiple_choice` 的 `user_answer`（或前端 `adaptPractice`）统一反序列化为 `string[]`；
   - `DiagnosisRepository` / `GET /mastery` 支持按 `folder_id`（课程）及 `unclassified` 过滤，匹配首页课程筛选心智；`WrongRecordItemResponse` 补充 `knowledge_point_name` 与 `material_title`。

### 3.2 作答与题目渲染体验重构（Frontend Practice & Preview）

1. **统一题目渲染组件 `<QuestionRichBody>`**（供出题核对、练习作答、报告复盘、错题卡片 4 处共用）：
   - 接入与 AI 助教同源的轻量化富文本/公式预处理管线（将纯文本 LaTeX/下标如 `P(Y=c_k|X=x_j)`、换行 `\n`、代码块/要点列表清洗排版，设置 `white-space: pre-wrap; word-break: break-word`）；
   - 将所有选择题选项统一渲染为「左字母徽章（A/B/C/D）+ 右自适应文本卡片」结构，并剔除选项内容可能自带的重复 `A.` 前缀；
   - `source_quote` 对含高乱码率的旧切片做警示折叠（「原文含扫描/公式识别噪声，点击查看原文/重扫页」），不再在题干正下方直接铺出乱码墙。
2. **分题型作答交互优化（`subpackages/practice/pages/session/index.vue`）**：
   - **单选 / 判断**：补齐圆形选框 + 选中态动画，支持「单选即保存」提示；
   - **多选**：显式标出「多选」提示与已选数量，修复 `adaptPractice` 解析 `JSON.parse` 字符串数组；
   - **填空**：按参考答案分号个数拆分为多格独立输入框（或提供「多空用分号分隔 / 回车下一空」的明确引导）；
   - **主观题**：展示本题满分分值与答题要点提示框，支持快速插入要点编号与草稿字数统计；
   - **出题核对卡（`QuestionPreviewCard.vue`）**：增加可折叠「参考答案 / 解析 / 评分细则」抽屉，让用户真正能核对题目质量后再开练。

### 3.3 「学情中心」信息架构重构（`pages/review/index.vue`）

将当前扁平堆砌的「我的题目 + 我的练习 + 错题巩固」升级为**「顶部实时刷新总览 + 4 个清晰分区（或分段切换 Tabs）」**：

1. **生命周期与数据可靠性铁律**：
   - `pages/review/index.vue` 改用 `onShow`（带短时防抖或脏标记）统一触发刷新，并显式调用 `bankSection.value?.loadBatches()`；
   - 所有区块统一具备 `loading / error + 重试 / empty` 三态，严禁静默 `catch` 后伪装成空状态；
   - 同步接入课程筛选条（全部 / 各课程 / 未分类资料），与工作台保持同一课程作用域体验。
2. **顶部「学情总览仪表盘」（接入 `GET /mastery` + `GET /practices` + `GET /wrong-records`）**：
   - **核心指标卡**：综合掌握度（环形/进度条百分比）、已掌握/待巩固/薄弱考点数、累计练习次数与平均得分率；
   - **判题进行中横幅**：若存在 `submitted` / `partially_graded` 练习，顶部高亮展示「有 N 份答卷正在判题/待重判，点击查看进度」，避免用户误以为「交卷没记录」。
3. **四个核心业务模块（推荐采用吸顶分段 Tabs：`薄弱掌握 | 错题本 | 练习记录 | 题库`）**：
   - **Tab 1 — 知识掌握与薄弱点（新增）**：按课程/资料展示四档掌握度分布（熟练/基本/薄弱/未学），薄弱考点按 `mastery_score` 升序置顶，显示「当前掌握度 + 练习次数 + 距上次练习天数（30 天遗忘提醒）+ 一键专项练」。
   - **Tab 2 — 错题攻克（重构 `WrongRecordCard`）**：展示真实知识点名称 + 错因标签（`概念偏差`/`表述不全`/`审题偏差`/`未作答`/`手工标记`）+ 连错次数；支持点击展开**我的错误作答 vs 标准答案 + 解析 + 一键标记「已攻克」**，以及按课程/未分类资料一键「错题变式再练」。
   - **Tab 3 — 练习记录（升级 `PracticeEntryCard`）**：展示来源类型徽章（常规/薄弱强化/错题巩固）、得分与得分率（如 `4/6 · 67%`）、状态徽章（作答中可「继续作答」、已完成可「查看诊断报告」、待重判可「重试判题」）。
   - **Tab 4 — 我的题库（优化 `QuestionBankSection`）**：保留批次分组、展开逐题勾选开练与手工记错题，补充批次维度「全部/待审核/可用」直观状态提示及单题预览抽屉。

---

## 4. Discovered `.trellis/spec/` Files (For Phase 2 Curation)

- `D:/code/Workspace/zhilian/.trellis/spec/backend/index.md`
- `D:/code/Workspace/zhilian/.trellis/spec/backend/directory-structure.md`
- `D:/code/Workspace/zhilian/.trellis/spec/backend/database-guidelines.md`
- `D:/code/Workspace/zhilian/.trellis/spec/backend/error-handling.md`
- `D:/code/Workspace/zhilian/.trellis/spec/backend/logging-guidelines.md`
- `D:/code/Workspace/zhilian/.trellis/spec/backend/quality-guidelines.md`
- `D:/code/Workspace/zhilian/.trellis/spec/frontend/index.md`
- `D:/code/Workspace/zhilian/.trellis/spec/frontend/api-payload-contracts.md`
- `D:/code/Workspace/zhilian/.trellis/spec/frontend/network-contract.md`
- `D:/code/Workspace/zhilian/.trellis/spec/frontend/state-management.md`
- `D:/code/Workspace/zhilian/.trellis/spec/frontend/component-guidelines.md`
- `D:/code/Workspace/zhilian/.trellis/spec/frontend/type-safety.md`
- `D:/code/Workspace/zhilian/.trellis/spec/frontend/quality-guidelines.md`
- `D:/code/Workspace/zhilian/.trellis/spec/guides/index.md`
- `D:/code/Workspace/zhilian/.trellis/spec/guides/cross-layer-thinking-guide.md`
- `D:/code/Workspace/zhilian/.trellis/spec/guides/code-reuse-thinking-guide.md`
