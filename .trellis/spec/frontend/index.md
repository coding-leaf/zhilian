# 前端开发规范（miniprogram）

> 本项目小程序（UniApp + Vue 3 + Pinia + Wot Design Uni）的开发规范索引。
> 当前版本：全面重构温润学术版（J1 黄金学习闭环已全线打通）。

---

## 概览

本项目采用 UniApp + Vue 3 (Vite + TypeScript) + Pinia 构建，整体视觉采用温润学术/纸质阅读风。
主包聚焦 3 个核心 Tab（工作台、学情、我的），业务拆分为 material（资料与出题）、practice（专注答题与草稿）、report（学情诊断）三个纯净高内聚分包。

---

## 规范索引

| 模块 | 职责与规范覆盖 | 核心文件与事实源 |
| --- | --- | --- |
| 目录架构 | 3-Tab 主包 + 3 核心业务分包结构 | `src/pages.json`、`src/manifest.json`、`vite.config.ts` |
| 领域状态与持久化 | Pinia 状态机与本地草稿双写自愈 | `src/stores/practice.ts`、`src/stores/material.ts`、`src/stores/folder.ts`、`src/stores/diagnosis.ts` |
| 网络与契约 | 强类型 RESTful 统一拦截与异常处理 | `src/utils/request.ts`、`src/api/index.ts`、`src/types/index.ts` |
| 视觉设计系统 | 温润学术纸质色盘与 Design Tokens | `src/App.vue`（全局 CSS Variables 与 paper-card 卡片） |
| 助教与智能交互 | 全局与局部 AI 助教启发式答疑抽屉 | `src/components/AiCoachDrawer.vue`、`src/api/index.ts` |
| 质量门禁 | ESLint + vue-tsc 类型检查 + Vitest 单元测试 | `package.json`、`vitest.config.ts`、`tests/practice.spec.ts` |

---

## 黄金切片流转契约 (J1)

1. **课程与资料导入解析**：`pages/index/index` 支持课程文件夹管理与筛选，上传资料至指定课程后，在讲义卡片或 `subpackages/material/pages/course/index` 手动触发 `POST /materials/{id}/parse` 并轮询解析状态；就绪后展示层级知识树与原文切片溯源。
2. **多考点多题型出题核对**：`course/index` 或 `questions/index` 支持按考点多选并勾选单选/多选/判断/填空/简答等 5 大题型，调用 `POST /questions/generate` 批量组卷。
3. **沉浸练习与多题型作答**：点击“开始作答”调用 `POST /practices` 初始化练习，跳转 `subpackages/practice/pages/session/index`。自适应渲染单选/多选/判断/填空/简答，改动实时双写 `uni.setStorageSync` 与后台草稿同步。
4. **交卷、主观题复查与错题再生**：点击交卷调用 `POST /practices/{id}/submit` 与 `POST /practices/{id}/diagnosis` 直达诊断报告页；客观题秒判，主观题展示得分与采分点，支持弹窗理由调用 `POST /grading/regrade` 申请 AI 复查；支持针对错题知识点一键举一反三再次生题。
5. **AI 助教答疑**：在工作台、知识点详情及题目解析中均可通过 `AiCoachDrawer` 调用 `POST /questions/{id}/ask-coach` 进行启发式解答与延伸追问。
