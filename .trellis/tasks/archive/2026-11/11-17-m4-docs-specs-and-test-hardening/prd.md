# M4: 失真文档与规范对齐及测试加固

## Goal

在 `M3` 前后端新模块结构稳定后，对齐重写 `docs/DESIGN.md`、`README.md`、`docs/后续待解决问题.md` 与 `.trellis/spec/{backend,frontend}/*.md` 事实源，补齐前端核心视图辅助与 Store 单测并纳入类型检查，同时治理测试中的并发调度抖动点，完成全仓重构的最终收口验证。

## Background & Verified Evidence

依据父任务 `research/02`、`03`、`04` 核实：
- **文档与规范失真（`04`）**：
  - `docs/DESIGN.md` 仍规定已卸载的 Wot Design Uni 蓝白风与不存在的组件/存储键，与 `App.vue` 温润学术纸质阅读风完全背离；
  - `README.md` 页面数（写 18 实为 8）、技术栈（仍列 Wot Design Uni）、迁移数、测试数与真实仓库不符；
  - `docs/后续待解决问题.md` 未核销已落地的 `P1-4`、`P1-9` 等修复项；
  - `.trellis/spec/{backend,frontend}/*.md` 仍停留在 `2026-09-29`，未反映 Python 3.13、`M2`/`M3` 新模块结构及修正后的跨层契约。
- **前端测试与类型盲区（`03`）**：
  - `miniprogram/src/subpackages/report/utils/reportView.ts` 覆盖率为 `0%`；`reviewView.ts`、`materialStore`、`folderStore` 存在关键分支缺口；
  - `miniprogram/tsconfig.json` 仅包含 `src/**`，导致 `vue-tsc` 从不检查 `miniprogram/tests/**`。
- **后端并发墙钟敏感测试（`02`）**：
  - `backend/tests/unit/integrations/storage/test_storage.py:302-313` 对零延迟操作断言 `< 0.04s`，在 Windows 全套并发跑测时易受调度器抖动影响；`AGENTS.md` 明确规定不得放宽 `tests/unit/core/algorithms/` 既有业务性能阈值，但可确保 `test_storage.py` 用确定性时钟断言避免假阳性。

## Requirements

- **R1 — 顶层项目文档重写对齐（Track `docs-and-tests`，`High`）**：
  - 重写 `docs/DESIGN.md`，以 `App.vue` 温润学术纸质色盘、自定义 `.vue` 组件体系、`src/styles/` Token 与真实存储键（`storageKeys.ts`）为唯一设计事实源；
  - 更新 `README.md` 技术栈、目录结构、页面路由表、测试与迁移规模说明；
  - 更新 `docs/后续待解决问题.md` 标记已解决条目，并在 `docs/legacy_sdlc/README.md`（新建简短说明）标注历史归档边界。
- **R2 — 前端核心单测补强与测试类型覆盖（Track `docs-and-tests`，`High`）**：
  - 新增 `miniprogram/tests/reportView.spec.ts` 覆盖 `reportView.ts` 核心纯函数，补充 `reviewView` / Store 关键分支测试；
  - 将 `tests/**/*.ts` 纳入前端 TypeScript 检查（通过更新 `tsconfig.json` 或新增 `tsconfig.test.json` 串联入 `type-check` 脚本）并清零类型错误。
- **R3 — 后端 `test_storage.py` 调度抖动治理（Track `docs-and-tests`，`High`）**：
  - 修正 `backend/tests/unit/integrations/storage/test_storage.py:302-313` 的脆弱墙钟差值断言（验证 `simulated_latency_ms` 注入调用行为而非赌 Windows 线程调度 `< 40ms`；**严格遵循 `AGENTS.md` 不放宽 `tests/unit/core/algorithms/` 下的既有阈值断言**）。
- **R4 — `.trellis/spec/**` 全面刷新（Main Session）**：
  - 由主会话对照 `M3` 落盘后的真实文件树更新 `.trellis/spec/backend/*.md` 与 `.trellis/spec/frontend/*.md`（含 `index.md`、`directory-structure.md`、`api-payload-contracts.md`、`component-guidelines.md`、`quality-guidelines.md` 等）并将核对日期更新至 `2026-11-17`。

## Acceptance Criteria

- [ ] **AC1**：`docs/DESIGN.md` 与 `README.md` 零 `wot-design-uni` 残留，指标与模块路径与真实代码一致。
- [ ] **AC2**：`reportView.ts` 具备高覆盖 Vitest 单测，`miniprogram/tests/**` 纳入 `pnpm run type-check` 且零报错。
- [ ] **AC3**：`.trellis/spec/{backend,frontend,guides}/*.md` 与重构后的真实文件树和契约对齐。
- [ ] **AC4**：宿主 Windows `pwsh` 下全量 `task verify` 全绿通过。
