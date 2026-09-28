# 前端UI全面重构与学习闭环技术方案设计 (Design)

## 1. 架构与设计原则

基于 UniApp (Vue 3 + TypeScript + Pinia + Wot Design Uni)，遵循组件化、单向数据流与清晰的领域分层：
- **API 接入层 (`src/api/`)**：统一封装后端 `/api/v1` 的 RESTful 端点（补充 folders, users, grading, coach, knowledge 相关接口）。
- **状态管理层 (`src/stores/`)**：
  - `userStore`：用户画像与个人信息修改。
  - `folderStore`：课程文件夹列表、当前选中课程、课程下资料与知识点分组。
  - `materialStore`：资料列表、上传、解析流水线轮询、知识树与切片。
  - `practiceStore`：多题型组卷参数构建、答题草稿、判题与重判申请、错题收集与再生题。
- **UI 页面与分包路由设计 (`src/pages.json`)**：
  - 主包页面：
    - `pages/index/index`：课程文件夹与资料工作台（支持切课程、看资料、快捷刷题）。
    - `pages/review/index`：学情与错题本（支持按错题知识点快速组卷）。
    - `pages/profile/index`：个人中心（昵称/头像修改）。
  - 分包 `subpackages/material`：
    - `pages/course/index`：课程详情与资料管理。
    - `pages/knowledge/index`：知识点树与切片扩展学习卡片。
    - `pages/generate/index`：勾选知识点与题型的组卷出题配置页。
  - 分包 `subpackages/practice`：
    - `pages/session/index`：多题型答题会话（单选、多选、判断、填空、主观简答）。
    - `pages/result/index`：答题结果页（客观题得分、主观题自评/申请复查、错题再生题）。
  - 分包 `subpackages/ai`：
    - `components/CourseCoachDrawer.vue` 或独立悬浮助教组件：读取课程切片与知识树答疑。

---

## 2. 核心模块契约与数据流

### 2.1 课程与资料管理流
1. 用户进入主页，拉取 `GET /folders` 列表。
2. 支持点击「+ 新建课程」，弹窗输入课程名并调用 `POST /folders`。
3. 进入课程后，点击上传文件（`POST /materials/upload?folder_id=...`），前端展示资料卡片（初始状态为 WAITING）。
4. 用户点击资料卡片的「解析资料」按钮，发送 `POST /materials/{id}/parse`；随后启动定时轮询 `GET /materials/{id}`，直到 `status === 'PARSED'`。

### 2.2 知识点树与切片扩展学习
1. 资料解析完成后，调用 `GET /materials/{id}/knowledge-tree` 获取多级树形结构。
2. 树形组件渲染知识点节点；点击节点调用 `GET /knowledge/{id}` 获取摘要及扩展定义，调用 `GET /knowledge/{id}/snippets` 展示教材原文证据切片。

### 2.3 知识点勾选与多题型出题组卷
1. 在课程或资料页点击「生成复习题」，跳转至组卷配置页。
2. 拉取当前课程的考点列表（`GET /folders/{folder_id}/knowledge-points`）供用户树形复选。
3. 用户选择题型（单选、多选、判断、填空、简答等）、题量及难度。
4. 点击「生成批次」，调用 `POST /questions/generate`，生成成功后调用 `POST /practices` 创建练习批次并返回 `practice_id`，立即跳入答题页。

### 2.4 多题型答题与结果判题闭环
1. 答题组件根据 `question.type`（或后端字段）动态渲染输入控件：
   - `single_choice`：单选 radio。
   - `multiple_choice`：多选 checkbox。
   - `true_false`：是非判断 toggle。
   - `fill_in_blank`：单行文本输入框。
   - `short_answer` / `case_analysis`：多行 textarea。
2. 交卷：调用 `POST /practices/{id}/submit`，紧接着调用 `POST /practices/{id}/diagnosis` 获取详细判题报告。
3. 诊断报告展示：
   - 客观题立即展示正确与否、标准答案、解析与采分点。
   - 主观题展示系统评分与采分点评语，并提供「申请复查」按钮。点击后输入理由调用 `POST /grading/regrade`。
4. 错题再生题：报告页底部统计错题，提取对应知识点 IDs，提供「AI 错题强化出题」按钮。点击后自动带入这些知识点调用出题流程，进入新批次。

### 2.5 课程/题目级 AI 助教
- 题目助教：在答题解析或报告卡片中，点击「问 AI 助教」，调用 `POST /questions/{id}/ask-coach`，弹窗展示 AI 老师的引导思路与思考提示。
- 课程助教：悬浮挂件，调起当前课程的智能问答抽屉，提供课程范围内的原件检索与考点答疑。
