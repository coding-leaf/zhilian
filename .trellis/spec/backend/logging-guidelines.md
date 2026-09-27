# Logging Guidelines

> 本项目后端的日志约定（以真实 logging 用法与配置为准）。

> **事实源**：`backend/app/services/*.py`、`backend/app/core/config.py`、`backend/app/core/security.py`、`backend/app/cli/main.py`、`backend/app/api/v1/materials.py`、`backend/alembic.ini`
> **最后核对**：2026-09-28 @ ca062a1
> **核对方式**：`rg "logging|getLogger|logger\.|_log_metric|generate_user_ref" backend/app`

---

## Overview

- 使用 Python 标准库 `logging`，不引入第三方日志框架。
- 服务模块统一以 `logger = logging.getLogger(__name__)` 获取模块级 logger（如 `app/services/grading.py`、`app/services/diagnosis.py`、`app/services/auth.py`）。
- CLI 在 `backend/app/cli/main.py::_configure_logging` 通过 `logging.basicConfig(level=..., format="%(levelname)s %(name)s: %(message)s", force=True)` 配置根 logger，级别由 `--log-level` 控制（默认 `INFO`）。
- Alembic 迁移日志由 `backend/alembic.ini` 的 `[loggers]`/`[loggers_*]` 段配置。
- SQLAlchemy 原始 SQL 回显默认关闭，由 `DatabaseSettings.echo`（`ZHILIAN_DB__ECHO`）控制。

代码锚点：`backend/app/services/grading.py`（`logger = logging.getLogger(__name__)`）、`backend/app/cli/main.py::_configure_logging`、`backend/alembic.ini`、`backend/app/core/config.py::DatabaseSettings.echo`。

---

## Log Levels

- `DEBUG`：仅调试期临时使用，仓库中业务日志基本不落到该级别。
- `INFO`：正常业务里程碑与度量（登录成功、解析入队、判分阶段完成、清理触发等），对应 `error_code=0`。
- `WARNING`：可恢复降级（LLM 判题异常降级为 `pending_regrade`、搜索补齐失败、对象清理单键失败、惰性清理失败、开发默认密钥告警）。
- `ERROR`：失败的终态或不可恢复异常（后台解析失败、诊断执行错误）。
- `LOGGER.exception(...)`：CLI 顶层未预期异常，记录完整堆栈后返回 `EXIT_RUNTIME(1)`。

代码锚点：`backend/app/services/grading.py`（`logger.warning("单题判分算法异常，安全降级为待重判: ...")`）、`backend/app/api/v1/materials.py::run_material_pipeline_background`（`logger.error(...)`）、`backend/app/core/config.py::validate_secret_key`（`logger.warning`）、`backend/app/cli/main.py::main`（`LOGGER.exception`）。

---

## Structured Logging

- 业务日志携带结构化字段，写入 `extra=` 字典，约定包含（部分模块称为「8 要素」）：
  `timestamp`、`level`、`logger_name`、`request_id`、`user_ref`、`target_id`、`duration_ms`、`error_code`、`action`。
- 度量日志（`GradingService._log_metric`）把上述 payload 以 `json.dumps(..., ensure_ascii=False)` 序列化后输出，前缀 `METRIC`。
- `DiagnosisService` 与 `AuthService` 直接以 `logger.info(msg, extra={...})` 形式记录成功里程碑与耗时。
- 用户标识**必须**先经 `generate_user_ref(user_id)` 计算不可逆脱敏摘要（SHA-256 前 8 位十六进制）再入日志。
- 单请求 ID / 批次 ID 用于串联同一操作的多条日志（`request_id`、出题 `batch_id`）。

代码锚点：`backend/app/services/grading.py::GradingService._log_metric`、`backend/app/services/diagnosis.py`（`_log_metric` 的 8 要素 payload）、`backend/app/services/auth.py`（登录成功 `extra`）、`backend/app/core/security.py::generate_user_ref`。

---

## What to Log

- 关键状态跃迁与里程碑：微信登录成功、资料解析入队/就绪/失败、知识树构建、判分阶段完成、报告生成、惰性清理触发。
- 度量与耗时：`duration_ms`、处理条数、`error_code`。
- 降级事件：LLM 超时降级、检索补齐失败、幂等快照写入失败、单键对象清理失败。
- 失败上下文：`failed_stage`、终态错误码、脱敏后的异常摘要（如 `str(exc)[:200]`）。
- 关联标识：`request_id`、`target_id`、`batch_id`、`user_ref`。

代码锚点：`backend/app/services/material.py`（`"material pipeline retry scheduled"`、`"material pipeline ready"`）、`backend/app/services/grading.py`（`"LLM判题异常或超时降级为待重判: ..."`）、`backend/app/services/folder.py`（`"lazy purge of expired folder failed"`）。

---

## What NOT to Log

- **明文用户标识**：`user_id`、OpenID、手机号——只允许 `user_ref` 脱敏摘要（`generate_user_ref`）。
- **密钥与令牌**：JWT/API Key/Secret/DB 密码/Storage 凭据——CLI 输出 DB URL 须经 `redact_url` 脱敏，token 只输出 `has_*_token` 布尔。
- **题目与作答原文**：题干、选项、标准答案、`user_answer`、`last_wrong_answer`、切片全文、OCR 原文。
- **大对象/二进制**：文件字节、向量等。
- 模型的 `__repr__` 同样遵守脱敏红线（如 `WrongRecord.__repr__` 只输出长度与标记）。

代码锚点：`backend/app/core/security.py::generate_user_ref`、`backend/app/cli/report.py::redact_url`、`backend/app/models/practice.py::WrongRecord.__repr__`、`backend/app/services/grading.py::_log_metric`（docstring 明示脱敏红线）。
