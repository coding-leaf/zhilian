"""8-page sliding-window semantic tagging and formula-repair service.

Uses a lightweight LLM (e.g. ``deepseek-flash``) with Zero-Rewrite-by-Default:
- Normal/VLM-reconstructed pages only emit lightweight metadata
  (``topic_title``, ``is_substantive``, ``merge_with_prev``, ``repaired_markdown=None``).
- Pages that skipped VLM or fell back from VLM and contain broken 2D math formulas
  (e.g. scattered ``|ω^T x_i + b|`` / ``||ω||`` fractions) receive
  ``needs_formula_repair=True`` and standard LaTeX reconstruction.
- Automatically bypassed for ``FakeLLMAdapter``, ``< 3`` pages, or when disabled.
- Any single batch failure silently degrades that batch to deterministic chunking.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.core.algorithms.material_chunking import (
    ChunkingResult,
    ParagraphInput,
    Snippet,
    split_material_into_snippets,
)
from app.core.algorithms.ocr_quality import has_scattered_math_blocks
from app.core.algorithms.semantic_chunking import (
    SEMANTIC_BATCH_MAX_CHARS,
    SEMANTIC_BATCH_MAX_PAGES,
    SEMANTIC_UNIT_MAX_CHARS,
    PageSemanticAnnotation,
    SemanticPageInput,
    build_semantic_snippets,
    normalize_topic_title,
    plan_semantic_batches,
    reindex_snippets,
)
from app.integrations.llm.fake import FakeLLMAdapter
from app.integrations.llm.protocol import LLMMessage, LLMOptions, LLMProtocol

_logger = logging.getLogger(__name__)

_MIN_PAGES_FOR_SEMANTIC_CHUNKING: int = 3
_SEMANTIC_CHUNK_MAX_TOKENS: int = 4096
_SEMANTIC_CHUNK_TIMEOUT: float = 35.0
_ANCHOR_TAIL_CHARS: int = 120

_SEMANTIC_SYSTEM_PROMPT: str = (
    "你是学术讲义结构化标注与局部公式修复助手。\n"
    "输入是一批按页排列的讲义页面（每页附带 page_number、used_vlm 与 formula_hint 标记）。\n"
    "请为输入中的每一页输出一条结构化标注：\n"
    "1. topic_title：2~24字的规范章节/知识主题名（跨页延续同一主题时严格复用上一页标题）；"
    "严禁把数学公式或符号表达式（如 ω^T x_i + b）当作主题名。\n"
    "2. is_substantive：仅封面、目录、过渡页、纯致谢、参考文献或无信息空白页为 false，"
    "其余正文为 true。\n"
    "3. merge_with_prev：若本页紧接上一页且同属一个未完结的定义、定理推导、证明或例题"
    "逻辑单元，设为 true。\n"
    "4. 默认 Zero-Rewrite：当 used_vlm=true 或页面公式完整可读时，"
    "必须设置 needs_formula_repair=false 且 repaired_markdown=null。\n"
    "5. 仅当 used_vlm=false 且页面存在明显散架的二维分式、上下标错位或残缺公式"
    "（例如独立成行的分子/分母 `|ω^T x_i + b|` / `||ω||`，常见于 formula_hint=true）时，"
    "才设置 needs_formula_repair=true，并在 repaired_markdown 中输出忠实还原为"
    "标准 `$...$` / `$$...$$` LaTeX 的该页完整正文；严禁总结、删减或编造原文没有的内容。"
)


class PageAnnotationSchema(BaseModel):
    """Single-page semantic annotation item returned by structured LLM output."""

    page_number: int
    topic_title: str = Field(default="", description="2~24字规范主题/章节名")
    is_substantive: bool = Field(default=True, description="是否为实质教学内容页")
    merge_with_prev: bool = Field(default=False, description="是否与上一页同属一个连续逻辑单元")
    needs_formula_repair: bool = Field(default=False, description="仅未走VLM且含散架公式时为true")
    repaired_markdown: str | None = Field(
        default=None,
        description="仅 needs_formula_repair=true 时输出修复后完整页面正文，否则必须为 null",
    )


class SemanticBatchAnnotationResponse(BaseModel):
    """Structured batch output wrapper for sliding-window page annotation."""

    pages: list[PageAnnotationSchema] = Field(default_factory=list)


@dataclass(frozen=True)
class SemanticChunkingOutcome:
    """Result of semantic chunking alongside any per-page formula-repaired markdown."""

    chunk_result: ChunkingResult
    repaired_page_texts: dict[int, str]


def should_use_semantic_chunking(
    pages: Sequence[SemanticPageInput],
    llm: LLMProtocol | None,
    *,
    enabled: bool = True,
) -> bool:
    """Return True when LLM sliding-window semantic tagging should run."""
    if not enabled or llm is None or isinstance(llm, FakeLLMAdapter):
        return False
    non_empty = sum(1 for p in pages if p.text.strip())
    return non_empty >= _MIN_PAGES_FOR_SEMANTIC_CHUNKING


def _enrich_formula_hints(pages: Sequence[SemanticPageInput]) -> list[SemanticPageInput]:
    enriched: list[SemanticPageInput] = []
    for page in pages:
        hint = page.needs_formula_repair_hint or (
            not page.used_vlm and has_scattered_math_blocks(page.text)
        )
        enriched.append(
            SemanticPageInput(
                page_number=page.page_number,
                text=page.text,
                used_vlm=page.used_vlm,
                needs_formula_repair_hint=hint,
            )
        )
    return enriched


def _build_batch_user_prompt(
    batch: Sequence[SemanticPageInput],
    *,
    last_topic_title: str,
    last_tail_summary: str,
) -> str:
    sections: list[str] = []
    if last_topic_title or last_tail_summary:
        sections.append(
            f"[上一批衔接锚点] topic={last_topic_title or '(无)'} | "
            f"结尾摘要={last_tail_summary or '(无)'}"
        )
    for page in batch:
        sections.append(
            f"[PAGE {page.page_number} | used_vlm={'true' if page.used_vlm else 'false'} | "
            f"formula_hint={'true' if page.needs_formula_repair_hint else 'false'}]\n"
            f"{page.text}"
        )
    return "\n\n---\n\n".join(sections)


def _to_domain_annotations(
    batch: Sequence[SemanticPageInput],
    parsed: SemanticBatchAnnotationResponse,
) -> list[PageSemanticAnnotation]:
    by_page = {item.page_number: item for item in parsed.pages}
    result: list[PageSemanticAnnotation] = []
    for page in batch:
        item = by_page.get(page.page_number)
        if item is None:
            result.append(PageSemanticAnnotation(page_number=page.page_number, topic_title=""))
            continue
        repaired = (
            item.repaired_markdown.strip()
            if (not page.used_vlm and item.needs_formula_repair and item.repaired_markdown)
            else None
        )
        result.append(
            PageSemanticAnnotation(
                page_number=page.page_number,
                topic_title=item.topic_title,
                is_substantive=item.is_substantive,
                merge_with_prev=item.merge_with_prev,
                needs_formula_repair=bool(repaired is not None),
                repaired_markdown=repaired,
            )
        )
    return result


def _fallback_batch_snippets(
    batch: Sequence[SemanticPageInput],
    fallback_paragraphs: Sequence[ParagraphInput],
    *,
    doc_type: str,
) -> ChunkingResult:
    batch_pages = {p.page_number for p in batch}
    scoped = [
        para
        for para in fallback_paragraphs
        if para.page_number is not None and para.page_number in batch_pages
    ]
    if not scoped:
        scoped = [
            ParagraphInput(
                text=p.text,
                source_ref=f"第 {p.page_number} 页",
                doc_type=doc_type,
                page_number=p.page_number,
            )
            for p in batch
            if p.text.strip()
        ]
    return split_material_into_snippets(
        scoped,
        max_chars=SEMANTIC_UNIT_MAX_CHARS,
        allow_cross_page_merge=True,
    )


def _annotate_single_batch(
    batch: Sequence[SemanticPageInput],
    llm: LLMProtocol,
    *,
    last_topic_title: str,
    last_tail_summary: str,
) -> list[PageSemanticAnnotation] | None:
    user_prompt = _build_batch_user_prompt(
        batch,
        last_topic_title=last_topic_title,
        last_tail_summary=last_tail_summary,
    )
    try:
        parsed, _resp = llm.generate_structured(
            messages=[
                LLMMessage(role="system", content=_SEMANTIC_SYSTEM_PROMPT),
                LLMMessage(role="user", content=user_prompt),
            ],
            response_model=SemanticBatchAnnotationResponse,
            options=LLMOptions(
                temperature=0.0,
                max_tokens=_SEMANTIC_CHUNK_MAX_TOKENS,
                timeout=_SEMANTIC_CHUNK_TIMEOUT,
            ),
        )
        return _to_domain_annotations(batch, parsed)
    except Exception as exc:
        _logger.warning(
            "semantic chunking batch degraded to deterministic fallback: pages=%s-%s error=%s",
            batch[0].page_number,
            batch[-1].page_number,
            type(exc).__name__,
        )
        return None


def _update_batch_anchors(
    batch: Sequence[SemanticPageInput],
    annotations: Sequence[PageSemanticAnnotation],
    prev_topic: str,
) -> tuple[str, str]:
    topic = prev_topic
    tail = ""
    ann_map = {a.page_number: a for a in annotations}
    for page in batch:
        ann = ann_map.get(page.page_number)
        if ann is not None:
            normalized = normalize_topic_title(ann.topic_title, fallback=topic)
            if normalized:
                topic = normalized
        if ann is None or ann.is_substantive:
            text = (
                ann.repaired_markdown
                if (ann and ann.needs_formula_repair and ann.repaired_markdown)
                else page.text
            )
            cleaned = " ".join(text.split())
            if cleaned:
                tail = cleaned[-_ANCHOR_TAIL_CHARS:]
    return topic, tail


def chunk_pages_semantically(
    *,
    pages: Sequence[SemanticPageInput],
    fallback_paragraphs: Sequence[ParagraphInput],
    llm: LLMProtocol | None,
    enabled: bool = True,
    doc_type: str = "pdf",
    batch_max_pages: int = SEMANTIC_BATCH_MAX_PAGES,
    batch_max_chars: int = SEMANTIC_BATCH_MAX_CHARS,
    on_progress: Callable[[int, int], None] | None = None,
) -> SemanticChunkingOutcome | None:
    """Run 8-page sliding-window semantic tagging with per-batch deterministic fallback."""
    if not should_use_semantic_chunking(pages, llm, enabled=enabled) or llm is None:
        return None

    enriched_pages = _enrich_formula_hints(pages)
    batches = plan_semantic_batches(
        enriched_pages,
        max_pages=batch_max_pages,
        max_chars=batch_max_chars,
    )
    if not batches:
        return None

    batch_annotations: list[list[PageSemanticAnnotation] | None] = []
    repaired_pages: dict[int, str] = {}
    last_topic = ""
    last_tail = ""

    for idx, batch in enumerate(batches, start=1):
        annotations = _annotate_single_batch(
            batch,
            llm,
            last_topic_title=last_topic,
            last_tail_summary=last_tail,
        )
        batch_annotations.append(annotations)
        if annotations is not None:
            for ann in annotations:
                if ann.needs_formula_repair and ann.repaired_markdown:
                    repaired_pages[ann.page_number] = ann.repaired_markdown
            last_topic, last_tail = _update_batch_anchors(batch, annotations, last_topic)
        else:
            last_tail = ""
        if on_progress is not None:
            on_progress(idx, len(batches))

    if all(item is None for item in batch_annotations):
        return None

    snippets_out: list[Snippet] = []
    cleaned_total = 0
    warnings_out: list[str] = []
    pending_pages: list[SemanticPageInput] = []
    pending_anns: list[PageSemanticAnnotation] = []

    def _flush_pending_semantic() -> None:
        nonlocal cleaned_total
        if not pending_pages:
            return
        res = build_semantic_snippets(pending_pages, pending_anns, doc_type=doc_type)
        snippets_out.extend(res.snippets)
        cleaned_total += res.cleaned_chars_count
        warnings_out.extend(res.warnings)
        pending_pages.clear()
        pending_anns.clear()

    for batch, anns in zip(batches, batch_annotations, strict=True):
        if anns is not None:
            pending_pages.extend(batch)
            pending_anns.extend(anns)
            continue
        _flush_pending_semantic()
        fb = _fallback_batch_snippets(batch, fallback_paragraphs, doc_type=doc_type)
        snippets_out.extend(fb.snippets)
        cleaned_total += fb.cleaned_chars_count
        warnings_out.extend(fb.warnings)

    _flush_pending_semantic()
    if not snippets_out:
        return None

    merged_result = reindex_snippets(
        snippets_out,
        cleaned_chars_count=cleaned_total,
        warnings=warnings_out,
    )
    return SemanticChunkingOutcome(
        chunk_result=merged_result,
        repaired_page_texts=repaired_pages,
    )


__all__ = [
    "PageAnnotationSchema",
    "SemanticBatchAnnotationResponse",
    "SemanticChunkingOutcome",
    "chunk_pages_semantically",
    "should_use_semantic_chunking",
]
