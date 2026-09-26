# PRD: Headless CLI 与真实链路闭环功能验证

## 1. 背景与问题 (Context)

平台已具备完整的后端分层架构与 1090 项单测，但**缺少一条可被 AI/开发者独立驱动、并对真实功能做端到端断言的“闭环验证通道”**，导致：

1. **功能是否真正可用无法自证**：单测大量使用 Fake LLM / Fake OCR / 内存 SQLite / 内存存储。测试全绿 ≠ 真实链路可用。实机上一个环节断掉（如鉴权、上传、解析、出题）就会让用户“第一步就卡死”。
2. **无法定位“卡在哪一环”**：没有统一的、可脚本化的执行入口，AI 只能靠 mock 单测推断，无法复现真实故障。
3. **已发现的真实缺陷样例（本任务要暴露并修复的对象）**：
   - `app/services/material.py::extract_text_from_raw_content` 对 `docx`/`pptx` 仅执行 `content.decode("utf-8", errors="ignore")`，而真实 DOCX/PPTX 是 ZIP 容器，必然解析失败 → 文档类资料无法闭环。
   - 前端/路由/服务三层的状态语义此前不一致（`all` 标签空列表等），靠 mock 单测长期未被发现。

因此需要一个 **headless CLI**：把领域能力抽成命令，AI 通过调用 CLI 即可驱动**真实 Provider 链路**（真实 LLM/OCR/Embedding/Search/DB/Storage）并断言闭环结果；一旦因**配置缺失**导致无法真实运行，必须**立即停下并报告缺失项**，禁止静默回落到 fake。

---

## 2. 目标与非目标 (Goals & Non-goals)

### 2.1 目标 (Goals)
1. **提供 headless CLI 入口** `python -m app.cli`，覆盖核心业务链路的可脚本化命令：配置体检、数据库迁移、鉴权、资料上传/解析/状态/知识树、出题、练习/交卷、判分、报告。
2. **强制真实链路**：CLI 默认要求真实 Provider；`doctor`/`smoke` 在检测到 `fake`/`memory` 回落时，以**专属退出码 + 明确修复指引**中止，绝不静默 mock。
3. **端到端 smoke 闭环**：一条命令跑通 `登录 → 上传 → 解析 → 知识树 → 出题 → 练习作答 → 交卷判分 → 诊断报告`，逐阶段断言并输出结构化 JSON，失败时**精确指出失败阶段与原始错误**。
4. **可重复、可隔离**：每次 smoke 使用独立用户命名空间，可重复执行；提供受保护的重置命令。
5. **离线自测**：CLI 自身逻辑必须能用 SQLite + Fake Provider 在 pytest 中离线验证（不联网）。
6. **暴露并驱动修复**：以 smoke 结果为证据，修复真实链路中的功能缺陷（本任务至少覆盖文档格式解析缺陷）。

### 2.2 非目标 (Non-goals)
- 不替代既有 HTTP API 契约；不修改对外 RESTful 路由响应结构。
- 不重构五大分层架构，不破坏既有 import-linter 契约。
- 不引入重型 CLI 框架（优先标准库 `argparse`），不新增生产运行时依赖。
- 前端小程序不纳入本任务闭环范围（后续可另立任务）。

---

## 3. 约束 (Constraints)

- **真实链路硬约束**：CLI 的 `smoke` 与 `doctor --require-real` 必须校验真实 Provider（LLM/OCR/Embedding/Search/Storage/DB）。检测到回落必须**停下报告**，列出缺失的环境变量键名与期望值形态；由用户配置后再继续。
- **配置问题即停**：任何因缺失/错误配置引发的失败，必须归因并明确报告，不得自动降级、不得伪造成功。
- **绝对禁止泄漏密钥**：CLI 输出必须对 `SecretStr` 全量脱敏，仅显示“是否已配置”。
- **架构合规**：必须通过 `ruff` / `ruff format` / `mypy` / `lint-imports`（5 契约）/ `pytest`。
- **无外部网络污染的测试**：pytest 内建网络阻断必须保持生效；CLI 离线测试只能使用 sqlite + fake provider。

---

## 4. 验收标准 (Acceptance Criteria)

### AC1: 配置体检命令
- `python -m app.cli doctor --json` 输出结构化体检：Provider 矩阵（provider 名 + key 是否已配，**不含明文**）、DB/Redis/MinIO 连通性、DB 迁移版本。
- 当真实 Provider 缺失（embedding/search=fake 或 storage=memory 或 db=sqlite）时，`doctor --require-real` 以退出码 `3` 退出，并逐条列出缺失项与建议的 `.env` 键。

### AC2: 端到端 smoke 闭环
- `python -m app.cli smoke --file <资料文件> --json` 在真实 Provider 下跑通全链路，成功时退出码 `0`，输出包含每阶段状态、关键实体 ID（user/material/version/knowledge_point/question/practice/report）与耗时的 JSON。
- 任一阶段断言失败时退出码 `2`，且 JSON 中 `failed_stage` + `error` 精确指向失败环节。

### AC3: 真实链路不可用即刻停下
- 当 embedding/search/provider 未被真实配置时，`smoke` 在**开始执行业务前**以退出码 `3` 中止，输出缺失配置清单；不执行任何 mock 业务。
- 基础设施不可达（DB/Redis/MinIO 端口不通）时退出码 `4`，并指出不可达组件。

### AC4: 文档格式解析缺陷修复
- 真实 DOCX（ZIP 容器）资料可被正确抽取文本并完成解析闭环（修复 `extract_text_from_raw_content` 的 docx/pptx 处理；若判断 pptx 超出范围须在 PRD 评审中显式确认）。
- 增加对应单测（真实 DOCX 二进制 → 正确抽取）。

### AC5: 可重复与隔离
- 连续执行两次 `smoke` 均成功，互不污染（每次生成独立用户与资料）。
- 提供 `python -m app.cli db reset --yes`（破坏性命令需显式确认）用于清理。

### AC6: 工程门禁全绿 + 离线自测
- CLI 具备离线单测（sqlite + fake provider），且 `ruff` / `format` / `mypy` / `lint-imports`（5 kept）/ `pytest` 全绿。
- 规范沉淀：将 CLI 契约（退出码、真实链路校验、脱敏）写入 `.trellis/spec/backend/`。

---

## 5. 交付物 (Deliverables)

1. `backend/app/cli/` 命令包（`python -m app.cli` 可运行）。
2. `doctor`、`smoke` 及业务域子命令。
3. 真实链路样例资料 fixture（至少一份可用的中文文档）。
4. 文档格式解析缺陷修复 + 单测。
5. CLI 离线单测（sqlite + fake）。
6. 后端规范沉淀（CLI 契约章节）。
7. 一次真实链路 smoke 运行的成功证据（JSON）。
