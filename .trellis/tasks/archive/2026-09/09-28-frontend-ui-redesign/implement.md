# 前端UI全面重构与学习闭环实施方案 (Implement Plan)

## 1. 实施检查清单 (Checklist)

- [ ] **Phase 1: API 客户端与类型定义扩充**
  - [ ] 1.1 在 `src/types/index.ts` 扩充 Folder, KnowledgeTree, Snippet, QuestionType (扩展 fill_in_blank, case_analysis 等), RegradeRequest, AskCoach 等契约模型。
  - [ ] 1.2 在 `src/api/index.ts` 中封装完整的前后端 API：
    - 个人画像更新：`apiUpdateUserProfile` (`PUT /users/me`)
    - 课程文件夹：`apiListFolders`, `apiCreateFolder`, `apiDeleteFolder`, `apiGetFolderKnowledgePoints`
    - 资料解析流水线：`apiTriggerMaterialParse` (`POST /materials/{id}/parse`)
    - 知识树与切片：`apiGetKnowledgeTree`, `apiGetKnowledgePointDetail`, `apiGetKnowledgePointSnippets`
    - 题目生成与 AI 助教：`apiGenerateQuestionsBatch`, `apiAskQuestionCoach`
    - 判题复查与重判：`apiRegradeAttempt` (`POST /grading/regrade`)
    - 错题与自适应练习：`apiListWrongRecords`

- [ ] **Phase 2: 状态管理与 Pinia Stores 升级**
  - [ ] 2.1 升级 `stores/auth.ts`，增加更新用户信息 action。
  - [ ] 2.2 新建 `stores/folder.ts`，负责管理用户课程、新建/删除文件夹、当前激活课程。
  - [ ] 2.3 增强 `stores/material.ts`，支持按课程过滤资料、手动触发解析、轮询资料解析状态。
  - [ ] 2.4 增强 `stores/practice.ts`，支持多题型数据模型、草稿保存、自动判题结果聚合、申请复查 action、错题知识点提取与一键生题。

- [ ] **Phase 3: 核心页面与交互组件重构**
  - [ ] 3.1 **个人中心与个人资料 (`pages/profile/index.vue`)**：支持查看及弹窗/表单编辑昵称和头像。
  - [ ] 3.2 **课程与资料工作台 (`pages/index/index.vue`)**：
    - 课程文件夹横向/纵向导航与新建课程弹窗。
    - 资料列表展示：状态徽标、手动「点击解析」按钮、轮询反馈。
    - 资料卡片提供「知识树学习」、「批次出题」入口。
  - [ ] 3.3 **知识点树与扩展学习页 (`subpackages/material/pages/knowledge/index.vue` 或 `course/index.vue`)**：
    - 知识树折叠层级渲染。
    - 点击知识点弹出抽屉/卡片展示：AI 详细讲解、教材原文切片 (Snippets) 溯源。
  - [ ] 3.4 **知识点选题与多题型出题配置 (`subpackages/material/pages/questions/index.vue`)**：
    - 知识点树多选勾选。
    - 题型复选框（单选、多选、判断、填空、简答等）。
    - 题量与难度滑动条，出题生成加载交互。
  - [ ] 3.5 **练习做题界面升级 (`subpackages/practice/pages/session/index.vue`)**：
    - 适配单选、多选、判断、填空、主观简答 5 种交互形式。
    - 答题卡与实时保存草稿。
  - [ ] 3.6 **诊断报告与复查/错题再生题 (`subpackages/report/pages/detail/index.vue`)**：
    - 客观题秒出分与正确答案高亮。
    - 主观题展示评语与得分，提供「申请 AI 复查」弹窗提交理由并实时更新重判结果。
    - 底部展示错题知识点，提供「错题强化：针对性再生题」按钮，一键调起新出题批次。
  - [ ] 3.7 **AI 助教浮窗与答疑组件 (`src/components/AiCoachDrawer.vue`)**：
    - 题目解析处一键追问 AI 助教。
    - 课程级全局浮动 AI 助手入口。

- [ ] **Phase 4: 质量门禁与端到端回归校验**
  - [ ] 4.1 编写/更新前端单元测试 (`miniprogram/tests/`) 覆盖多题型作答、课程切换与复查流程。
  - [ ] 4.2 运行质量门禁：`pnpm run lint`、`pnpm run type-check`、`pnpm run test:unit`。

---

## 2. 验证命令

```bash
cd miniprogram && pnpm run lint && pnpm run type-check && pnpm run test:unit
```
