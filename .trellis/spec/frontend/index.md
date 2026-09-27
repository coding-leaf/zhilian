# 前端开发规范（miniprogram）

> 本项目小程序（UniApp + Vue 3 + Pinia + Wot Design Uni）的开发规范索引。

---

## 概览

本目录收录前端开发规范。每份文档都以 `miniprogram/src/**` 的真实代码为事实源，
并在正文中给出可 grep 的路径/符号锚点；量化设计参数以 `docs/DESIGN.md` 为准。

---

## 规范索引

| Guide | 覆盖范围 | 事实源 | 最后核对 |
| --- | --- | --- | --- |
| [Directory Structure](./directory-structure.md) | 模块组织与文件布局 | `miniprogram/src/**`、`miniprogram/src/pages.json`、`miniprogram/vite.config.ts` | 2026-09-28 |
| [Component Guidelines](./component-guidelines.md) | 组件模式、props、组合 | `miniprogram/src/components/**`、`miniprogram/src/subpackages/**/components/**` | 2026-09-28 |
| [Hook Guidelines](./hook-guidelines.md) | 组合式函数、数据获取模式 | `miniprogram/src/**/composables/*` | 2026-09-28 |
| [State Management](./state-management.md) | 本地状态、全局状态、服务端状态 | `miniprogram/src/stores/*` | 2026-09-28 |
| [Quality Guidelines](./quality-guidelines.md) | 代码标准、禁止模式、质量门禁 | `miniprogram/src/**`、`miniprogram/tests/**`、`miniprogram/package.json` | 2026-09-28 |
| [Type Safety](./type-safety.md) | 类型模式与校验 | `miniprogram/src/types/*`、`miniprogram/tsconfig.json` | 2026-09-28 |

---

## 如何阅读与维护这些规范

1. 文档记录的是项目**实际约定**（而非理想态）。
2. 每条约定都应能在「事实源」列出的路径中找到依据。
3. 「最后核对」是最后一次对照代码核对的时间；若代码已明显偏离，应重新核对并更新。
4. 新增或修改规范时，请同步更新本索引的「事实源」与「最后核对」。

---

**语言**：本目录下的规范正文以**中文**撰写，代码标识符、路径与命令保持原文。
