"""Pure functional algorithm kernel package."""

from app.core.algorithms.material_chunking import (
    ChunkingResult,
    ParagraphInput,
    Snippet,
    split_material_into_snippets,
)

__all__ = [
    "ChunkingResult",
    "ParagraphInput",
    "Snippet",
    "split_material_into_snippets",
]
