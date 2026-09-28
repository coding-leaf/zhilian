# 全新前端架构与用户体验重构 Technical Design

## 1. 整体架构与设计原则

彻底废弃旧版多层分散嵌套、状态凌乱的页面模式，采用三层分层设计：
1. **基础展示层与原子设计系统 (UI & Components)**：统一的主流学术科技风格主题变量（颜色、圆角、阴影、Typography），基于 `wot-design-uni` 做二次轻量主题适配。
2. **状态与离线数据层 (Stores & Sync Engine)**：Pinia 驱动，构建本地缓存（Storage）与后端 API 双轨同步引擎，解耦页面与底层网络抖动。
3. **业务流编排层 (Composables & Services)**：将出题状态轮询、拍照质检替换、作答离线断点暂存、判题状态机等抽离为高内聚的 Composables。

---

## 2. 路由与包结构规划 (`pages.json`)

### 2.1 主包核心 Tab（三 Tab 架构）
- `pages/index/index`：【学习工作台】（课程文件夹列表、最近未完成练习恢复、快速多格式导入）。
- `pages/review/index`：【学情与错题】（知识点掌握度雷达概览、错题攻克看板、时间/课程筛选、多选组卷购物车）。
- `pages/profile/index`：【我的】（个人信息、学习资产概览、归档课程箱、数据安全与隐私、账号物理注销）。
- `pages/auth/login`：【用户授权登录】（极简微信一键授权与状态回跳）。

### 2.2 独立子包划分
- **`subpackages/material/`（资料与出题）**：
  - `pages/upload/index`：多图拍照画廊质检（J2 单页重拍替换）与文件导入。
  - `pages/course/index`：课程详情与资料管理。
  - `pages/verify/index`：出题配置与题目质检核对清单（J3 增删改、来源查看与开练）。
- **`subpackages/practice/`（作答引擎）**：
  - `pages/session/index`：沉浸式卡片作答（左右滑屏、悬浮答题卡、离线暂存）。
  - `pages/transition/index`：交卷后 AI 诊断中过渡动效态（分步亮起、后台转跳）。
- **`subpackages/report/`（诊断报告与追问）**：
  - `pages/detail/index`：学情诊断报告（掌握度画像、薄弱点提炼、一键强化练）。
  - `pages/explanation/index`：题目深度解析详情（J5 采分点对齐、AI 复核/自评打分、AI 助教深度追问）。

---

## 3. 核心领域设计与状态契约

### 3.1 离线断点防丢引擎 (`usePracticeSync`)
- **本地持久化 Key**：`practice_draft_${practice_id}`。
- **存储结构**：
  ```ts
  interface PracticeLocalDraft {
    practiceId: string;
    currentIndex: number;
    answers: Record<string, {
      questionId: string;
      answer: string | string[];
      flagged: boolean;
      updatedAt: number;
    }>;
    lastSyncedAt: number;
  }
  ```
- **同步策略**：
  - 答题触发立即写入本地 Storage（毫秒级无延迟）。
  - 防抖（800ms）或切题、切后台时调用 `PUT /api/v1/practices/{id}/answers` 同步至后端。
  - 恢复场景：小程序冷启动、热启动或断网重连进入 `practice/pages/session/index` 时，比对本地草稿与服务端数据，取时间戳最新版本无缝恢复。

### 3.2 多页拍照质检与替换机制 (`useMaterialOCR`)
- 一次性选择最多 9 张图片，生成本地预检队列：
  ```ts
  interface OCRPageItem {
    pageNumber: number;
    localPath: string;
    remoteUrl?: string;
    isQualified: boolean;
    unqualifiedReason?: string;
    isReshooting: boolean;
  }
  ```
- 支持针对单个 `pageNumber` 调用相机重拍，仅重传并替换该页数据，无须整套重新上传。

### 3.3 主观题采分对齐与双通道纠偏
- 数据协议统一适配：
  - 命中采分点（Hit Points）、遗漏采分点（Missed Points）、讲义引文原文（Source Reference）。
  - 纠偏状态机：`AI_GRADED` -> `REGRADE_REQUESTED` (AI 复核中) 或 `USER_SELF_EVALUATED` (用户自评覆盖)。

### 3.4 追问 AI 助教交互设计 (`useAICoach`)
- 抽屉式对话交互，上下文自动绑定当前题目、题干、学生答案、采分点与讲义原文。
- 允许学生输入追问（如：“为什么这里要用递归而不是迭代？”），调用后端专用答疑接口返回深入通俗讲解。

---

## 4. 后端轻量接口补齐设计 (Backend Micro-Extensions)

### 4.1 组卷接口扩展支持指定题目列表 (`POST /api/v1/practices`)
- **请求体入参模型 `PracticeCreateRequest` 扩展**：
  ```python
  question_ids: list[uuid.UUID] | None = Field(
      default=None,
      description="指定题目主键列表（用于错题本勾选题精确组卷；提供时优先直接以此题目列表生成练习试卷）",
  )
  ```
- **服务端逻辑**：在 `PracticeService.create_practice` 中，若 `options.question_ids` 非空，直接检索并校验这批题目的有效性与租户归属，组装成练习快照返回，完美支持 J7。

### 4.2 AI 助教深度答疑接口 (`POST /api/v1/questions/{id}/ask-coach`)
- **请求体模型 `AskCoachRequest`**：
  ```python
  class AskCoachRequest(BaseModel):
      user_prompt: str = Field(..., min_length=1, max_length=1000, description="学生追问内容")
      user_answer: str | None = Field(default=None, description="学生的原始作答")
      grading_points: list[str] | None = Field(default=None, description="相关采分点")
  ```
- **响应体模型 `AskCoachResponse`**：
  ```python
  class AskCoachResponse(BaseModel):
      reply: str = Field(..., description="AI 助教通俗生动的深度解析内容")
      suggestions: list[str] = Field(default_factory=list, description="推荐延伸思考提示")
  ```

---

## 5. 主流视觉设计系统 (`styles/theme.scss`)
- **Primary Color**：`#1E40AF` / `#2563EB`（科技蓝/知性靛蓝）。
- **Neutral Backgrounds**：
  - 背景底色：`#F8FAFC`（Slate-50）。
  - 卡片底色：`#FFFFFF`（带 0.5px `#E2E8F0` 边框与柔和阴影 `0 2px 8px rgba(0,0,0,0.04)`）。
- **Feedback & Accent**：
  - Success / Correct：`#10B981`（翠绿，采分命中）。
  - Warning / Weakness：`#F59E0B`（琥珀橙，遗漏采分点与薄弱知识点）。
  - Danger / Wrong：`#EF4444`（朱红，错误标记）。
- **Typography**：
  - 题干大字号清晰护眼，行高 1.6，代码与公式专用等宽字族。
