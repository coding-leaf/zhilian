# 前端完全重构与J1端到端切片闭环 (Implementation Plan)

## 1. 执行清单 (Ordered Checklist)

### 阶段一：环境清理与工程底座重构 (Scaffolding & Foundation)
- [x] **Step 1.1**: 归档并清理 `miniprogram` 中陈旧、断裂的临时组件和无用占位页面，重新初始化 `package.json` 与 Vite/TS 配置。
- [x] **Step 1.2**: 引入 UnoCSS 与 Wot Design Uni，配置温润学术风格的 Design Tokens（纸张底色、墨黑文字、边框与圆角规范）。
- [x] **Step 1.3**: 搭建统一网络请求模块 `src/utils/request.ts` 与认证拦截器，对齐后端 API 强类型接口定义。
- [x] **Step 1.4**: 配置精简的 `pages.json`（3-Tab 主包 + 3 核心业务分包）。

### 阶段二：J1 核心领域模型与状态机搭建 (Domain & State)
- [x] **Step 2.1**: 实现 `useAuthStore`（微信登录与 token 持久化）。
- [x] **Step 2.2**: 实现 `useMaterialStore`（资料上传、状态轮询与出题请求）。
- [x] **Step 2.3**: 实现 `usePracticeMachine`（作答题目索引、草稿本地持久化防丢、交卷及报告轮询）。
- [x] **Step 2.4**: 实现 `useDiagnosisStore`（诊断报告数据解析与展示）。

### 阶段三：页面视图重构与端到端串联 (Views & J1 Vertical Slice)
- [x] **Step 3.1**: 重构工作台 `pages/index/index`（温润书卷感头部、资料快捷上传卡片、最近学习状态）。
- [x] **Step 3.2**: 重构资料出题核对页 `subpackages/material/pages/questions/index`（题目卡片、题型标签、来源讲义锚点、“开始答题”底栏）。
- [x] **Step 3.3**: 重写练习作答页面 `subpackages/practice/pages/session/index`（专注沉浸答题卡片、选项点击即时存草稿、交卷未答提示）。
- [x] **Step 3.4**: 重构学情报告页面 `subpackages/report/pages/detail/index`（综合得分概览、掌握度分析、逐题依据与原文回溯、继续练习闭环）。

### 阶段四：验证与质检门禁 (Verification & Quality Gate)
- [x] **Step 4.1**: 执行前端代码规范检查：`pnpm run lint` 与 `pnpm run type-check`。
- [x] **Step 4.2**: 运行单元测试：`pnpm run test:unit`。
- [x] **Step 4.3**: 运行完整质量门禁验证：构建 `pnpm run build:mp-weixin` 成功。
- [x] **Step 4.4**: J1 黄金链路端到端逻辑跑通与中断恢复自测。

## 2. 验证与检查命令 (Validation Commands)
```bash
# 进入前端目录
cd miniprogram

# 代码风格与语法检查
pnpm run lint

# TypeScript 严格类型检查
pnpm run type-check

# 单元测试
pnpm run test:unit

# 前端构建验证
pnpm run build:mp-weixin
```

## 3. 风险点与回退策略 (Risks & Rollback)
- **风险 1：微信小程序端 UnoCSS 兼容性**
  - *应对方案*：使用 `unocss-preset-uni` 或标准化 CSS 变量，确保小程序的编译层能够精准解析 class 名。
- **风险 2：报告生成异步延时导致的白屏等待**
  - *应对方案*：在交卷流转中增加优雅的过渡态（Transition Loading 轮询），在 5 秒内未完成时提供“后台生成中，完成后可在学情页查看”的安全兜底，绝不跳往空白页。
