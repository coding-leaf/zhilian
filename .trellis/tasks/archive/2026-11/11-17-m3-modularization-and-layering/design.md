# Technical Design — M3: 前后端深层解耦与巨型模块拆分

## 1. Parallel Track Architecture (`XHigh` Authors + Skeptical Verifier)

由于 `M3` 涉及千行上帝类拆分（最高 CC=73）与 6 个核心 `.vue` 页面重构，属于**高难度结构手术**，按用户规则双作者轨道与核验器均升级使用 `gemini-4-hydrogen-xhigh`（或作者 `XHigh` + 核验 `XHigh`）：

- **`be-modular`（`workspace: "share"`，`model: "gemini-4-hydrogen-xhigh"`）**：独占 `backend/**`。若任务内部可进一步无碰撞拆分（如纯提取器/重试工具 vs Service 拆分），允许 `be-modular` 按需自招 Helper。
- **`fe-modular`（`workspace: "share"`，`model: "gemini-4-hydrogen-xhigh"`）**：独占 `miniprogram/**`。
- **`verifier-m3`（`workspace: "inherit"`，`model: "gemini-4-hydrogen-xhigh"`）**：逐项核查行数红线（`.vue <= 300`）、圈复杂度门禁（`max-complexity`）、零裸 SQL / 零 monkey-patch 及全套单测。

## 2. Backward-Compatible Module Split Strategy

1. **后端 Facade 保兼容原则**：
   - 拆分 `services/question.py`、`material.py`、`diagnosis.py`、`practice.py`、`grading.py` 时，原模块路径（如 `from app.services.diagnosis import DiagnosisService`）必须保持 100% 可导入，内部委托给新拆分的纯粹子模块（如 `core/extractors/*`、`core/algorithms/knowledge_tree.py`、`services/_diagnosis_report.py`、`services/_question_generation.py` 等），确保 100+ 个测试文件与 `AppContainer` 无需大面积改导入路径即可无缝运行。
2. **前端 Barrel 保兼容原则**：
   - `src/types/index.ts` 拆分为 `src/types/{auth,folder,material,knowledge,question,practice,diagnosis,wrong}.ts` 后，`src/types/index.ts` 通过 `export * from './...'` 全量重导出；
   - `src/api/index.ts` 拆分为 `src/api/modules/{auth,folders,materials,knowledge,questions,practices,grading,diagnosis,wrong}.ts` 后，`src/api/index.ts` 全量重导出。
