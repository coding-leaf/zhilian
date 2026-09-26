# Design: Headless CLI 与真实链路闭环验证

## 1. 架构定位与边界 (Architectural Boundaries)

### 1.1 新增模块
新增独立包 `app/cli/`（入口 `python -m app.cli`），作为**可执行适配层**：

```
app/
├── cli/
│   ├── __init__.py
│   ├── __main__.py        # 入口：raise SystemExit(main())
│   ├── main.py            # argparse 全局装配与子命令分发 (<300 行)
│   ├── context.py         # CliContext：settings/container/provider 预检/脱敏
│   ├── errors.py          # CliError + 退出码常量
│   ├── report.py          # 结构化 JSON 输出与阶段记录
│   ├── fixtures.py        # 样例资料生成/定位（txt 生成、docx 真实 zip 生成）
│   ├── smoke.py           # 全链路编排与断言
│   └── commands/
│       ├── __init__.py
│       ├── doctor.py      # 配置体检
│       ├── db.py          # 迁移升级 / 受保护重置
│       ├── auth.py        # 登录 / 画像
│       ├── material.py    # 上传 / 解析 / 状态 / 知识树
│       ├── question.py    # 出题 / 列表
│       ├── practice.py    # 建练习 / 作答 / 交卷
│       └── grading.py     # 判分 / 诊断报告
```

### 1.2 是否违反 import-linter 契约
- 契约 `五层单向架构依赖契约` 仅约束 `[app.api, app.services, app.repositories]`，`app.cli` 不在其中，不冲突。
- 契约 `核心基础模块禁止反向依赖上层业务` 只约束 `app.core`；`app.cli` 可导入 `app.services` / `app.container` / `app.models` / `app.core`。
- **约束**：`app.cli` 必须通过 `AppContainer` 工厂拿到服务，禁止绕过容器自行 `new` 引擎或拼装 Provider；`app.cli` 不得被任何上层（api/services/repositories/integrations/core）反向导入。

---

## 2. 执行引擎决策 (Execution Engine)

**决策：服务直驱（in-process service-driven）为默认引擎；HTTP 模式列为后续可选。**

- 理由：
  1. 真实重链路（解析流水线、知识抽取、出题、判分）耗时可达分钟级且需逐阶段状态与错误归因，直驱可同步执行并精确捕获 `failed_stage`。
  2. 现有 `tests/integration/test_p0_full_chain_e2e.py` 已用 ASGITransport + fake 覆盖路由层；CLI 的价值增量在“真实 Provider + 全链路断言”，而非重复路由测试。
  3. 避免引入 uvicorn 进程、端口、worker 消费队列等复杂度。
- 约束：直驱必须复用生产同款装配（`AppContainer.create()` → `create_*_service(session)`），且解析必须走 `parse_material_pipeline`，不得绕过业务逻辑。

---

## 3. 命令契约 (Command Surface & Contracts)

### 3.1 全局参数
`python -m app.cli <command> [subcommand] [options]`
- `--json`：结构化输出（供 AI 解析）
- `--db-url <url>`：覆盖数据库（默认取 settings）
- `--allow-fake`：仅用于 pytest 离线自测；允许 fake provider（`smoke`/`doctor` 真实链路模式下默认禁用）
- `--log-level <level>`

### 3.2 退出码 (Exit Codes)
| 码 | 含义 | 触发场景 |
|---|---|---|
| 0 | 成功 | 命令与断言全部通过 |
| 1 | 运行时错误 | 未预期异常 |
| 2 | 断言失败 | smoke 某阶段断言不成立 |
| 3 | 配置缺失/非真实 Provider | embedding/search=fake、storage=memory、db=sqlite、key 未配 |
| 4 | 基础设施不可达 | DB/Redis/MinIO 端口或鉴权失败 |

### 3.3 子命令
- `doctor [--require-real]`：Provider 矩阵 + 连通性 + 迁移版本。
- `db upgrade` / `db reset --yes`：Alembic 升级（`alembic.config` + `command.upgrade`）；reset 为破坏性，需 `--yes`。
- `auth login --code <c> [--nickname <n>]` / `auth profile --user-id <id>`。
- `material upload --file <path> [--title] [--user-id]`。
- `material parse --material-id <id> [--version-id] [--user-id]`（同步执行流水线）。
- `material status --material-id <id>` / `material tree --material-id <id> [--version-id]`。
- `question generate --material-id <id> --knowledge-point-id <id> [--count] [--types]`。
- `practice create --user-id <id> --question-ids <csv>` / `practice submit --practice-id <id> [--answers <json>]`。
- `grading grade --practice-id <id>` / `diagnosis report --practice-id <id>`。
- `smoke [--file <path>] [--image <path>] [--keep]`：全链路闭环。

---

## 4. 真实链路校验与配置即停 (Real-Provider Gate)

`context.py` 提供 `assert_real_providers(settings) -> list[Gap]`：
- 校验项：`llm.provider != fake`、`ocr.provider != fake`、`embedding.provider != fake`、`search.provider != fake`、`storage.provider != memory`、`db_url` 非 sqlite。
- `ocr` 仅在 smoke 含图片/O CR 阶段时强制（文本文档 smoke 不强制 OCR）。
- 发现缺口：收集为结构化 `Gap(code, env_key, expected, actual)`，由命令层以退出码 `3` 中止并打印修复指引（键名 + 期望形态），**不执行任何业务**。
- `doctor` 始终打印矩阵；`--require-real` 决定是否以退出码 3 失败。

脱敏：所有 `SecretStr` 仅输出 `configured: true/false`，禁止 `get_secret_value()` 落入输出。

---

## 5. Smoke 编排 (Closed-Loop Scenario)

每阶段包 `report.stage(name)`，记录 `status/elapsed/ids/error`。执行序列（直驱服务）：

1. `preflight`：`assert_real_providers` + DB/Redis/MinIO 连通 + 迁移版本校验。
2. `login`：`auth.login_with_wechat(code=f"cli-smoke-{run_id}")` → `user_id`（独立命名空间，保证可重复）。
3. `import`：读取 `--file`（默认生成的中文 txt fixture）→ `material.import_material_file(...)` → `material_id/version_id`，断言 `status in {pending, parsing}`。
4. `parse`：`material.parse_material_pipeline(material_id, version_id, user_id)` → 断言终态 `READY`；失败则将 `failed_stage`+`error_message` 归因输出（退出码 2）。
5. `snippets`：断言该版本切片数 > 0 且 embedding 非空。
6. `tree`：`knowledge.get_knowledge_tree(...)` → 断言节点数 > 0，取首个叶子/根 `knowledge_point_id`。
7. `questions`：`question.generate_questions(user_id, material_id, version_id, knowledge_point_id, options)` → 断言生成题数 > 0。
8. `practice`：`practice.create_practice(user_id, CreatePracticeOptions(...))` → `save_answer` 作答 → `submit_practice`。
9. `grading`：`grading.grade_practice_submission(practice_id, user_id)` → 断言判分结果存在。
10. `report`：`diagnosis.generate_diagnosis_report(user_id, practice_id)` → 断言报告存在。
11. `summary`：输出 JSON 汇总；全绿退出码 0，否则 2。

`--keep` 保留数据；默认 smoke 保留（便于复查），重置靠 `db reset`。

---

## 6. 资料解析缺陷修复 (DOCX/PPTX 文本抽取)

**问题**：`extract_text_from_raw_content` 对 `docx`/`pptx` 使用 `content.decode("utf-8", errors="ignore")`，真实文件为 ZIP 容器 → 抽取为乱码/空 → 流水线必然失败。

**方案（不新增生产依赖，使用标准库 `zipfile` + `xml.etree.ElementTree`）**：
- DOCX：读取 `word/document.xml`，抽取所有 `w:t` 文本节点，按 `w:p` 段落聚合。
- PPTX：读取 `ppt/slides/slide*.xml`，抽取 `a:t` 文本节点（按 slide 序号排序）。
- 抽取失败（非 zip/缺关键成员）→ 抛出 `MaterialInvalidError`（明确的“文档损坏或格式不支持”）。
- 保持 `txt/md`、`pdf`、图片分支不变。
- 新增纯函数 helper（放 `app/services/material.py` 内或 `app/core/algorithms`，视纯度而定），并补充单测：真实 DOCX 二进制 → 期望段落文本。

---

## 7. 样例资料 fixture

- 主 fixture：`fixtures.py` 生成的中文技术讲义 TXT（数百字、含章节结构），保证足够切片与考点抽取。
- DOCX fixture：运行时用 `zipfile` 构造**真实**最小 DOCX（`[Content_Types].xml` / `_rels/.rels` / `word/document.xml`），用于验证修复后的 DOCX 解析。
- OCR leg：`smoke --image <path>` 可选；用户提供真实含字图片时执行 OCR 子链路（`import → parse` 走 OCR 分支）。未提供时跳过并在 JSON 标注 `skipped`。

---

## 8. 容错与回退 (Rollout & Resilience)

- **不静默降级**：任何 fake/memory 回落都视为配置错误（退出码 3），除非显式 `--allow-fake`（仅测试）。
- **可重复**：run_id 隔离用户与资料。
- **变更可控**：CLI 为纯新增包 + 一处解析缺陷修复，不改动既有 API/DB 契约，回滚只需删除 `app/cli/` 与单点回退解析函数。
- **分阶段评审**：本任务虽为多交付，但按 `implement.md` 分为「骨架+doctor」「业务子命令」「smoke」三段，每段完成后暂停评审，符合“切勿一次派发过多任务”。
