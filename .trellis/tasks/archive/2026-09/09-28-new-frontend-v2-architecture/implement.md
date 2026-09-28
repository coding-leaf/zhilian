# 全新前端架构与用户体验重构 Implementation Plan

## Phase 1: 后端关键接口协同支持 (Backend Micro-Extensions)
- [x] 1.1 扩展 `backend/app/schemas/practice.py` 与 `backend/app/services/practice.py`：支持 `question_ids` 直接组卷。
- [x] 1.2 在 `backend/app/api/v1/questions.py` 中新增 `POST /api/v1/questions/{id}/ask-coach` 接口支持 AI 助教答疑。
- [x] 1.3 编写并通过后端单元测试，确保后端完全契约就绪。

## Phase 2: 基础底座与视觉设计系统构建 (Foundation)
- [x] 2.1 构建视觉设计系统变量 `src/styles/theme.scss` 与全局样式规范（主色、中性色、卡片阴影、圆角、排版）。
- [x] 2.2 改造 `src/pages.json`，配置三 Tab 规范（学习工作台、学情与错题、我的与数据管理）及清晰的二级子包页面。
- [x] 2.3 搭建主包 Tab 骨架：
  - `pages/index/index.vue`（学习工作台）
  - `pages/review/index.vue`（学情看板与错题攻克）
  - `pages/profile/index.vue`（个人中心与数据安全治理）
- [x] 2.4 验证基础路由切换与样式编译。

## Phase 3: 核心作答引擎与极致离线防丢系统 (J4 Core Engine)
- [x] 3.1 实现离线防丢与秒存引擎 `src/composables/usePracticeSync.ts`（双轨持久化：Storage 毫秒级写入 + 后端防抖同步）。
- [x] 3.2 实现沉浸式作答页 `subpackages/practice/pages/session/index.vue`：
  - 顶部进度与倒计时。
  - 卡片左右滑屏切题容器（单选/多选/简答组件）。
  - 底部悬浮答题卡抽屉（已答/未答/标记疑问状态指示）。
  - 交卷未答智能拦阻与确认机制。
- [x] 3.3 编写作答断点恢复与离线同步单元测试。

## Phase 4: 诊断报告生成、深度解析与 AI 追问 (J5, J6, UX Delighter)
- [x] 4.1 实现交卷过渡动效态 `subpackages/practice/pages/transition/index.vue`（分步动效与后台静默生成容灾）。
- [x] 4.2 重构诊断报告页 `subpackages/report/pages/detail/index.vue`：
  - 综合得分与掌握度雷达图。
  - 薄弱知识点清单与“一键针对性强化练”直接组卷流。
- [x] 4.3 实现题目深度解析与纠偏页 `subpackages/report/pages/explanation/index.vue`：
  - 客观题标准解析与引文查看。
  - 主观题命中/遗漏采分点视觉对齐。
  - AI 复核与自评打分双通道纠错。
  - 核心体验增强：【追问 AI 助教】抽屉式深度对话解惑。

## Phase 5: 资料导入、多页 OCR 质检与出题核验流 (J1, J2, J3)
- [x] 5.1 实现多格式/多图选择组件与画廊质检页 `subpackages/material/pages/upload/index.vue`：
  - 一次选最多 9 张图片，缩略图网格画廊展示。
  - 异常页状态标识与单页即时重拍替换能力（J2）。
  - 聊天文件与本地多文档格式选择（PDF/DOCX/PPTX/TXT/MD）。
- [x] 5.2 实现题目质检核对清单 `subpackages/material/pages/verify/index.vue`（J3）：
  - 题目来源展开与讲义原文对齐。
  - AI 质检建议展示、题目增删改查。
  - 一键开启作答闭环。

## Phase 6: 学情错题攻克看板与个人中心数据治理 (J7, J8)
- [x] 6.1 实现错题攻克看板 `pages/review/index.vue`：
  - 掌握进度环与课程/题型/时间多维筛选。
  - 错题购物车多选机制：勾选特定错题并点击【组合练习】，使用带 `question_ids` 的 `createPractice` 接口直接生成针对性练习并前往作答（闭合 J7）。
  - 单题温习与标记已攻克状态流转。
- [x] 6.2 实现个人中心与数据安全治理 `pages/profile/index.vue`：
  - 个人学习资产概览。
  - 归档课程管理箱。
  - 隐私承诺说明、数据物理擦除与账号注销流程（J8）。

## Phase 7: 全链路串联、代码清理与质量检验
- [x] 7.1 清理历史无用的旧组件与弃用页面，确保工程整洁。
- [x] 7.2 运行全面类型检查与代码检查：`npm run type-check` 和 `npm run lint`。
- [x] 7.3 运行单元测试套件：前端 `npm run test:unit` 与 后端 `pytest`。
- [x] 7.4 执行 J1~J8 端到端验收用例核验。
