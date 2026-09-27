# Error Handling

> 本项目后端的错误处理约定（以真实异常定义与处理器为准）。

> **事实源**：`backend/app/core/errors.py`、`backend/app/main.py`、`backend/app/api/v1/*.py`、`backend/app/cli/errors.py`、`backend/app/cli/main.py`
> **最后核对**：2026-09-28 @ ca062a1
> **核对方式**：`rg "class .*Error|exception_handler|status_code=" backend/app/core/errors.py backend/app/main.py backend/app/cli/errors.py`

---

## Overview

- 业务错误统一继承 `AppError`（`app/core/errors.py`），携带：5 位 `error_code`、面向用户的 `message`、`status_code`、结构化 `details`。
- FastAPI 层由全局异常处理器把 `AppError` 翻译为统一 JSON 响应；请求体校验失败由 `RequestValidationError` 处理器翻译。
- CLI 层使用独立的 `CliError`（`app/cli/errors.py`），携带进程退出码与修复建议。
- 禁止用裸 `except Exception: pass` 吞错；降级路径必须记录告警并显式声明语义（如 `pending_regrade`）。

代码锚点：`backend/app/core/errors.py::AppError`、`backend/app/main.py::app_error_handler`、`backend/app/cli/errors.py::CliError`。

---

## Error Types

`AppError` 体系按 5 位错误码分域（`app/core/errors.py` 模块 docstring）：

| 前缀 | 域 | 代表异常 |
|---|---|---|
| 10xxx | 参数校验/请求格式 | `RequestValidationError` → `code=10001` |
| 20xxx | 鉴权/权限 | `AuthenticationError`(20001/401)、`PermissionDeniedError`(20002/403) |
| 30xxx | 外部能力/网络 | `StorageError`(30001)、`OCRError`(30004)、`EmbeddingError`(30007)、`SearchError`(30010)、`LLMError`(30011)、`LLMResponseFormatError`(30014)、`QueueError`(30015)、`IdempotencyConflictError`(30017/409) |
| 40xxx | 算法/质量门禁 | `MaterialInvalidError`(40001/400)、`ReshootLimitExceededError`(40002)、`MaterialParseError`(40003/500)、`MaterialNotFoundError`(40004/404)、`KnowledgePointQualityError`(40005)、`KnowledgeNotFoundError`(40007/404)、`MissingSourceSnippetError`(40003/400)、`QuestionQualityCheckError`(40008)、`QuestionNotFoundError`(40009/404)、`PracticeNotFoundError`(40010/404)、`PracticeStatusError`(40011/400)、`PracticeEmptyQuestionsError`(40012/400)、`GradingNotAllowedError`(40014/400)、`PracticeNotGradedError`(40016/400)、`WrongRecordNotFoundError`(40019/404)、`FolderNotFoundError`(40020/404)、`FolderNameConflictError`(40021/409) |
| 50xxx | 内部/数据库 | 通用 `AppError` 默认 `40000/400` |

`AppError.to_dict()` 输出 `{"code", "message", "details"}`；`code` / `detail` 为兼容别名属性。
`AuthenticationError` 额外约定 `details={"reason": ...}`（如 `token_expired` / `token_invalid` / `missing_sub` / `missing_token_version`）。

代码锚点：`backend/app/core/errors.py::AppError.to_dict`、`backend/app/core/errors.py::AuthenticationError`、`backend/app/core/errors.py::MaterialInvalidError`、`backend/app/core/errors.py::FolderNameConflictError`。

---

## Error Handling Patterns

- **抛出点**：Service 层校验失败即抛对应 `AppError` 子类，不做「静默跳过 / 部分成功降级」；多步骤编排 fail-fast，任一子步骤异常立即 `rollback()` 并 re-raise。
- **捕获点**：仅在需要降级语义时 `except` 具体异常并记录告警，例如 LLM 判分异常降级为 `pending_regrade`（`item.score = None`），或惰性清理失败仅 `rollback()` 不阻断只读查询。
- **事务**：`except` 后应先 `self.session.rollback()` 再抛出或降级，避免脏会话。
- **并发冲突**：报告生成 `IntegrityError` 需 `rollback()` 后回查既有记录并幂等返回，不得上升为未处理 500。
- **参数兼容**：兼容旧客户端的入参（如删除原因 body 兜底）应集中在一处解析，禁止散落。

代码锚点：`backend/app/services/grading.py`（LLM 异常降级）、`backend/app/services/diagnosis.py`（`IntegrityError` 回滚回查）、`backend/app/services/folder.py::FolderService._purge_expired`（失败仅回滚不阻断）。

---

## API Error Responses

- **业务异常**：`app_error_handler` 返回 `status_code=exc.status_code`，body 为 `{"code": exc.error_code, "message": exc.message, "details": exc.details}`。
- **请求校验失败**：`validation_error_handler` 固定返回 HTTP 422，body 为 `{"code": 10001, "message": "请求参数校验失败", "details": exc.errors()}`。
- **健康检查降级**：`GET /health` 在数据库不可达时返回 HTTP 503 + 结构化诊断。
- 路由层不自行构造错误 JSON，一律通过抛出 `AppError` 子类让全局处理器统一输出。

代码锚点：`backend/app/main.py::app_error_handler`、`backend/app/main.py::validation_error_handler`、`backend/app/main.py::health_check`。

---

## CLI Exit Codes

`backend/app/cli/errors.py` 定义退出码契约，`backend/app/cli/main.py::main` 负责把异常映射为退出码：

| 常量 | 值 | 含义 |
|---|---|---|
| `EXIT_OK` | 0 | 成功 |
| `EXIT_RUNTIME` | 1 | 未预期运行时错误（`LOGGER.exception` 后返回） |
| `EXIT_ASSERTION` | 2 | smoke 阶段断言失败（含 `failed_stage`/原始 `error`） |
| `EXIT_CONFIG` | 3 | 配置缺失或非真实 Provider |
| `EXIT_INFRA` | 4 | 基础设施不可达 |

- 可预期错误抛 `CliError(exit_code=..., remediation=...)`，由 `_report_cli_error` 输出并返回其 `exit_code`。
- `KeyboardInterrupt` → 告警并返回 `EXIT_RUNTIME`。
- 输出必须脱敏：DB URL 经 `redact_url` 脱敏为 `***`，token 只输出布尔，不含密钥明文。

代码锚点：`backend/app/cli/errors.py::CliError`、`backend/app/cli/main.py::_report_cli_error`、`backend/app/cli/main.py::main`、`backend/app/cli/report.py::redact_url`。

---

## Common Mistakes

- 直接把 `Exception` 转成 500 而不区分业务错误码，导致前端无法按码分支。
- 在路由层 `try/except` 后自行 `JSONResponse`，绕过全局处理器造成结构不一致。
- 降级路径忘记 `rollback()`，脏会话污染同请求后续查询。
- 把待重判写成 `score=0.0`，与「真实判错 0 分」不可区分（应写 `score=None` 并由 `grading_status` 表达）。
- CLI 输出回显密钥/token 明文，或因配置缺口静默回落 fake Provider。

代码锚点：`backend/tests/unit/core/test_errors.py`、`backend/app/schemas/practice.py::PracticeItemDetailResponse.synchronize_item_fields`、`backend/app/cli/context.py::CliContext.assert_real_providers`。
