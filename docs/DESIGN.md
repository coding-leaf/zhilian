# ZhiLian Mini-Program Design Specification (DESIGN.md)

本文件是智练微信小程序前端设计的唯一客观参数事实源，基于 **Wot Design Uni** 组件库体系构建，所有数值严禁使用模糊区间，必须采用具体工程参数。

---

## 1. 核心设计原则与量化标准 (Core Standards)

1. **零表情包原则 (Zero-Emoji Policy)**：
   - 全系统（页面、组件、弹窗、Toast、标签）严禁使用 Unicode Emoji 表情符号（如 `U+1F300 ~ U+1FAFF`）；
   - 所有状态与指示一律使用结构化文本、状态徽章（`wd-tag`）或矢量图标展示。
2. **触控与移动端人体工程学参数**：
   - 最小点击热区尺寸：`88rpx × 88rpx`（44px × 44px）；
   - 选项卡片最小高度：`96rpx`（48px）；
   - 底部吸底操作栏安全适配：必须包含 `padding-bottom: env(safe-area-inset-bottom)`。
3. **物理弹性微交互参数**：
   - 按压缩放比例：`transform: scale(0.985)`；
   - 过渡时间与缓动曲线：`transition: transform 0.16s cubic-bezier(0.4, 0, 0.2, 1)`；
   - 页面切入动画：`animation: viewFade 0.24s cubic-bezier(0.16, 1, 0.3, 1)`。

---

## 2. 颜色参数表与 Wot 变量覆盖 (Color Tokens)

禁止在业务组件中使用未经本规范收敛的裸 Hex 色值。

### 2.1 基础色盘与 Wot Design Uni 映射矩阵

| Token 变量名 (SCSS) | 具体 Hex 色值 | RGB 数值 | 对比度 (WCAG) | 语义说明与适用位置 |
| :--- | :--- | :--- | :--- | :--- |
| `$--wot-color-theme` | `#2563EB` | `rgb(37, 99, 235)` | 4.6:1 (AA) | 品牌主交互色、主按钮、高光边框、活动进度 |
| `$--wot-color-theme-hover` | `#1D4ED8` | `rgb(29, 78, 216)` | 6.2:1 (AAA) | 主按钮按压态、激活链接 |
| `$--wot-color-theme-light` | `#EFF6FF` | `rgb(239, 246, 255)` | - | 单选题/多选题选中态底色、胶囊底色 |
| `$--wot-color-theme-border`| `#BFDBFE` | `rgb(191, 219, 254)` | - | 选中项外光晕描边 |
| `$--wot-color-success` | `#10B981` | `rgb(16, 185, 129)` | 4.5:1 (AA) | 判对状态色、良好/精通掌握度 |
| `$--wot-color-success-bg` | `#ECFDF5` | `rgb(236, 253, 245)` | - | 判对反馈横幅底色、掌握度进度底色 |
| `$--wot-color-success-border`| `#A7F3D0` | `rgb(167, 243, 208)`| - | 判对卡片边框 |
| `$--wot-color-success-text` | `#065F46` | `rgb(6, 95, 70)` | 7.1:1 (AAA) | 判对加粗文案 |
| `$--wot-color-warning` | `#F59E0B` | `rgb(245, 158, 11)` | 4.5:1 (AA) | 需巩固状态色、自评待确认警示 |
| `$--wot-color-warning-bg` | `#FFFBEB` | `rgb(255, 251, 235)`| - | 警示卡片底色 |
| `$--wot-color-warning-border`| `#FDE68A` | `rgb(253, 230, 138)`| - | 警示卡片边框 |
| `$--wot-color-warning-text` | `#92400E` | `rgb(146, 64, 14)` | 7.2:1 (AAA) | 警示文字 |
| `$--wot-color-danger` | `#EF4444` | `rgb(239, 68, 68)` | 4.5:1 (AA) | 判错状态色、错题高亮 |
| `$--wot-color-danger-bg` | `#FEF2F2` | `rgb(254, 242, 242)`| - | 判错反馈横幅底色 |
| `$--wot-color-danger-border`| `#FECACA` | `rgb(254, 202, 202)`| - | 判错卡片边框 |
| `$--wot-color-danger-text` | `#991B1B` | `rgb(153, 27, 27)` | 7.4:1 (AAA) | 判错加粗文案 |
| `$--wot-color-gray-1` | `#F8FAFC` | `rgb(248, 250, 252)`| - | 小程序全页面背景色 (冷灰护眼) |
| `$--wot-color-gray-2` | `#F1F5F9` | `rgb(241, 245, 249)`| - | 未选中选项卡底色、搜索框底色 |
| `$--wot-color-gray-4` | `#E2E8F0` | `rgb(226, 232, 240)`| - | 发丝边框色 (1px) |
| `$--wot-color-gray-5` | `#CBD5E1` | `rgb(203, 213, 225)`| - | 次级描边色、单选圆圈未选边框 |
| `$--wot-color-gray-6` | `#94A3B8` | `rgb(148, 163, 184)`| - | 未学状态灰色、失活占位文字 |
| `$--wot-color-gray-7` | `#64748B` | `rgb(100, 116, 139)`| 4.6:1 (AA) | 辅助说明小字、题目出处与用时 |
| `$--wot-color-gray-8` | `#334155` | `rgb(51, 65, 85)` | 7.3:1 (AAA) | 选项文本、常规段落描述 |
| `$--wot-color-gray-9` | `#0F172A` | `rgb(15, 23, 42)` | 13.8:1 (AAA)| 题干标题、页面大标题 |

### 2.2 掌握度四级状态离散参数矩阵

与算法层 `aggregate_mastery_scores` 严格对齐：

| 掌握度等级 (Tier) | 分值判定条件 | 文本色 (Color) | 背景色 (Background) | 进度条填充 (Fill) | 徽章文案 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **精通 (Mastered)** | `score >= 0.70` | `#7C3AED` | `#F5F3FF` | `#8B5CF6` | `精通` |
| **良好 (Proficient)** | `0.40 <= score < 0.70` | `#059669` | `#ECFDF5` | `#10B981` | `良好` |
| **需巩固 (Weak)** | `0.00 < score < 0.40` | `#B45309` | `#FFFBEB` | `#F59E0B` | `需巩固` |
| **未学 (Unlearned)** | `score == 0.00` | `#64748B` | `#F1F5F9` | `#94A3B8` | `未学` |

---

## 3. 尺寸、间距、圆角与阴影具体参数表

### 3.1 间距参数表 (Spacing Tokens)

| Token 变量名 | 参数值 (rpx) | 等效像素 (px) | 适用场景 |
| :--- | :--- | :--- | :--- |
| `--spacing-xs` | `8rpx` | 4px | 标签内边距、图标与文字间距 |
| `--spacing-sm` | `12rpx` | 6px | 选项卡片内图标与文字间距 |
| `--spacing-md` | `16rpx` | 8px | 选项卡片之间的垂直间距、列表项间距 |
| `--spacing-lg` | `24rpx` | 12px | 卡片常规内边距、模块垂直间距 |
| `--spacing-xl` | `32rpx` | 16px | 页面左右水平安全边距、题干卡片内边距 |
| `--spacing-xxl` | `44rpx` | 22px | 大卡片区块垂直间距 |

### 3.2 字体排版参数表 (Typography Tokens)

| 样式层级 | 字号 (rpx) | 字重 (Font Weight) | 行高 (Line Height) | 适用场景 |
| :--- | :--- | :--- | :--- | :--- |
| **Display Title** | `44rpx` (22px) | `800` | `1.15` | 诊断报告总分展示 |
| **Section Title** | `32rpx` (16px) | `700` | `1.35` | 页面顶部大标题、题干大字 |
| **Card Title** | `28rpx` (14px) | `700` | `1.40` | 卡片标题、选项正文 |
| **Body Regular** | `26rpx` (13px) | `500` | `1.55` | 题目解析正文、资料大纲节点 |
| **Caption Meta** | `22rpx` (11px) | `500` | `1.30` | 状态标签、倒计时、题目计数出处 |

### 3.3 圆角固定参数表 (Squircle Radii)

| Token 变量名 | 参数值 (rpx) | 等效像素 (px) | 适用组件 |
| :--- | :--- | :--- | :--- |
| `--radius-sm` | `8rpx` | 4px | 选项字母标识方块、微型标签 |
| `--radius-md` | `16rpx` | 8px | 单选题/多选题选项盒子卡片、次级卡片 |
| `--radius-lg` | `24rpx` | 12px | 题干大卡片、报告卡片、弹出抽屉头部 |
| `--radius-pill` | `9999rpx` | - | 按钮、胶囊徽章、倒计时徽章 |

### 3.4 光影弥散参数表 (Elevation & Shadows)

| Token 变量名 | 参数定义 (CSS box-shadow) | 适用场景 |
| :--- | :--- | :--- |
| `--shadow-card` | `0 8rpx 24rpx -4rpx rgba(15, 23, 42, 0.05), 0 2rpx 6rpx -1rpx rgba(15, 23, 42, 0.02)` | 常规卡片容器、选项卡片 |
| `--shadow-btn-primary`| `0 8rpx 20rpx -2rpx rgba(37, 99, 235, 0.32)` | 页面主操作按钮（强化按压高光） |
| `--shadow-sheet` | `0 -12rpx 32rpx rgba(15, 23, 42, 0.08)` | 底部滑出抽屉、答题卡浮层 |

---

## 4. Wot Design Uni 核心组件装配规则表

| 业务场景 | 目标组件 | 明确样式参数约束 | 交互状态与状态机定义 |
| :--- | :--- | :--- | :--- |
| **题干展示** | `wd-card` | `background: #FFFFFF; border-radius: 24rpx; padding: 32rpx; border: 1px solid #E2E8F0;` | 纯白微浮，无状态变化 |
| **单选选项卡片** | 自定义 `OptionCard.vue` (集成 `wd-radio`) | `min-height: 96rpx; border-radius: 16rpx; padding: 24rpx 28rpx; border: 1.5px solid #E2E8F0;` | **默认**：纯白底灰框<br>**选中**：`border-color: #2563EB; background: #EFF6FF;`<br>**判对**：`border-color: #10B981; background: #ECFDF5;`<br>**判错**：`border-color: #EF4444; background: #FEF2F2;` |
| **多选选项卡片** | 自定义 `OptionCard.vue` (集成 `wd-checkbox`) | 同单选卡片尺寸，左侧采用带微圆角方框勾选指示器 (`border-radius: 6rpx`) | 独立勾选切换，支持多项高亮并存，支持整卡点击触控触发 |
| **主观简答题输入** | `wd-textarea` / `wd-card` | `min-height: 240rpx; border-radius: 16rpx; padding: 24rpx; border: 1.5px solid #E2E8F0; font-size: 28rpx;` | **聚焦**：`border-color: #2563EB; box-shadow: 0 0 0 1px #2563EB;`<br>右下角浮动实时字数统计（如 `128/500`） |
| **主操作按钮** | `wd-button` | `height: 88rpx; border-radius: 9999rpx; font-size: 28rpx; font-weight: 700;` | **Normal**：`#2563EB`<br>**Active**：`#1D4ED8; transform: scale(0.975);` |
| **掌握度条** | `wd-progress` | `height: 8rpx; border-radius: 4rpx; background: #F1F5F9;` | 颜色按四级掌握度表格设置对应的 Fill 色 |
| **状态胶囊** | `wd-tag` | `padding: 4rpx 16rpx; border-radius: 9999rpx; font-size: 22rpx; font-weight: 600;` | 背景与边框见 2.1 节语义色定义 |
| **答题卡抽屉** | `wd-popup` + `wd-grid` | 抽屉圆角 `border-top-left-radius: 24rpx; border-top-right-radius: 24rpx; padding-bottom: env(safe-area-inset-bottom);`<br>题号单元格：`72rpx × 72rpx`，圆角 `12rpx` | **已答**：底色 `#EFF6FF` 描边 `#BFDBFE` 字色 `#2563EB`<br>**当前**：纯色底 `#2563EB` 字色 `#FFFFFF`<br>**未答**：底色 `#F1F5F9` 字色 `#64748B`<br>点击即刻无缝跳题并自动收拢抽屉 |
| **吸底常驻操作栏** | 统一封装 `BottomActionBar.vue` | `height: 112rpx; background: rgba(255, 255, 255, 0.92); backdrop-filter: blur(20px); border-top: 1px solid #E2E8F0; padding-bottom: env(safe-area-inset-bottom);` | 吸附屏幕底部 (`fixed bottom: 0`)，父级列表预留等高占位 (`height: calc(112rpx + env(safe-area-inset-bottom))`) 防遮挡 |
| **出题配置组合面板** | `wd-form` / 模块化卡片集合 | 考点多选 (`wd-checkbox`)、题型胶囊 (`wd-tag` 切换态)、难度与题量步进器 (`1~50题`，符合 FR-27)、出题策略 (`wd-radio`)、乱序抽题开关 (`wd-switch`) | 状态双向绑定，提供“刷题模式 (逐题即判)”与“模考模式 (集中交卷)”两种节奏选择 |
| **连续作答流转状态机** | 统一由 `practiceStore` 调度 | 单一线性题目队列（顺序/乱序抽题，同知识点题目不相邻符合 FR-31），作答区由 `current_question.type` 动态渲染组件，**严禁用户在题内手动切题型** | 切题（上一题/下一题/答题卡跳转）自动触发草稿本地落盘；全答完或提前交卷后统一进入判题与溯源流转 |

---

## 5. 面向用户的自然文案对照字典 (Copywriting Dictionary)

严格禁止在 UI 呈现底层开发与算法术语：

| 业务场景 | 严禁出现的开发术语 (Forbidden) | 强制使用的用户界面文案 (Required) |
| :--- | :--- | :--- |
| **出题配置** | `基于本地向量检索(Top20粗排+BM25精排)及LLM调度` | `定制练习题` / `智能组卷` |
| **出题策略** | `优先抽取低于0.40知识点` | `优先强化薄弱点` |
| **出题策略** | `全局知识点均匀覆盖测试` | `全范围均衡练习` |
| **资料门禁** | `门禁状态: 乱码率 21%` | `第 4 页文字模糊，需重新拍摄` |
| **资料切片** | `切片: 78, 深度: 3` | `12 个核心考点` |
| **即时判题** | `客观题秒判规则核 match_and_grade_answer 判定` | `回答正确` / `回答错误` |
| **判题反馈** | `申请自评修正或重判 (4000x)` | `如对判题有疑问，可申请人工复核` |
| **掌握度** | `艾宾浩斯30天半衰期模型衰减 score=0.91` | `知识掌握度看板` / `精通`（不显示浮点数） |
| **错题本** | `WrongRecord 标记为已消灭` | `消灭错题` |

---

## 6. 前端代码实现硬性阈值 (Engineering Hard Limits)

1. **单文件代码行数门限**：
   - 任何单 `.vue` 文件不得超过 **300 行**。超过必须拆分（如 `PracticeSession.vue` 必须拆分为 `QuizHeader.vue`、`OptionCard.vue`、`BottomActionBar.vue`）。
2. **包体积限制**：
   - 主包体积严格限制在 **2.0 MB** 以内；
   - 资料管理页面置于 `subpackages/material/`；
   - 诊断报告与错题本页面置于 `subpackages/report/`。
3. **Storage 持久化白名单（仅 3 项）**：
   - `auth_tokens`：用户 Access/Refresh Token 及版本；
   - `practice_drafts`：未交卷时的本地作答草稿队列；
   - `user_settings`：音效、主题与字号偏好。
   - **题目全文与资料内容绝对严禁存入本地 Storage**。
