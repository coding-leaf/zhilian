# Implementation Plan — M3: 前后端深层解耦与巨型模块拆分

## 1. Execution Steps

1. **Step 0（Coordinator）**：基于 `refs/swarm-opt/m2-base` 激活 `11-17-m3-modularization-and-layering`。
2. **Step 1A（`be-modular`，`XHigh`，`workspace: "share"`）**：
   - 下沉 Service 裸 `select()`/`delete()` 到 Repo；修复 `practices.py` 越层导入并加 `import-linter` 契约；修复 `FolderService` DI；消除 ORM monkey-patch；
   - 抽取 `core/logging.py` 指标记录、`integrations/_http_retry.py`、`core/extractors/`、`core/algorithms/knowledge_tree.py`；
   - 拆解 `DiagnosisService.generate_diagnosis_report` 及超复杂函数，下调 `pyproject.toml` `max-complexity` 至 `<= 15`（若个别 schema 双向兼容校验器需保留，针对性拆分为小函数使全仓 0 个 `C901` 违规）；
   - 跑通 `ruff format/check`、`mypy app`、`lint-imports`、全量 `pytest`。
3. **Step 1B（`fe-modular`，`XHigh`，`workspace: "share"`，与 1A 并行）**：
   - 按域拆分 `src/types/` 与 `src/api/`；
   - 抽取 `utils/poller.ts`、`utils/knowledgeTree.ts`、`utils/storageKeys.ts`、`styles/tokens.scss`、`styles/modal.scss`；
   - 拆解 6 个 >300 行 `.vue` 文件至全部 `<= 300` 行，补齐 `safe-area-inset-bottom`、`retake_required` 样式并移除 Emoji；
   - 跑通 `pnpm run lint`、`pnpm run type-check`、`pnpm run test:unit` 及行数核验脚本。
4. **Step 2（`verifier-m3`，`XHigh`）**：核验所有硬性指标后唤醒 `@coordinator`。
5. **Step 3（Coordinator）**：合入主工作区并固定 `refs/swarm-opt/m3-base`，推进 `M4`。
