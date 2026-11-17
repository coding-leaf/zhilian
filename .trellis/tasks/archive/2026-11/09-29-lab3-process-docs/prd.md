# 交付文档集：README、开发过程文档、后续待解决问题

> 父任务：`09-29-lab3-delivery-wrapup`，覆盖其 **R1**。
> **排期约束**：`docs/screenshots/` 的清单会被《开发过程文档》引用，故本任务的
> 「过程文档定稿」宜排在 `lab3-ui-screenshots` 之后；其余部分不受约束。

## Goal

把散在 6 处的过程素材汇成**老师能一口气读完**的三份文档，并使根 `README.md` 成为
公共仓库的可读门面。老师点开链接后不需要追问「这是什么、怎么跑、做到哪了」。

## 需求

- R1.1 根 `README.md`：项目定位、技术栈、主链路（8 节点）、目录结构、本地启动、
  质量门禁命令、当前完成度与已知问题入口。
- R1.2 `docs/开发过程文档.md`：时间线（2026-09-23 → 09-29）、任务体系（40 个 ZL 任务 +
  Trellis 任务树）、迭代节奏、关键决策、**缺陷修复史**、质量证据、版本控制说明。
- R1.3 `docs/后续待解决问题.md`：未收口任务与已知问题，每项含现状、影响、下一步。

## 素材来源（已核实存在）

| 文档 | 素材 |
| --- | --- |
| `README.md` | `Taskfile.yml`、`deploy/docker-compose.yml`、`backend/pyproject.toml`、`miniprogram/package.json`、`docs/DESIGN.md` |
| `开发过程文档.md` | `docs/legacy_sdlc/{ROADMAP,ARCHIVE,LEADER_ALIGNMENT}.md`、`docs/legacy_sdlc/ZL-*/`、`.trellis/tasks/**`、`.trellis/workspace/coding-leaf/journal-1.md` |
| `后续待解决问题.md` | `09-29-field-test-fix-batch-1/prd.md`、`09-29-question-bank-tab/prd.md`、`LEADER_ALIGNMENT.md`、`AGENTS.md` |

## Acceptance Criteria

- [ ] AC-1 三份文档均存在且非空
- [ ] AC-2 `README.md` 内的启动与门禁命令**可直接复制执行**，且与 `Taskfile.yml` 一致
- [ ] AC-3 《开发过程文档》每个结论都能在仓库中定位出处（文件路径或提交号）
- [ ] AC-4 《开发过程文档》含**版本控制章节**，如实写出：远端分支形态、无合并提交的历史、
  CI 与分支保护的现状与偏差（承接 design.md 5.2 的偏差留痕）
- [ ] AC-5 《开发过程文档》的缺陷修复史至少覆盖三个「静默失效」类缺陷的根因，
  且引用的提交号真实存在
- [ ] AC-6 《后续待解决问题》覆盖全部 9 个未收口 Trellis 任务与 `question-bank-tab`
  的 R1–R6 与 5 条已知问题
- [ ] AC-7 三份文档**均不含真实姓名**（C-1）
- [ ] AC-8 文档不引用 `docs/screenshots/` 中不存在的文件

## Out of Scope

- 不改写 `docs/specs_extracted/` 三份基线文档（除父任务 R4.6 的单独修正项）。
- 不新增功能说明文档（本任务只做汇总，不新写需求/设计）。
