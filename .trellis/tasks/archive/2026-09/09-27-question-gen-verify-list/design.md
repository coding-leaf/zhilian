# Design: 生题效果可核验（独立题目页）

## 1. 页面与路由

- 新增：`miniprogram/src/subpackages/material/pages/questions/index.vue`（+ `questions.scss`）。
- 注册：`pages.json` → material 分包 pages 增 `pages/questions/index`，标题「题目列表」。
- 入参契约（统一）：`material_id`（兼容读取 `materialId` / `id`）。

## 2. 数据流

```
onLoad(material_id) → fetchQuestionList({material_id, page, page_size})
   ↓ PageResult<QuestionItem>
listData(本地 ref, 与全局 Store 隔离) → 渲染列表
onShow → 重新拉取（反映最新/删除后状态）
编辑/删除/痕迹 → 复用 QuestionEditDrawer / QuestionAuditDrawer / deleteQuestion
```

## 3. 组件与复用

- 迁移 `knowledge-tree/index.vue` 现有题目卡片渲染（题型徽标、难度、题干、答案、操作按钮）。
- 复用 `QuestionEditDrawer.vue`、`QuestionAuditDrawer.vue`（已存在）。
- 选项渲染：`QuestionOption { key, text }`；主观题（`short_answer`）隐藏选项区。

## 4. 交互与状态

- 加载态：`wd-loading` + 文案；空态：图标 + 「暂无题目，去知识树生成」+ 跳知识树按钮。
- 分页：下拉/触底加载更多（`page`/`page_size`）；去重合并。
- 操作后本地即时更新（编辑替换、删除移除），无需整页刷新。

## 5. 兼容与隔离

- 采用「页面本地 `listData`」模式，避免覆盖全局 Store 首页切片（沿用既有约定）。
- 不改后端；仅消费既有 `GET /api/v1/questions`。

## 6. 回滚

- 删除新增页面与 `pages.json` 注册项即可。

## 7. 测试

- 单测：页面组件（mock `fetchQuestionList`）断言列表渲染、空态、删除后更新；参数解析（`material_id`/`materialId`/`id`）。
