# 知识架构、PDF 抽取乱码与异步生题阻塞专项调研报告

## Executive Summary

1. **生题冻结全站请求（15s 超时）根因**：`POST /api/v1/questions/generate`（`backend/app/api/v1/questions.py:120`）被声明为 `async def`，却同步调用 `QuestionService`、同步 SQLAlchemy `Session`（`psycopg`）以及同步 `httpx.Client` + `time.sleep`（`OpenAICompatibleLLMAdapter`、`OpenAICompatibleEmbeddingAdapter`）。7 考点/9 题实测触发 7 轮串行 LLM+Embedding+PGVector 阻塞调用，活库 `batch_b44cc12c2bdd` 首尾落库间隔达 **89.18s**（总耗时 ~100s+，超过前端 `LONG_REQUEST_TIMEOUT_MS=90000`），期间 `uvicorn` 单线程 `asyncio` 事件循环 **100% 卡死**，导致用户切回首页后的 `GET /materials`（15s 超时）及其他所有端点全部阻塞超时，同时后台最终仍在超时后写入孤儿批次。全站 `api/v1/*.py` 60+ 路由均存在同类 `async def` 调同步 I/O 隐患。
2. **PDF 公式乱码（`AB&A&`、`"#$"$`、`!" ! #`）根因**：活库与 MinIO 实测 `贝叶斯分类器.pdf` 第 6/7/11 页包含缺少 `/ToUnicode` CMap 的 `SymbolMT`（`/MacRomanEncoding`）字体。`extract_text_from_raw_content`（`core/extractors.py:209`）仅用 `pypdf` 抽文本且只校验非空字符 `>= 10`，**完全不触发 OCR**；即便调用 `verify_ocr_quality`，`ocr_quality.py:44-46` 的 `VALID_PRINTABLE_CHAR_PATTERN` 把 `! " # $ & = A B` 全部视为合法可打印字符，导致 23 个切片中乱码最严重的 Snippet #3/#4/#7 测得 `gibberish_ratio = 0.000`！该污染直接连带导致 `batch_b44cc12c2bdd` 中 **3/9 道题**触发 `NO_SOURCE`（实词重合率 0.167~0.214 < 0.30）被降级拦截。
3. **同名重复考点（`朴素贝叶斯分类器` x2）与 250 字纯文本墙根因**：`KnowledgeService._run_extraction_with_retries`（`services/knowledge.py:250,286`）降级重试时按 `batch_size=20` 将 23 个切片切为两批（`#0..19` 与 `#20..22`），跨批抽取出两个同名 `朴素贝叶斯分类器`；去重函数 `deduplicate_candidate_points`（`core/algorithms/knowledge_tree.py:86-151`）**没有规范化同名合并**，仅用 `f"{name} {description}"` 做向量余弦阈值 `> 0.92` 去重——实测两节点 `BAAI/bge-m3` 余弦相似度仅 **0.8537**（因摘要长度分别为 274 字与 52 字），导致漏合。全库 4 份有效资料共存在 **9 组同名重复考点**。同时 `KnowledgePoint` 仅存单一 `description: Text`、`KnowledgePointList.vue` 全量展开长段文本且跨批缺父节点上下文导致树退化为扁平（`is_low_confidence=True`）。
4. **重设计路线**：(a) **非阻塞生题**：立即将同步路由改为 `def`（释放线程池）并基于现有 RQ+Redis Worker 新增 `generate_questions_job` + `question_generation_jobs` 持久化进度表与异步轮询流；(b) **PDF 公式链路**：增加 `/ToUnicode` 字体缺失与 ASCII 符号乱码启发式检测，按页渲染转图走 OCR/多模态 VLM 还原 `$LaTeX$`，并在分片前清洗 PPT 项目符号伪影；(c) **结构化知识模型**：向后兼容扩展 `KnowledgePoint.structured_content`（`core_summary` / `key_takeaways` / `key_formulas` / `importance` / `common_pitfalls`），跨批注入已建大纲并前置同名归一化合并。

---

## 一、问题 1：点击生题冻结全站请求（15s 超时）的精确根因与异步架构重设计

### 1.1 代码与运行期双端证据链

#### (1) 前端请求侧（未并发饱和连接池，而是单批长请求超 90s + 首页请求撞上 15s）
- `miniprogram/src/subpackages/material/composables/useQuestionCompose.ts:100-118` 点击生成后调用 `generateForPoints` → `generateQuestionsInBatches`（`miniprogram/src/utils/questionGeneration.ts:31-51`）。
- 实测配置（7 个考点、9 题、`MAX_QUESTION_BATCH = 20`）由 `planGenerationBatches`（`miniprogram/src/api/adapters/questionPlanning.ts:14-36`）只规划为 **1 个批次**，串行发送 1 次 `POST /api/v1/questions/generate`（`for (const batch of batches)`，非并发轰炸连接池）。
- `apiGenerateQuestions`（`miniprogram/src/api/modules/questions.ts:31-46`）显式传入 `timeout: LONG_REQUEST_TIMEOUT_MS`（`90000` ms，定义于 `miniprogram/src/utils/requestError.ts:29`）；而首页 `apiGetMaterialList`（`miniprogram/src/api/modules/materials.ts:48-64`）与 `useQuestionCompose.ts:118` 的 `apiListQuestionBatches` 均使用 `request()` 默认超时 `DEFAULT_REQUEST_TIMEOUT_MS = 15000` ms（`miniprogram/src/utils/request.ts:48`、`requestError.ts:20`）。
- 注意：`miniprogram/src/manifest.json:11-20` 未配置 `networkTimeout`，在部分微信基础库/调试环境或回退逻辑下，默认网络超时或返回首页后的 `GET /materials` / `apiListQuestionBatches` 会直接触发 `classifyTransportFailure` 报错：`请求超时（15秒），请检查后端是否可达`（`requestError.ts:111-115`）。

#### (2) 后端事件循环卡死（致命根因：`async def` 执行全同步阻塞链）
- `backend/app/api/v1/questions.py:120`：
  ```python
  @router.post("/questions/generate", ...)
  async def generate_questions(...):
      ...
      question_service.generate_questions_for_knowledge_points(...)
  ```
- **核心机制**：在 FastAPI / Starlette 中，普通 `def` 路由会被自动派发到 `anyio.to_thread.run_sync` 线程池（默认 40 线程）并发执行；而 **`async def` 路由直接在 `uvicorn` 唯一主线程 `asyncio` 事件循环上执行**。
- 然而后端全套基础设施均为**纯同步阻塞实现**：
  1. **数据库层**：`AppContainer.create`（`backend/app/container.py:102-116`）使用同步 `create_engine` + `psycopg` + `Session`。
  2. **大模型调用**：`OpenAICompatibleLLMAdapter._send_request_with_retries`（`backend/app/integrations/llm/openai.py:118-155`）使用同步 `httpx.Client`（默认 `timeout=30.0`）+ 同步 `time.sleep(delay)`（`max_retries=3`），外层再套 LangGraph 校验自愈重试（`backend/app/integrations/llm/agent_graph.py:180-183`）。
  3. **向量化调用**：`OpenAICompatibleEmbeddingAdapter._send_request_with_retries`（`backend/app/integrations/embedding/openai.py:109-137`）同样使用同步 `httpx.Client` + `time.sleep(delay)`。
  4. **串行循环放大**：`QuestionService.generate_questions_for_knowledge_points`（`backend/app/services/question.py:476-491`）对 7 个考点执行 **7 次严格串行**循环；每次循环内部先后执行：混合检索（同步向量化 + PGVector 查询）→ `run_question_generation_loop`（`services/_question_generation.py:314-413`，单考点最多 `1 + max_retries=2` = 3 次 LLM 同步调用 + 每次批量 Embedding）。

#### (3) 活库实测时间轴铁证（`batch_b44cc12c2bdd`）
对 PostgreSQL 活库执行只读查询，定位到本次复现对应的批次 `batch_b44cc12c2bdd`（`贝叶斯分类器.pdf`，9 题，difficulty=4，覆盖全部 7 个考点）：

| 序号 | 考点名称 | 题型 | 落库状态 | `created_at` (UTC) | 与首题间隔 |
|---|---|---|---|---|---|
| 1–2 | 概率论基础 | multiple_choice (2题) | 1 available, 1 pending_review | `11:44:36.273Z` | +0.0s |
| 3–4 | 文本数据概率估计 | short_answer, single_choice | 2 available | `11:44:53.041Z` | +16.8s |
| 5 | 贝叶斯分类原理 | multiple_choice | 1 available | `11:45:05.419Z` | +29.1s |
| 6 | 朴素贝叶斯分类器 (#1) | single_choice | 1 pending_review | `11:45:22.445Z` | +46.2s |
| 7 | 特征概率计算 | single_choice | 1 pending_review | `11:45:39.279Z` | +63.0s |
| 8 | 成绩分类实例 | multiple_choice | 1 available | `11:45:53.456Z` | +77.2s |
| 9 | 朴素贝叶斯分类器 (#2) | short_answer | 1 available | `11:46:05.452Z` | **+89.2s** |

- **关键结论**：仅从第 1 个考点实体构造/flush 到第 7 个考点实体构造/flush 就耗时 **89.18 秒**；加上第 1 个考点之前的检索+LLM 生成（约 12–16s）及最终 `commit()` + `attach_source_snippets()`，后端实际耗时 **~101–105 秒**（已超过前端 `LONG_REQUEST_TIMEOUT_MS = 90000`）。
- 更严重的是：在这 **100+ 秒** 内，`uvicorn` 主事件循环无法 `accept` 或响应任何新请求——用户切回首页触发的 `GET /api/v1/materials?folder_id=...` 和 `GET /api/v1/folders` 被死死堵在 TCP backlog 中直到 **15s 超时失败**；且即使用户端已超时放弃，后端仍在第 ~105s 把 9 道题静默提交进库，形成前端无感知的「孤儿批次」。

#### (4) 全站同类 `async def` 阻塞审计
经扫描 `backend/app/api/v1/*.py` 全部 60+ 端点，**所有路由均误标为 `async def` 却调用同步 Service**：
- 高危长耗时阻塞端点：`POST /questions/generate`（`questions.py:120`）、`POST /questions/{id}/ask-coach`（`questions.py:278`）、`POST /coach/ask`（`questions.py:313`）、`POST /grading/regrade`（`grading.py:107`）、`POST /practices/{id}/diagnosis`（`diagnosis.py:45`）、`POST /knowledge/materials/{id}/extract`（`knowledge.py:178`）、`POST /materials/{id}/parse`（`sync=True` 路径，`materials.py:460`）。

### 1.2 异步生题架构重设计方案

现状基础设施已有 `deploy/docker-compose.yml:39-59` 的 `worker` 服务及 `backend/app/worker.py`（RQ + Redis `zhilian_high` / `zhilian` 队列，已在 `parse_material_pipeline` 与 `grading_jobs` 使用），可直接复用：

1. **止血层（全路由同步化修正）**：
   - 将 `backend/app/api/v1/*.py` 中所有调用同步 `Session` / 同步 `httpx` Service 的路由从 `async def` 改为 `def`（仅 `_read_upload_content_guarded` / `_resolve_delete_reason` 等读取请求体流处保留异步或抽离），让 FastAPI 自动调度到 `anyio` 线程池，**彻底杜绝单接口拖死全站事件循环**。
2. **异步化层（非阻塞生题任务 + 进度持久化 + 跨页面感知）**：
   - **新增 DB 模型 `QuestionGenerationJob`（表 `question_generation_jobs`）**：字段含 `id (UUID)`、`user_id`、`folder_id`、`material_id`、`batch_id`、`status`（`queued` / `running` / `completed` / `failed`）、`total_kps`、`completed_kps`、`requested_count`、`generated_count`、`qualified_count`、`pending_count`、`error_message`、`request_payload (JSONB)`、`created_at`、`updated_at`、`completed_at`。不用纯 Redis `Job.meta` 替代的原因：需支持用户离开页面后在首页/学情页恢复查看进行中或刚完成的任务，且不受 Redis `result_ttl=86400` 过期约束。
   - **扩展 RQ 任务注册表**：
     - `backend/app/integrations/queue/protocol.py:18`：`REGISTERED_TASK_NAMES` 增加 `"generate_questions_job"`。
     - `backend/app/worker.py:61-64`：`REGISTERED_TASKS` 注册 `_generate_questions`，并在 `handle_job_terminal_failure`（`worker.py:137-186`）补齐 `generate_questions_job` 的失败态回写（参照 `_mark_grading_failed`）。
   - **API 契约演进**：
     - `POST /api/v1/questions/generate`（或新增 `POST /api/v1/questions/generate-jobs`，建议支持 `async_mode: bool = True` 默认开启并返回 HTTP `202 Accepted`）：原子创建 `QuestionGenerationJob(status='queued')`，投递 `zhilian_high` 队列（`priority=1`），**< 100ms 立即返回 `{ job_id, batch_id, status: "queued", total_kps }`**。
     - `GET /api/v1/questions/jobs/{job_id}`：返回任务实时进度（`completed_kps / total_kps`、当前百分比、完成后的 `batch_id` 与题目摘要）。
     - `GET /api/v1/questions/jobs?active_only=true`：供首页/出题页/学情页全局浮窗恢复「后台正在生成题目（3/7 考点）」状态。
   - **Worker 内部执行优化**：
     - 每个 KP 落库后更新 `completed_kps += 1`（或先并发请求各 KP 的 LLM/Embedding——用 `ThreadPoolExecutor(max_workers=3)` 把 7 考点总耗时从 ~100s 压到 ~30s，再在主线程单事务落库并提交，兼顾原子性与进度反馈）。
   - **前端交互闭环**：
     - 点击「一键智能出题」不再锁死当前页 90 秒；提交即返回任务卡片/全局进度条（复用 `createPoller` 每 2s 轮询 `GET /questions/jobs/{job_id}`）；用户可自由切回首页或浏览讲义，完成后全局 Toast/悬浮条引导「点击查看生成的 9 道题目并开始作答」。

---

## 二、问题 2：PDF 幻灯片公式乱码（`AB&A&`、`"#$"$`、`!" ! #`）的底层归因与修复路径

### 2.1 实测证据（MinIO 原始 PDF + 活库切片 + 门禁源码）

直接从 MinIO 读取 `贝叶斯分类器.pdf`（29 页，`732,968` bytes，storage_key: `users/.../v1/636c1fa2805bae1c.pdf`）并用 `pypdf` 逐页检查字体对象与抽取结果：

1. **字体编码铁证（Page 6 / Page 7 / Page 11）**：
   - Page 6（对应 Snippet #3）：嵌入字体 `/TT35`、`/TT40` 均为 `/BaseFont: /AAAA*+SymbolMT`、`/Subtype: /TrueType`、**`/Encoding: /MacRomanEncoding`**、**`has_ToUnicode: False`**。
   - Page 7（对应 Snippet #4）：嵌入字体 `/TT42`、`/TT50` 同为 `SymbolMT` + `MacRomanEncoding` + **`has_ToUnicode: False`**。
   - Page 11（对应 Snippet #7）：嵌入字体 `/TT77` 同为 `SymbolMT` + `MacRomanEncoding` + **`has_ToUnicode: False`**。
   - 由于 PowerPoint 导出的公式对象（如条件概率 $P(B|A)=\frac{P(AB)}{P(A)}$、全概率公式、贝叶斯公式、连乘符号等）使用无 `/ToUnicode` CMap 的 `SymbolMT` 字形编码，`pypdf` 按 `MacRomanEncoding` 单字节码点解码为可见 ASCII 标点与字母，直接产出：
     - Snippet #3（Page 6）：`!"\n!"!#" !"\n!#"!#" =\n!"#!#!#\n$\n!\n"\n!\n! #AB#BAB !=\n=`
     - Snippet #4（Page 7）：`AB&A&\nAB&A&\nB&\nAB&A&BA&\n!\n"#$"$\n"#$"$\n"$\n"#$"$"$\n!" ! " ! # " ! " ! # "==!" # !"!# " !#!"#`
     - 另有 PPT 项目符号字体 `Wingdings-Regular`（`/TT22`）在每页被抽成伪前缀字符 `l`、`n`、`ü`、`r`（见 Snippet #1/#2/#6/#8/#9）。

2. **三大流水线盲区为何全线放行乱码**：
   - **盲区 A（PDF 绕过 OCR 与质量门禁）**：`MaterialService.parse_material_pipeline`（`backend/app/services/material.py:383-419`）仅对图片格式 `("png", "jpg", "jpeg", "image")` 走 `process_initial_ocr_page` + `verify_ocr_quality`。`pdf` 走 `extract_text_from_raw_content`（`backend/app/core/extractors.py:209-210`）→ `_extract_text_from_pdf`（`extractors.py:69-90`），唯一的拦截门槛是 `len([c for c in full_text if not c.isspace()]) < 10`。只要 PPT 含有 10 个以上中文标题字，乱码公式页就 100% 静默放行。注意 `BaiduOCRAdapter` 已实现 `recognize_pdf_page(pdf_bytes, page_number)`（`integrations/ocr/baidu.py:398-420`），但上层流水线**从未调用**，且 `OCRProtocol`（`integrations/ocr/protocol.py:82-129`）也尚未暴露该能力。
   - **盲区 B（`ocr_quality.py` 将 ASCII 符号乱码判定为 0% 乱码）**：
     - `VALID_PRINTABLE_CHAR_PATTERN`（`backend/app/core/algorithms/ocr_quality.py:44-46`）允许全部 ASCII 标点与字母数字（`!"#$%&'()*+,-./:;<=>?@[\]^_`{|}~`、`A-Z`、`a-z`）。
     - 对活库 `贝叶斯分类器.pdf` 全部 23 个切片实测 `calculate_gibberish_ratio`：
       - Snippet #3：`valid_chars=63`，**`gibberish_ratio=0.000`**
       - Snippet #4：`valid_chars=49`，**`gibberish_ratio=0.000`**
       - Snippet #7：`valid_chars=114`，**`gibberish_ratio=0.000`**
     - 现有乱码率算法只能抓 `\ufffd` 或控制字符，对「无 ToUnicode 字体映射出的 ASCII 标点堆」**完全失明**。
   - **盲区 C（级联毒害下游出题质检 `NO_SOURCE`）**：
     - `material_chunking.py:28-30,77-87` 只清洗控制字符与零宽字符。
     - 由于 Snippet #3/#4 公式变成 `AB&A&` / `"#$"$`，活库 `batch_b44cc12c2bdd` 中**3/9 道题**在 `question_quality.py` 的 `NO_SOURCE` 检查中失败（`概率论基础` 实词重合率 `0.167`、`朴素贝叶斯分类器` `0.200`、`特征概率计算` `0.214`，均低于 `0.30` 阈值）而被降级为 `pending_review`——因为题目里的正常数学表述无法与切片中的乱码符号对齐！

### 2.2 PDF 抽取 + 乱码检测 + OCR/VLM 兜底 + 文本清洗完整修复方案

1. **Stage 1：页级 PDF 元数据与文本健康双检（`core/extractors.py` + `core/algorithms/ocr_quality.py`）**：
   - **字体 CMap 体检**：在 `_extract_text_from_pdf` 改为按页返回 `PdfPageExtraction(page_number, text, suspect_fonts, needs_ocr, reason)`；检查每页 `/Resources -> /Font`，若存在非标准文本字体且 **`"/ToUnicode" not in fobj` 且编码为 `/MacRomanEncoding` / `/WinAnsiEncoding` / 含 `Symbol` / `MTExtra` / `CambriaMath` 等字样**，标记该页为 `suspect_unmapped_font`。
   - **ASCII 符号乱码纯函数检测器**（新增于 `ocr_quality.py`）：
     - 计算单页/单行「连续非自然数学标点簇密度」：如正则 `re.findall(r'[!"#$%&\'*=?@^~]{2,}', line)`（如 `!"#!#`、`"#$"$`、`AB&A&`）及「孤立符号行比例」（去除空白后中文字数=0 且标点占比 `> 45%` 的短行）。超过阈值即判定 `SYMBOL_FONT_GARBLED`。
   - **空白/扫描页兜底**：单页有效字符 `< 10` 或整份有效字数不足时同样触发该页 OCR，而非直接报错拒收整份扫描 PDF。
2. **Stage 2：按页渲染 + 公式友好的 OCR / 多模态 VLM 重建（`services/material.py` + `integrations/ocr`）**：
   - 对于命中 `suspect_unmapped_font`、`SYMBOL_FONT_GARBLED` 或 `INSUFFICIENT_CHARS` 的**特定页码**（如本例 29 页中仅需重处理约 6–8 个含公式页，而非全本 29 页，成本可控）：
     - 方案优先序：**将异常 PDF 页渲染为高清 PNG（`pypdfium2` / `PyMuPDF`，避免受限 `BaiduOCRAdapter.recognize_pdf_page` 单页接口不通用）** → 优先调用**带公式识别能力的多模态视觉大模型（VLM）**直接输出「保留原文中文 + `$LaTeX$` 数学公式」的 Markdown 文本；若未配置视觉模型，则降级到 `ocr_adapter.recognize_image`（或 `recognize_pdf_page`）并经文本 LLM 结合上下文修复公式。
     - 在 `MaterialOCRPage` 记录这些异常 PDF 页的恢复日志与质量评估结果。
3. **Stage 3：PPT 清洗与语义切片增强（`core/algorithms/material_chunking.py`）**：
   - 增加 PPT 导出常见伪项目符号清洗规则：行首独立的 `[lnür]\s*`（Wingdings/Symbol 映射出的 `l `、`n `、`ü `、`r `）统一归一化为标准列表符 `- `；清除跨页独立页码行与无意义纯标点残行。
   - **切分粒度与上下文保留**：PPT 每页通常 100–250 字，保留 `page_number` 写入 `source_info={"source_ref": ..., "page_number": page_num}`（当前 `material_chunking.py` 走默认 `"段落"`，导致 `SnippetSourceResponse` 中所有切片 `page_index` 全部回退为 `1`！见 `schemas/knowledge.py:99-101`）。

---

## 三、问题 3：知识点架构缺陷、同名重复（`朴素贝叶斯分类器` x2）与移动端重设计

### 3.1 活库诊断与代码根因

#### (1) 为何出现两个 `朴素贝叶斯分类器`？（全库 9 组重复铁证）
- **切批窗口冲突**：`KnowledgeService._run_extraction_with_retries`（`backend/app/services/knowledge.py:238-252,286`）首轮 `batch_size=40`；若触发质检不通过重试（`re_extract_count=1/2`），`current_batch_size` 缩为 `20`。`贝叶斯分类器.pdf` 共 23 个切片，被切为 **Batch 1 (`#0..19`)** 与 **Batch 2 (`#20..22`)**，两次独立调用 LLM 且 **Batch 2 完全不知道 Batch 1 已抽取了哪些节点**。
- **向量去重盲区**：`knowledge.py:254-260` 拼接 `f"{it.name} {it.description}".strip()` 送去向量化，再调用 `deduplicate_candidate_points(..., similarity_threshold=0.92)`（`core/algorithms/knowledge_tree.py:86-151`）。
  - 活库实测两枚 `朴素贝叶斯分类器`：
    - `id=ede532fc...`：关联切片 `[9, 10, 11, 12, 15]`，`description` 长度 **274 字**（详细阐述独立假设、优缺点）。
    - `id=489eeaed...`：关联切片 `[20, 21, 22]`，`description` 长度 **52 字**（例题结尾的分类器构建步骤）。
  - 使用活库同一模型 `BAAI/bge-m3` 实测两者拼接文本余弦相似度 = **`0.8537`（< 0.92）**！
  - `deduplicate_candidate_points` **完全没有「规范化名称精确匹配（exact/normalized name dedup）」逻辑**，导致同名不同描述的节点全部漏过合并！
- **全库泛化影响**：活库共 5 份未删除资料，其中 **4 份均存在同名重复考点（共 9 组）**：
  - `贝叶斯分类器.pdf`：`朴素贝叶斯分类器` x2
  - `第六章 - 降维算法.pdf`：`主成分分析算法` x2、`累计方差贡献率` x2
  - `第二章 - 线性回归.pdf`：`多元线性回归` x2、`唯一解条件` x2
  - `第二章 - 广义线性回归.pdf`：`逻辑回归` x2、`评价指标` x2、`多分类逻辑回归` x2、`ROC曲线` x2
- **模型与前端透传放大**：`knowledge_points` 表（`models/knowledge.py:116-121`）无 `(version_id, normalized_name)` 唯一性约束；`useComposeConfig.ts:49-50` 与 `questions/index.vue:101` 将全部节点展平为 `{ id, name }` 胶囊列表，`QuestionConfigPanel.vue:11-21` 直接并排渲染两枚完全无法区分的 `朴素贝叶斯分类器` 胶囊。

#### (2) 为何知识点退化为「250 字大段纯文本墙 + 扁平树」？
- **数据模型扁平**：`KnowledgePoint`（`models/knowledge.py:64-92`）除 `name`/`level`/`parent_id` 外只有单一 `description: Text`；`ExtractedKnowledgeItem`（`core/algorithms/knowledge_tree.py:24-39`）也仅有单个字符串字段 `description`。
- **Prompt 失控与跨批孤儿节点**：`_build_batch_prompt`（`services/knowledge.py:150-157`）未约束 `description` 的结构、字数与要点格式，导致模型在 `贝叶斯分类器.pdf` 上吐出 181–274 字大段 prose（平均 149 字，最大 274 字），而在 `Maven基础讲义` 上甚至全部吐出 0 字空串（`avg_desc_len=0`）；且全部 5 份活跃资料都被质检判定为 **`is_low_confidence=True`**（`贝叶斯分类器.pdf` 7 个节点中有 5 个为 `level=1` 根节点、`max_level=2`，触发质检不合格/降级）。
- **前端展示无结构**：`KnowledgePointList.vue:8-23` 不区分父子层级直接全量平铺，并把整个 `node.description` 全文铺开在卡片上，没有核心一句话、没有要点列表、没有公式高亮、没有重要度分级与折叠/展开机制。

### 3.2 结构化知识点 Schema 与抽取流水线升级方案

#### (1) 向后兼容的后端模型与 API Schema 升级
在 `knowledge_points` 表保留 `description`（改为写入**简明一句话核心定义 <= 60 字**，确保旧版出题/助教上下文拼装零破坏），新增结构化字段 `structured_content: JSONB`（默认 `{}`，Alembic 迁移零停机兼容历史数据）以及 `importance: String(16)`（`core` / `important` / `supporting`，默认 `important`）与 `sort_order: Integer`：

```json
// KnowledgeStructuredContent (存储于 knowledge_points.structured_content JSONB)
{
  "core_summary": "在给定类别条件下假设特征相互独立，以极大化后验概率完成分类。",
  "key_takeaways": [
    "条件独立假设：P(X|Y=c_k) = ∏ P(x_j|Y=c_k)",
    "P(X) 与类别无关，决策时可省略",
    "零概率问题需通过拉普拉斯平滑（分子+1，分母+L）修正"
  ],
  "key_formulas": [
    "P(Y=c_k | X) \\propto P(Y=c_k) \\prod_{j=1}^{n} P(x_j | Y=c_k)"
  ],
  "exam_role": "core",
  "common_pitfalls": [
    "误将先验概率与后验概率混淆",
    "特征存在强相关性时分类准确率会下降"
  ]
}
```
- **API 兼容策略**：`KnowledgeTreeNodeResponse` 与 `KnowledgePointDetailResponse`（`schemas/knowledge.py:16-64`）继续返回 `description`（即 `core_summary`），同时新增可选字段 `structured_content: KnowledgeStructuredContent | None = None` 与 `importance: str = "important"`；对历史无 `structured_content` 的老数据，前端按 `description` 自动降级折叠展示。
- **`FolderKnowledgePointItem`（`schemas/folder.py:85-94`）增强**：补充 `parent_id`、`level`、`core_summary`（或 `importance`）、`snippet_count`，让课程级选考点也能按树形/重要性分组展示，而不是 7 个扁平胶囊。

#### (2) 抽取与去重核心修复（`services/knowledge.py` + `core/algorithms/knowledge_tree.py`）
1. **跨批大纲上下文传递**：分批抽取（`batch_idx > 0`）时，将前面批次已抽出的 `{temp_id, name, level}` 树形骨架注入 `_build_batch_prompt`，要求模型若发现同一概念的新切片，直接**复用已有 `temp_id` 补充要点**；若发现子概念，则把 `parent_temp_id` 挂到已有父节点下，彻底消除跨批重复与伞状 L1 孤儿节点。
2. **两阶段强制去重（`deduplicate_candidate_points`）**：
   - **第一阶段（确定性同名归一化合并）**：构造 `norm_name = re.sub(r"[\s\-_（）()：:·]+", "", item.name).lower()`；凡 `norm_name` 相同（且不构成明显不同父语境，或同资料内名称一致）的节点，**无条件合并**到先出现（或信息更完整/层级更靠上）的主节点：
     - 并集聚合 `source_snippet_indices`；
     - 合并去重 `key_takeaways`、`key_formulas`、`common_pitfalls`；
     - 若一者有 `parent_temp_id` 而另一者为 `None`，优先保留有效父节点关系并重定向所有指向被合并节点的 `parent_temp_id`。
   - **第二阶段（向量语义去重）**：对合并后的独立节点再用 `name + core_summary`（不再拼接长篇大论稀释语义）计算余弦相似度去重。
3. **质检阈值与分层树优化**：针对 PPT 短讲义（如 23 切片、2000–4000 字）优化 `knowledge_quality.py` 中 `MIN_KP_COUNT_SMALL_DOC` / `MAX_LEVEL_2_RATIO` 的误伤，并在 Prompt 中明确要求构造「章节主题(L1) → 核心原理/模型(L2) → 计算方法/公式/实例(L3)」2~3 层树形结构。

---

## 四、已发现并核对的 `.trellis/spec/` 路径清单

- 后端规范（已核对）：
  - `D:\code\Workspace\zhilian\.trellis\spec\backend\index.md`
  - `D:\code\Workspace\zhilian\.trellis\spec\backend\directory-structure.md`
  - `D:\code\Workspace\zhilian\.trellis\spec\backend\database-guidelines.md`
  - `D:\code\Workspace\zhilian\.trellis\spec\backend\error-handling.md`
  - `D:\code\Workspace\zhilian\.trellis\spec\backend\quality-guidelines.md`
  - `D:\code\Workspace\zhilian\.trellis\spec\backend\logging-guidelines.md`
- 前端规范（已核对）：
  - `D:\code\Workspace\zhilian\.trellis\spec\frontend\index.md`
  - `D:\code\Workspace\zhilian\.trellis\spec\frontend\network-contract.md`
  - `D:\code\Workspace\zhilian\.trellis\spec\frontend\api-payload-contracts.md`
  - `D:\code\Workspace\zhilian\.trellis\spec\frontend\state-management.md`
  - `D:\code\Workspace\zhilian\.trellis\spec\frontend\type-safety.md`
  - `D:\code\Workspace\zhilian\.trellis\spec\frontend\component-guidelines.md`
  - `D:\code\Workspace\zhilian\.trellis\spec\frontend\hook-guidelines.md`
- 跨层规范：
  - `D:\code\Workspace\zhilian\.trellis\spec\guides\index.md`
  - `D:\code\Workspace\zhilian\.trellis\spec\guides\cross-layer-thinking-guide.md`
  - `D:\code\Workspace\zhilian\.trellis\spec\guides\code-reuse-thinking-guide.md`
