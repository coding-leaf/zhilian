# Implement Plan: 生题效果可核验（独立题目页）

> 前端命令在 `miniprogram/` 下用 `pnpm`。禁止 Git Commit。

## Stage 1：页面骨架 + 路由（评审门 A）
- [ ] 新建 `subpackages/material/pages/questions/index.vue` + `questions.scss`。
- [ ] `pages.json` 注册 `pages/questions/index`（标题「题目列表」）。
- [ ] 参数解析 `material_id|materialId|id`。
- 验证：`pnpm run type-check`

## Stage 2：数据加载 + 列表渲染
- [ ] `fetchQuestionList({ material_id, page, page_size })` → 本地 `listData`。
- [ ] 渲染题目卡片（题型/难度/题干/答案/解析），主观题隐藏选项。
- [ ] 加载态 / 空态（含「去知识树生成」跳转）。
- [ ] `onShow` 重新拉取。
- 验证：`pnpm run type-check && pnpm run test:unit`

## Stage 3：操作与复用（评审门 B）
- [ ] 接入 `QuestionEditDrawer`（编辑）、`QuestionAuditDrawer`（痕迹）、`deleteQuestion`（删除 + 确认）。
- [ ] 操作后本地列表即时更新。
- [ ] 分页/加载更多（去重合并）。
- 验证：`pnpm run lint && pnpm run type-check && pnpm run test:unit`

## Stage 4：入口与单测
- [ ] 知识树页提供「查看题目列表」入口（跳本页）。
- [ ] 单测：`tests/unit/pages/questionList.spec.ts`（渲染/空态/删除更新/参数解析）。
- 验证：全量前端门禁。
- **评审门 C**：人工确认核验体验后交主会话。

## 全量门禁
```bash
pnpm run lint && pnpm run type-check && pnpm run test:unit
```

## 回滚点
- 删除页面与 `pages.json` 注册项。

## 风险
- 题目页与知识树页可能出现入口重复，需与 `progress-nav` 统一（本任务只加入口，不删旧 Tab；旧 Tab 收敛在 `progress-nav` 处理）。
