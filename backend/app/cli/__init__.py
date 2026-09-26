"""智练 Headless CLI 可执行适配层包。

入口：`python -m app.cli <command> [subcommand] [options]`（工作目录 backend/）。

该包严格遵循 AGENTS.md 规范：
- 仅作为可执行适配层，通过 AppContainer 工厂获取领域服务；
- 不得被 app.api / app.services / app.repositories / app.integrations / app.core 反向导入；
- 默认强制真实 Provider 链路，检测到 fake/memory 回落时以专属退出码立即中止。
"""

__all__: list[str] = []
