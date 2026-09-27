# 课程文件夹与出题-答题闭环重构

## Goal

让「上传资料 → 解析知识树 → 出题 → 答题 → 判题」形成用户可感知的完整闭环；以「课程文件夹」承载课程分类，并在**同一文件夹内对多份资料联合综合出题**；资料可默认落「未分类」再移动归位；课程删除采用**归档 + 可恢复 + 7 天反悔期**；答题统一界面、按题型分流判题；控制台移除总学习分、改为课程入口。前后端全改（含后端模型与数据库迁移）。

## Background / 已确认事实（代码证据）

- **无课程/文件夹实体**：`materials` 表扁平、按 `user_id` 归属，无分类层级（`backend/app/models/material.py:86`）。
- **解析/知识树/出题的原子单元是「资料 + 版本」**：
  - 知识树 `KnowledgePoint` 绑定 `(material_id, version_id)`（`backend/app/models/knowledge.py:42,49`）。
  - `Question` 绑定 `(material_id, version_id, knowledge_point_id)`（`backend/app/models/question.py:131,138,145`）。
- **多批次上传 = 同一资料的「版本」**：`MaterialVersion`（`material.py:180`）支持重新导入产生递增版本；秒传去重在内容相同时复用存储。
- **资料产生路径仅 3 条**：API 上传（`materials.py:198`）、CLI `material import`（`cli/commands/material.py:134`）、`smoke`（`cli/smoke.py:245`），均走 `import_material_file`（`services/material.py:516`）。
- **练习创建后端已具备**：`POST /practices` 支持 `material_id + knowledge_point_ids + mode` 组卷（`backend/app/api/v1/practices.py:48`）；`Practice.material_id` 目前 `NOT NULL`（`practice.py:234`）。
- **前端答题页存在但入口断裂**：
  - 答题页 `subpackages/practice/pages/session/index`（`miniprogram/src/pages.json:94`）。
  - 仅两处可进入：控制台「继续练习」草稿卡（`pages/index/index.vue:151`）、报告/错题本「一键强化/巩固」（`subpackages/report/components/ContinuePracticeBar.vue:142`）。
  - 出题产物「题目列表」页**无「开始答题」入口**（`subpackages/material/pages/questions/index.vue`）。
  - 组卷 API `createPractice`（`miniprogram/src/api/practice.ts:25`）定义后**全库零调用** → 「用生成的题目组卷」未接线。
- **判题机制已具备**：客观题离线秒判、主观题 LLM/AI 兜底、用户自评 `GradingChannel{offline,ai,user_self}`、`pending_regrade` 三态（`practice.py:70-84`）。
- **控制台总学习分**：`MasteryDashboardBar` 展示 `overall_score` 综合掌握度分与四档分布（`miniprogram/src/components/home/MasteryDashboardBar.vue`）。
- **需求文档依据**：目标用户为自学者；顶层实体是「学习资料」，练习范围按「章节或知识点」勾选（章节来自解析来源信息，非用户手建）；为不把质量责任转移给用户，已取消知识点人工编辑。

## Requirements

- R1：用户可自建单层「课程文件夹」。
- R2：文件夹内可一次性 / 多批次上传多份资料；每份资料独立解析、独立生成知识树。
- R3：**可在同一文件夹内跨其下多份 ready 资料联合综合出题**（资料级知识树不变，出题时跨资料联合抽题）。
- R4：资料解析完成后可出题；出题产物按文件夹范围可查。
- R5：独立答题页闭环——从课程/题目范围「开始答题」组卷并进入作答；判题按题型分流（客观秒判 / 主观 LLM / 降级自评），界面统一。
- R6：控制台首屏改为课程文件夹列表入口；移除「总学习分」。
- R7：修复「出题产物无答题入口」断链（`createPractice` 接线）。
- R8：**上传不必先建课程**——未指定课程的资料默认落「未分类」（`folder_id` 可空，前端虚拟分组，不可归档/重命名）。
- R9：**资料可在「未分类 ↔ 课程」及课程之间移动**。
- R10：**删除课程 = 归档（软删除）**：列表隐藏、归入「已归档」可随时恢复；归档时其下资料一并归档；**7 天反悔期**，逾期清理。

## Decisions（已确认）

- D1（OQ1）：文件夹**不是**纯分类容器；需支持「同文件夹内多份资料联合综合出题」。
- D2（OQ2）：跨资料综合出题采用「**资料级知识树 + 出题时跨资料联合**」——知识树不合并、不落课程级树。
- D3（OQ3）：答题实现「**仅判题分流，界面统一**」——一套线性作答界面；B（刷题/模考节奏分流）不做。
- D4（OQ4）：控制台改为「**课程文件夹列表入口**」，下方保留快捷上传与最近学习；移除综合掌握度分卡。
- D5（OQ5）：**不做存量迁移**——除测试外无真实用户，直接清空现有数据。
- D6（OQ6）：**单层课程文件夹**，一份资料只属一个课程；`parent_id` 字段预留可空，未来可升级嵌套。
- D7（修订）：**保留「未分类」**为默认桶（`folder_id` 可空 + 前端虚拟分组）；上传不必先建课程；未分类内可移动资料归位。
- D8（本轮）：**课程删除 = 归档可恢复**（软删除 + 7 天反悔 + 逾期清理）；归档连带其下资料。
- D9（本轮）：**全局快捷上传不再阻断**——未选课程即落未分类（覆盖此前「上传必须先选课程」的设想）。

## Task Map（父任务 + 可独立验证的子任务）

> 父任务承载需求集、任务地图与跨子任务验收；子任务各自拥有 `prd.md`/`design.md`/`implement.md`。依赖写入子任务，不靠树位置隐式表达。

- **P（本任务）**：父任务，承载需求、拆解与最终集成验收。
- **C1 后端 · 课程文件夹实体、归档与资料归属（迁移 0005）**：`material_folders` 模型（含 `archived_at`）+ `materials.folder_id`（可空）+ 文件夹 CRUD + 归档/恢复/逾期清理 + 资料按课程过滤 + 移动资料 API。验证：`pytest` + 路由契约。无前置。
- **C2 后端 · 文件夹范围出题与组卷**：出题支持 `folder_id` 范围（跨资料联合）、`questions` 列表按文件夹过滤、`POST /practices` 支持文件夹范围组卷。验证：`pytest`。**依赖 C1**。
- **C3 前端 · 课程 IA、未分类/归档与控制台改版**：控制台课程列表 + 课程详情（资料 + 上传 + 移动资料）+ 文件夹增删改 + 未分类「移动归位」+ 已归档列表/恢复 + 移除总分卡。验证：`lint`/`type-check`/`test:unit`/`build:mp-weixin`。**依赖 C1**。
- **C4 前端 · 课程内出题→答题闭环**：课程内出题入口、题目列表（文件夹范围）+「开始答题」→ 组卷 → 跳答题页；判题分流展示。验证：`lint`/`type-check`/`test:unit` + 真机手动 E2E。**依赖 C2、C3**。

## Acceptance Criteria（跨子任务，端到端）

- [x] AC1：新建课程 → 校内多次上传多份资料 → 各自解析出知识树，均可见（C1+C3）。*端到端真机项待人工确认（本环境无小程序运行时）。*
- [x] AC2：在课程内对多份资料联合出题，题目覆盖多个来源资料且带溯源（C2+C4）。*真实 LLM/真机项待人工确认。*
- [x] AC3：题目列表（课程范围）可「开始答题」，进入统一答题页完成作答并交卷（C4）。*真机项待人工确认。*
- [x] AC4：交卷后客观题秒判、主观题 LLM 判、降级转自评；结果正确展示（C4，复用既有判题链路）。
- [x] AC5：控制台首屏为课程列表（含未分类），无「总学习分」综合掌握度分卡（C3，单测断言）。
- [x] AC6：不选课程上传 → 落「未分类」；从未分类可移动资料到指定课程（C1+C3）。
- [x] AC7：删除课程 → 进「已归档」可恢复；恢复后资料与知识树完好；7 天后清理（C1+C3）。
- [x] AC8：两端全工具链绿（后端 `ruff`/`format`/`mypy`/`lint-imports`/`pytest` 1313 passed/91.88%；前端 `lint`/`type-check`/`test:unit` 616 passed/`build:mp-weixin`）。

## Completion Record（2026-09-27）

- 子任务全部归档：C1 `09-27-folder-backend-model`、C2 `09-27-folder-scope-generation`、C3 `09-27-course-ia-frontend`、C4 `09-27-question-answer-loop`。
- 迁移：`0005_create_material_folders`、`0006_practice_folder_scope`（均对称可回滚）。
- 规格沉淀：backend《Course Folder Scope Generation & Practice Assembly》+ 归档/惰性清理契约；frontend《Course IA Navigation, Unclassified & Archive Contracts》《Course-Scope Generate -> Question List -> Start Practice Loop Contract》。
- 待人工确认：AC1–AC3 的真机/真实 LLM 端到端（`smoke --image` OCR 子链路仍为 skipped，与本次无关）。
- 非功能性：`src/api/material.ts` 已拆分（>300 行消除）；`materialStore` 之外的 `folderStore` 为新增第 5 个 Store，与 README「4-Store」表述待后续对齐（已在 C3 复核记录）。

## Out of Scope

- 多层嵌套文件夹（`parent_id` 仅预留）。
- 一份资料跨课程多归属。
- 刷题/模考双节奏答题模式（D3）。
- 课程级合并知识树（D2）。
- 与信息架构无关的纯视觉/文案改版。

## Open Questions

（无阻塞项）
