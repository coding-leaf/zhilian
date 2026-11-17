"""Markdown 结构化分块纯函数。

把整页 Markdown / 纯文本拆成「段落块」，同时把以下结构视为不可拆分的原子块：

- ``$$ ... $$`` 展示公式（含跨多行）与 ``\\[ ... \\]``；
- 以 ``|`` 开头的 Markdown 管道表格（连续表格行）；
- ````` ``` ````` 围栏代码块。

纯计算，无任何外部 I/O，符合 core.algorithms 分层约束。
"""

from __future__ import annotations

_FENCE = "```"


def _is_table_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.count("|") >= 2


def _display_math_closes_inline(line: str) -> bool:
    """单行内 ``$$...$$`` 已闭合（出现偶数次且 >= 2 次）。"""
    return line.count("$$") >= 2


def _collect_display_math(lines: list[str], start: int) -> int:
    """从 start 行起收集展示公式，返回块结束行（含）。未闭合时吞到文末由调用方兜底。"""
    first = lines[start].strip()
    if first.startswith("\\["):
        closer = "\\]"
        if closer in first[2:]:
            return start
    else:
        closer = "$$"
        if _display_math_closes_inline(first):
            return start
    for idx in range(start + 1, min(len(lines), start + 40)):
        if closer in lines[idx]:
            return idx
    return start  # 未闭合：按单行处理，避免吞掉整页


def _starts_display_math(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith(("$$", "\\["))


def split_markdown_blocks(text: str) -> list[str]:
    """将文本拆分为结构化块列表，保持 ``$$..$$`` 公式与 Markdown 表格完整。

    规则：
    1. 空行分隔普通段落块（块内保留原有换行）；
    2. 展示公式与连续表格行各自成为独立原子块；
    3. 全文不含任何空行时（硬折行的旧式文本），退化为逐行成块以便后续合并器聚合。

    Args:
        text: 页面或章节文本。

    Returns:
        list[str]: 去除首尾空白后的非空块列表。
    """
    if not text or not text.strip():
        return []

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    has_blank_line = any(not ln.strip() for ln in lines)

    blocks: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            joined = "\n".join(buffer).strip()
            if joined:
                blocks.append(joined)
            buffer.clear()

    idx = 0
    while idx < len(lines):
        line = lines[idx]
        stripped = line.strip()

        if stripped.startswith(_FENCE):
            flush()
            end = idx + 1
            while end < len(lines) and not lines[end].strip().startswith(_FENCE):
                end += 1
            end = min(end, len(lines) - 1)
            blocks.append("\n".join(lines[idx : end + 1]).strip())
            idx = end + 1
            continue

        if _starts_display_math(line):
            flush()
            end = _collect_display_math(lines, idx)
            blocks.append("\n".join(lines[idx : end + 1]).strip())
            idx = end + 1
            continue

        if _is_table_line(line):
            flush()
            end = idx
            while end + 1 < len(lines) and _is_table_line(lines[end + 1]):
                end += 1
            blocks.append("\n".join(lines[idx : end + 1]).strip())
            idx = end + 1
            continue

        if not stripped:
            flush()
        elif has_blank_line:
            buffer.append(line)
        else:
            blocks.append(stripped)
        idx += 1

    flush()
    return [b for b in blocks if b]


__all__ = ["split_markdown_blocks"]
