# 前端UI全面重构与学习闭环业务流实现 PRD

## 1. Goal & Value (目标与价值)

全面重构智练小程序的前端 UI 与交互架构，贯通从「用户个人中心」->「课程文件夹与资料管理」->「手动触发解析与知识树扩展学习」->「知识点勾选多题型组卷刷题」->「客观题秒判、主观题自评/复查」->「错题自适应再生题」->「课程/题目级 AI 助教答疑」的全链路学习闭环。

---

## 2. Confirmed Facts (基于代码库已核实的事实)

### 后端 API 现状与能力支撑：
1. **用户与个人信息**：
   - `GET /api/v1/users/me`：获取当前登录用户画像（昵称、头像等）。
   - `PUT /api/v1/users/me`：更新当前用户昵称 `nickname` 与头像 `avatar_url`。
2. **课程文件夹管理**：
   - `GET /api/v1/folders`、`POST /api/v1/folders`、`PATCH /api/v1/folders/{id}`、`DELETE /api/v1/folders/{id}`：完整支持课程文件夹的增删改查。
   - `GET /api/v1/folders/{folder_id}/knowledge-points`：直接支持按课程获取所有资料聚合的考点列表，且按资料分组。
3. **资料管理与解析**：
   - `POST /api/v1/materials/upload`（支持 `folder_id`）：上传资料至指定课程。
   - `POST /api/v1/materials/{id}/parse`：手动触发资料解析流水线。
   - `GET /api/v1/materials/{id}/knowledge-tree`：获取指定资料的 2~5 级知识点树形拓扑。
   - `GET /api/v1/knowledge/{id}` & `GET /api/v1/knowledge/{id}/snippets`：获取知识点详情及其溯源原文切片片段。
4. **多题型与组卷出题**：
   - 后端支持 7 种题型：`single_choice` (单选)、`multiple_choice` (多选)、`true_false` (判断)、`fill_in_blank` (填空)、`term_explanation` (名词解释)、`short_answer` (简答)、`case_analysis` (案例分析)。
   - `POST /api/v1/questions/generate`：支持传入 `folder_id` 或 `material_id`，配合 `knowledge_point_ids`、`question_types`、`count`、`difficulty` 进行多知识点批量出题。
5. **练习批次与作答**：
   - `POST /api/v1/practices`：支持基于 `folder_id` / `material_id` / `knowledge_point_ids` / `question_ids` 创建练习批次试卷。
   - `PUT /api/v1/practices/{id}/answers`：保存作答草稿。
   - `POST /api/v1/practices/{id}/submit`：交卷。
   - `POST /api/v1/practices/{id}/diagnosis`：生成诊断报告。
6. **判题与复查**：
   - `POST /api/v1/grading/self-evaluate`：支持主观题自评打分。
   - `POST /api/v1/grading/regrade`：支持主观题申请 AI 重新判题（复查），入参 `attempt_item_id` 与 `reason`。
7. **错题本与自适应再生题**：
   - `GET /api/v1/diagnosis/wrong-records`：查询错题本列表，包含错题关联的 `knowledge_point_id`、错误原因与掌握度。
   - 错题再生题逻辑闭环：提取错题涉及的 `knowledge_point_ids`，调用 `POST /api/v1/questions/generate` 生成针对性练习题并组卷。
8. **AI 助教答疑**：
   - `POST /api/v1/questions/{id}/ask-coach`：题目级 AI 助教深入启发式解析与延伸思考。
   - 课程级/资料级知识点追问扩展：结合后端 `GET /api/v1/knowledge/{id}/snippets` 及知识树。

---

## 3. Requirements (需求清单)

### 模块一：个人中心与账户信息
- **REQ-1.1**: 用户可在「我的」页面查看当前头像与昵称。
- **REQ-1.2**: 用户可点击编辑昵称和头像，保存时调用 `PUT /api/v1/users/me` 更新。

### 模块二：课程文件夹与资料工作台
- **REQ-2.1**: 工作台以「课程文件夹」为主视图，支持新建课程、重命名课程、删除课程，展示各课程下的资料数和知识点数。
- **REQ-2.2**: 进入课程后，支持上传新资料到当前课程（调用 `/materials/upload` 并携带 `folder_id`）。
- **REQ-2.3**: 资料卡片展示当前状态（待解析 WAITING / 解析中 PROCESSING / 已就绪 PARSED / 失败 FAILED）。
- **REQ-2.4**: 用户可手动点击「开始解析」按钮，调用 `POST /api/v1/materials/{id}/parse` 触发后台解析流水线，前端提供轮询状态更新机制。

### 模块三：知识树与知识点深度学习
- **REQ-3.1**: 资料解析就绪后，用户可进入「知识图谱/知识点学习」视图，查看层级知识树拓扑结构。
- **REQ-3.2**: 点击任意知识点节点，查看该知识点的详细 AI 讲解、核心定义与溯源原文切片（Snippet）。
- **REQ-3.3**: 支持知识点扩展生成学习内容（基于知识点详情或 AI 助教交互）。

### 模块四：多知识点多题型出题与组卷
- **REQ-4.1**: 在课程或资料页提供「开始刷题 / 生成复习题」入口。
- **REQ-4.2**: 选题配置抽屉/弹窗：
  - 用户可多选知识点（勾选本次批次需要覆盖的知识点）。
  - 用户可勾选题型范围（单选、多选、填空、判断、简答/分析题）。
  - 用户可调整题量与难度。
- **REQ-4.3**: 点击生成后，调用出题流水线并创建批次练习（`POST /practices`），跳转进入练习会话。

### 模块五：批次答题、即时评分与判题复查
- **REQ-5.1**: 练习作答界面自适应多题型交互：
  - 单选/多选：交互选项卡。
  - 判断题：正确/错误开关。
  - 填空题：输入框填空。
  - 简答/案例分析题：多行文本输入。
- **REQ-5.2**: 交卷后立即进入结果/诊断报告：客观题即时出分与解析。
- **REQ-5.3**: 主观题显示判题得分与采分点，提供「申请 AI 复查 / 重新判题」功能，弹出输入复核理由弹窗，调用 `POST /grading/regrade`。

### 模块六：错题自适应再生题与再次答题
- **REQ-6.1**: 在诊断报告或错题本中，高亮显示本次批次错题及其归属知识点。
- **REQ-6.2**: 提供「错题针对性巩固 / AI 举一反三再生题」按钮：自动聚合当前错题关联的知识点 ID，调用出题生成新批次并一键进入新一轮练习。

### 模块七：课程级 & 题目级 AI 助手
- **REQ-7.1**: 题目级助教：在答题解析或报告页，可点击「AI 助教」，调用 `/questions/{id}/ask-coach` 进行上下文答疑。
- **REQ-7.2**: 课程级助手悬浮入口：在课程工作台提供 AI 对话抽屉，支持根据当前课程的知识树与资料切片为用户提供导学与答疑。

---

## 4. Acceptance Criteria (验收标准)

- [ ] AC-1: 用户在个人中心能成功修改并持久化自定义昵称与头像。
- [ ] AC-2: 用户能创建新课程文件夹，并将资料上传到指定课程中。
- [ ] AC-3: 用户在资料卡片上手动点击「解析资料」后，界面能正确反馈解析中状态，并在解析完成后呈现知识树与知识点讲解。
- [ ] AC-4: 在课程/资料出题页，用户能按知识点勾选、选择单选/多选/判断/填空/简答等题型并成功生成批次练习。
- [ ] AC-5: 练习支持各类题型作答与交卷，交卷后客观题自动打分，主观题可成功触发申请 AI 复查。
- [ ] AC-6: 练习结束后，用户能通过错题一键触发针对该知识点的「再次生题」并进入新一轮练习。
- [ ] AC-7: 用户能在题目和课程中调起 AI 助教获得解析答疑。

---

## 5. Out of Scope (非本期核心范围)

- 后端核心模型与已有数据库迁移重构（尽量复用后端已具备的完备 RESTful API，仅在必要时补充小粘合接口）。
- 离线缓存离线作答（依赖线上网络与后端 LLM 实时响应）。
