# Design: 出题生成进度反馈与生成后跳转

## 1. 交互时序

```
点击「开始定制出题」
  → 校验配置
  → submitting=true：全表单禁用 + 显示「进行中」面板（阶段文案 + 计时）
  → POST /questions/generate（真实 30s+）
  → 成功：关闭抽屉 → navigateTo 题目页(material_id) → toast
  → 空结果：留在抽屉，提示「本次未产出合格题目」+ 重试
  → 失败：留在抽屉，按错误类型提示 + 重试（保留配置）
  → finally: submitting=false
```

## 2. 进度表现（前端动画，非真实进度）

- 阶段文案轮播：`检索切片 → 命制题目 → 质检门禁`（`setInterval` 定时切换，请求结束清理）。
- 计时器：`elapsed` 秒数自增显示，让用户确认「没死」。
- 组件卸载/关闭时清理定时器，避免泄漏。

## 3. 跳转契约

- `uni.navigateTo({ url: '/subpackages/material/pages/questions/index?material_id=<id>' })`。
- 失败兜底：`fail` 回调 toast「题目页打开失败」，并保留成功提示，不静默。
- 参数与 `verify-list` 页面契约一致（`material_id`）。

## 4. 错误分类

- 网络/超时（`request` 抛错）→「网络异常，请重试」。
- 业务错误（40003 无切片/门禁、40007 越权等）→ 展示后端 `message`。
- 空结果（`qualified_questions` 为空）→「未产出合格题目，可调整考点/题量后重试」。

## 5. 旧逻辑收敛

- 移除知识树页 `handleGenerateSuccess` 的「本地追加 + 切 Tab」逻辑（避免双数据源）；改为跳转题目页。
- 保留/移除知识树页内题目 Tab 由评审门确认（默认：移除，题目统一在题目页）。

## 6. 超时

- 核对 `utils/request.ts` 超时是否 >= 60s；不足则为本接口配置更长超时或可配置项。

## 7. 测试

- 单测：提交中显示进行中状态；成功后调用 `navigateTo`（mock）；失败/空结果展示提示且可重试；重复点击无效；定时器清理。
