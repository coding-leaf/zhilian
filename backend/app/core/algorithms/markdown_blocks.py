"""Markdown 结构化分块纯函数。

把整页 Markdown / 纯文本拆成「段落块」，同时把以下结构视为不可拆分的原子块：

- ``$$ ... $$`` 展示公式（含跨多行）与 ``\\[ ... \\]``；
- 以 ``|`` 开头的 Markdown 管道表格（连续表格行）；
- ````` ``` ````` 围栏代码块。

纯计算，无任何外部 I/O，符合 core.algorithms 分层约束。
"""

from __future__ import annotations

import re

_FENCE = "```"
_CJK_OR_PUNCT_RE: re.Pattern[str] = re.compile(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]")
_HEADING_LINE_RE: re.Pattern[str] = re.compile(r"^#{1,6}\s+")
_LIST_LINE_RE: re.Pattern[str] = re.compile(r"^(?:[-*•]\s+|\d+[.)]\s+)")
_HR_LINE_RE: re.Pattern[str] = re.compile(r"^(?:[-*_]){3,}$")
_CHAPTER_HEADING_RE: re.Pattern[str] = re.compile(
    r"^(?:第[一二三四五六七八九十百千\d]+[章节讲篇部]|\d+(?:\.\d+)+\s+\S)"
)
_SENTENCE_END_CHARS: frozenset[str] = frozenset("。！？；：.!?;:…")
_CLOSING_WRAPPER_CHARS: str = "”’\"')）】》」』"
_HEADING_PUNCT_CHARS: frozenset[str] = frozenset("，、。！？；：,.!?;:()（）=$\\`")
_TRAILING_PARTICLES: tuple[str, ...] = (
    "的",
    "了",
    "和",
    "与",
    "或",
    "在",
    "对",
    "将",
    "把",
    "被",
    "中",
    "等",
    "及",
    "是",
    "为",
    "可",
)
_LEADING_CONTINUATION_CHARS: tuple[str, ...] = (
    "的",
    "了",
    "和",
    "与",
    "或",
    "等",
    "，",
    "、",
    "。",
    "）",
    ")",
)


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


def _is_prose_line(stripped: str) -> bool:
    """判断单行是否属于可参与视觉折行重连的普通正文行（非空、非块标记）。"""
    return bool(
        stripped
        and not (
            stripped.startswith(_FENCE)
            or _starts_display_math(stripped)
            or _is_table_line(stripped)
            or _HEADING_LINE_RE.match(stripped)
            or _LIST_LINE_RE.match(stripped)
            or stripped.startswith(">")
            or _HR_LINE_RE.match(stripped)
        )
    )


def _ends_sentence_or_break(prev: str) -> bool:
    """判断前一行末尾是否已构成句末终止标点、冒号或破折号。"""
    stripped = prev.rstrip()
    if not stripped:
        return True
    if stripped.endswith(("--", "——")):
        return True
    core = stripped.rstrip(_CLOSING_WRAPPER_CHARS)
    if not core:
        return False
    return core[-1] in _SENTENCE_END_CHARS


def _is_short_standalone_heading(prev_stripped: str, curr_stripped: str) -> bool:
    """避免把独立短小标题（如“基本概念”）误拼接到下一行正文。"""
    if _CHAPTER_HEADING_RE.match(prev_stripped):
        return len(prev_stripped) <= 24 and not _ends_sentence_or_break(prev_stripped)
    if not (2 <= len(prev_stripped) <= 10):
        return False
    if any(ch in _HEADING_PUNCT_CHARS for ch in prev_stripped):
        return False
    if prev_stripped.endswith(_TRAILING_PARTICLES):
        return False
    if curr_stripped.startswith(_LEADING_CONTINUATION_CHARS):
        return False
    return bool(_CJK_OR_PUNCT_RE.search(prev_stripped))


def _join_wrapped_lines(prev: str, curr: str) -> str:
    """将 PDF 视觉硬折断的连续两行按中英文边界自然重连。"""
    left = prev.rstrip()
    right = curr.lstrip()
    if not left:
        return right
    if not right:
        return left
    if (
        len(left) >= 2
        and left[-1] == "-"
        and left[-2].isascii()
        and left[-2].isalpha()
        and right[0].isascii()
        and right[0].isalpha()
    ):
        return left[:-1] + right
    if _CJK_OR_PUNCT_RE.search(left[-1]) or _CJK_OR_PUNCT_RE.search(right[0]):
        return left + right
    if left[-1] in "([{\"'/" or right[0] in ")]},.;:!?%/":
        return left + right
    return f"{left} {right}"


def unwrap_pdf_visual_line_breaks(text: str) -> str:
    """重连 PyMuPDF 等抽取文本中被行宽硬折断的中英文自然段落。

    严格保留 Markdown 标题、列表、围栏代码块、GFM 管道表格、``$$...$$`` / ``\\[...\\]``
    展示公式块、引用块、空行及句末标点后的真实换行。
    """
    if not text or not text.strip():
        return text

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    prose_buf: list[str] = []

    def flush_prose() -> None:
        if prose_buf:
            out.extend(prose_buf)
            prose_buf.clear()

    idx = 0
    while idx < len(lines):
        line = lines[idx]
        stripped = line.strip()

        if stripped.startswith(_FENCE):
            flush_prose()
            end = idx + 1
            while end < len(lines) and not lines[end].strip().startswith(_FENCE):
                end += 1
            end = min(end, len(lines) - 1)
            out.extend(lines[idx : end + 1])
            idx = end + 1
            continue

        if _starts_display_math(line):
            flush_prose()
            end = _collect_display_math(lines, idx)
            out.extend(lines[idx : end + 1])
            idx = end + 1
            continue

        if _is_table_line(line):
            flush_prose()
            end = idx
            while end + 1 < len(lines) and _is_table_line(lines[end + 1]):
                end += 1
            out.extend(lines[idx : end + 1])
            idx = end + 1
            continue

        if not _is_prose_line(stripped):
            flush_prose()
            out.append(line)
            idx += 1
            continue

        if (
            not prose_buf
            or _ends_sentence_or_break(prose_buf[-1])
            or (len(prose_buf) == 1 and _is_short_standalone_heading(prose_buf[-1], stripped))
        ):
            prose_buf.append(stripped)
        else:
            prose_buf[-1] = _join_wrapped_lines(prose_buf[-1], stripped)
        idx += 1

    flush_prose()
    return "\n".join(out)


__all__ = ["split_markdown_blocks", "unwrap_pdf_visual_line_breaks"]
