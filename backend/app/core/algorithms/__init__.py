"""Pure functional algorithm kernel package."""

from app.core.algorithms.material_chunking import (
    ChunkingResult,
    ParagraphInput,
    Snippet,
    split_material_into_snippets,
)
from app.core.algorithms.ocr_quality import (
    BatchQualityReport,
    OCRPageInput,
    OCRQualityConfig,
    PageQualityResult,
    UnqualifiedReasonCode,
    calculate_gibberish_ratio,
    calculate_median_length,
    clean_ocr_text,
    count_valid_characters,
    evaluate_page_quality,
    verify_ocr_quality,
)

__all__ = [
    "BatchQualityReport",
    "ChunkingResult",
    "OCRPageInput",
    "OCRQualityConfig",
    "PageQualityResult",
    "ParagraphInput",
    "Snippet",
    "UnqualifiedReasonCode",
    "calculate_gibberish_ratio",
    "calculate_median_length",
    "clean_ocr_text",
    "count_valid_characters",
    "evaluate_page_quality",
    "split_material_into_snippets",
    "verify_ocr_quality",
]
