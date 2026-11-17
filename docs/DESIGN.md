# ZhiLian Mini-Program Design Specification (DESIGN.md)

本文件是智练微信小程序前端设计的唯一客观事实源，基于 **温润学术纸质阅读风（Warm Academic Paper）** 与原生小程序组件 + 自定义 `.vue` 组件体系构建，所有色值、样式令牌、组件边界、工程阈值与持久化契约均与 `miniprogram/src/` 真实实现保持 100% 一致。

---

## 1. 核心设计原则与量化标准 (Core Standards)

1. **零表情包原则 (Zero-Emoji Policy)**：
   - 全系统（页面、组件、弹窗、Toast、标签）严禁使用 Unicode Emoji 表情符号（如 `U+1F300 ~ U+1FAFF` 及杂项符号）；
   - 所有状态与指示一律使用结构化文本、状态徽章（`.status-badge` / `.badge` / `.q-type-badge`）或纯 CSS 矢量对勾（`src/styles/tokens.scss` 中的 `@mixin css-checkmark`）。
2. **安全区与触控人体工程学参数**：
   - 底部吸底操作栏与底部弹出抽屉安全区适配：统一采用 `calc(<base> + env(safe-area-inset-bottom))`（共享基元 `.bottom-fixed-bar` 或 `@include safe-bottom-padding($base)`）；
   - 底部固定栏所在页面容器需预留底部安全留白（如 `padding-bottom: calc(180rpx + env(safe-area-inset-bottom))`），防止遮挡列表末项；
   - 主操作按钮（`.paper-btn-primary` / `.action-btn` / `.full-btn`）高度为 `80rpx ~ 88rpx`，答题卡题号网格单元为 `80rpx × 80rpx`，弹窗确认/取消按钮为 `76rpx`。
3. **微信小程序事件防穿透规范**：
   - `@dcloudio/uni-mp-compiler` 会静默丢弃 `@tap.self`，严禁在遮罩容器上使用 `@tap.self`；
   - 所有弹窗与抽屉（`src/styles/modal.scss`）必须拆分为独立热区：`.modal-overlay` / `.sheet-overlay` 内放置全覆盖 `.modal-backdrop`（`position: absolute; top/bottom/left/right: 0; z-index: 0;`）绑定 `@tap="close"`，内容面板 `.modal-content` / `.sheet-panel` 设置 `position: relative; z-index: 1;`。
4. **深层知识树渲染规范**：
   - `mp-weixin` 禁止组件模板递归自渲染；所有知识树须先经 `miniprogram/src/utils/knowledgeTree.ts::flattenKnowledgeTree` 前序展开后，再通过单层 `v-for` 与缩进层级渲染。

---

## 2. 颜色与样式令牌体系 (Design Tokens)

所有 CSS 自定义属性统一定义在 `miniprogram/src/App.vue` 的 `page { ... }` 选择器中；SCSS 别名与共享 Mixin 定义在 `miniprogram/src/styles/tokens.scss`。全局导航栏与 TabBar 配置位于 `miniprogram/src/pages.json`（页面/导航底色 `#F7F5F0`，Tab 未选中 `#78716C`，Tab 选中 `#1E3A8A`）。

### 2.1 纸张底色与中性墨色 (`App.vue` `--color-*`)

| CSS 变量 | SCSS 变量 (`tokens.scss`) | 色值 | 语义说明与适用位置 |
| :--- | :--- | :--- | :--- |
| `--color-paper-bg` | `$color-paper-bg` | `#F7F5F0` | 全局温润纸张页面背景色（同步 `pages.json` `backgroundColor` / `navigationBarBackgroundColor`） |
| `--color-paper-card` | `$color-paper-card` | `#FFFFFF` | 卡片容器背景（`.paper-card`、`.sheet-panel`） |
| `--color-surface-subtle` | `$color-surface-subtle` | `#FAFAF9` | 输入框底色、题干依据/解析浅底块 |
| `--color-surface-muted` | `$color-surface-muted` | `#F5F5F4` | 次级按钮、未选中标签、待解析徽章底色 |
| `--color-surface-slate` | — | `#F8FAFC` | 教材溯源切片卡片底色 |
| `--color-surface-warm` | — | `#FBFBF9` | 轻量卡片次级暖白底色 |
| `--color-paper-border` | `$color-paper-border` | `#E7E5E4` | 发丝边框色（`1px` 卡片与分隔线 `.stat-divider`） |
| `--color-border-strong` | `$color-border-strong` | `#D6D3D1` | 次级强描边 |
| `--color-border-slate` | — | `#CBD5E1` | 冷灰描边 |
| `--color-ink-primary` | `$color-ink-primary` | `#1C1917` | 主标题、题干正文、核心数值 |
| `--color-ink-body` | `$color-ink-body` | `#44403C` | 常规正文、选项文本、解析内容 |
| `--color-ink-secondary` | `$color-ink-secondary` | `#57534E` | 次级说明文字、按钮次要文字 |
| `--color-ink-subtle` | `$color-ink-subtle` | `#78716C` | 辅助元信息、刷新按钮、未选中 Tab |
| `--color-ink-muted` | `$color-ink-muted` | `#A8A29E` | 空态提示、占位提示、ID 辅助文字 |
| `--color-ink-slate` | — | `#334155` | 切片正文文本 |
| `--color-ink-slate-muted` | — | `#475569` | 次级冷灰文本 |
| `--color-ink-slate-subtle` | — | `#64748B` | 章节标注、次要元信息 |
| `--color-ink-on-primary` | `$color-ink-on-primary` | `#FFFFFF` | 主色按钮反白文字、勾选对勾颜色 |

### 2.2 品牌与语义色 (`App.vue` `--color-*`)

| CSS 变量 | SCSS 变量 (`tokens.scss`) | 色值 | 语义说明与适用位置 |
| :--- | :--- | :--- | :--- |
| `--color-academic-blue` | `$color-academic-blue` | `#1E3A8A` | 品牌主交互色、主按钮（`.paper-btn-primary`）、选中 Tab、题号强调 |
| `--color-blue-accent` | — | `#3B82F6` | 行动卡片描述文字、次级蓝色强调 |
| `--color-blue-bg` | `$color-blue-bg` | `#EFF6FF` | 浅蓝底色（选中胶囊、讲义助教按钮、行动卡片渐变起点） |
| `--color-blue-border` | `$color-blue-border` | `#BFDBFE` | 浅蓝描边（`.action-card`、头像徽章） |
| `--color-blue-border-strong` | — | `#93C5FD` | 已作答答题卡高亮描边 |
| `--color-blue-tint` | — | `rgba(30, 58, 138, 0.08)` | 首页 Hero 标签半透底色 |
| `--color-blue-shadow` | — | `rgba(30, 58, 138, 0.35)` | 悬浮助教按钮阴影 |
| `--color-blue-badge` | — | `rgba(30, 58, 138, 0.8)` | 头像右下角编辑角标底色 |
| `--color-academic-teal` | `$color-academic-teal` | `#0D9488` | 学术青辅色、登录态胶囊文字 |
| `--color-teal-dark` | — | `#245C51` | 深青色强调 |
| `--color-teal-accent` | — | `#176B62` | 青色次级强调 |
| `--color-teal-bg` | — | `#EEF7F4` | 青色浅底 |
| `--color-teal-tint` | — | `rgba(13, 148, 136, 0.1)` | 登录态胶囊半透底色 |
| `--color-correct` | `$color-correct` | `#15803D` | 命中采分点标题色 |
| `--color-success` | `$color-success` | `#059669` | 已解析徽章（`.status-ready`）、判对标签（`.tag-correct`） |
| `--color-success-strong` | — | `#166534` | 命中采分点列表文案 |
| `--color-success-bg` | `$color-success-bg` | `#ECFDF5` | 已解析/判对浅绿底色 |
| `--color-success-bg-soft` | — | `#F0FDF4` | 柔绿底色 |
| `--color-success-border` | — | `#86EFAC` | 成功边框 |
| `--color-success-border-soft` | — | `#BBF7D0` | 柔和成功边框 |
| `--color-warm-amber` | `$color-warm-amber` | `#D97706` | 解析中徽章（`.status-parsing`）、待判标签（`.tag-pending`） |
| `--color-warning-strong` | — | `#B45309` | 需巩固警告文字 |
| `--color-warning-deep` | — | `#92400E` | 复查/自评按钮深琥珀文字 |
| `--color-warning-dark` | — | `#78350F` | 警告深棕文字 |
| `--color-warning-bg` | `$color-warning-bg` | `#FFFBEB` | 解析中/待判浅琥珀底色 |
| `--color-warning-bg-strong` | — | `#FEF3C7` | 复查/自评按钮底色 |
| `--color-warning-border` | — | `#FDE68A` | 警告边框 |
| `--color-orange` | — | `#EA580C` | 橙色警告强调 |
| `--color-orange-strong` | — | `#C2410C` | 需重拍徽章文字（`.status-retake_required`） |
| `--color-orange-deep` | — | `#9A3412` | 深橙提示文案 |
| `--color-orange-bg` | — | `#FFF7ED` | 需重拍徽章底色（`.status-retake_required`） |
| `--color-orange-border` | — | `#FED7AA` | 橙色描边 |
| `--color-wrong` | `$color-wrong` | `#B91C1C` | 遗漏要点、错误提示、退出登录按钮文字 |
| `--color-danger` | `$color-danger` | `#DC2626` | 解析失败徽章（`.status-failed`）、判错标签（`.tag-wrong`） |
| `--color-danger-strong` | — | `#991B1B` | 遗漏要点列表文案 |
| `--color-danger-bg` | `$color-danger-bg` | `#FEF2F2` | 失败/判错浅红底色 |
| `--color-danger-bg-soft` | — | `#FEE2E2` | 退出登录按钮底色 |
| `--color-danger-border` | — | `#FECACA` | 错误边框 |
| `--color-danger-border-strong` | — | `#FCA5A5` | 强错误边框 |
| `--color-sky` / `--color-sky-bg` | — | `#0284C7` / `#E0F2FE` | 辅助信息标签色 |
| `--color-purple` / `--color-purple-bg` | — | `#7E22CE` / `#F3E8FF` | 进阶状态标签色 |
| `--color-overlay` / `--color-overlay-strong` | — | `rgba(0, 0, 0, 0.4)` / `rgba(0, 0, 0, 0.45)` | 居中弹窗与底部抽屉半透遮罩 |
| `--color-bar-bg` | — | `rgba(255, 255, 255, 0.95)` | 吸底操作栏半透磨砂底色 |
| `--color-scrim-light` / `--color-white-translucent` | — | `rgba(0, 0, 0, 0.08)` / `rgba(255, 255, 255, 0.2)` | 轻度遮罩与反白半透底 |

### 2.3 共享样式层 (`src/styles/`)

| 文件 | 职责与核心类 / Mixin |
| :--- | :--- |
| `App.vue` | 全局 CSS 变量、盒模型规范、`paper-card`（白底、`1px solid --color-paper-border`、圆角 `16rpx`）、`paper-btn-primary`（`--color-academic-blue`、圆角 `12rpx`、按压透明度 `0.85`） |
| `src/styles/tokens.scss` | `$color-*` SCSS 变量别名（指向 `--color-*`，零重复规则输出）；`@mixin safe-bottom-padding($base: 24rpx)`；`@mixin css-checkmark(...)` |
| `src/styles/modal.scss` | 居中弹窗与底部抽屉基础样式：`.modal-overlay`、`.sheet-overlay`、`.modal-backdrop`、`.modal-content`、`.sheet-panel`、`.modal-header`、`.modal-title`、`.modal-close`、`.modal-footer`、`.modal-cancel-btn`、`.modal-confirm-btn`、`.form-tips`、`.form-input`、`.form-textarea` |
| `src/styles/common.scss` | 跨页语义基元：`.section-title-row`、`.section-title`、`.section-refresh`、`.stat-divider`、`.empty-state`、`.empty-text`、`.bottom-fixed-bar`（含 `env(safe-area-inset-bottom)`）、`.status-badge`/`.badge` 五态（`ready`/`parsing`/`failed`/`pending`/`retake_required`）、`.action-card` |

---

## 3. 页面路由与自定义组件清单 (Pages & Custom Components)

小程序共包含 **8 个页面**（主包 4 页 + 3 个分包共 4 页，对齐 `miniprogram/src/pages.json`）与 **23 个自定义 `.vue` 组件**（全部不依赖任何第三方 UI 组件库）。

### 3.1 页面路由表 (`miniprogram/src/pages.json`)

| 归属包 | 页面路径 | 导航栏标题 | 职责 |
| :--- | :--- | :--- | :--- |
| 主包 (Tab 1) | `pages/index/index` | 智练 | 工作台：课程文件夹切换、资料上传、讲义列表与手动解析、全局 AI 助教 |
| 主包 (Tab 2) | `pages/review/index` | 学情概览 | 题库批次勾选组卷、我的练习恢复/查看、按课程/资料分组的错题巩固 |
| 主包 (Tab 3) | `pages/profile/index` | 个人中心 | 账号信息、头像与昵称编辑、学习足迹统计看板、登录/退出 |
| 主包 | `pages/auth/login` | 登录智练 | 微信快捷登录与本地开发登录入口 |
| `subpackages/material` | `pages/course/index` | 资料详情 | 资料解析状态与进度、知识树层级展示、知识点详情与教材原文切片溯源 |
| `subpackages/material` | `pages/questions/index` | 核对出题 | 智能组卷配置（考点/题型/题量/难度）与生成题目核对、覆盖缺口补齐 |
| `subpackages/practice` | `pages/session/index` | 练习作答 | 连续作答会话、7 类题型动态渲染、答题卡抽屉、草稿串行落盘与幂等交卷 |
| `subpackages/report` | `pages/detail/index` | 诊断报告 | 作答进度/判题轮询、诊断摘要与薄弱点、逐题核对、AI 复查/自评与错题再生 |

### 3.2 自定义组件清册（23 个 `.vue` 组件）

| 所属目录 | 组件文件 | 职责与核心样式/契约 |
| :--- | :--- | :--- |
| `src/components/` | `AiCoachDrawer.vue` | 底部滑出 AI 智能助教抽屉（复用 `modal.scss` `.sheet-overlay`/`.modal-backdrop`；footer 含 `env(safe-area-inset-bottom)`） |
| `src/components/` | `CoachMessageList.vue` | 助教对话消息流、快捷追问建议胶囊与来源讲义跳转卡片 |
| `src/pages/index/components/` | `FolderFilterBar.vue` | 课程文件夹横向滚动胶囊栏与新建/重命名/归档操作入口 |
| `src/pages/index/components/` | `FolderFormModal.vue` | 课程新建/重命名居中弹窗（复用 `modal.scss`） |
| `src/pages/index/components/` | `MaterialItemCard.vue` | 讲义卡片（支持 `ready`/`parsing`/`failed`/`pending`/`retake_required` 五态徽章、解析/出题/软删除操作） |
| `src/pages/profile/components/` | `LearningStatisticsCard.vue` | 学习足迹三项统计看板（已建课程 / 就绪讲义 / 涵盖考点），支持 `ready`/`error`/`logged-out`/`loading` 四态 |
| `src/pages/profile/components/` | `ProfileEditModal.vue` | 个人昵称与头像编辑弹窗（复用 `modal.scss`） |
| `src/pages/review/components/` | `PracticeEntryCard.vue` | 练习记录条目卡（区分可恢复「继续作答」与终态「查看结果」） |
| `src/pages/review/components/` | `QuestionBankSection.vue` | 「我的题目」题库区块容器（挂载即加载批次、分批加载更多、错误重试、批量开练） |
| `src/pages/review/components/` | `QuestionBatchRow.vue` | 题库批次行（全选/半选/未选三态、展开题目、来源展示） |
| `src/pages/review/components/` | `QuestionBankQuestionRow.vue` | 题库单题行（可用态勾选、待审核不可选提示、记入/取消错题动作分道） |
| `src/pages/review/components/` | `WrongRecordCard.vue` | 错题记录卡片（显示快照题干、待巩固/已攻克徽章与单考点针对出题入口） |
| `src/subpackages/material/components/` | `MaterialCourseHeader.vue` | 资料详情头部卡（状态徽章、解析触发、已生成题目回访入口） |
| `src/subpackages/material/components/` | `KnowledgePointList.vue` | 扁平化知识树列表（按 `level` 缩进展示，点击打开溯源抽屉） |
| `src/subpackages/material/components/` | `KnowledgeSnippetModal.vue` | 知识点详情与教材原文切片抽屉（显示 `page_index` 页码与可选 `chapter_title`；footer 含 `env(safe-area-inset-bottom)`） |
| `src/subpackages/material/components/` | `QuestionConfigPanel.vue` | 组卷配置面板（考点全选/多选、7 大题型多选、题量 1–15 滑块与覆盖调整提示、难度 1–5 滑块） |
| `src/subpackages/material/components/` | `QuestionPreviewPanel.vue` | 核对生成题目容器（批次来源提示、覆盖缺口补齐引导、底部固定开练栏） |
| `src/subpackages/material/components/` | `QuestionPreviewCard.vue` | 单题预览卡片（题号、题型、难度、选项、讲义依据切片、剔除与单题重生成） |
| `src/subpackages/practice/components/` | `AnswerCardDrawer.vue` | 答题卡底部抽屉（`80rpx` 题号圆钮区分当前/已答/未答；含 `env(safe-area-inset-bottom)`） |
| `src/subpackages/report/components/` | `ReportSummaryCard.vue` | 得分总览、未判完提示横幅、学习建议与薄弱点列表 |
| `src/subpackages/report/components/` | `AdaptivePracticeCard.vue` | 判题进度引导、`partially_graded` 重试判题入口与错题针对性再生题卡片 |
| `src/subpackages/report/components/` | `AttemptResultCard.vue` | 逐题核对卡（区分 `unanswered`/`grading`/`pending_regrade`/`graded`，命中/遗漏采分点、AI 复查/自评与问助教） |
| `src/subpackages/report/components/` | `GradingActionModal.vue` | 主观题申请 AI 复查与自行评分弹窗（复用 `modal.scss`） |

---

## 4. 题型、状态机与交互规则 (Domain UI Contracts)

1. **支持题型（7 类，对齐 `src/types/question.ts::QuestionType`）**：
   - 客观题：`single_choice`（单选题）、`multiple_choice`（多选题）、`true_false`（判断题）、`fill_in_blank`（填空题）；
   - 主观题：`term_explanation`（名词解释）、`short_answer`（简答题）、`case_analysis`（案例分析）。
2. **资料状态机（5 态，对齐 `src/types/material.ts::MaterialStatus`）**：
   - `pending`（待解析）、`parsing`（排队中 / 解析中）、`ready`（已解析）、`failed`（解析失败）、`retake_required`（需要重拍）。
3. **判题与诊断展示红线**：
   - `grading` / `pending_regrade` / `unanswered` 题目不得显示为 `0` 分或答错（由 `reportView.ts::resolveResultBadge` 统一映射为「判题中」「待重判」「未作答」）；
   - 仅当整卷 `fullyGraded` 为真时才展示正式诊断得分率与完整诊断结论，否则保留「全卷仍在判题中」提示；
   - 判题重试按钮仅在 `session.status === 'partially_graded'` 且未全判时出现。

---

## 5. 面向用户的自然文案对照字典 (Copywriting Dictionary)

严格禁止在 UI 呈现底层开发、数据库与算法术语：

| 业务场景 | 严禁出现的开发术语 (Forbidden) | 强制使用的用户界面文案 (Required) |
| :--- | :--- | :--- |
| **出题配置** | `基于本地向量检索及 LLM 调度` | `智能组卷与出题配置` |
| **资料门禁** | `门禁状态: 乱码率 21%` / `retake_required` | `需要重拍` / `文字模糊需重拍` |
| **资料删除** | `已移至回收站`（系统无回收站恢复入口） | `资料已删除`（确认框明确提示历史作答记录保留且无法在应用内恢复） |
| **即时判题** | `match_and_grade_answer` / `score=0` | `正确 x/y` / `错误 x/y` / `判题中` / `待重判` / `未作答` |
| **判题复核** | `regrade_attempt` / `self_evaluate_attempt` | `申请 AI 复查` / `自行评分` |
| **掌握度** | `半衰期衰减 score=0.72` | `掌握度 72%` / `需重点巩固的薄弱点` |
| **错题本** | `WrongRecord` / `is_mastered=true` | `已消灭错题` / `已攻克` / `待巩固` / `已掌握` |

---

## 6. 前端代码实现硬性阈值与持久化契约 (Engineering Hard Limits)

1. **单文件 `.vue` 行数上限**：
   - 任何单 `.vue` 文件（SFC）不得超过 **300 行**。复杂页面必须拆分为 `components/` 子组件与 `composables/` 编排模块，共享样式沉淀至 `src/styles/` 或同域 `.scss`。
2. **包体积与分包布局**：
   - 主包体积严格限制在 **2.0 MB** 以内；
   - 资料与出题页置于 `subpackages/material/`；
   - 练习作答页置于 `subpackages/practice/`；
   - 诊断报告页置于 `subpackages/report/`。
3. **Storage 持久化白名单（事实源：`miniprogram/src/utils/storageKeys.ts`）**：
   - `STORAGE_KEYS.ACCESS_TOKEN`（键名 `'access_token'`）：用户登录 JWT Access Token；
   - `practiceDraftStorageKey(userId, practiceId)`（键名 `` `practice_draft_${userId || 'anonymous'}_${practiceId}` ``）：按「用户 + 练习」隔离的未交卷作答草稿（交卷成功后调用 `clearPracticeStorage` 清除）；
   - `practiceSubmitStorageKey(practiceId)`（键名 `` `practice_submit_key_${practiceId}` ``）：练习交卷幂等键 `Idempotency-Key`（交卷成功后清除）。
   - **禁止散落裸字符串 key**，统一经 `storageKeys.ts` 读取；**资料全文与题库全集严禁长期持久化到本地 Storage**。
