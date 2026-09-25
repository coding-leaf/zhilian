#!/usr/bin/env python3
"""Architecture Layer Dependency Checker.

Scans Python files under the backend application root using AST to enforce
strict layered boundaries and unidirectional import rules defined in AGENTS.md.
"""

import argparse
import ast
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        reconfig_out = getattr(sys.stdout, "reconfigure", None)
        if callable(reconfig_out):
            reconfig_out(encoding="utf-8", errors="replace")
        reconfig_err = getattr(sys.stderr, "reconfigure", None)
        if callable(reconfig_err):
            reconfig_err(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 禁止在计算核中导入的外部重型库或上层模块
ALGORITHM_FORBIDDEN_MODULES: set[str] = {
    "fastapi",
    "sqlalchemy",
    "httpx",
    "requests",
    "redis",
    "boto3",
    "app.services",
    "app.repositories",
    "app.api",
}

# 各层禁用的导入规则集合
LAYER_RULES: dict[str, list[tuple[set[str], str]]] = {
    # 纯函数计算核禁令
    "app/core/algorithms": [
        (
            ALGORITHM_FORBIDDEN_MODULES,
            "纯函数计算核严禁导入 Web 框架、ORM/网络库或上层业务服务/仓储",
        ),
    ],
    # 路由层严禁跨层导入仓储
    "app/api": [
        (
            {"app.repositories"},
            "路由层严禁跨层导入仓储层 (app.repositories)",
        ),
    ],
    # 仓储层严禁导入路由与外部适配层
    "app/repositories": [
        (
            {"fastapi", "app.integrations"},
            "仓储层严禁导入 Web 框架 (fastapi) 或适配层 (app.integrations)",
        ),
    ],
    # 适配层严禁导入业务服务层
    "app/integrations": [
        (
            {"app.services"},
            "外部适配层严禁反向导入服务层 (app.services)",
        ),
    ],
    # 核心通用支持严禁导入上层业务模块
    "app/core": [
        (
            {"app.services", "app.repositories", "app.api"},
            "核心支持层严禁导入上层业务模块 (app.services / app.repositories / app.api)",
        ),
    ],
}


class ImportVisitor(ast.NodeVisitor):
    """AST visitor collecting all imported module names."""

    def __init__(self) -> None:
        self.imports: list[tuple[str, int]] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.append((alias.name, node.lineno))
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            self.imports.append((node.module, node.lineno))
            for alias in node.names:
                full_name = f"{node.module}.{alias.name}"
                self.imports.append((full_name, node.lineno))
        self.generic_visit(node)


def check_file(file_path: Path, app_root: Path) -> list[str]:
    """Check a single python file for layer violations."""
    try:
        content = file_path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(file_path))
    except (SyntaxError, OSError) as exc:  # pragma: no cover
        return [f"解析失败 {file_path}: {exc}"]

    visitor = ImportVisitor()
    visitor.visit(tree)

    relative_str = file_path.relative_to(app_root.parent).as_posix()
    violations: list[str] = []

    for layer_prefix, rules in LAYER_RULES.items():
        # 若是算法核，特殊优先匹配更深路径
        if layer_prefix == "app/core/algorithms" and not relative_str.startswith(
            layer_prefix
        ):
            continue
        if layer_prefix != "app/core/algorithms" and not relative_str.startswith(
            layer_prefix
        ):
            continue

        for forbidden_set, reason in rules:
            for imported_mod, lineno in visitor.imports:
                for forbidden in forbidden_set:
                    if imported_mod == forbidden or imported_mod.startswith(
                        f"{forbidden}."
                    ):
                        violations.append(
                            f"{file_path}:{lineno} 违规导入 '{imported_mod}' -> {reason}"
                        )

    return violations


def main() -> int:
    """CLI entrypoint for layer dependency checking."""
    parser = argparse.ArgumentParser(
        description="Check architectural layer boundaries."
    )
    parser.add_argument(
        "--root", default="backend/app", help="Path to application root"
    )
    args = parser.parse_args()

    root_path = Path(args.root).resolve()
    if not root_path.exists():
        print(f"❌ 路径不存在: {root_path}")
        return 1

    py_files = [f for f in root_path.rglob("*.py") if f.is_file()]
    all_violations: list[str] = []

    for py_file in py_files:
        violations = check_file(py_file, root_path)
        all_violations.extend(violations)

    if all_violations:
        print("❌ 发现分层架构导入违规:")
        for violation in all_violations:
            print(f"  - {violation}")
        return 1

    print(f"✅ 分层依赖检查通过: 扫描了 {len(py_files)} 个文件，0 违规导入。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
