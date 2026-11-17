# Implementation Plan — M4: 失真文档与规范对齐及测试加固

## 1. Execution Steps

1. 基于 `refs/swarm-opt/m3-base` 激活 `11-17-m4-docs-specs-and-test-hardening`。
2. `docs-and-tests`（`High`，`share`）完成 `docs/DESIGN.md`、`README.md`、`docs/后续待解决问题.md`、`docs/legacy_sdlc/README.md` 更新，新增 `reportView.spec.ts` 与测试类型检查配置，修复 `test_storage.py` 脆弱计时测试，跑通前后端门禁。
3. `verifier-m4`（`High`）核验所有文档路径/数字真实性与测试门禁。
4. 主会话合入变更、刷新 `.trellis/spec/{backend,frontend}/*.md`、清理全部 `refs/swarm-opt/*` 临时引用、执行最终全仓 `task verify`，并向用户提交 Phase 3.4 分批提交方案。
