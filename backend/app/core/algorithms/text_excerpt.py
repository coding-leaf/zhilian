"""Clean excerpt trimming and neighbor-snippet text merging (pure functions).

Used to replace hard ``content[:320]`` truncation (which cuts mid-sentence and
mid-formula) and to stitch neighbor snippets together for context expansion.
Complies with pure functional kernel constraints (zero external I/O).
"""

from collections.abc import Sequence

from app.core.algorithms.material_chunking import (
    Span,
    enclosing_span,
    find_protected_spans,
    is_sentence_boundary,
)

# 截断时追加的省略号（仅在确实发生截断时追加；计入 max_chars 预算）
ELLIPSIS: str = "…"

# 截断点不应低于 max_chars 的 40%（除非找不到任何更靠后的合法位置）
_MIN_CUT_RATIO: float = 0.4

# 邻接片段去重：接缝处后缀/前缀重叠至少 20 字符才视为滑动窗口重叠
_MIN_SEAM_OVERLAP: int = 20

_CLAUSE_PUNCTUATION: str = "，；、,;"


def _unclosed_math_opener(prefix: str) -> int | None:
    """返回前缀中未闭合公式的开启符位置（`$$` 块优先于 `$` 行内），没有则 None。"""
    display_open: int | None = None
    inline_open: int | None = None
    idx = 0
    while idx < len(prefix):
        char = prefix[idx]
        if char == "\\":
            idx += 2
            continue
        if char == "$":
            if prefix.startswith("$$", idx):
                if display_open is not None:
                    display_open = None
                elif inline_open is None:
                    display_open = idx
                idx += 2
                continue
            if display_open is None:
                inline_open = None if inline_open is not None else idx
        idx += 1
    return display_open if display_open is not None else inline_open


def _has_unclosed_math(prefix: str) -> bool:
    """判断前缀是否以未闭合的 `$...$` / `$$...$$` 结尾（切在公式中间）。"""
    return _unclosed_math_opener(prefix) is not None


def _is_inside_table_row(text: str, pos: int) -> bool:
    """判断切点 ``pos`` 是否落在 Markdown 表格行中间（行尾/换行处切开是允许的）。"""
    if pos <= 0 or pos >= len(text) or text[pos - 1] == "\n" or text[pos] == "\n":
        return False
    line_start = text.rfind("\n", 0, pos) + 1
    return text[line_start:pos].lstrip().startswith("|")


def _is_safe_cut(text: str, pos: int, math_spans: Sequence[Span]) -> bool:
    """切点 ``pos``（切掉 text[pos:]）是否不破坏公式与表格行。"""
    return (
        enclosing_span(math_spans, pos) is None
        and not _has_unclosed_math(text[:pos])
        and not _is_inside_table_row(text, pos)
    )


def _find_cut(
    text: str, lo: int, hi: int, math_spans: Sequence[Span], clause_level: bool
) -> int | None:
    """在 [lo, hi] 内从右向左寻找最靠后的安全断点（句末标点或次级标点之后）。"""
    for idx in range(hi - 1, lo - 1, -1):
        char = text[idx]
        hit = char in _CLAUSE_PUNCTUATION if clause_level else is_sentence_boundary(text, idx)
        if hit and _is_safe_cut(text, idx + 1, math_spans):
            return idx + 1
    return None


def _hard_cut(text: str, limit: int, math_spans: Sequence[Span]) -> int:
    """无任何标点可用时的兜底：回退到公式起点之前；若公式从头开始则不可避免地在 limit 硬切。"""
    enclosing = enclosing_span(math_spans, limit)
    if enclosing is not None and enclosing[0] > 0:
        return enclosing[0]
    opener = _unclosed_math_opener(text[:limit])
    if opener is not None and opener > 0:
        return opener
    return limit


def trim_excerpt_cleanly(text: str, max_chars: int = 480) -> str:
    """把文本裁剪为不超过 ``max_chars`` 的整洁摘录，不在句中/公式中/表格行中硬切。

    - 文本长度 <= ``max_chars`` 时原样返回；
    - 否则在 ``max_chars - 1`` 之内（为省略号预留 1 字符，结果总长 <= ``max_chars``）
      选取最靠后的句末断点（``。！？.!?`` 与换行；小数 ``3.14``、版本号、``e.g.`` 不算句末）；
    - 断点不低于 ``max_chars`` 的 40%；窗口内 40% 之后没有句末时，退而求其次选次级标点
      （``，；、,;``），再没有才使用 40% 之前的句末，最后兜底硬切；
    - 断点绝不落在 ``$...$`` / ``$$...$$`` 内部或存在未闭合 ``$`` 之后（回退到公式起点之前），
      也不落在 Markdown 表格行中间；
    - 仅在确实截断时追加 ``…``；非空（非全空白）输入永不返回空串。

    Args:
        text: 原始文本。
        max_chars: 摘录最大字符数（含省略号），默认 480。

    Returns:
        str: 整洁摘录。

    Raises:
        ValueError: ``max_chars`` 不是正整数时抛出。
    """
    if max_chars <= 0:
        raise ValueError("max_chars must be a positive integer")
    if len(text) <= max_chars:
        return text
    if text.strip():
        # 前导空白不应挤占摘录预算（也避免截出纯空白摘录）
        text = text.lstrip()
        if len(text) <= max_chars:
            return text

    limit = max(max_chars - len(ELLIPSIS), 1)
    floor = int(max_chars * _MIN_CUT_RATIO)
    math_spans = find_protected_spans(text, tables=False)

    cut = (
        _find_cut(text, floor, limit, math_spans, clause_level=False)
        or _find_cut(text, floor, limit, math_spans, clause_level=True)
        or _find_cut(text, 0, limit, math_spans, clause_level=False)
        or _hard_cut(text, limit, math_spans)
    )

    head = text[:cut].rstrip() or text[:limit].strip()
    if not head:
        return text[:max_chars]
    return head + ELLIPSIS


def _seam_overlap(accumulated: str, nxt: str) -> int:
    """计算 accumulated 后缀与 nxt 前缀的最大重叠长度（< _MIN_SEAM_OVERLAP 视为 0）。"""
    if len(nxt) < _MIN_SEAM_OVERLAP or len(accumulated) < _MIN_SEAM_OVERLAP:
        return 0
    probe = nxt[:_MIN_SEAM_OVERLAP]
    search_from = max(0, len(accumulated) - len(nxt))
    pos = accumulated.find(probe, search_from)
    while pos != -1:
        tail = accumulated[pos:]
        if nxt.startswith(tail):
            return len(tail)
        pos = accumulated.find(probe, pos + 1)
    return 0


def merge_adjacent_snippet_texts(texts: Sequence[str]) -> str:
    """把相邻片段文本拼接为连续上下文，并去除接缝处滑动窗口造成的重复。

    相邻两段若 前段后缀 == 后段前缀 且重叠 >= 20 字符，则只保留一份重叠；
    否则以换行连接。空白片段被跳过；后段完全包含于前段尾部时不重复追加。

    Args:
        texts: 按顺序排列的相邻片段文本。

    Returns:
        str: 拼接后的文本（无输入时为空串）。
    """
    merged = ""
    for text in texts:
        if not text.strip():
            continue
        if not merged:
            merged = text
            continue
        overlap = _seam_overlap(merged, text)
        merged = merged + text[overlap:] if overlap else merged + "\n" + text
    return merged


__all__ = ["ELLIPSIS", "merge_adjacent_snippet_texts", "trim_excerpt_cleanly"]
