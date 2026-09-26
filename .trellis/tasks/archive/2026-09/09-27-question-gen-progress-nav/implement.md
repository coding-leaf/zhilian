# Implement Plan: 出题生成进度反馈与生成后跳转

> 前端命令在 `miniprogram/` 下用 `pnpm`。禁止 Git Commit。
> 依赖：`09-27-question-gen-verify-list`（题目页）须先就绪。

## Stage 1：进行中状态（评审门 A）
- [ ] `QuestionConfigDrawer.vue`：提交时显示「进行中」面板（阶段文案 + 计时），全表单禁用。
- [ ] 定时器实现与清理（`onUnmounted` / 关闭时 `clearInterval`）。
- 验证：`pnpm run type-check && pnpm run test:unit`

## Stage 2：成功跳转
- [ ] 成功后 `uni.navigateTo` 题目页（`material_id`），带 `fail` 兜底；保留成功 toast。
- [ ] 知识树页 `handleGenerateSuccess` 改为「关闭抽屉 + 跳转」，移除本地追加/切 Tab 旧逻辑。
- 验证：`pnpm run test:unit`

## Stage 3：失败/空结果重试（评审门 B）
- [ ] 错误分类提示（网络 vs 业务 vs 空结果），保留用户配置可重试。
- [ ] 重复提交防护确认。
- [ ] 核对 `utils/request.ts` 超时（>= 60s 或本接口单独配置）。
- 验证：`pnpm run lint && pnpm run type-check && pnpm run test:unit`
- **评审门 B**：人工确认交互闭环后交主会话。

## Stage 4：单测
- [ ] `tests/unit/components/QuestionConfigDrawer.spec.ts` 扩展：进行中/成功跳转/失败重试/防重复/定时器清理。
- 验证：全量前端门禁。

## 全量门禁
```bash
pnpm run lint && pnpm run type-check && pnpm run test:unit
```

## 回滚点
- 还原 `QuestionConfigDrawer.vue` 与 `knowledge-tree/index.vue` 的改动。

## 风险
- 阶段文案为「示意进度」，需在文案上避免误导为真实进度（如「正在命制…」而非百分比）。
