"""分模块覆盖率阈值检查（《代码管理工作介绍 V1.0》§4.3）。

用法（在 backend/ 目录下执行）：

    uv run pytest tests --cov=app --cov-branch --cov-report=term-missing --cov-fail-under=80
    uv run coverage json -o coverage.json
    uv run python ../tooling/check_coverage.py --report coverage.json

阈值（唯一事实源，与文档 §4.3、概要设计 §7.3 同步维护）：

| 范围                        | 行覆盖 | 分支覆盖 |
| --------------------------- | -----: | -------: |
| 全局（backend/app）          |  ≥ 80% |    ≥ 70% |
| app/core/algorithms（算法核） |  ≥ 95% |    ≥ 90% |
| app/core/security.py        |  ≥ 95% |        — |
| app/services（服务层）        |  ≥ 85% |        — |

设计要点：
- 路径归一化：coverage.py 在 Windows 输出反斜杠路径，统一转 `/` 再匹配；
- 目录前缀以 `/` 结尾（如 `app/services/`），避免误匹配同名前缀文件；
- 任一规则不满足即输出明细并以非零状态退出，供流水线阻断。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Rule:
    """单条覆盖率阈值规则。

    Attributes:
        name: 规则展示名。
        prefix: 匹配前缀（文件全路径，或目录前缀以 `/` 结尾）。
        line: 行覆盖率下限（百分数）。
        branch: 分支覆盖率下限（百分数）；None 表示不检查分支。
    """

    name: str
    prefix: str
    line: float
    branch: float | None


RULES: tuple[Rule, ...] = (
    Rule("全局", "", 80.0, 70.0),
    Rule("算法核 app/core/algorithms", "app/core/algorithms/", 95.0, 90.0),
    Rule("安全模块 app/core/security.py", "app/core/security.py", 95.0, None),
    Rule("服务层 app/services", "app/services/", 85.0, None),
)


@dataclass
class Aggregate:
    """一组文件的覆盖率聚合值。"""

    statements: int = 0
    covered_statements: int = 0
    branches: int = 0
    covered_branches: int = 0
    files: int = 0

    @property
    def line_percent(self) -> float:
        if self.statements == 0:
            return 100.0
        return self.covered_statements / self.statements * 100.0

    @property
    def branch_percent(self) -> float:
        if self.branches == 0:
            return 100.0
        return self.covered_branches / self.branches * 100.0


def _normalized(path: str) -> str:
    """coverage 路径归一化：反斜杠转正斜杠。"""
    return path.replace("\\", "/")


def _matches(path: str, rule: Rule) -> bool:
    if not rule.prefix:
        return True
    if rule.prefix.endswith("/"):
        return path.startswith(rule.prefix)
    return path == rule.prefix


def load_report(report_path: Path) -> dict[str, dict[str, object]]:
    """读取 coverage.json 并返回 {归一化路径: summary}。"""
    data = json.loads(report_path.read_text(encoding="utf-8"))
    files: dict[str, dict[str, object]] = {}
    for raw_path, info in data.get("files", {}).items():
        summary = info.get("summary", {})
        files[_normalized(raw_path)] = summary
    return files


def aggregate(files: dict[str, dict[str, object]], rule: Rule) -> Aggregate:
    agg = Aggregate()
    for path, summary in files.items():
        if not _matches(path, rule):
            continue
        agg.files += 1
        agg.statements += int(summary.get("num_statements", 0))
        agg.covered_statements += int(summary.get("covered_lines", 0))
        agg.branches += int(summary.get("num_branches", 0))
        agg.covered_branches += int(summary.get("covered_branches", 0))
    return agg


def check(files: dict[str, dict[str, object]]) -> bool:
    """执行全部规则检查，输出明细，返回是否全部通过。"""
    all_passed = True
    print(f"{'规则':<34}{'文件数':>6}{'行覆盖':>10}{'分支覆盖':>12}  判定")
    print("-" * 78)
    for rule in RULES:
        agg = aggregate(files, rule)
        line_ok = agg.line_percent >= rule.line
        line_text = f"{agg.line_percent:.1f}% (≥{rule.line:.0f}%)"
        if rule.branch is None:
            branch_text = "—"
            branch_ok = True
        else:
            branch_ok = agg.branch_percent >= rule.branch
            branch_text = f"{agg.branch_percent:.1f}% (≥{rule.branch:.0f}%)"
        passed = line_ok and branch_ok
        all_passed = all_passed and passed
        mark = "PASS" if passed else "FAIL"
        print(f"{rule.name:<34}{agg.files:>6}{line_text:>16}{branch_text:>16}  {mark}")
        if not passed:
            missing = []
            if not line_ok:
                missing.append(f"行覆盖 {agg.line_percent:.1f}% < {rule.line:.0f}%")
            if not branch_ok and rule.branch is not None:
                missing.append(f"分支覆盖 {agg.branch_percent:.1f}% < {rule.branch:.0f}%")
            print(f"  -> 不满足：{'；'.join(missing)}")
    print("-" * 78)
    return all_passed


def main() -> int:
    parser = argparse.ArgumentParser(description="分模块覆盖率阈值检查（文档 §4.3）")
    parser.add_argument("--report", required=True, help="coverage.py JSON 报告路径")
    args = parser.parse_args()

    report_path = Path(args.report)
    if not report_path.is_file():
        print(f"报告不存在：{report_path}（先执行 coverage json -o {report_path.name}）")
        return 2

    files = load_report(report_path)
    if not files:
        print("报告中没有任何文件数据：请检查 --cov=app 与 source 配置。")
        return 2

    passed = check(files)
    print("覆盖率阈值检查通过。" if passed else "覆盖率阈值检查未通过，阻断合并。")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
