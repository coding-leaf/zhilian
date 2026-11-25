"""Semantic page annotation and logical-unit chunking pure algorithm kernel.

Pure functional kernel (zero ORM, zero SQLAlchemy, zero network/file IO):
1. Plans 8-page / 8000-char sliding batches for LLM semantic tagging;
2. Filters non-substantive template pages (with an all-empty fallback guard);
3. Aggregates contiguous pages sharing the same logical unit and topic title
   (preserving ``page_number..page_end`` and ``source_ref="第 X-Y 页"``);
4. Splits oversized logical units at ``max_chars=1400`` while protecting
   ``$$...$$`` display math, ``$...$`` inline math, and Markdown pipe tables.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from app.core.algorithms.document_denoising import is_non_substantive_chapter
from app.core.algorithms.material_chunking import (
    DEFAULT_MAX_SNIPPETS,
    DEFAULT_OVERLAP_CHARS,
    ChunkingResult,
    Snippet,
    clean_pseudo_bullet_glyphs,
    clean_text_and_count_removals,
    is_valid_chapter_title,
    split_paragraph_into_ranges,
)

SEMANTIC_UNIT_MAX_CHARS: int = 1400
SEMANTIC_UNIT_OVERLAP_CHARS: int = DEFAULT_OVERLAP_CHARS
SEMANTIC_BATCH_MAX_PAGES: int = 8
SEMANTIC_BATCH_MAX_CHARS: int = 8000
MAX_TOPIC_TITLE_CHARS: int = 24


@dataclass(frozen=True)
class SemanticPageInput:
    """Normalized page input for semantic annotation and unit chunking."""

    page_number: int
    text: str
    used_vlm: bool = False
    needs_formula_repair_hint: bool = False


@dataclass(frozen=True)
class PageSemanticAnnotation:
    """Lightweight per-page semantic tag produced by the sliding-window LLM pass."""

    page_number: int
    topic_title: str
    is_substantive: bool = True
    merge_with_prev: bool = False
    needs_formula_repair: bool = False
    repaired_markdown: str | None = None


@dataclass(frozen=True)
class LogicalUnit:
    """Cohesive cross-page logical unit ready for range splitting."""

    topic_title: str
    content: str
    page_number: int
    page_end: int | None
    source_ref: str
    doc_type: str = "pdf"


def plan_semantic_batches(
    pages: Sequence[SemanticPageInput],
    *,
    max_pages: int = SEMANTIC_BATCH_MAX_PAGES,
    max_chars: int = SEMANTIC_BATCH_MAX_CHARS,
) -> list[list[SemanticPageInput]]:
    """Group ordered pages into batches bounded by page count and character budget."""
    if not pages:
        return []
    safe_max_pages = max(1, max_pages)
    safe_max_chars = max(1, max_chars)

    batches: list[list[SemanticPageInput]] = []
    current_batch: list[SemanticPageInput] = []
    current_chars = 0

    for page in pages:
        page_len = len(page.text)
        exceeds_pages = len(current_batch) >= safe_max_pages
        exceeds_chars = bool(current_batch) and (current_chars + page_len > safe_max_chars)
        if exceeds_pages or exceeds_chars:
            batches.append(current_batch)
            current_batch = []
            current_chars = 0
        current_batch.append(page)
        current_chars += page_len

    if current_batch:
        batches.append(current_batch)
    return batches


def normalize_topic_title(title: str, fallback: str = "") -> str:
    """Normalize a semantic topic title, rejecting math-formula noise and overlong strings."""
    cleaned, _ = clean_text_and_count_removals(title)
    candidate = cleaned.strip().lstrip("#").strip()
    if (
        not candidate
        or not is_valid_chapter_title(candidate)
        or is_non_substantive_chapter(candidate)
    ):
        return fallback
    if len(candidate) > MAX_TOPIC_TITLE_CHARS:
        return candidate[:MAX_TOPIC_TITLE_CHARS].rstrip()
    return candidate


def resolve_page_effective_text(
    page: SemanticPageInput,
    annotation: PageSemanticAnnotation | None,
) -> tuple[str, int]:
    """Select repaired or original page text (Zero-Rewrite by default for clean/VLM pages)."""
    raw_text = page.text
    if (
        annotation is not None
        and not page.used_vlm
        and annotation.needs_formula_repair
        and annotation.repaired_markdown
        and annotation.repaired_markdown.strip()
    ):
        raw_text = annotation.repaired_markdown
    cleaned, removed = clean_text_and_count_removals(raw_text)
    cleaned = clean_pseudo_bullet_glyphs(cleaned).strip()
    return cleaned, removed


def _format_page_source_ref(page_start: int, page_end: int | None) -> str:
    if page_end is not None and page_end > page_start:
        return f"第 {page_start}-{page_end} 页"
    return f"第 {page_start} 页"


def _select_substantive_pages(
    pages: Sequence[SemanticPageInput],
    ann_map: dict[int, PageSemanticAnnotation],
) -> list[tuple[SemanticPageInput, PageSemanticAnnotation | None]]:
    """Filter non-substantive pages while preserving all pages if every page was filtered."""
    non_empty = [(p, ann_map.get(p.page_number)) for p in pages if p.text.strip()]
    if not non_empty:
        return []
    kept = [(p, ann) for p, ann in non_empty if ann is None or ann.is_substantive]
    return kept if kept else non_empty


def aggregate_logical_units(
    pages: Sequence[SemanticPageInput],
    annotations: Sequence[PageSemanticAnnotation],
    *,
    doc_type: str = "pdf",
) -> tuple[list[LogicalUnit], int]:
    """Aggregate substantive pages into cohesive cross-page logical units."""
    ann_map = {ann.page_number: ann for ann in annotations}
    selected = _select_substantive_pages(pages, ann_map)
    if not selected:
        return [], 0

    units: list[LogicalUnit] = []
    total_removed = 0
    last_topic = ""

    for page, ann in selected:
        effective_text, removed = resolve_page_effective_text(page, ann)
        total_removed += removed
        if not effective_text:
            continue

        raw_topic = ann.topic_title if ann is not None else ""
        topic = normalize_topic_title(raw_topic, fallback=last_topic)
        if topic:
            last_topic = topic

        should_merge = bool(
            units
            and ann is not None
            and ann.merge_with_prev
            and units[-1].topic_title == topic
            and (units[-1].page_end or units[-1].page_number) < page.page_number
        )
        if should_merge:
            prev = units[-1]
            combined = f"{prev.content}\n\n{effective_text}"
            units[-1] = LogicalUnit(
                topic_title=prev.topic_title,
                content=combined,
                page_number=prev.page_number,
                page_end=page.page_number,
                source_ref=_format_page_source_ref(prev.page_number, page.page_number),
                doc_type=doc_type,
            )
        else:
            units.append(
                LogicalUnit(
                    topic_title=topic,
                    content=effective_text,
                    page_number=page.page_number,
                    page_end=None,
                    source_ref=_format_page_source_ref(page.page_number, None),
                    doc_type=doc_type,
                )
            )
    return units, total_removed


def build_semantic_snippets(
    pages: Sequence[SemanticPageInput],
    annotations: Sequence[PageSemanticAnnotation],
    *,
    max_chars: int = SEMANTIC_UNIT_MAX_CHARS,
    overlap_chars: int = SEMANTIC_UNIT_OVERLAP_CHARS,
    max_snippets: int = DEFAULT_MAX_SNIPPETS,
    doc_type: str = "pdf",
) -> ChunkingResult:
    """Convert semantically annotated pages into protected, provenance-preserving Snippets."""
    if max_chars <= 0:
        raise ValueError("max_chars must be a positive integer")
    if overlap_chars < 0:
        raise ValueError("overlap_chars must be a non-negative integer")
    if max_snippets <= 0:
        raise ValueError("max_snippets must be a positive integer")

    warnings_list: list[str] = []
    effective_overlap = overlap_chars
    if overlap_chars >= max_chars:
        effective_overlap = 0
        warnings_list.append(
            f"overlap_chars ({overlap_chars}) >= max_chars ({max_chars}), degraded to 0 overlap"
        )

    units, total_removed = aggregate_logical_units(pages, annotations, doc_type=doc_type)
    snippets: list[Snippet] = []
    global_offset = 0

    for unit in units:
        ranges = split_paragraph_into_ranges(unit.content, max_chars, effective_overlap)
        unit_start = global_offset
        for start_idx, end_idx in ranges:
            part = unit.content[start_idx:end_idx]
            snippets.append(
                Snippet(
                    index=len(snippets),
                    content=part,
                    char_count=len(part),
                    start_offset=unit_start + start_idx,
                    end_offset=unit_start + end_idx,
                    chapter_title=unit.topic_title,
                    source_ref=unit.source_ref,
                    doc_type=unit.doc_type,
                    page_number=unit.page_number,
                    page_end=unit.page_end,
                )
            )
        global_offset += len(unit.content)

    is_truncated = len(snippets) > max_snippets
    if is_truncated:
        warnings_list.append(
            f"Snippet count ({len(snippets)}) exceeded max_snippets ({max_snippets}), truncated"
        )
        snippets = snippets[:max_snippets]

    return ChunkingResult(
        snippets=tuple(snippets),
        total_count=len(snippets),
        is_truncated=is_truncated,
        max_chars=max_chars,
        overlap_chars=effective_overlap,
        cleaned_chars_count=total_removed,
        warnings=tuple(warnings_list),
    )


def reindex_snippets(
    snippets: Sequence[Snippet],
    *,
    max_chars: int = SEMANTIC_UNIT_MAX_CHARS,
    overlap_chars: int = SEMANTIC_UNIT_OVERLAP_CHARS,
    max_snippets: int = DEFAULT_MAX_SNIPPETS,
    cleaned_chars_count: int = 0,
    warnings: Sequence[str] = (),
) -> ChunkingResult:
    """Re-index merged snippets from semantic and fallback batches into one ChunkingResult."""
    warnings_list = list(warnings)
    capped = list(snippets)
    is_truncated = len(capped) > max_snippets
    if is_truncated:
        warnings_list.append(
            f"Snippet count ({len(capped)}) exceeded max_snippets ({max_snippets}), truncated"
        )
        capped = capped[:max_snippets]

    reindexed: list[Snippet] = []
    cursor = 0
    for idx, item in enumerate(capped):
        length = len(item.content)
        reindexed.append(
            Snippet(
                index=idx,
                content=item.content,
                char_count=length,
                start_offset=cursor,
                end_offset=cursor + length,
                chapter_title=item.chapter_title,
                source_ref=item.source_ref,
                doc_type=item.doc_type,
                page_number=item.page_number,
                page_end=item.page_end,
            )
        )
        cursor += length

    return ChunkingResult(
        snippets=tuple(reindexed),
        total_count=len(reindexed),
        is_truncated=is_truncated,
        max_chars=max_chars,
        overlap_chars=overlap_chars,
        cleaned_chars_count=cleaned_chars_count,
        warnings=tuple(warnings_list),
    )


__all__ = [
    "MAX_TOPIC_TITLE_CHARS",
    "SEMANTIC_BATCH_MAX_CHARS",
    "SEMANTIC_BATCH_MAX_PAGES",
    "SEMANTIC_UNIT_MAX_CHARS",
    "SEMANTIC_UNIT_OVERLAP_CHARS",
    "LogicalUnit",
    "PageSemanticAnnotation",
    "SemanticPageInput",
    "aggregate_logical_units",
    "build_semantic_snippets",
    "normalize_topic_title",
    "plan_semantic_batches",
    "reindex_snippets",
    "resolve_page_effective_text",
]
