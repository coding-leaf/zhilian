# 后端开发规范（backend）

> 本项目后端（FastAPI + SQLAlchemy async + Alembic + LangGraph）的开发规范索引。

---

## 概览

本目录收录后端开发规范。每份文档都以 `backend/app/**` 的真实代码为事实源，
并在正文中给出可 grep 的路径/符号锚点。

---

## 规范索引

| Guide | 覆盖范围 | 事实源 | 最后核对 |
| --- | --- | --- | --- |
| [Directory Structure](./directory-structure.md) | 模块组织与文件布局、分层边界 | `backend/app/**`、`backend/pyproject.toml` | 2026-09-29 |
| [Database Guidelines](./database-guidelines.md) | ORM 模式、查询、DML 影响行数、迁移、迁移一致性闸门 | `backend/app/models/**`、`backend/app/repositories/**`、`backend/migrations/versions/**`、`backend/alembic.ini`、`backend/tests/unit/models/**` | 2026-09-29 |
| [Error Handling](./error-handling.md) | 异常类型与处理策略 | `backend/app/core/errors.py`、`backend/app/api/**`、`backend/app/cli/errors.py` | 2026-09-28 |
| [Quality Guidelines](./quality-guidelines.md) | 代码标准、禁止模式、质量门禁 | `backend/app/**`、`backend/tests/**`、`backend/migrations/**`、`backend/pyproject.toml` | 2026-09-29 |
| [Logging Guidelines](./logging-guidelines.md) | 结构化日志与日志级别 | `backend/app/core/config.py`、`backend/app/**` | 2026-09-28 |

---

## 如何阅读与维护这些规范

1. 文档记录的是项目**实际约定**（而非理想态）。
2. 每条约定都应能在「事实源」列出的路径中找到依据。
3. 「最后核对」是最后一次对照代码核对的时间；若代码已明显偏离，应重新核对并更新。
4. 新增或修改规范时，请同步更新本索引的「事实源」与「最后核对」。

---

**语言**：本目录下的规范正文以**中文**撰写，代码标识符、路径与命令保持原文。
