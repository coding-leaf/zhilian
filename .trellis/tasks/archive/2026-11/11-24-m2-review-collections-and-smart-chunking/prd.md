# PRD: M2 学情全量联动归类 + PDF/PPT 智能切片与复习级知识卡

> **父任务**：`11-24-product-ux-quality-upgrade`
> **前置完成**：M1 (`11-24-m1-ai-quality-katex-coach-fix`, 已归档并部署至 `aliyun`)
> **调研依据**：
> - `../11-24-product-ux-quality-upgrade/research/02-review-filter-and-collections.md`
> - `../11-24-product-ux-quality-upgrade/research/03-chunking-and-kp-summary-redesign.md`

## 1. 背景与目标

基于 M1 前的 6 张真机测试截图，M2 解决剩余两大核心产品体验短板（纯 UI 视觉打磨留给 M3）：

1. **学情页课程筛选断层 + 题目缺少收纳归类**：
   - 真机切到课程「啊」后，仅「学情总览」变为 `0% / 0 考点`，下方「错题本 (4)」「练习记录 (2)」「我的题库」仍显示全量课程数据。
   - 「我的题库」只有按时间戳平铺的生成批次，无法按讲义/考点浏览，也无法把重点题/易错题收进自定义题单。
2. **PDF/PPT 抽取噪声多 + 知识点总结单薄无法考前复习**：
   - 考点弹窗出现无意义元考点「本章知识小结梳理」，总结仅有裸词条（如 `• 核技巧`）甚至写着「小结仅给出条目名称，未展开具体推导」。
   - 原文依据直接吐出第 41 页目录 + `福建師範大學 FUJIAN NORMAL UNIVERSITY` 校名水印、第 42 页「谢谢！」。
   - PDF 数学公式求和号 `∑` 被抽成 `☒`（U+2612）且未触发 VLM/OCR 修复。

## 2. 功能需求与验收标准

### 2.1 学情 4 Tab 课程全量联动过滤
- **R1.1 统一后端课程过滤参数**：统一解析 `?folder_id=<uuid|__none__>`（保留 `GET /wrong-records` 既有 `unclassified: bool` 向后兼容），全覆盖 5 个接口：
  - `GET /mastery`（已有，复用统一解析）
  - `GET /wrong-records`：列表、计数、以及同响应内的 **`groups` 聚合计数** 全部按 `folder_id` / `unclassified` 过滤
  - `GET /practices`：支持 `folder_id` / `__none__`，通过 `OUTER JOIN Material` 正确归属单资料练习（`Practice.folder_id IS NULL AND Material.folder_id == X`）、课程练习与未分类练习；返回真实 `total`（修正原先 `len(items_raw)` 截断问题）及批量回填 `folder_name` / `material_title`
  - `GET /questions/batches`：支持 `folder_id` / `__none__`，按过滤后题目集合统计批次数、`question_count` 与 `available_count`
  - `GET /questions`：补齐 `folder_id="__none__"` / `unclassified=true` 支持
- **R1.2 前端 4 Tab 实时同步**：
  - 切换顶部课程胶囊时，同步刷新「考点掌握 / 错题本 / 练习记录 / 我的题库」（带请求代际 token 防竞态），清空旧课程下的错题勾选、题库三态勾选与批次展开缓存。
  - Tab 徽标数字准确反映当前课程范围（练习记录读真实 `total`）。
  - 在错题本选定单一课程时，隐藏冗余的跨课程二级单选条，但保留该课程激活状态以支持「一键举一反三」。

### 2.2 题库双轨收纳归类（客观归类 + 自定义题单）
- **R2.1 客观归类视图（零 DB 迁移）**：
  - 后端新增 `GET /questions/grouped-summary`（受 `folder_id` 约束），返回按「讲义 → 考点」分组的题目计数与摘要（批量查询，零 N+1），配合 `GET /questions`（支持 `material_id` / `knowledge_point_id`）展开浏览与勾选开练。
- **R2.2 自定义题单收藏夹（Alembic 迁移 `0014_question_collections`）**：
  - 新增 `question_collections` 与 `question_collection_items` 两张标准关系表（SQLite + PG 完全兼容）。
  - 全量 REST API 严格禁用 `PATCH`（仅 `GET / POST / PUT / DELETE`）：
    - `GET /collections`（支持 `?folder_id=<uuid|__none__>`，批量聚合 `question_count`）
    - `POST /collections`、`PUT /collections/{id}`、`DELETE /collections/{id}`（仅删题单关联，绝不删原题）
    - `GET /collections/{id}/questions`（自动排除软删除题目）
    - `POST /collections/{id}/items`（批量幂等收纳）、`DELETE /collections/{id}/items/{question_id}`（移出）
    - `GET /questions/{id}/collections` & `POST /questions/{id}/collections`（单题多选同步归属）
  - `POST /practices` 支持可选 `collection_id`（取该题单下活跃题目，上限 `MAX_PRACTICE_QUESTIONS=50`），打通「整单开练」。
- **R2.3 跨页面统一「收纳」入口**：
  - 在「我的题库」提供 3 个清晰视图切换：`按题单收纳` | `按讲义/考点` | `按生成批次`。
  - 在「题库题目行」「错题本卡片」「练习报告单题解析」提供统一「收纳」按钮，打开复用底部抽屉 `CollectionPickerDrawer.vue`（勾选已有题单或底栏输入名称「新建并收进」）。

### 2.3 PDF/PPT 智能去噪切片与考前复习级知识卡（零 DB 迁移）
- **R3.1 跨页去噪与模板页过滤（纯函数模块 `core/algorithms/document_denoising.py`）**：
  - PyMuPDF 保留块坐标 `(x0, y0, x1, y1)`，跨页频率 + 顶底带位置自动剔除重复页眉/页脚/双语校名水印（含 `福建師範大學 FUJIAN NORMAL UNIVERSITY` 样本）与纯页码行。
  - 页面角色分类：`COVER` / `TOC` / `SECTION_DIVIDER` / `CHAPTER_SUMMARY` / `REFERENCES` / `THANK_YOU` / `LOW_INFO` / `CONTENT`；空洞目录页、致谢页（「谢谢！」）、纯罗列式空小结页直接丢弃；`SECTION_DIVIDER` 仅更新 `current_chapter_title` 不产正文切片；全模板页时自动回退防误杀。
  - PPTX 升级为按幻灯片抽取 `extract_pptx_slides`，保留真实 `page_number`、标题占位符与段落边界。
- **R3.2 `☒` / `\ufffd` 乱码修复与 VLM/OCR 兜底**：
  - `ocr_quality.py` 检出 `\ufffd`、`☒` (`\u2612`)、`▯` (`\u25af`) 及数学语境方框，命中 1 处即判定 `is_garbled=True` 触发 VLM；扩充 `_SYMBOL_FONT_MARKERS`。
  - 无 VLM 或单页 VLM 失败时，脏页渲染 150 DPI PNG 走统一 `ocr.recognize_image` 兜底。
  - 前端 `richText.ts::isGarbledSnippetText` 同步识别 `☒` / `\ufffd`，历史脏切片立即引导重新解析。
- **R3.3 同章短页柔合并与极短噪声修复**：
  - 修复 `_is_ultra_short_noise_snippet` 放行「谢谢！」的漏洞。
  - 同章节相邻短 PPT 页允许跨页柔合并（`target_chars=500`, `max_chars=800`），通过 `source_info["page_end"]` 保留跨页溯源（如 `第 12–13 页`），绝不跨章。
- **R3.4 三层封杀元考点 + 复习级知识卡 + 高信噪比原文依据**：
  - `compute_chapter_stats` 与 `check_chapter_coverage` 跳过非实质章节（小结/目录/致谢等）；Prompt 禁止抽取元考点；`knowledge_quality.py` 扩展元名称黑名单并新增 `CONTENT_DEPTH` 检查（禁止空洞裸词条与「未展开具体推导」类废话）。
  - JSONB `structured_content` 向后兼容演进：`core_summary` 放宽至 200 字并用 `trim_excerpt_cleanly` 保护公式；`key_takeaways` 要求 2~5 条完整陈述句；`key_formulas` 要求带符号说明；新增可选 `derivation_steps` 与 `common_mistakes`。
  - 抽取改为字符预算分批（`<= 12` 切片且 `<= 6000` 字，贴合章节边界）+ `max_tokens=4096`。
  - 写入期 + 读取期双层去噪排序原文依据（最多 5 条，老资料立即过滤掉「谢谢！」和校名水印；过滤后为空则返回 `[]` 展示友好提示）。
  - 前端 `KnowledgeSnippetModal.vue`（严格 `<= 300` 行）升级 5 块考前复习卡片结构与页码范围展示，空板块自动隐藏，完全兼容老数据。

## 3. 非目标（留给 M3 或后续）
- 全站 Academic Editorial 视觉精修与排版重塑（属于 M3 `11-24-m3-academic-editorial-ui-polish`）。
- 微信小程序隐私协议后台配置（用户确认暂缓，后续上线前统一处理）。
- 已有历史讲义的批量离线重解析脚本（历史数据读取期已自动去噪，用户点击详情页「重新解析」即可升级为完整复习卡）。

## 4. 质量门禁
- `task verify-backend` 全绿（`ruff`、`mypy --strict`、`lint-imports`、`pytest --cov=app --cov-branch --cov-fail-under=80`、核心算法单测全绿、模型与迁移一致性检查全绿）。
- `task verify-frontend` 全绿（`eslint`、`vue-tsc`、`vitest`、`mpWeixinCompatGuard.spec.ts`，且所有 `.vue <= 300` 行、0 裸 Hex、0 Emoji、0 `PATCH`）。
- `pnpm run build:mp-weixin` 0 `span` 警告，包体符合小程序限制。
