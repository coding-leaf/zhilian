# Implement Plan: Headless CLI 与真实链路闭环验证

> 执行原则：按 Stage 推进，**每个 Stage 完成后暂停评审**再进入下一阶段（“切勿一次派发过多任务”）。
> 所有后端命令在 `backend/` 下用 `uv run` 执行。禁止 Git Commit（由主会话在收尾阶段统一提交）。

## Stage 0：准备（当前）
- [ ] 用户完成真实 Provider 配置：`ZHILIAN_EMBEDDING__PROVIDER` 及其 base/key/model/dimension(1024)、`ZHILIAN_SEARCH__PROVIDER=pgvector`。
- [ ] 运行 `python -m app.cli doctor` 的**前置替代检查**：`uv run python -c` 打印 provider 矩阵确认非 fake（Stage 1 会产品化）。
- 退出条件：embedding/search 非 fake；DB/Redis/MinIO 连通；DB 迁移为 head。

---

## Stage 1：CLI 骨架 + `doctor`（评审门 A）
- [ ] 新建 `app/cli/` 包：`__init__.py` / `__main__.py` / `main.py` / `context.py` / `errors.py` / `report.py`。
- [ ] `errors.py`：`CliError` 与退出码常量（0/1/2/3/4）。
- [ ] `context.py`：`CliContext`（`--db-url` 覆盖、`AppContainer.create`、`assert_real_providers`、连通性探测、SecretStr 脱敏）。
- [ ] `commands/doctor.py`：Provider 矩阵 + DB/Redis/MinIO 连通 + 迁移版本；`--require-real` 失败退出码 3。
- [ ] `commands/db.py`：`db upgrade`（Alembic API）、`db reset --yes`（破坏性）。
- [ ] 离线单测：`tests/unit/cli/test_doctor.py`（sqlite+fake，`--allow-fake`），断言退出码与脱敏。
- 验证：`uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run lint-imports && uv run pytest tests`
- **评审门 A**：人工确认命令形态、退出码、脱敏输出后再继续。

---

## Stage 2：业务域子命令（评审门 B）
- [ ] `commands/auth.py`：`login` / `profile`。
- [ ] `commands/material.py`：`upload` / `parse`（同步 `parse_material_pipeline`）/ `status` / `tree`。
- [ ] `commands/question.py`：`generate` / `list`。
- [ ] `commands/practice.py`：`create` / `answer`（可选）/ `submit`。
- [ ] `commands/grading.py`：`grade` / `diagnosis report`。
- [ ] `fixtures.py`：中文 TXT 生成 + 真实最小 DOCX（zipfile）生成。
- [ ] 修复 `extract_text_from_raw_content` 的 `docx`/`pptx`（zipfile + ElementTree），失败抛 `MaterialInvalidError`。
- [ ] 单测：
  - `tests/unit/services/` 新增 DOCX 抽取用例（真实 zip 二进制 → 期望段落）。
  - `tests/unit/cli/test_material_commands.py`（sqlite+fake 离线）。
- 验证：同 Stage 1 全量门禁 + `lint-imports` 5 kept。
- **评审门 B**：人工确认文档解析修复与子命令契约后再继续。

---

## Stage 3：`smoke` 全链路闭环 + 真实运行（评审门 C）
- [ ] `smoke.py`：按 design.md 第 5 节编排 11 阶段，逐阶段 `report.stage`。
- [ ] 断言：终态 `READY`、切片>0、知识树>0、题>0、判分存在、报告存在。
- [ ] 失败归因：`failed_stage` + 原始错误写入 JSON；退出码 2。
- [ ] 前置校验：真实 Provider 缺失退出码 3；基础设施不可达退出码 4；**业务执行前中止**。
- [ ] 离线单测：`tests/unit/cli/test_smoke_offline.py`（sqlite+fake，`--allow-fake`，断言编排与退出码，不联网）。
- [ ] **真实运行**：`uv run python -m app.cli smoke --json`，捕获 JSON 与失败阶段。
- [ ] 依据真实运行结果修复暴露的真实缺陷（若超出单点，先停下与用户确认拆分新任务）。
- 验证：全量门禁 + 至少一次真实 smoke 退出码 0（或显式配置缺口报告）。
- **评审门 C**：人工确认真实链路成功证据。

---

## Stage 4：规范沉淀与收尾（评审门 D）
- [ ] 更新 `.trellis/spec/backend/quality-guidelines.md`：新增「Headless CLI 契约」章节（退出码、真实链路校验、脱敏、直驱服务原则）。
- [ ] 全量门禁复核：`ruff` / `format` / `mypy` / `lint-imports`(5 kept) / `pytest`。
- [ ] 输出真实 smoke 成功 JSON 作为交付证据。
- **评审门 D** → 交主会话进入 Phase 3 收尾（spec/commit/wrap-up）。

---

## 验证命令（每个 Stage 必跑）
```bash
# 在 backend/ 下
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run lint-imports
uv run pytest tests

# staged 真实运行（Stage 3，需真实配置）
uv run python -m app.cli doctor --require-real --json
uv run python -m app.cli smoke --json
```

## 回滚点
- Stage 1/2/3 均为新增 `app/cli/` 与单点解析修复；回滚 = 删除 `app/cli/` 并回退 `extract_text_from_raw_content` 改动。
- `db reset` 为破坏性命令，仅在显式 `--yes` 下执行，不作为验证步骤默认动作。

## 风险
- 真实 LLM（`gemini-3.5-flash-lite` 经中转）对 Function Calling/结构化输出的支持可能不足 → Stage 3 会暴露；届时按“配置问题即停”报告。
- 真实 embedding 维度必须 1024，否则与 DB `Vector(1024)` 冲突 → `doctor` 前置校验。
- smoke 真实耗时可能数分钟 → 由分阶段日志与超时参数缓解。
