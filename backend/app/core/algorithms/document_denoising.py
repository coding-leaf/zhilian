"""Document cross-page denoising, slide/page role classification, and evidence ranking.

Pure functional kernel for:
1. Cross-page repeated header, footer, page-number, and institutional watermark removal;
2. Page/slide role classification (cover, TOC, section divider, summary, references, content);
3. Non-substantive chapter filtering shared across chunking, knowledge tree, and quality gates;
4. Write-time and read-time evidence snippet denoising and relevance ranking.

Zero ORM, SQLAlchemy, or network/filesystem I/O.
"""

import enum
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


class PageRole(enum.StrEnum):
    """Semantic role of a single PDF page or PPTX slide."""

    COVER = "cover"
    TOC = "toc"
    SECTION_DIVIDER = "section_divider"
    CHAPTER_SUMMARY = "chapter_summary"
    REFERENCES = "references"
    THANK_YOU = "thank_you"
    LOW_INFO = "low_info"
    CONTENT = "content"


@dataclass(frozen=True)
class PageTextBlock:
    """Positioned text block extracted from a document page."""

    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    page_width: float
    page_height: float


@dataclass(frozen=True)
class PageTextInput:
    """Page-level text and optional layout blocks for cross-page denoising."""

    page_number: int
    text: str
    blocks: tuple[PageTextBlock, ...] = ()


class EvidenceSnippetLike(Protocol):
    """Minimal duck-typed snippet protocol for evidence filtering and ranking."""

    @property
    def content(self) -> str: ...

    @property
    def chapter_title(self) -> str: ...

    @property
    def snippet_index(self) -> int: ...


# ---------------------------------------------------------------------------
# Shared non-substantive chapter / template patterns
# ---------------------------------------------------------------------------

_CHAPTER_PREFIX_RE: re.Pattern[str] = re.compile(
    r"^\s*(?:#{1,6}\s*|第\s*[一二三四五六七八九十百\d]+\s*[章节讲篇部]\s*|"
    r"[一二三四五六七八九十]+\s*[、.．]\s*|\d+(?:\.\d+)*\s*[、.．)]\s*|"
    r"\([一二三四五六七八九十\d]+\)\s*)*"
)

NON_SUBSTANTIVE_CHAPTER_PATTERNS: re.Pattern[str] = re.compile(
    r"(?:^(?:本章|本节|课程|知识|重点|期末)?(?:小结|总结|知识小结|知识梳理|梳理|"
    r"回顾|重点回顾|目录|提纲|大纲|内容提要|课程内容|主要内容|内容概览|"
    r"封面|致谢|感谢|参考文献|参考资料|参考书目|附录|课后习题|思考题|作业|"
    r"课程介绍|教学目标|学习目标|引言|前言|序言|答疑|讨论与交流|"
    r"q\s*&\s*a|summary|recap|contents|outline|agenda|references|"
    r"bibliography|thank\s*you|thanks|appendix|exercises)$|"
    r"(?:本章|本节)?知识(?:小结|总结)梳理|课后(?:思考题|习题|作业))",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Watermark, page number, and template page patterns
# ---------------------------------------------------------------------------

_PURE_PAGE_NUMBER_RE: re.Pattern[str] = re.compile(
    r"^\s*(?:第\s*\d+\s*页(?:\s*/\s*共\s*\d+\s*页)?|\d+\s*/\s*\d+|"
    r"-\s*\d+\s*-|—\s*\d+\s*—|page\s+\d+(?:\s+of\s+\d+)?|\[\s*\d+\s*\])\s*$",
    re.IGNORECASE,
)

_CHINESE_INSTITUTION_LINE_RE: re.Pattern[str] = re.compile(
    r"^[\u4e00-\u9fff·•\s]{2,18}(?:大学|大學|学院|學院|师范大学|師範大學|"
    r"师范学院|師範學院|理工大学|理工大學|研究院|实验室|實驗室)"
    r"(?:[\s·\-—|]+[\u4e00-\u9fffA-Za-z\s.&-]{2,45})?$"
)

_ENGLISH_INSTITUTION_LINE_RE: re.Pattern[str] = re.compile(
    r"^[A-Za-z\s.&,'\-]{4,60}\b(?:UNIVERSITY|COLLEGE|INSTITUTE|SCHOOL)\b[A-Za-z\s.&,'\-]*$",
    re.IGNORECASE,
)

_THANK_YOU_KEYWORD_RE: re.Pattern[str] = re.compile(
    r"^(?:谢谢(?:大家|各位|聆听|观看|欣赏)?|感谢(?:大家|各位|聆听|观看)?|"
    r"敬请(?:各位老师同学)?(?:批评)?指正|批评指正|请多指教|完|结束|"
    r"the\s*end|thank\s*you(?:\s+(?:very\s+much|for\s+(?:listening|watching|your\s+attention)))?|"
    r"thanks(?:\s+for\s+(?:listening|watching))?|q\s*&\s*a|questions?(?:\s*&\s*answers?)?|"
    r"答疑(?:与交流)?|讨论与交流)$",
    re.IGNORECASE,
)

_TOC_HEADER_RE: re.Pattern[str] = re.compile(
    r"^(?:目录|目\s*录|提纲|大纲|内容提要|课程内容|本章内容|主要内容|内容概览|"
    r"contents|table\s+of\s+contents|outline|agenda)$",
    re.IGNORECASE,
)

_SUMMARY_HEADER_RE: re.Pattern[str] = re.compile(
    r"^(?:小结|本章小结|本节小结|课程小结|知识小结|知识小结梳理|知识梳理|"
    r"知识回顾|重点回顾|本章总结|总结|summary|recap|review)$",
    re.IGNORECASE,
)

_REFERENCES_HEADER_RE: re.Pattern[str] = re.compile(
    r"^(?:参考文献|参考资料|参考书目|references|bibliography)$",
    re.IGNORECASE,
)

_CITATION_LINE_RE: re.Pattern[str] = re.compile(r"^\s*(?:\[\d+\]|\(\d+\))\s+\S+")
_LIST_ITEM_LINE_RE: re.Pattern[str] = re.compile(
    r"^\s*(?:[-*•▪▫◆◇●○]|\d+[.、)．]|[一二三四五六七八九十]+[、.．]|\(\d+\))\s*\S+"
)
_INLINE_LIST_SPLIT_RE: re.Pattern[str] = re.compile(r"(?:^|\s)\d+[.、．]\s*\S+")
_COVER_META_RE: re.Pattern[str] = re.compile(
    r"(?:主讲|授课|教师|讲师|学院|大学|大學|第\s*[一二三四五六七八九十\d]+\s*章|"
    r"课程|课件|ppt|汇报|lecturer|instructor|chapter\s+\d+)",
    re.IGNORECASE,
)

_STRIP_EDGE_PUNCT_RE: re.Pattern[str] = re.compile(
    r"[\s。！？!?.,，、；;：:~～·…—\-_()（）\[\]【】\"'“”‘’]+"
)
_STRIP_TITLE_EDGE_RE: re.Pattern[str] = re.compile(r"^[\s#*>•\-:：]+|[\s。！？!?.,，、:：]+$")
_DIGITS_AND_SPACE_RE: re.Pattern[str] = re.compile(r"[\d\s]+")
_TRAILING_PROSE_STOP: tuple[str, ...] = ("。", "！", "？", "!", "?", "；", ";", "，", ",")
_FORMULA_OR_EQUAL_RE: re.Pattern[str] = re.compile(r"(?:\$|\\\[|\\begin\{|=|≤|≥|∈|∑|∫)")
_SUBSTANTIVE_CUES_RE: re.Pattern[str] = re.compile(
    r"(?:定义|定理|公式|性质|推导|条件|步骤|原理|算法|目标函数|约束|证明|假设|等价于|是指|称为)"
)
_CJK_OR_WORD_TOKEN_RE: re.Pattern[str] = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2}")

_MIN_CROSS_PAGE_DENOISE_PAGES: int = 4
_BAND_TOP_RATIO: float = 0.16
_BAND_BOTTOM_RATIO: float = 0.84
_Y_CONSISTENCY_TOLERANCE: float = 0.06
_HEADER_FOOTER_MAX_LEN: int = 80
_LINE_FALLBACK_MAX_LEN: int = 60
_MULTI_BLANK_LINES_RE: re.Pattern[str] = re.compile(r"\n{3,}")
_SECTION_FORBIDDEN_CHARS: frozenset[str] = frozenset("。！？!?;；=$\\|`")


def is_non_substantive_chapter(title: str | None) -> bool:
    """Return True if a chapter title denotes a structural/template section."""
    if not title or not title.strip():
        return False
    stripped = _CHAPTER_PREFIX_RE.sub("", title.strip())
    core = _STRIP_TITLE_EDGE_RE.sub("", stripped)
    if not core:
        return False
    return bool(NON_SUBSTANTIVE_CHAPTER_PATTERNS.search(core))


def _is_standalone_page_number_line(line: str) -> bool:
    """Return True if a single line is purely a page counter or pagination marker."""
    return bool(_PURE_PAGE_NUMBER_RE.match(line.strip()))


def _is_standalone_institution_watermark_line(line: str) -> bool:
    """Return True if a single short line is an isolated university/college watermark."""
    stripped = line.strip()
    if not stripped or len(stripped) > 65:
        return False
    if any(ch in "。！？!?=;$" for ch in stripped):
        return False
    if _CHINESE_INSTITUTION_LINE_RE.match(stripped):
        return True
    has_cjk = bool(re.search(r"[\u4e00-\u9fff]", stripped))
    return bool(not has_cjk and _ENGLISH_INSTITUTION_LINE_RE.match(stripped))


def strip_display_watermark_lines(text: str) -> str:
    """Strip isolated institutional watermark lines and pure page-number lines."""
    if not text or not text.strip():
        return ""
    kept: list[str] = []
    for raw_line in text.splitlines():
        if _is_standalone_page_number_line(raw_line):
            continue
        if _is_standalone_institution_watermark_line(raw_line):
            continue
        kept.append(raw_line)
    cleaned = "\n".join(kept).strip()
    return _MULTI_BLANK_LINES_RE.sub("\n\n", cleaned)


def _normalize_for_cross_page_freq(text: str) -> str:
    """Normalize a line or block by stripping digits/spaces and lowercasing."""
    return _DIGITS_AND_SPACE_RE.sub("", text).lower()


def _record_block_candidates(
    page: PageTextInput,
    block_pages: dict[str, set[int]],
    block_y_ratios: dict[str, list[float]],
    block_in_band: dict[str, bool],
) -> None:
    """Record positioned block candidates from a multi-block page."""
    if len(page.blocks) < 2:
        return
    pn = page.page_number
    for blk in page.blocks:
        ph = blk.page_height if blk.page_height > 0 else 1.0
        in_band = (blk.y1 <= _BAND_TOP_RATIO * ph) or (blk.y0 >= _BAND_BOTTOM_RATIO * ph)
        y_ratio = blk.y0 / ph
        candidates = [blk.text.strip(), *(ln.strip() for ln in blk.text.splitlines())]
        for cand in candidates:
            if (
                not cand
                or len(cand) > _HEADER_FOOTER_MAX_LEN
                or "$" in cand
                or "=" in cand
                or any(ch in "。！？!?" for ch in cand)
            ):
                continue
            norm = _normalize_for_cross_page_freq(cand)
            if not norm:
                continue
            block_pages.setdefault(norm, set()).add(pn)
            block_y_ratios.setdefault(norm, []).append(y_ratio)
            if in_band:
                block_in_band[norm] = True


def _record_line_candidates(
    page: PageTextInput,
    line_pages: dict[str, set[int]],
    edge_line_pages: dict[str, set[int]],
) -> None:
    """Record line-level header/footer candidates from pages with >= 2 non-empty lines."""
    lines = [ln.strip() for ln in page.text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return
    pn = page.page_number
    for idx, ln in enumerate(lines):
        if (
            len(ln) > _LINE_FALLBACK_MAX_LEN
            or "$" in ln
            or "=" in ln
            or any(ch in "。！？!?" for ch in ln)
        ):
            continue
        norm = _normalize_for_cross_page_freq(ln)
        if not norm:
            continue
        line_pages.setdefault(norm, set()).add(pn)
        if idx < 2 or idx >= len(lines) - 2:
            edge_line_pages.setdefault(norm, set()).add(pn)


def _collect_cross_page_noise_keys(pages: Sequence[PageTextInput]) -> set[str]:
    """Identify normalized text keys that repeat across pages as headers/footers/watermarks."""
    total_pages = len(pages)
    if total_pages < _MIN_CROSS_PAGE_DENOISE_PAGES:
        return set()

    min_band_hits = max(3, math.ceil(0.35 * total_pages))
    min_line_hits = max(3, math.ceil(0.40 * total_pages))

    block_pages: dict[str, set[int]] = {}
    block_y_ratios: dict[str, list[float]] = {}
    block_in_band: dict[str, bool] = {}
    line_pages: dict[str, set[int]] = {}
    edge_line_pages: dict[str, set[int]] = {}

    for page in pages:
        _record_block_candidates(page, block_pages, block_y_ratios, block_in_band)
        _record_line_candidates(page, line_pages, edge_line_pages)

    noise_keys: set[str] = set()
    for norm, pns in block_pages.items():
        if len(pns) < min_band_hits:
            continue
        ratios = sorted(block_y_ratios[norm])
        median_y = ratios[len(ratios) // 2]
        consistent_y = all(abs(r - median_y) <= _Y_CONSISTENCY_TOLERANCE for r in ratios)
        if block_in_band.get(norm, False) or consistent_y:
            noise_keys.add(norm)

    for norm, pns in edge_line_pages.items():
        if len(pns) >= min_band_hits:
            noise_keys.add(norm)

    for norm, pns in line_pages.items():
        if len(pns) >= min_line_hits:
            noise_keys.add(norm)

    return noise_keys


def _filter_page_lines(text: str, noise_keys: set[str]) -> str:
    """Filter deterministic watermark lines and cross-page repeated noise from one page."""
    paragraphs = re.split(r"\n\s*\n", text.strip())
    kept_paragraphs: list[str] = []
    for para in paragraphs:
        kept_lines: list[str] = []
        for raw_line in para.splitlines():
            stripped = raw_line.strip()
            if not stripped:
                continue
            if _is_standalone_page_number_line(stripped):
                continue
            if _is_standalone_institution_watermark_line(stripped):
                continue
            if noise_keys and len(stripped) <= _HEADER_FOOTER_MAX_LEN:
                norm = _normalize_for_cross_page_freq(stripped)
                if norm in noise_keys:
                    continue
            kept_lines.append(stripped)
        if kept_lines:
            kept_paragraphs.append("\n".join(kept_lines))
    return "\n\n".join(kept_paragraphs).strip()


def strip_repeated_headers_footers(pages: Sequence[PageTextInput]) -> list[str]:
    """Remove repeated headers, footers, page numbers, and institutional watermarks."""
    if not pages:
        return []
    noise_keys = _collect_cross_page_noise_keys(pages)
    return [_filter_page_lines(page.text, noise_keys) for page in pages]


def _normalize_header_line(line: str) -> str:
    """Strip markdown heading markers, numbering prefixes, and punctuation."""
    stripped = _CHAPTER_PREFIX_RE.sub("", line.strip())
    return _STRIP_TITLE_EDGE_RE.sub("", stripped)


def _is_thank_you_page(text: str) -> bool:
    """Return True if page text is a closing/thank-you/Q&A slide (punctuation-safe)."""
    compact = _STRIP_EDGE_PUNCT_RE.sub("", text)
    if not compact or len(compact) > 40:
        return False
    if _THANK_YOU_KEYWORD_RE.match(compact):
        return True
    segments = [
        _STRIP_EDGE_PUNCT_RE.sub("", seg) for seg in re.split(r"[\n。！？!?]+", text) if seg.strip()
    ]
    non_empty = [seg for seg in segments if seg]
    return bool(
        non_empty
        and len(non_empty) <= 3
        and all(_THANK_YOU_KEYWORD_RE.match(seg) for seg in non_empty)
    )


def _is_toc_page(text: str, lines: Sequence[str]) -> bool:
    """Return True if page text is an outline or table-of-contents slide/page."""
    first_norm = _normalize_header_line(lines[0])
    if _TOC_HEADER_RE.match(first_norm):
        return True
    if _FORMULA_OR_EQUAL_RE.search(text):
        return False
    prose_stops = sum(text.count(ch) for ch in ("。", "；", ";"))
    if prose_stops > 1:
        return False
    list_lines = [ln for ln in lines if _LIST_ITEM_LINE_RE.match(ln)]
    if len(list_lines) >= 3 and len(list_lines) / len(lines) >= 0.60:
        avg_len = sum(len(ln) for ln in list_lines) / len(list_lines)
        if avg_len <= 22:
            return True
    inline_items = _INLINE_LIST_SPLIT_RE.findall(text)
    return len(inline_items) >= 3 and len(text) <= 200


def _is_empty_chapter_summary(text: str, lines: Sequence[str]) -> bool:
    """Return True if a summary slide only lists bare topics without tables/formulas."""
    first_norm = _normalize_header_line(lines[0])
    if not _SUMMARY_HEADER_RE.match(first_norm):
        return False
    body_lines = lines[1:]
    body_text = "\n".join(body_lines).strip()
    if not body_text:
        return True
    table_rows = sum(
        1 for ln in body_lines if ln.lstrip().startswith("|") and ln.rstrip().endswith("|")
    )
    if table_rows >= 2:
        return False
    formula_hits = len(_FORMULA_OR_EQUAL_RE.findall(body_text))
    effective_body_chars = sum(1 for ch in body_text if not ch.isspace())
    if formula_hits >= 2 and effective_body_chars >= 180:
        return False
    if effective_body_chars < 120:
        return True
    short_list_lines = sum(
        1 for ln in body_lines if len(ln) <= 22 and (_LIST_ITEM_LINE_RE.match(ln) or "。" not in ln)
    )
    return (short_list_lines / len(body_lines)) >= 0.60


def _is_references_page(lines: Sequence[str]) -> bool:
    """Return True if page text is a bibliography/references page."""
    first_norm = _normalize_header_line(lines[0])
    if _REFERENCES_HEADER_RE.match(first_norm):
        return True
    citation_count = sum(1 for ln in lines if _CITATION_LINE_RE.match(ln))
    return citation_count >= 2 and (citation_count / len(lines)) >= 0.50


def _is_cover_page(text: str, lines: Sequence[str], page_number: int, total_pages: int) -> bool:
    """Return True if page 1 of a multi-page deck/document is purely a title/cover slide."""
    if page_number != 1 or total_pages < _MIN_CROSS_PAGE_DENOISE_PAGES:
        return False
    effective_chars = sum(1 for ch in text if not ch.isspace())
    if effective_chars >= 100:
        return False
    if _FORMULA_OR_EQUAL_RE.search(text) or "。" in text:
        return False
    if _COVER_META_RE.search(text):
        return True
    return len(lines) <= 4 and effective_chars <= 50


def _is_section_divider(text: str, lines: Sequence[str]) -> bool:
    """Return True if page is a short standalone section transition slide."""
    if len(lines) > 2:
        return False
    effective_chars = sum(1 for ch in text if not ch.isspace())
    if effective_chars == 0 or effective_chars > 35:
        return False
    if any(ch in _SECTION_FORBIDDEN_CHARS for ch in text):
        return False
    if text.strip().endswith(_TRAILING_PROSE_STOP):
        return False
    joined = " ".join(lines).strip()
    if joined.isdigit():
        return False
    return not is_non_substantive_chapter(joined)


def classify_slide_or_page(
    text: str,
    page_number: int,
    total_pages: int,
    *,
    is_slide_like: bool = True,
) -> PageRole:
    """Classify a denoised page or slide into its semantic PageRole."""
    stripped = text.strip()
    if not stripped:
        return PageRole.LOW_INFO
    if _is_thank_you_page(stripped):
        return PageRole.THANK_YOU

    lines = [ln.strip() for ln in stripped.splitlines() if ln.strip()]
    if not lines:
        return PageRole.LOW_INFO
    if _is_references_page(lines):
        return PageRole.REFERENCES
    first_norm = _normalize_header_line(lines[0])
    if _SUMMARY_HEADER_RE.match(first_norm):
        return (
            PageRole.CHAPTER_SUMMARY
            if _is_empty_chapter_summary(stripped, lines)
            else PageRole.CONTENT
        )
    if _is_toc_page(stripped, lines):
        return PageRole.TOC
    if is_slide_like and _is_cover_page(stripped, lines, page_number, total_pages):
        return PageRole.COVER
    if _is_section_divider(stripped, lines):
        return PageRole.SECTION_DIVIDER

    meaningful_chars = _STRIP_EDGE_PUNCT_RE.sub("", stripped)
    if len(meaningful_chars) < 8 and not _FORMULA_OR_EQUAL_RE.search(stripped):
        return PageRole.LOW_INFO
    return PageRole.CONTENT


def classify_pages_with_fallback(
    pages: Sequence[tuple[int, str]],
    *,
    is_slide_like: bool = True,
) -> list[PageRole]:
    """Classify pages and fall back to CONTENT if no page qualifies as CONTENT."""
    total_pages = len(pages)
    if total_pages == 0:
        return []
    roles = [
        classify_slide_or_page(text, pn, total_pages, is_slide_like=is_slide_like)
        for pn, text in pages
    ]
    if any(role == PageRole.CONTENT for role in roles):
        return roles
    return [PageRole.CONTENT if text.strip() else PageRole.LOW_INFO for _pn, text in pages]


def _tokenize_for_relevance(text: str) -> set[str]:
    """Extract normalized word tokens and CJK bigrams for relevance scoring."""
    lowered = text.lower()
    tokens = set(_CJK_OR_WORD_TOKEN_RE.findall(lowered))
    cjk_runs = re.findall(r"[\u4e00-\u9fff]{2,}", lowered)
    for run in cjk_runs:
        for idx in range(len(run) - 1):
            tokens.add(run[idx : idx + 2])
    return tokens


def _is_noise_evidence_text(content: str, chapter_title: str) -> bool:
    """Return True if a snippet is non-substantive template/title/thank-you noise."""
    cleaned = strip_display_watermark_lines(content)
    if not cleaned:
        return True
    chapter = chapter_title.strip()
    if chapter and cleaned == chapter and len(cleaned) <= 30:
        return True
    if _is_thank_you_page(cleaned):
        return True
    lines = [ln.strip() for ln in cleaned.splitlines() if ln.strip()]
    if not lines:
        return True
    if (
        _is_toc_page(cleaned, lines)
        or _is_references_page(lines)
        or _is_empty_chapter_summary(cleaned, lines)
    ):
        return True
    if len(cleaned) < 15 and not _FORMULA_OR_EQUAL_RE.search(cleaned):
        has_stop = any(ch in "。！？!?." for ch in cleaned)
        core_len = len(_STRIP_EDGE_PUNCT_RE.sub("", cleaned))
        return not has_stop or core_len < 6
    return False


def _score_evidence_snippet(
    cleaned_content: str,
    kp_tokens: set[str],
) -> float:
    """Score snippet relevance and informational density for a target knowledge point."""
    snippet_tokens = _tokenize_for_relevance(cleaned_content)
    overlap = len(kp_tokens & snippet_tokens) if kp_tokens else 0
    overlap_score = overlap / max(1, len(kp_tokens)) if kp_tokens else 0.0
    formula_bonus = 0.35 if _FORMULA_OR_EQUAL_RE.search(cleaned_content) else 0.0
    cue_bonus = 0.25 if _SUBSTANTIVE_CUES_RE.search(cleaned_content) else 0.0
    density_bonus = min(len(cleaned_content), 500) / 500.0 * 0.25
    return overlap_score * 2.0 + formula_bonus + cue_bonus + density_bonus


def filter_and_rank_evidence_snippets[TSnippet: EvidenceSnippetLike](
    snippets: Sequence[TSnippet],
    kp_name: str,
    kp_summary: str = "",
    *,
    max_items: int = 5,
) -> list[TSnippet]:
    """Filter out noisy/template snippets and rank remaining evidence by relevance."""
    if not snippets or max_items <= 0:
        return []

    kp_tokens = _tokenize_for_relevance(f"{kp_name} {kp_summary}")
    scored: list[tuple[float, int, TSnippet]] = []
    for snip in snippets:
        raw_content = snip.content or ""
        chapter = snip.chapter_title or ""
        if _is_noise_evidence_text(raw_content, chapter):
            continue
        cleaned = strip_display_watermark_lines(raw_content)
        score = _score_evidence_snippet(cleaned, kp_tokens)
        scored.append((score, -snip.snippet_index, snip))

    if not scored:
        return []
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in scored[:max_items]]


__all__ = [
    "NON_SUBSTANTIVE_CHAPTER_PATTERNS",
    "PageRole",
    "PageTextBlock",
    "PageTextInput",
    "classify_pages_with_fallback",
    "classify_slide_or_page",
    "filter_and_rank_evidence_snippets",
    "is_non_substantive_chapter",
    "strip_display_watermark_lines",
    "strip_repeated_headers_footers",
]
