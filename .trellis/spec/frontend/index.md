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
| 领域状态与持久化 | Pinia 状态机与本地草稿双写自愈 | `src/stores/practice.ts`、`src/stores/material.ts`、`src/stores/diagnosis.ts` |
| 网络与契约 | 强类型 RESTful 统一拦截与异常处理 | `src/utils/request.ts`、`src/api/index.ts`、`src/types/index.ts` |
| 视觉设计系统 | 温润学术纸质色盘与 Design Tokens | `src/App.vue`（全局 CSS Variables 与 paper-card 卡片） |
| 质量门禁 | ESLint + vue-tsc 类型检查 + Vitest 单元测试 | `package.json`、`vitest.config.ts`、`tests/practice.spec.ts` |

---

## 黄金切片流转契约 (J1)

1. **导入与解析**：`pages/index/index` 通过 `chooseMessageFile` 或 `chooseImage` 上传资料至 `POST /materials/upload`，跳转 `subpackages/material/pages/course/index` 轮询解析。
2. **出题核对**：`course/index` 点击智能出题调用 `POST /questions/generate`，生成完毕后跳至 `subpackages/material/pages/questions/index` 预览题目与依据。
3. **沉浸练习**：点击“开始作答”调用 `POST /practices` 初始化练习，跳转 `subpackages/practice/pages/session/index`。选项改动实时双写 `uni.setStorageSync` 与后台草稿同步。
4. **交卷与直达诊断**：点击交卷调用 `POST /practices/{id}/submit` 与 `POST /practices/{id}/diagnosis`，直接安全跳转至真正的报告页 `subpackages/report/pages/detail/index`，杜绝占位页与断头跳转。
