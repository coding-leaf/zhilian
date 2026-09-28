# Python 3.12 回退兼容性研究

## 用户决策与当前状态
用户明确要求尝试将正式 backend/.venv 回退到 3.12；当前处于规划阶段，尚未切换正式环境，也未修改任何业务代码。

## 已核实事实
- 正式环境：backend/.venv，Python 3.13.14。
- 已安装解释器：CPython 3.12.13，uv python find 3.12 可解析。
- backend/pyproject.toml requires-python >=3.12；Ruff target-version py312；mypy python_version 3.12；未跟踪的 backend/pyrightconfig.json 声明 3.12。
- 项目没有 backend/.python-version。uv --verbose 显示默认 3.13 来自用户级 C:/Users/15262/AppData/Roaming/uv/.python-version，而非项目要求。不可为本项目更改全局默认；正式切换需项目级版本钉住，避免 uv 将环境切回 3.13。
- 已有 AGENTS.md 的用户未提交增量里写着 runtime Python 3.13；实施时仅对这一行作精确版本同步，保留其他内容。

## 隔离实验
路径：.trellis/.runtime/python312-probe（git check-ignore 确认为忽略路径）。
通过 UV_PROJECT_ENVIRONMENT 指向此目录，并执行 uv sync --locked --python 3.12 --extra dev。
结果：成功安装 109 包，uv.lock 字节完全未变；原 backend/.venv 未修改。
随后 uv run --no-sync 实际运行 3.12.13（打印 sys.version 确认），应用 app.main 导入成功。
注意：未指定 --python 的 uv run 会警告用户全局 3.13 请求不匹配；--no-sync 保留了已验证的 3.12 环境。后续命令显式 --python 3.12，以消除歧义。

## 静态检查结果
- ruff format --check .：通过，238 文件。
- ruff check .：失败，仅前次审查已有两项：app/schemas/practice.py:134 SIM102；tests/unit/services/test_question_service.py:1423 I001。不是回退造成。
- mypy app：通过，130 源文件。
- lint-imports：通过，5 个契约 kept。
- 原始记录：python312-static-checks.json。
- 后端 tests/unit 在 180 秒上限内未完成：停在 tests/unit/cli/test_doctor.py:104 的真实 localhost PostgreSQL 探测（app/cli/context.py:310），faulthandler 栈已记录于 python312-unit-tests.txt。已清理本轮探针测试进程；不能算测试通过，也不能归因为 Python 3.12 不兼容。另行运行 tests/unit/services 做 J1 服务层兼容性验证，不替代完整门禁。

## 建议实施方案（待最终规划批准）
1. 保留原 3.13 环境，核实无服务或测试占用后再操作。
2. 对原 .venv 与备份目标解析绝对路径，验证都位于明确的本项目目录后，使用 PowerShell Move-Item -LiteralPath 移至唯一备份位置；不删除旧环境。
3. 增加 backend/.python-version=3.12，保留 requires-python >=3.12 与 lock 内容不动；不更改用户全局 pin。
4. 在正式 backend/.venv 原位置重新 uv sync --locked --python 3.12 --extra dev；不能直接移动探针环境充当正式环境（脚本可能嵌入旧绝对路径）。
5. 验证 uv run python -V、应用导入、LSP 解释器指向、完整后端及前端门禁与小程序构建。
6. 失败则保留失败现场，经过路径校验将原环境移回原位置并还原本任务的项目 pin 变更；不要恢复或覆盖其他人的修改。

## 风险
正式环境迁移会影响依赖该路径的运行进程；切换时需主动检查。用户级 3.13 pin 不应被更改。已有 Ruff 失败需作为显式的小范围质量修复纳入计划。

## 服务层验证补充
显式 uv run --no-sync --python 3.12 pytest tests/unit/services：235 passed in 7.19s，无 stderr 警告。记录见 python312-service-tests.txt。此结果支持运行时兼容，不表示完整门禁已通过。
