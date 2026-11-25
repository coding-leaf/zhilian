"""Material chunking algorithm module.

Implements pure functional text chunking with multi-level punctuation degradation,
semantic overlap alignment, isolated short snippet merging, and safety truncation.
Complies with pure functional kernel constraints (zero external I/O, zero network/ORM dependencies).

Formula / table safety:
    ``$$...$$`` display math, ``$...$`` inline math and Markdown pipe tables are
    *protected spans*. Split points and overlap starts are never placed inside them.
    The ``max_chars`` hard limit always wins: a protected block that alone exceeds
    ``max_chars`` is split at its own line (row) boundaries, and only when it has no
    newline at all is it hard-cut at ``max_chars`` (unavoidable). Chunks are therefore
    never longer than ``max_chars``.
"""

import re
from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import dataclass

from app.core.algorithms.document_denoising import (
    PageRole,
    classify_slide_or_page,
    strip_display_watermark_lines,
)

# 决策基线条目与依据常量注释：
# 依据：概要设计说明书第 3.2 节知识片段切分标准，单个检索单元适配嵌入向量模型最佳窗口
DEFAULT_MAX_CHARS: int = 800

# 依据：概要设计说明书与需求规格说明书第 3.2.1 节，相邻片段保留约 15% 上下文语义重叠
DEFAULT_OVERLAP_CHARS: int = 120

# 依据：RAG 碎片化治理（research/rag-pdf-fragmentation-and-formulas.md）
# 低于 120 字符的片段语义信息过少（如 `σi\n2` 这类公式碎行），需循环合并至 >= 120 字符
DEFAULT_MIN_CHARS: int = 120

# 依据：同页同章连续段落向目标块大小聚合，兼顾检索粒度与上下文完整性
DEFAULT_TARGET_CHARS: int = 500

# 依据：系统防护基线与 NFR-22 限制，单份资料切片上限 3000 片段，防范超大恶意文档引发拒绝服务
DEFAULT_MAX_SNIPPETS: int = 3000

# 正则匹配非法控制字符（除 \n 与 \t 外）与零宽/BOM 字符
# ASCII \x00-\x08, \x0b-\x0c, \x0e-\x1f, \x7f 以及 Unicode 零宽字符 \u200b-\u200f, \ufeff
ILLEGAL_CONTROL_CHARS_PATTERN: re.Pattern[str] = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b-\u200f\ufeff]"
)

# 一级句末标点（中文 。！？ 与英文 .!? 以及换行符 \n）
# 注意：`.` 仅在非小数/版本号/缩写语境下才视为句末（见 is_sentence_boundary）
PRIMARY_PUNCTUATION_CHARS: str = "。！？!?.\n"

# 二级次级标点（中文 ，；、 与英文 ,;）
SECONDARY_PUNCTUATION_CHARS: str = "，；、,;"

# `.` 句号守卫：这些缩写（小写比较）末尾的 `.` 不是句末
_ABBREVIATIONS: tuple[str, ...] = (
    "e.g.",
    "i.e.",
    "vs.",
    "fig.",
    "eq.",
    "dr.",
    "mr.",
    "mrs.",
    "ms.",
    "prof.",
    "al.",
    "cf.",
    "approx.",
)
_ABBREVIATION_LOOKBACK: int = 8

# 受保护片段：$$...$$ 块公式、$...$ 行内公式（开 $ 后非空白，闭 $ 前非空白）与 Markdown 管道表
_MATH_SPAN_RE: re.Pattern[str] = re.compile(
    r"(?<!\\)\$\$[\s\S]{1,4000}?(?<!\\)\$\$"
    r"|(?<!\\)\$(?![\s$])(?:[^$\n]|\n(?!\n)){1,300}?(?<![\s\\])\$"
)
_TABLE_BLOCK_RE: re.Pattern[str] = re.compile(
    r"(?:^[ \t]*\|[^\n]*\|[ \t]*(?:\n|\Z))+", re.MULTILINE
)

# Wingdings/Symbol 等 PPT 伪列表符号在 PDF/文本抽出后常呈现为行首孤立 l/n/ü 或私用区字符
PSEUDO_BULLET_LINE_PATTERN: re.Pattern[str] = re.compile(
    r"(?m)^([ \t]*)(?:l|n|ü|[\uf06c\uf06e\uf0fc\uf0a7\uf0b7\uf0d8\uf076])\s+"
)
_MD_HEADING_PREFIX_RE: re.Pattern[str] = re.compile(r"^#{1,6}\s+")
_ULTRA_SHORT_NOISE_MAX_CHARS: int = 15
_CROSS_PAGE_SHORT_SLIDE_MAX_CHARS: int = 260
_NUMBERED_PREFIX_RE: re.Pattern[str] = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*[.、)．]?|\(\d+\)|[一二三四五六七八九十]+[、.．]|[-*•▪●○])\s*"
)
_PUNCT_SPACE_RE: re.Pattern[str] = re.compile(
    r"[\s。！？!?.,，、；;：:~～·…—\-_()（）\[\]【】\"'“”‘’]+"
)
_SUBSTANTIVE_SHORT_TERM_RE: re.Pattern[str] = re.compile(r"(?:定义|定理|公式|条件|步骤)")
_TITLE_FORBIDDEN_MATH_CHARS: frozenset[str] = frozenset("+-*/^_=<>≤≥≠≈∈∉⊂⊃∪∩∑∫∏√∞±×÷·‖|${}[]`\\−")
_TITLE_GREEK_RE: re.Pattern[str] = re.compile(r"[\u0370-\u03ff\U0001d400-\U0001d7ff]")


def is_valid_chapter_title(title: str) -> bool:
    """防御性校验章节标题：拒绝数学公式表达式与运算符碎片覆盖章节状态。"""
    stripped = _MD_HEADING_PREFIX_RE.sub("", title.strip()).strip()
    if not stripped or "\n" in stripped or len(stripped) > 80:
        return False
    if _TITLE_GREEK_RE.search(stripped):
        return False
    if any(ch in _TITLE_FORBIDDEN_MATH_CHARS for ch in stripped):
        return False
    return not stripped.startswith(("(", "（", "-", "+", "="))


@dataclass(frozen=True)
class ParagraphInput:
    """输入段落结构化描述（可选扩展格式）。"""

    text: str
    source_ref: str = "段落"
    doc_type: str = "txt"
    is_title: bool = False
    title_level: int = 0
    page_number: int | None = None
    page_end: int | None = None


@dataclass(frozen=True)
class Snippet:
    """输出的不可变知识片段。"""

    index: int
    content: str
    char_count: int
    start_offset: int
    end_offset: int
    chapter_title: str
    source_ref: str
    doc_type: str
    page_number: int | None = None
    page_end: int | None = None


@dataclass(frozen=True)
class ChunkingResult:
    """资料分块算法统一输出包装对象。"""

    snippets: tuple[Snippet, ...]
    total_count: int
    is_truncated: bool
    max_chars: int
    overlap_chars: int
    cleaned_chars_count: int
    warnings: tuple[str, ...]


Span = tuple[int, int]


def clean_pseudo_bullet_glyphs(text: str) -> str:
    """将 PPT 导出的 Wingdings 伪项目符号（l / n / ü 等）规范化为 Markdown 列表 `- `。"""
    if not text:
        return text
    return PSEUDO_BULLET_LINE_PATTERN.sub(r"\1- ", text)


def clean_text_and_count_removals(text: str) -> tuple[str, int]:
    """过滤非法控制字符与零宽字符并返回剔除计数。

    Args:
        text: 待清洗的原始文本字符串。

    Returns:
        tuple[str, int]: 清洗后的文本以及剔除的非法字符总数。
    """
    cleaned_text, count = ILLEGAL_CONTROL_CHARS_PATTERN.subn("", text)
    return cleaned_text, count


# ---------------------------------------------------------------------------
# 受保护片段（公式 / 表格）与句末判定
# ---------------------------------------------------------------------------


def _merge_spans(spans: list[Span]) -> list[Span]:
    """合并相互重叠的片段区间，返回按起点升序且互不重叠的列表。"""
    merged: list[Span] = []
    for start, end in sorted(spans):
        if merged and start < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def find_protected_spans(text: str, *, math: bool = True, tables: bool = True) -> list[Span]:
    """定位文本中不可从内部切断的区间：`$$..$$`、`$..$` 公式与 Markdown 管道表。

    Args:
        text: 目标文本。
        math: 是否保护 LaTeX 公式。
        tables: 是否保护 Markdown 管道表（整张表作为一个区间）。

    Returns:
        list[tuple[int, int]]: 升序、互不重叠的 (start, end) 半开区间。
    """
    spans: list[Span] = []
    if math and "$" in text:
        spans.extend(m.span() for m in _MATH_SPAN_RE.finditer(text))
    if tables and "|" in text:
        for match in _TABLE_BLOCK_RE.finditer(text):
            start, end = match.span()
            while end > start and text[end - 1] == "\n":
                end -= 1
            spans.append((start, end))
    return _merge_spans(spans)


def enclosing_span(spans: Sequence[Span], pos: int) -> Span | None:
    """返回严格包含切点 ``pos`` 的区间（start < pos < end），否则 None。"""
    idx = bisect_left(spans, pos, key=lambda span: span[0])
    if idx == 0:
        return None
    start, end = spans[idx - 1]
    return (start, end) if start < pos < end else None


def _is_period_sentence_end(text: str, idx: int) -> bool:
    """判断 ``text[idx] == '.'`` 是否为真正的句末句号（排除小数、版本号、缩写、省略号）。"""
    prev_ch = text[idx - 1] if idx > 0 else ""
    next_ch = text[idx + 1] if idx + 1 < len(text) else ""
    if not prev_ch or prev_ch.isspace():
        return False
    # `3.14` / `v1.2` / `e.g` / `file.txt` / `a.b`：句点后紧跟 ASCII 字母数字
    if next_ch == "." or (next_ch.isascii() and next_ch.isalnum()):
        return False
    lookback = text[max(0, idx - _ABBREVIATION_LOOKBACK) : idx + 1].lower()
    for abbr in _ABBREVIATIONS:
        if lookback.endswith(abbr):
            before = len(lookback) - len(abbr) - 1
            if before < 0 or not lookback[before].isalnum():
                return False
    return True


def is_sentence_boundary(text: str, idx: int) -> bool:
    """判断 ``text[idx]`` 是否为一级句末标点（`.` 需通过小数/版本/缩写守卫）。"""
    char = text[idx]
    if char not in PRIMARY_PUNCTUATION_CHARS:
        return False
    if char == ".":
        return _is_period_sentence_end(text, idx)
    return True


def _is_clause_boundary(text: str, idx: int) -> bool:
    """判断 ``text[idx]`` 是否为二级次级标点（千分位 `1,000` 中的逗号除外）。"""
    char = text[idx]
    if char not in SECONDARY_PUNCTUATION_CHARS:
        return False
    if char == ",":
        prev_ch = text[idx - 1] if idx > 0 else ""
        next_ch = text[idx + 1] if idx + 1 < len(text) else ""
        return not (prev_ch.isdigit() and next_ch.isdigit())
    return True


def _scan_split(text: str, lo: int, hi: int, spans: Sequence[Span], primary: bool) -> int | None:
    """在 [lo, hi) 内从右向左寻找不落在受保护区间内部的标点切点（返回切点位置，即标点之后）。"""
    for idx in range(hi - 1, lo - 1, -1):
        hit = is_sentence_boundary(text, idx) if primary else _is_clause_boundary(text, idx)
        if hit and enclosing_span(spans, idx + 1) is None:
            return idx + 1
    return None


def align_overlap_sentence_boundary(
    prev_text: str,
    overlap_chars: int,
    protected_spans: Sequence[Span] | None = None,
) -> str:
    """提取上一个片段末尾的重叠子串并向完整句首对齐。

    重叠只会从完整句子的起点开始：起点必须紧跟在一级句末标点（或文本开头）之后，
    且不在公式/表格内部；绝不从 `,`/`;` 等次级标点之后的半句开始。
    重叠窗口内没有合法句首时返回空串（宁可无重叠，也不从半句开始）。

    Args:
        prev_text: 上一个切片的完整正文。
        overlap_chars: 允许的最大重叠字符数。
        protected_spans: 可选的受保护区间（相对 ``prev_text``）；缺省时自动计算。

    Returns:
        str: 对齐到完整句首的重叠文本；无合法对齐点时为空串。
    """
    if overlap_chars <= 0 or not prev_text:
        return ""

    spans = find_protected_spans(prev_text) if protected_spans is None else protected_spans
    length = len(prev_text)
    for pos in range(max(0, length - overlap_chars), length):
        if pos > 0 and not is_sentence_boundary(prev_text, pos - 1):
            continue
        if enclosing_span(spans, pos) is not None:
            continue
        start = pos
        while start < length and prev_text[start].isspace():
            start += 1
        if start < length and enclosing_span(spans, start) is None:
            return prev_text[start:]
    return ""


def find_best_split_point(
    text: str,
    start_index: int,
    target_end_index: int,
    protected_spans: Sequence[Span] | None = None,
) -> int:
    """在指定窗口内按多级标点降级策略寻找最佳断句位置。

    降级顺序：一级句末标点 -> 二级次级标点 -> 硬切。任何一级都不会选择落在
    ``$$..$$`` / ``$..$`` 公式或 Markdown 表格内部的位置。若理想结束点恰好落在
    受保护区间内部：区间之前还有内容则回退到区间起点之前再找断点；区间自身
    即占满窗口（超长公式/表格）则在区间内最后一个换行（行/行边界）处断开，
    无换行时才硬切（不可避免）。

    Args:
        text: 目标段落正文。
        start_index: 当前切片在段落内的起始字符索引。
        target_end_index: 当前切片在段落内的理想结束字符索引。
        protected_spans: 可选的受保护区间；缺省时自动计算。

    Returns:
        int: 决策出的最佳切分位置索引。
    """
    spans = find_protected_spans(text) if protected_spans is None else protected_spans

    enclosing = enclosing_span(spans, target_end_index)
    if enclosing is not None:
        if enclosing[0] > start_index:
            return find_best_split_point(text, start_index, enclosing[0], spans)
        newline = text.rfind("\n", start_index, target_end_index)
        return newline + 1 if newline > start_index else target_end_index

    for primary in (True, False):
        split = _scan_split(text, start_index, target_end_index, spans, primary)
        if split is not None:
            return split

    # 三级降级：无任何标点，强制在窗口末尾硬切
    return target_end_index


def _clip_spans(spans: Sequence[Span], lo: int, hi: int) -> list[Span]:
    """把全局区间裁剪并平移到切片 [lo, hi) 的局部坐标。"""
    return [(max(s, lo) - lo, min(e, hi) - lo) for s, e in spans if s < hi and e > lo]


def split_paragraph_into_ranges(
    text: str, max_chars: int, overlap_chars: int
) -> list[tuple[int, int]]:
    """将单段超长文本基于标点降级与重叠步进切分为多个字符范围。

    Args:
        text: 待切分段落文本。
        max_chars: 单切片字符上限。
        overlap_chars: 实际生效的重叠字符数。

    Returns:
        list[tuple[int, int]]: 各切片在段落内的 (start_index, end_index) 范围列表。
    """
    total_len = len(text)
    if total_len <= max_chars:
        return [(0, total_len)]

    spans = find_protected_spans(text)
    ranges: list[tuple[int, int]] = []
    current_start = 0

    while True:
        if total_len - current_start <= max_chars:
            ranges.append((current_start, total_len))
            break

        target_end = current_start + max_chars
        split_end = find_best_split_point(text, current_start, target_end, spans)
        ranges.append((current_start, split_end))

        current_start = split_end
        if overlap_chars > 0:
            slice_text = text[ranges[-1][0] : split_end]
            aligned_overlap = align_overlap_sentence_boundary(
                slice_text,
                overlap_chars,
                _clip_spans(spans, ranges[-1][0], split_end),
            )
            if aligned_overlap and len(aligned_overlap) < len(slice_text):
                current_start = split_end - len(aligned_overlap)

    return ranges


# ---------------------------------------------------------------------------
# 短片段合并
# ---------------------------------------------------------------------------


def _same_segment(
    left: Snippet,
    right: Snippet,
    *,
    allow_cross_page_merge: bool = False,
) -> bool:
    """判断两个片段是否满足合并边界：绝不跨章，仅在开启时允许同章相邻短页柔合并。"""
    if left.chapter_title != right.chapter_title or left.doc_type != right.doc_type:
        return False
    if left.page_number == right.page_number and left.source_ref == right.source_ref:
        return True
    if not allow_cross_page_merge:
        return False
    if left.page_number is None or right.page_number is None:
        return False
    if not left.chapter_title.strip() and left.doc_type != "pptx":
        return False
    left_end = left.page_end if left.page_end is not None else left.page_number
    return 0 <= right.page_number - left_end <= 1


def _join_snippets(left: Snippet, right: Snippet) -> Snippet:
    """拼接相邻片段；同段相邻窗口的重叠部分（按偏移判定）自动去重，跨页时保留 page_end。"""
    overlap = left.end_offset - right.start_offset
    head = right.content[:overlap] if overlap > 0 else ""
    if overlap > 0 and left.content.endswith(head):
        content = left.content + right.content[overlap:]
    else:
        content = left.content + "\n" + right.content

    left_page = left.page_number
    left_end = left.page_end if left.page_end is not None else left.page_number
    right_end = right.page_end if right.page_end is not None else right.page_number
    if left_page is not None and right_end is not None and right_end > left_page:
        merged_page_end: int | None = max(left_end or left_page, right_end)
        source_ref = f"第 {left_page}-{merged_page_end} 页"
    else:
        merged_page_end = left.page_end
        source_ref = left.source_ref

    return Snippet(
        index=left.index,
        content=content,
        char_count=len(content),
        start_offset=left.start_offset,
        end_offset=max(left.end_offset, right.end_offset),
        chapter_title=left.chapter_title,
        source_ref=source_ref,
        doc_type=left.doc_type,
        page_number=left.page_number,
        page_end=merged_page_end,
    )


def _try_forward_merge(
    current: Snippet,
    nxt: Snippet,
    min_chars: int,
    target_chars: int,
    max_chars: int,
    *,
    allow_cross_page_merge: bool = False,
) -> Snippet | None:
    """尝试把 ``nxt`` 并入 ``current``（支持同章相邻短页柔合并，绝不跨章）。"""
    if not _same_segment(current, nxt, allow_cross_page_merge=allow_cross_page_merge):
        return None
    same_page = current.page_number == nxt.page_number and current.source_ref == nxt.source_ref
    current_short = current.char_count < min_chars
    joined = _join_snippets(current, nxt)

    if same_page:
        if not current_short and nxt.char_count < min_chars:
            return None
        limit = max_chars if current_short else target_chars
        return joined if joined.char_count <= limit else None

    if _is_ultra_short_noise_snippet(current) or _is_ultra_short_noise_snippet(nxt):
        return None
    if current_short and joined.char_count <= max_chars:
        return joined
    if (
        nxt.char_count < _CROSS_PAGE_SHORT_SLIDE_MAX_CHARS
        and current.char_count < target_chars
        and joined.char_count <= target_chars
        and joined.char_count <= max_chars
    ):
        return joined
    return None


def _append_with_backfill(
    output: list[Snippet],
    item: Snippet,
    min_chars: int,
    max_chars: int,
    *,
    allow_cross_page_merge: bool = False,
) -> None:
    """追加成品片段；若其仍是短片段且无法向后合并，则尽量并回前一同段/同章邻页片段。"""
    if (
        item.char_count < min_chars
        and output
        and _same_segment(output[-1], item, allow_cross_page_merge=allow_cross_page_merge)
    ):
        same_page = (
            output[-1].page_number == item.page_number and output[-1].source_ref == item.source_ref
        )
        if not same_page and _is_ultra_short_noise_snippet(item):
            output.append(item)
            return
        joined = _join_snippets(output[-1], item)
        if joined.char_count <= max_chars:
            output[-1] = joined
            return
    output.append(item)


def merge_isolated_short_snippets(
    snippets: list[Snippet],
    min_chars: int,
    max_chars: int = DEFAULT_MAX_CHARS,
    target_chars: int = DEFAULT_TARGET_CHARS,
    *,
    allow_cross_page_merge: bool = True,
) -> list[Snippet]:
    """循环累积合并短片段，并把同页/同章邻页的连续短片段聚合到目标块大小。"""
    if min_chars <= 0 or not snippets:
        return snippets

    target = min(max(target_chars, min_chars), max_chars)
    merged: list[Snippet] = []
    current: Snippet | None = None

    for snippet in snippets:
        if current is None:
            current = snippet
            continue
        combined = _try_forward_merge(
            current,
            snippet,
            min_chars,
            target,
            max_chars,
            allow_cross_page_merge=allow_cross_page_merge,
        )
        if combined is not None:
            current = combined
            continue
        _append_with_backfill(
            merged,
            current,
            min_chars,
            max_chars,
            allow_cross_page_merge=allow_cross_page_merge,
        )
        current = snippet

    if current is not None:
        _append_with_backfill(
            merged,
            current,
            min_chars,
            max_chars,
            allow_cross_page_merge=allow_cross_page_merge,
        )

    return [
        Snippet(
            index=idx,
            content=item.content,
            char_count=item.char_count,
            start_offset=item.start_offset,
            end_offset=item.end_offset,
            chapter_title=item.chapter_title,
            source_ref=item.source_ref,
            doc_type=item.doc_type,
            page_number=item.page_number,
            page_end=item.page_end,
        )
        for idx, item in enumerate(merged)
    ]


def _is_ultra_short_noise_snippet(snippet: Snippet) -> bool:
    """判定合并后仍残留的致谢、目录碎片、纯页码/水印或极短无信息残片。"""
    stripped = snippet.content.strip()
    if not stripped:
        return True
    if len(stripped) >= 120:
        return False
    chapter = snippet.chapter_title.strip()
    if chapter and stripped == chapter and len(stripped) <= 30:
        return True
    if not strip_display_watermark_lines(stripped):
        return True
    role = classify_slide_or_page(stripped, 1, 1, is_slide_like=True)
    if role in {PageRole.THANK_YOU, PageRole.TOC, PageRole.REFERENCES, PageRole.LOW_INFO}:
        return True
    if len(stripped) >= _ULTRA_SHORT_NOISE_MAX_CHARS:
        return False
    if "$" in stripped or "=" in stripped or _SUBSTANTIVE_SHORT_TERM_RE.search(stripped):
        return False
    core = _PUNCT_SPACE_RE.sub("", _NUMBERED_PREFIX_RE.sub("", stripped))
    if len(core) < 12:
        return not (any(ch in "。！？" for ch in stripped) and len(core) >= 3)
    return False


def _filter_ultra_short_noise_snippets(snippets: list[Snippet]) -> list[Snippet]:
    """在至少保留一条实质切片的前提下，过滤孤立极短无信息碎片并重排 index。"""
    if len(snippets) <= 1:
        return snippets
    kept = [item for item in snippets if not _is_ultra_short_noise_snippet(item)]
    if not kept or len(kept) == len(snippets):
        return snippets
    return [
        Snippet(
            index=idx,
            content=item.content,
            char_count=item.char_count,
            start_offset=item.start_offset,
            end_offset=item.end_offset,
            chapter_title=item.chapter_title,
            source_ref=item.source_ref,
            doc_type=item.doc_type,
            page_number=item.page_number,
            page_end=item.page_end,
        )
        for idx, item in enumerate(kept)
    ]


def _unpack_paragraph_item(
    item: str | ParagraphInput,
    default_source_ref: str,
    default_doc_type: str,
) -> tuple[str, str, str, bool, int | None, int | None]:
    if isinstance(item, ParagraphInput):
        return (
            item.text,
            item.source_ref,
            item.doc_type,
            item.is_title,
            item.page_number,
            item.page_end,
        )
    return item, default_source_ref, default_doc_type, False, None, None


def split_material_into_snippets(
    paragraphs: Sequence[str | ParagraphInput],
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
    min_chars: int = DEFAULT_MIN_CHARS,
    max_snippets: int = DEFAULT_MAX_SNIPPETS,
    default_doc_type: str = "txt",
    default_source_ref: str = "段落",
    target_chars: int = DEFAULT_TARGET_CHARS,
    *,
    filter_short_noise: bool | None = None,
    allow_cross_page_merge: bool = True,
) -> ChunkingResult:
    """把解析后的段落序列切分为可检索的知识片段。

    Args:
        paragraphs: 段落序列，支持原生字符串或 ParagraphInput 结构体。
        max_chars: 单个片段字符数上限，默认 800（硬限制）。
        overlap_chars: 相邻片段字符重叠量，默认 120。
        min_chars: 孤立短片段合并下限字符数，默认 120。
        max_snippets: 单份资料切片上限安全门槛，默认 3000。
        default_doc_type: 字符串段落默认的资料类型标记。
        default_source_ref: 字符串段落默认的来源标记。
        target_chars: 同页同章连续段落聚合的目标块大小，默认 500。

    Returns:
        ChunkingResult: 包含只读知识片段列表、截断状态与审计元数据的包装对象。

    Raises:
        ValueError: 当 max_chars <= 0、overlap_chars < 0、min_chars < 0、
            target_chars < 0 或 max_snippets <= 0 时抛出。
    """
    if max_chars <= 0:
        raise ValueError("max_chars must be a positive integer")
    if overlap_chars < 0:
        raise ValueError("overlap_chars must be a non-negative integer")
    if min_chars < 0:
        raise ValueError("min_chars must be a non-negative integer")
    if target_chars < 0:
        raise ValueError("target_chars must be a non-negative integer")
    if max_snippets <= 0:
        raise ValueError("max_snippets must be a positive integer")

    warnings_list: list[str] = []
    effective_overlap = overlap_chars
    if overlap_chars >= max_chars:
        effective_overlap = 0
        warnings_list.append(
            f"overlap_chars ({overlap_chars}) >= max_chars ({max_chars}), degraded to 0 overlap"
        )

    # 阶段 1: 文本预清洗与段落标准化
    should_filter = (min_chars >= 40) if filter_short_noise is None else filter_short_noise
    total_cleaned_chars = 0
    current_chapter_title = ""
    raw_snippets: list[Snippet] = []
    global_char_offset = 0

    for item in paragraphs:
        raw_text, source_ref, doc_type, is_title, page_number, page_end = _unpack_paragraph_item(
            item, default_source_ref, default_doc_type
        )

        cleaned_text, removed_count = clean_text_and_count_removals(raw_text)
        cleaned_text = clean_pseudo_bullet_glyphs(cleaned_text)
        total_cleaned_chars += removed_count

        if not cleaned_text.strip():
            continue

        if is_title:
            candidate_title = _MD_HEADING_PREFIX_RE.sub("", cleaned_text.strip()).strip()
            if is_valid_chapter_title(candidate_title):
                current_chapter_title = candidate_title
                continue

        if (
            should_filter
            and current_chapter_title
            and cleaned_text.strip() == current_chapter_title
            and len(cleaned_text.strip()) <= 30
        ):
            continue

        para_start_offset = global_char_offset
        ranges = split_paragraph_into_ranges(cleaned_text, max_chars, effective_overlap)

        for start_idx, end_idx in ranges:
            snippet_content = cleaned_text[start_idx:end_idx]
            raw_snippets.append(
                Snippet(
                    index=len(raw_snippets),
                    content=snippet_content,
                    char_count=len(snippet_content),
                    start_offset=para_start_offset + start_idx,
                    end_offset=para_start_offset + end_idx,
                    chapter_title=current_chapter_title,
                    source_ref=source_ref,
                    doc_type=doc_type,
                    page_number=page_number,
                    page_end=page_end,
                )
            )

        global_char_offset += len(cleaned_text)

    # 阶段 2: 短段循环累积合并 + 同页/同章邻页目标块聚合
    optimized_snippets = merge_isolated_short_snippets(
        raw_snippets,
        min_chars,
        max_chars,
        target_chars,
        allow_cross_page_merge=allow_cross_page_merge,
    )

    # 阶段 2.5: 过滤合并后仍残留的孤立无信息极短残片（默认仅在正常合并阈值 >= 40 时启用）
    if should_filter:
        optimized_snippets = _filter_ultra_short_noise_snippets(optimized_snippets)

    total_count = len(optimized_snippets)

    # 阶段 3: 3000 上限安全截断
    is_truncated = False
    if total_count > max_snippets:
        is_truncated = True
        warnings_list.append(
            f"Total snippets ({total_count}) exceeded max_snippets ({max_snippets}), "
            f"truncated to {max_snippets}"
        )
        final_snippets = tuple(optimized_snippets[:max_snippets])
    else:
        final_snippets = tuple(optimized_snippets)

    return ChunkingResult(
        snippets=final_snippets,
        total_count=total_count,
        is_truncated=is_truncated,
        max_chars=max_chars,
        overlap_chars=effective_overlap,
        cleaned_chars_count=total_cleaned_chars,
        warnings=tuple(warnings_list),
    )
