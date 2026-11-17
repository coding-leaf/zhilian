# Technical Design — M4: 失真文档与规范对齐及测试加固

## 1. Track Division (`Swarm` Worker + Main Session `.trellis/spec/**`)

- **`docs-and-tests`（`workspace: "share"`，`model: "gemini-4-hydrogen-high"`）**：修改非 `.trellis/**` 路径（`docs/**`、`README.md`、`miniprogram/tests/**`、`miniprogram/tsconfig*.json`、`miniprogram/package.json` `type-check` 脚本、`backend/tests/unit/integrations/storage/test_storage.py`）。严守 `AGENTS.md` 红线：**绝不放宽 `tests/unit/core/algorithms/` 阈值**，**绝不触碰 `.trellis/**`**。
- **`verifier-m4`（`workspace: "inherit"`，`model: "gemini-4-hydrogen-high"`）**：核查文档事实准确性（grep 验证路径/命令/计数）、`tests/**` 类型检查与全套单测。
- **Main Session Coordinator**：在合并 `docs-and-tests` 后，统一刷新 `.trellis/spec/{backend,frontend}/*.md`（因 `.trellis/**` 归主会话专管），执行最终全仓 `task verify`。
