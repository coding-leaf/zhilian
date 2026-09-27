# Design — Refresh Trellis specs against actual codebase

## 1. 目标与非目标

**目标**：把 `.trellis/spec/` 从「模板空壳 + 误植工具文档 + 部分活文档」变成一套
与真实代码对齐、且**自带过期信号**的事实源。

**非目标**：不引入 CI 校验脚本，不改产品代码，不把 spec 变成自动生成物。
抗腐坏依靠**可 grep 的锚点 + 人工/代理核对**，不依赖尚未存在的工具链。

## 2. 语料边界（现状 → 目标）

| 区域 | 现状 | 目标 |
|---|---|---|
| `backend/*.md` 4 个空壳 | `To be filled` | 按代码填实，带 front-matter + 代码锚点 |
| `frontend/*.md` 5 个空壳 | `To be filled` | 同上 |
| `*/quality-guidelines.md` | 活的 41 个 scenario | 逐条核对，补代码锚点，修/删过期项 |
| `guides/*.md` | Trellis 工具文档 + 3 处重复 | 本地化为智练跨层/复用指南，去重 |
| `*/index.md` ×3 | 模板状态 / 不全 | 列真实文件 + 最后核对日期 + 语言声明修正 |

## 3. 抗腐坏约定（核心设计）

### 3.1 每份 spec 顶部 front-matter 块

所有 spec 文件（含 quality-guidelines）在 H1 之后插入统一块：

```markdown
> **事实源**：`backend/app/services/material.py`、`backend/app/models/material.py` …
> **最后核对**：2026-09-28 @ <git short sha>
> **核对方式**：`rg "ParseStatus|failed_stage" backend/app backend/tests`
```

- `事实源`：该文档断言所依赖的代码路径，供读者直接跳转。
- `最后核对`：人工/代理最后一次对照代码的日期与提交，提供**过期信号**。
- `核对方式**：一条可复制的 grep/rg 命令，任何人可重跑以发现漂移。

### 3.2 每个断言附可 grep 的代码锚点

quality-guidelines 的每个 `### Scenario` 增加一节：

```markdown
#### 代码锚点
- `backend/app/services/material.py::MaterialService.retry_material_pipeline`
- `backend/app/models/material.py::MaterialVersion.parse_status`
```

规则：锚点写 **路径::符号**，符号必须是当前代码里真实存在的可搜索标识符。
若某 scenario 无法给出锚点，则该 scenario 判定为「无代码依据」→ 删除或改写。

空壳类文档（directory-structure 等）同样在每个小节末尾列锚点路径。

### 3.3 index 状态列 = 最后核对日期

`backend/index.md` / `frontend/index.md` 的表改为：

| Guide | 覆盖范围 | 事实源 | 最后核对 |
|---|---|---|---|
| Directory Structure | ... | `backend/app/**` | 2026-09-28 |

并删除与事实不符的 `**Language**: English` 行，改为中文声明。

## 4. 41 个 scenario 的核对方法

对 `backend/quality-guidelines.md`（25）与 `frontend/quality-guidelines.md`（16）逐个执行：

1. **抽取断言**：从 `Scope/Signatures/Contracts/Wrong vs Correct` 中取出被点名的
   API 路由、服务方法、模型字段、常量、组件/composable、store action。
2. **定位代码**：`rg` 上述符号，确认存在且行为与描述一致（含 HTTP 状态码、默认值、
   状态机取值、边界条件）。
3. **裁决**并记录到审计台账：
   - `verified`：描述与代码一致 → 仅补代码锚点。
   - `corrected`：位置/名称/数值漂移 → 改写为代码现状。
   - `removed`：功能已不存在或语义被覆盖 → 删除该 scenario，并在台账说明原因。
4. **回填锚点**：为保留的 scenario 补 `#### 代码锚点`。

台账文件（执行期产出，非 spec）：
- `.trellis/tasks/09-28-refresh-trellis-spec/audit-backend.md`（25 行表）
- `.trellis/tasks/09-28-refresh-trellis-spec/audit-frontend.md`（16 行表）

每行：`Scenario | 抽取符号 | rg 结果位置 | 裁决 | 处置摘要`。

## 5. 空壳文档的内容来源（避免臆造）

| 文件 | 主要事实源 |
|---|---|
| `backend/directory-structure.md` | `backend/app/**` 目录、`pyproject.toml`（hatch packages）、import-linter 分层 |
| `backend/database-guidelines.md` | `backend/app/models/*`、`backend/migrations/versions/*`、`alembic.ini`、async session 注入（`app/api/deps/db.py`） |
| `backend/error-handling.md` | `backend/app/core/errors.py`、`app/api/**` 的异常映射、CLI `app/cli/errors.py` |
| `backend/logging-guidelines.md` | 代码中 logging 用法（`rg "logger|logging" backend/app`）、配置（`app/core/config.py`） |
| `frontend/directory-structure.md` | `miniprogram/src/**`、`pages.json`、`vite.config.ts` |
| `frontend/component-guidelines.md` | `miniprogram/src/components/**`、`subpackages/**/components/**`（Vue SFC 约定、props/emits） |
| `frontend/hook-guidelines.md` | `miniprogram/src/**/composables/*`（`useMaterialPolling` 等） |
| `frontend/state-management.md` | `miniprogram/src/stores/*`（Pinia 约定、`index.ts` 导出） |
| `frontend/type-safety.md` | `miniprogram/src/types/*`、`tsconfig.json`、ESLint no-explicit-any |

每份文档都要求**先读代码再写**；写入的每条约定必须能被上表路径中的代码佐证。

## 6. guides 本地化与去重

- 删除 `cross-layer-thinking-guide.md` 的三段重复块，标题唯一化。
- 删除纯 Trellis 包内部章节（`Cross-Platform Template Consistency`、
  `Generated Runtime Template Upgrade Consistency`、`Versioned Documentation Boundary`、
  `Mode-Detection Probe Checklist`、`Event Log / Projection Boundary`）。
- 保留并本地化的部分：
  - `Cross-Layer Thinking Guide`：数据流映射、边界表 → 改写为
    **API ↔ miniprogram** 边界（字段名钉死、序列化/日期、store 状态）、
    Material/Question/Practice 的真实跨层链路。
  - `Code Reuse Thinking Guide`：保留「先搜索」原则与 reducer/穷尽分支；
    删除 Trellis 模板注册相关小节，改以本项目 `composables/`、`utils/` 复用为例。
- `guides/index.md` 与两处 `*/index.md` 同步更新。

## 7. 兼容与回滚

- 变更范围仅 `.trellis/spec/**`（+ 任务目录），**不触碰产品代码**，因此：
  - 前后端质量门禁与运行时行为不变。
  - 回滚 = `git revert`/`git checkout` 该次 spec 提交，无数据迁移。
- 风险：删除过期 scenario 可能移除仍被引用的知识 → 缓解：删除项必须在审计台账写明
  原因与被替代处，且 PR 可逐条 review。
- 风险：锚点符号写错 → 缓解：验收要求逐条 `rg` 命中。

## 8. 关键权衡

- **可 grep 锚点 vs 行号**：选符号而非 `file:line`，因为行号随编辑漂移；符号相对稳定。
- **删除 vs 保留过期 scenario**：选删除（配合台账），避免「僵尸契约」误导后续实现；
  这正是用户所指的文档腐坏。
- **不引入校验脚本**：本次保持纯文档，降低风险；若后续需要可另开任务做 CI 校验。
